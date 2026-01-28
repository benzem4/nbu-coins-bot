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
    cur.close()
    conn.close()

def add_user(user_id):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute('INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING', (user_id,))
    conn.commit()
    cur.close()
    conn.close()

# --- ПАРСИНГ ТА РОЗУМНЕ СОРТУВАННЯ ---
def get_coins_data():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
    try:
        response = requests.get(URL, headers=headers, timeout=25)
        soup = BeautifulSoup(response.text, 'html.parser')
        all_links = soup.find_all('a', href=lambda x: x and '/p-' in x)
        
        coins_map = {}
        newly_updated, available, waiting = [], [], []
        seen_hrefs = set()

        for link in all_links:
            href = link.get('href')
            if not href or href in seen_hrefs: continue
            seen_hrefs.add(href)
            
            title = (link.get('title') or link.get_text(strip=True)).strip()
            if len(title) < 5: continue
            
            parent = link.find_parent(['div', 'li', 'td'])
            p_text = parent.get_text(separator=' ').lower() if parent else ""
            
            # Шукаємо ціну
            price_match = re.search(r'(\d[\d\s]*грн)', p_text)
            price = price_match.group(1).replace('\xa0', ' ') if price_match else "Очікується"
            
            # Визначаємо статус
            is_in_stock = "наявності" in p_text or ("грн" in price and "очікується" not in p_text)
            status = "AVAILABLE" if is_in_stock else "WAITING"
            
            coins_map[title] = {"status": status, "price": price}
            
            full_link = f"https://coins.bank.gov.ua{href}"
            entry = f"🔹 **[{title}]({full_link})**\n💰 {price}"

            # ЛОГІКА КАТЕГОРІЙ:
            # 1. Якщо є ціна, але ще не в наявності (АБО є слова "дата", "продаж") -> НОВИНКИ
            if ("грн" in price and not is_in_stock) or ("продажу з" in p_text):
                newly_updated.append(entry)
            # 2. Якщо реально в наявності
            elif is_in_stock:
                available.append(entry)
            # 3. Все інше
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
    cur.execute("SELECT user_id FROM users")
    users = [row[0] for row in cur.fetchall()]
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
            # Подія: З'явилася в наявності
            if old_status == "WAITING" and data['status'] == "AVAILABLE":
                await notify_all(f"🔥 **З'ЯВИЛОСЬ У ПРОДАЖУ!**\n\n🔹 {title}\n💰 Ціна: {data['price']}\n\nПоспішайте купити! 🚀")
            # Подія: З'явилася ціна або дата (але ще не продаж)
            elif "очікується" in old_price.lower() and "грн" in data['price'].lower():
                await notify_all(f"🆕 **ОНОВЛЕНО ІНФОРМАЦІЮ!**\n\n🔹 {title}\n💰 Встановлено ціну: {data['price']}\n\nСкоро буде доступно! 👀")
            
            cur.execute("UPDATE last_state SET last_status = %s, last_price = %s WHERE coin_title = %s", 
                        (data['status'], data['price'], title))
        else:
            cur.execute("INSERT INTO last_state (coin_title, last_status, last_price) VALUES (%s, %s, %s)", 
                        (title, data['status'], data['price']))
            # Повідомляємо про нову позицію в каталозі взагалі
            await notify_all(f"✨ **НОВА МОНЕТА В КАТАЛОЗІ!**\n\n🔹 {title}\n💰 Статус: {data['price']}")

    conn.commit()
    cur.close(); conn.close()

# --- МЕНЮ ТА ОБРОБНИКИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    add_user(message.chat.id)
    kb = ReplyKeyboardBuilder()
    kb.button(text="🔍 Перевірити каталог")
    if message.chat.id == ADMIN_ID:
        kb.button(text="📊 Статистика")
        kb.button(text="🧪 Тест розсилки")
    kb.adjust(1, 2)
    await message.answer("✅ Моніторинг НБУ активований!", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "🔍 Перевірити каталог")
async def manual_check(message: types.Message):
    data_map, newly, av, wt = get_coins_data()
    
    if data_map is None:
        await message.answer("❌ Помилка зв'язку з сайтом НБУ.")
        return

    sections = []
    if newly:
        sections.append("🔥 **НОВИНКИ ТА ОНОВЛЕННЯ:**\n" + "\n\n".join(newly))
    if av:
        sections.append("🟢 **В НАЯВНОСТІ:**\n" + "\n\n".join(av[:15]))
    if wt:
        sections.append("⏳ **ОЧІКУЮТЬСЯ:**\n" + "\n\n".join(wt[:10]))
    
    if not sections:
        await message.answer("🔍 На сторінці нічого не знайдено. Можливо, сайт тимчасово змінив структуру.")
    else:
        # Telegram має ліміт повідомлення, тому розбиваємо якщо дуже довге
        full_text = "\n\n" + "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n".join(sections)
        await message.answer(full_text[:4096], parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.chat.id != ADMIN_ID: return
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM users"); u_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM last_state"); c_count = cur.fetchone()[0]
    cur.close(); conn.close()
    
    await message.answer(f"📊 **АДМІН-СТАТИСТИКА:**\n\n👤 Користувачів: {u_count}\n📦 Монет у базі: {c_count}\n🕒 {datetime.now(kyiv_tz).strftime('%H:%M:%S')}")

@dp.message(F.text == "🧪 Тест розсилки")
async def test_send(message: types.Message):
    if message.chat.id == ADMIN_ID:
        await message.answer("🚀 Запуск тесту...")
        await notify_all("🧪 Тестове повідомлення: система сповіщень працює коректно!")

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
