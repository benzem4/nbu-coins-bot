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

# --- CONFIG ---
API_TOKEN = os.getenv('TELEGRAM_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = int(os.getenv('ADMIN_CHAT_ID', 0))
URL = "https://coins.bank.gov.ua/catalog.html"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
kyiv_tz = pytz.timezone('Europe/Kyiv')
scheduler = AsyncIOScheduler(timezone=kyiv_tz)

# --- DATABASE ---
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

# --- ADVANCED SCRAPER ---
def get_coins_data():
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Referer': 'https://coins.bank.gov.ua/'
    }
    try:
        # Спроба 1: Основний каталог
        session = requests.Session()
        response = session.get(URL, headers=headers, timeout=30)
        
        # Якщо НБУ видає 403 або пусту сторінку, пробуємо "прогріти" куки через головну
        if response.status_code != 200 or len(response.text) < 5000:
            session.get("https://coins.bank.gov.ua/", headers=headers)
            response = session.get(URL, headers=headers, timeout=30)

        soup = BeautifulSoup(response.text, 'html.parser')
        all_links = soup.find_all('a', href=re.compile(r'/p-'))
        
        coins_map, newly, available, waiting = {}, [], [], []
        seen = set()

        for link in all_links:
            href = link.get('href')
            if not href or href in seen: continue
            seen.add(href)
            
            title = (link.get('title') or link.get_text(strip=True)).strip()
            if len(title) < 4: continue
            
            # Шукаємо контейнер з даними
            parent = link.find_parent(['div', 'td', 'li', 'span'])
            p_text = parent.get_text(separator=' ', strip=True).lower() if parent else ""
            p_text = p_text.replace('\xa0', ' ')
            
            # Витягуємо ціну
            price_match = re.search(r'(\d[\d\s]*грн)', p_text)
            price = price_match.group(1).strip() if price_match else "Очікується"
            
            # Визначаємо статус
            is_in_stock = "наявності" in p_text and "немає" not in p_text
            # Якщо є ціна, але немає напису "очікується" — це теж продаж
            if not is_in_stock and "грн" in price and "очікується" not in p_text:
                is_in_stock = True

            status = "AVAILABLE" if is_in_stock else "WAITING"
            coins_map[title] = {"status": status, "price": price}
            
            full_link = f"https://coins.bank.gov.ua{href}" if not href.startswith('http') else href
            entry = f"🔹 **[{title}]({full_link})**\n💰 {price}"

            # Сортування: Новинки (є ціна/дата, але не в продажу) > Продаж > Очікується
            if "грн" in price and not is_in_stock:
                newly.append(entry)
            elif is_in_stock:
                available.append(entry)
            else:
                waiting.append(entry)
                
        return coins_map, newly, available, waiting
    except Exception as e:
        print(f"Crit error: {e}")
        return None, [], [], []

# --- NOTIFICATIONS ---
async def notify_all(text):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users"); users = [row[0] for row in cur.fetchall()]
    cur.close(); conn.close()
    for uid in users:
        try:
            await bot.send_message(uid, text, parse_mode="Markdown", disable_web_page_preview=True)
            await asyncio.sleep(0.1)
        except: pass

async def monitor_changes():
    current_map, _, _, _ = get_coins_data()
    if not current_map: return

    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    
    for title, data in current_map.items():
        cur.execute("SELECT last_status, last_price FROM last_state WHERE coin_title = %s", (title,))
        res = cur.fetchone()
        
        if res:
            old_status, old_price = res
            if old_status == "WAITING" and data['status'] == "AVAILABLE":
                await notify_all(f"🔥 **З'ЯВИЛОСЬ У ПРОДАЖУ!**\n\n{title}\n💰 {data['price']}\n🚀 Купуйте швидше!")
            elif "очікується" in old_price.lower() and "грн" in data['price'].lower():
                await notify_all(f"🆕 **ВСТАНОВЛЕНО ЦІНУ!**\n\n{title}\n💰 {data['price']}\n👀 Скоро запуск!")
            
            cur.execute("UPDATE last_state SET last_status=%s, last_price=%s WHERE coin_title=%s", 
                        (data['status'], data['price'], title))
        else:
            cur.execute("INSERT INTO last_state VALUES (%s, %s, %s)", (title, data['status'], data['price']))
            await notify_all(f"✨ **НОВА МОНЕТА:** {title}\n💰 Статус: {data['price']}")

    conn.commit()
    cur.close(); conn.close()

# --- HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    add_user(message.chat.id)
    kb = ReplyKeyboardBuilder()
    kb.button(text="🔍 Перевірити каталог")
    if message.chat.id == ADMIN_ID:
        kb.button(text="📊 Статистика")
        kb.button(text="🧪 Тест розсилки")
    kb.adjust(1, 2)
    await message.answer("🦾 Моніторинг НБУ 2.0 запущено!", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "🔍 Перевірити каталог")
async def manual_check(message: types.Message):
    data, newly, av, wt = get_coins_data()
    if data is None:
        await message.answer("❌ НБУ заблокував запит. Спробуйте пізніше.")
        return

    msg_parts = []
    if newly: msg_parts.append("🆕 **ОНОВЛЕННЯ / ЦІНИ:**\n" + "\n\n".join(newly))
    if av: msg_parts.append("🟢 **В НАЯВНОСТІ:**\n" + "\n\n".join(av[:15]))
    if wt: msg_parts.append("⏳ **ОЧІКУЮТЬСЯ:**\n" + "\n\n".join(wt[:10]))
    
    if not msg_parts:
        await message.answer("🔍 Порожньо. Можливо, техроботи на сайті НБУ.")
    else:
        await message.answer("\n\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n".join(msg_parts), parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.chat.id != ADMIN_ID: return
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM users"); u_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM last_state"); c_count = cur.fetchone()[0]
    cur.close(); conn.close()
    await message.answer(f"📊 **АДМІН-КАНАЛ:**\n👤 Підписників: {u_count}\n📦 Монет у базі: {c_count}")

@dp.message(F.text == "🧪 Тест розсилки")
async def test_send(message: types.Message):
    if message.chat.id == ADMIN_ID:
        await notify_all("🧪 Тест системи сповіщень успішний!")

# --- RUNNER ---
async def handle(request): return web.Response(text="Running")

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
