import asyncio
import os
import requests
import re
import psycopg2
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import pytz
from aiohttp import web

# --- НАЛАШТУВАННЯ ---
API_TOKEN = os.getenv('TELEGRAM_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = int(os.getenv('ADMIN_CHAT_ID', 0))
URL = "https://coins.bank.gov.ua/catalog.html"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
kyiv_tz = pytz.timezone('Europe/Kyiv')
scheduler = AsyncIOScheduler(timezone=kyiv_tz)

# --- БАЗА ДАНИХ ---
def init_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY)')
    cur.execute('''CREATE TABLE IF NOT EXISTS last_state 
                   (coin_title TEXT PRIMARY KEY, last_status TEXT, last_price TEXT)''')
    conn.commit()
    cur.close(); conn.close()

def add_user(user_id):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute('INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING', (user_id,))
    conn.commit()
    cur.close(); conn.close()

# --- ПАРСИНГ З ПОКРАЩЕНИМ ВИЯВЛЕННЯМ ---
def get_coins_data():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    try:
        response = requests.get(URL, headers=headers, timeout=25)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Шукаємо всі посилання, що містять паттерн товару /p-
        all_links = soup.find_all('a', href=re.compile(r'/p-'))
        
        coins_map = {}
        newly_updated, available, waiting = [], [], []
        seen_hrefs = set()

        for link in all_links:
            href = link.get('href')
            if not href or href in seen_hrefs: continue
            seen_hrefs.add(href)
            
            title = (link.get('title') or link.get_text(strip=True)).strip()
            if len(title) < 4: continue # Пропускаємо занадто короткі назви
            
            # Шукаємо контейнер з ціною (може бути div, td, li або span)
            parent = link.find_parent(['div', 'td', 'li', 'span', 'tr'])
            p_text = parent.get_text(separator=' ').lower() if parent else ""
            p_text = p_text.replace('\xa0', ' ') # Чистимо спецпробіли
            
            # Шукаємо ціну: цифри + грн
            price_match = re.search(r'(\d[\d\s]*грн)', p_text)
            price = price_match.group(1).strip() if price_match else "Очікується"
            
            # Статус: якщо є ціна і немає слова "очікується" АБО є слово "наявності"
            is_in_stock = "наявності" in p_text or ("грн" in price and "очікується" not in p_text)
            status = "AVAILABLE" if is_in_stock else "WAITING"
            
            coins_map[title] = {"status": status, "price": price}
            full_link = f"https://coins.bank.gov.ua{href}" if not href.startswith('http') else href
            entry = f"🔹 **[{title}]({full_link})**\n💰 {price}"

            # Сортування:
            if ("грн" in price and not is_in_stock) or ("продажу з" in p_text):
                newly_updated.append(entry)
            elif is_in_stock:
                available.append(entry)
            else:
                waiting.append(entry)
                
        return coins_map, newly_updated, available, waiting
    except Exception as e:
        print(f"Scraper Error: {e}")
        return None, [], [], []

# --- СПОВІЩЕННЯ ---
async def notify_all(text):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users"); users = [row[0] for row in cur.fetchall()]
    cur.close(); conn.close()
    for user_id in users:
        try:
            await bot.send_message(user_id, text, parse_mode="Markdown", disable_web_page_preview=True)
            await asyncio.sleep(0.05)
        except: pass

async def monitor_changes():
    current_map, _, _, _ = get_coins_data()
    if not current_map: return

    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    
    for title, data in current_map.items():
        cur.execute("SELECT last_status, last_price FROM last_state WHERE coin_title = %s", (title,))
        result = cur.fetchone()
        
        if result:
            old_status, old_price = result
            if old_status == "WAITING" and data['status'] == "AVAILABLE":
                await notify_all(f"🔥 **З'ЯВИЛОСЬ У ПРОДАЖУ!**\n\n🔹 {title}\n💰 {data['price']}\n\nПоспішайте! 🚀")
            elif "очікується" in old_price.lower() and "грн" in data['price'].lower():
                await notify_all(f"🆕 **ВСТАНОВЛЕНО ЦІНУ!**\n\n🔹 {title}\n💰 Ціна: {data['price']}\n\nСкоро буде! 👀")
            
            cur.execute("UPDATE last_state SET last_status = %s, last_price = %s WHERE coin_title = %s", 
                        (data['status'], data['price'], title))
        else:
            cur.execute("INSERT INTO last_state (coin_title, last_status, last_price) VALUES (%s, %s, %s)", 
                        (title, data['status'], data['price']))
            await notify_all(f"✨ **НОВА МОНЕТА В КАТАЛОЗІ!**\n\n🔹 {title}\n💰 Стан: {data['price']}")

    conn.commit()
    cur.close(); conn.close()

# --- МЕНЮ ТА КОМАНДИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    add_user(message.chat.id)
    kb = ReplyKeyboardBuilder()
    kb.button(text="🔍 Перевірити каталог")
    if message.chat.id == ADMIN_ID:
        kb.button(text="📊 Статистика")
        kb.button(text="🧪 Тест розсилки")
    kb.adjust(1, 2)
    await message.answer("✅ Моніторинг НБУ активований! Я напишу сюди, як тільки статус монет зміниться.", 
                         reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "🔍 Перевірити каталог")
async def manual_check(message: types.Message):
    data_map, newly, av, wt = get_coins_data()
    if data_map is None:
        await message.answer("❌ Тимчасово не вдалося підключитися до НБУ.")
        return

    res = []
    if newly: res.append("🆕 **ОНОВЛЕННЯ / ЦІНИ:**\n" + "\n\n".join(newly))
    if av: res.append("🟢 **В НАЯВНОСТІ:**\n" + "\n\n".join(av[:15]))
    if wt: res.append("⏳ **ОЧІКУЮТЬСЯ:**\n" + "\n\n".join(wt[:10]))
    
    if not res:
        await message.answer("🔍 Товарів не знайдено. Спробуйте через 5-10 хв, сайт НБУ може бути перевантажений.")
    else:
        text = "\n\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n".join(res)
        await message.answer(text[:4096], parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.chat.id != ADMIN_ID: return
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM users"); u_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM last_state"); c_count = cur.fetchone()[0]
    cur.close(); conn.close()
    await message.answer(f"📊 **АДМІН-ІНФО:**\n\n👤 Користувачів: {u_count}\n📦 Монет у базі: {c_count}\n🕒 {datetime.now(kyiv_tz).strftime('%H:%M:%S')}")

@dp.message(F.text == "🧪 Тест розсилки")
async def test_send(message: types.Message):
    if message.chat.id == ADMIN_ID:
        await message.answer("🚀 Тест розсилки...")
        await notify_all("🧪 Тест сповіщень: Система працює!")

# --- ЗАПУСК ---
async def handle(request): return web.Response(text="Bot is running")

async def main():
    init_db()
    app = web.Application(); app.router.add_get('/', handle)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 10000))).start()

    scheduler.add_job(monitor_changes, 'interval', minutes=3)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
