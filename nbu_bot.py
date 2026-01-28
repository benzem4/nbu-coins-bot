import asyncio
import os
import requests
import re
import sqlite3
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import pytz
from aiohttp import web


# --- НАЛАШТУВАННЯ ---
API_TOKEN = os.getenv('TELEGRAM_TOKEN')
URL = "https://coins.bank.gov.ua/catalog.html"
DB_NAME = "subscribers.db"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
kyiv_tz = pytz.timezone('Europe/Kyiv')
scheduler = AsyncIOScheduler(timezone=kyiv_tz)

# --- РОБОТА З БАЗОЮ ДАНИХ ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)')
    conn.commit()
    conn.close()

def add_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('SELECT user_id FROM users')
    users = [row[0] for row in cur.fetchall()]
    conn.close()
    return users

# --- ПАРСИНГ ТА КАТЕГОРИЗАЦІЯ ---
def get_categorized_coins():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
    try:
        response = requests.get(URL, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        all_links = soup.find_all('a', href=lambda x: x and '/p-' in x)
        seen = {}
        for link in all_links:
            href = link.get('href')
            if href and href not in seen:
                title = link.get('title') or link.get_text(strip=True)
                if title and len(title) > 5:
                    parent = link.find_parent(['div', 'li'])
                    seen[href] = {'title': title.strip(), 'parent': parent}

        available = []
        waiting = []

        for href, data in seen.items():
            parent_text = data['parent'].get_text() if data['parent'] else ""
            full_link = href if href.startswith('http') else 'https://coins.bank.gov.ua' + href
            
            price = "Очікується"
            price_match = re.search(r'(\d[\d\s]*грн)', parent_text)
            if price_match: price = price_match.group(1)

            entry = f"🔹 **[{data['title']}]({full_link})**\n💰 {price}"

            if "наявності" in parent_text.lower() or ("грн" in price and "очікується" not in parent_text.lower()):
                available.append(entry)
            else:
                waiting.append(entry)

        return available, waiting
    except Exception as e:
        print(f"Error: {e}")
        return None, None

# --- ВЗАЄМОДІЯ ---
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔍 Перевірити каталог")
    builder.button(text="🔔 Статус підписки")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    add_user(message.chat.id)
    await message.answer(
        "👋 Вітаю! Ви підписані на оновлення нумізматики НБУ.\n"
        "Перевірки: 09:00 та 22:00.\nКористуйтеся меню нижче:",
        reply_markup=main_menu()
    )

@dp.message(F.text == "🔍 Перевірити каталог")
async def manual_check(message: types.Message):
    msg = await message.answer("🔄 Звертаюся до НБУ, зачекайте...")
    available, waiting = get_categorized_coins()
    
    if available is None:
        await msg.edit_text("❌ Не вдалося отримати дані.")
        return

    text = "✅ **В НАЯВНОСТІ:**\n" + ("\n\n".join(available[:10]) if available else "Порожньо")
    text += "\n\n" + "⏳ **ОЧІКУЮТЬСЯ:**\n" + ("\n\n".join(waiting[:10]) if waiting else "Порожньо")
    
    await msg.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)

# --- РОЗСИЛКА ---
async def daily_broadcast():
    available, waiting = get_categorized_coins()
    if not available and not waiting: return

    users = get_all_users()
    report = "📢 **Щоденний звіт НБУ**\n\n✅ В продажу: " + str(len(available))
    report += "\n⏳ Очікується: " + str(len(waiting))
    report += "\n\nНатисніть кнопку в меню, щоб побачити повний список."

    for user_id in users:
        try:
            await bot.send_message(user_id, report, parse_mode="Markdown")
            await asyncio.sleep(0.05) # Захист від спам-фільтра Telegram
        except:
            continue

# --- WEB SERVER & MAIN ---
async def handle(request): return web.Response(text="Alive")

async def main():
    init_db()
    # Web server
    app = web.Application(); app.router.add_get('/', handle)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 10000))).start()

    # Scheduler
    scheduler.add_job(daily_broadcast, 'cron', hour=9, minute=0)
    scheduler.add_job(daily_broadcast, 'cron', hour=22, minute=0)
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
