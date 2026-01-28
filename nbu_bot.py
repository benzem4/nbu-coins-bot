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

# --- SCRAPER ---
def get_coins_data():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    try:
        session = requests.Session()
        session.get("https://coins.bank.gov.ua/", headers=headers, timeout=15)
        response = session.get(URL, headers=headers, timeout=20)
        
        if response.status_code != 200: return None, [], [], []

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
            
            parent = link.find_parent(['div', 'td', 'li'])
            p_text = parent.get_text(separator=' ', strip=True).lower() if parent else ""
            price_match = re.search(r'(\d[\d\s]*грн)', p_text)
            price = price_match.group(1).replace('\xa0', ' ').strip() if price_match else "Очікується"
            
            is_in_stock = "у продажу" in p_text or "наявності" in p_text
            status = "AVAILABLE" if is_in_stock else "WAITING"
            
            coins_map[title] = {"status": status, "price": price}
            full_link = f"https://coins.bank.gov.ua{href}" if not href.startswith('http') else href
            entry = f"🔹 **[{title}]({full_link})**\n💰 {price}"

            if ("грн" in price and not is_in_stock): newly.append(entry)
            elif is_in_stock: available.append(entry)
            else: waiting.append(entry)
                
        return coins_map, newly, available, waiting
    except Exception as e:
        print(f"Scraper Error: {e}")
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
            old_s, old_p = res
            if old_s == "WAITING" and data['status'] == "AVAILABLE":
                await notify_all(f"🔥 **З'ЯВИЛОСЬ У ПРОДАЖУ!**\n\n{title}\n💰 {data['price']}")
            elif "очікується" in old_p.lower() and "грн" in data['price'].lower():
                await notify_all(f"🆕 **ВСТАНОВЛЕНО ЦІНУ!**\n\n{title}\n💰 {data['price']}")
            cur.execute("UPDATE last_state SET last_status=%s, last_price=%s WHERE coin_title=%s", (data['status'], data['price'], title))
        else:
            cur.execute("INSERT INTO last_state VALUES (%s, %s, %s)", (title, data['status'], data['price']))
    conn.commit(); cur.close(); conn.close()

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
    await message.answer(
        "👋 Вітаю! Я моніторю нумізматику НБУ.\n"
        "⏰ Автоматичні перевірки: **09:00** та **22:00** за Києвом.\n"
        "Ви також можете перевірити стан вручну кнопкою нижче.",
        reply_markup=kb.as_markup(resize_keyboard=True)
    )

@dp.message(F.text == "🔍 Перевірити каталог")
async def manual_check(message: types.Message):
    data, newly, av, wt = get_coins_data()
    if data is None:
        await message.answer("⚠️ Сайт НБУ не віддає дані. Можливо, ведуться технічні роботи.")
        return
    
    parts = []
    if newly: parts.append("🆕 **ОНОВЛЕННЯ / ЦІНИ:**\n" + "\n\n".join(newly))
    if av: parts.append("🟢 **В НАЯВНОСТІ:**\n" + "\n\n".join(av[:15]))
    if wt: parts.append("⏳ **ОЧІКУЮТЬСЯ:**\n" + "\n\n".join(wt[:10]))
    
    final_text = "\n\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n".join(parts) if parts else "🔍 На сторінці товарів не знайдено."
    await message.answer(final_text[:4096], parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.chat.id != ADMIN_ID: return
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM users"); u_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM last_state"); c_count = cur.fetchone()[0]
    cur.close(); conn.close()
    await message.answer(f"📊 **АДМІН-СТАТИСТИКА:**\n👤 Користувачів: {u_count}\n📦 Монет у базі: {c_count}")

# --- WEB SERVER & MAIN ---
async def handle(request): return web.Response(text="Bot Alive")

async def main():
    init_db()
    app = web.Application(); app.router.add_get('/', handle)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 10000))).start()
    
    # Налаштування розкладу: 9:00 та 22:00
    scheduler.add_job(monitor_changes, 'cron', hour=9, minute=0)
    scheduler.add_job(monitor_changes, 'cron', hour=22, minute=0)
    
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
