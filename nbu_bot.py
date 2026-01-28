import asyncio
import os
import re
import psycopg2
import random
import time
import cloudscraper
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

# --- CONFIG ---
API_TOKEN = os.getenv('TELEGRAM_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
PROXY_URL = os.getenv('PROXY_URL')
ADMIN_ID = int(os.getenv('ADMIN_CHAT_ID', 0))
URL = "https://coins.bank.gov.ua/catalog.html"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone='Europe/Kyiv')

# --- DATABASE ---
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY)')
        cur.execute('''CREATE TABLE IF NOT EXISTS last_state 
                       (coin_title TEXT PRIMARY KEY, last_status TEXT, last_price TEXT)''')
        conn.commit()
        cur.close(); conn.close()
    except: pass

def add_user(user_id):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute('INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING', (user_id,))
        conn.commit()
        cur.close(); conn.close()
    except: pass

# --- SCRAPER (Clean version) ---
def get_coins_data():
    proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
    
    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
        
        # Прямий запит без зайвих перевірок
        response = scraper.get(URL, proxies=proxies, timeout=30)
        
        if response.status_code != 200:
            return None, [], [], []

        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.find_all('a', href=re.compile(r'/p-'))
        
        coins_map, newly, available, waiting = {}, [], [], []
        seen = set()

        for link in items:
            href = link.get('href')
            if not href or href in seen: continue
            seen.add(href)
            
            title = (link.get('title') or link.get_text(strip=True)).strip()
            if len(title) < 5: continue
            
            parent = link.find_parent(['div', 'li', 'td'])
            p_text = parent.get_text(separator=' ', strip=True).lower() if parent else ""
            
            price_match = re.search(r'(\d[\d\s]*грн)', p_text)
            price = price_match.group(1).replace('\xa0', ' ').strip() if price_match else "Очікується"
            
            is_in_stock = any(x in p_text for x in ["наявності", "купити", "кошик"])
            status = "AVAILABLE" if is_in_stock else "WAITING"
            
            coins_map[title] = {"status": status, "price": price}
            full_link = f"https://coins.bank.gov.ua{href}"
            entry = f"🔹 **[{title}]({full_link})**\n💰 {price}"

            if is_in_stock: available.append(entry)
            else: waiting.append(entry)
                
        return coins_map, newly, available, waiting
    except:
        return None, [], [], []

# --- MONITORING ---
async def notify_all(text):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users"); users = [row[0] for row in cur.fetchall()]
        cur.close(); conn.close()
        for uid in users:
            try:
                await bot.send_message(uid, text, parse_mode="Markdown", disable_web_page_preview=True)
                await asyncio.sleep(0.05)
            except: pass
    except: pass

async def monitor_changes():
    current_map, _, _, _ = get_coins_data()
    if not current_map: return
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        for title, data in current_map.items():
            cur.execute("SELECT last_status, last_price FROM last_state WHERE coin_title = %s", (title,))
            res = cur.fetchone()
            if res:
                if res[0] == "WAITING" and data['status'] == "AVAILABLE":
                    await notify_all(f"🔥 **З'ЯВИЛОСЬ У ПРОДАЖУ!**\n\n🔹 {title}\n💰 {data['price']}")
                cur.execute("UPDATE last_state SET last_status=%s, last_price=%s WHERE coin_title=%s", (data['status'], data['price'], title))
            else:
                cur.execute("INSERT INTO last_state VALUES (%s, %s, %s)", (title, data['status'], data['price']))
        conn.commit(); cur.close(); conn.close()
    except: pass

# --- HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    add_user(message.chat.id)
    kb = ReplyKeyboardBuilder()
    kb.button(text="🔍 Перевірити каталог")
    if message.chat.id == ADMIN_ID:
        kb.button(text="📊 Статистика")
    kb.adjust(1)
    await message.answer("✅ Моніторинг НБУ активний. Чекаємо оновлень завтра.", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "🔍 Перевірити каталог")
async def manual_check(message: types.Message):
    data, _, av, wt = get_coins_data()
    if data is None:
        await message.answer("⚠️ Сайт не відповів (можливо, захист ще діє).")
        return
    res = []
    if av: res.append("🟢 **В НАЯВНОСТІ:**\n" + "\n\n".join(av[:15]))
    if wt: res.append("⏳ **ОЧІКУЮТЬСЯ:**\n" + "\n\n".join(wt[:10]))
    await message.answer(("\n\n⎯⎯⎯⎯⎯\n\n".join(res) if res else "🔍 Порожньо"), parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.chat.id != ADMIN_ID: return
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM users"); u = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM last_state"); c = cur.fetchone()[0]
        cur.close(); conn.close()
        await message.answer(f"📊 Статистика:\n👤 Користувачів: {u}\n📦 Монет у базі: {c}")
    except: pass

# --- WEB SERVER ---
async def handle(request): return web.Response(text="Running")

async def main():
    init_db()
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    await web.TCPSite(runner, '0.0.0.0', port).start()

    scheduler.add_job(monitor_changes, 'interval', minutes=30) # Перевірка кожні 30 хв
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
