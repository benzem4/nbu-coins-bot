import asyncio
import os
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import pytz
from aiohttp import web

# --- НАЛАШТУВАННЯ ЗІ ЗМІННИХ СЕРЕДОВИЩА ---
API_TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_ID = os.getenv('ADMIN_CHAT_ID')
URL = "https://coins.bank.gov.ua/catalog.html"

# Ініціалізація бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
kyiv_tz = pytz.timezone('Europe/Kyiv')
scheduler = AsyncIOScheduler(timezone=kyiv_tz)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (ЩОБ НЕ ЗАСИНАВ) ---
async def handle(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render передає порт у змінну середовища PORT
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

# --- ЛОГІКА ПАРСИНГУ ---
def get_coins_data():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(URL, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        items = soup.find_all('div', class_='product-item-info')
        report = []
        
        for item in items[:15]:
            name_el = item.find('a', class_='product-item-link')
            name = name_el.text.strip() if name_el else "Без назви"
            
            status_el = item.find('div', class_='stock')
            status = status_el.text.strip() if status_el else "Статус невідомий"
            
            price_el = item.find('span', class_='price')
            price = price_el.text.strip() if price_el else "Ціна не вказана"
            
            report.append(f"🪙 **{name}**\n💰 {price} | 📌 {status}")
        
        return "\n\n".join(report) if report else "Дані на сайті не знайдено."
    except Exception as e:
        return f"❌ Помилка зв'язку з сайтом: {str(e)}"

# --- РОБОТА БОТА ---
async def send_scheduled_report():
    data = get_coins_data()
    current_time = datetime.now(kyiv_tz).strftime("%H:%M")
    try:
        await bot.send_message(ADMIN_ID, f"⏰ **Звіт НБУ ({current_time}):**\n\n{data}", parse_mode="Markdown")
    except Exception as e:
        print(f"Error sending report: {e}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Оновити зараз 🔄", callback_data="check_now"))
    
    await message.answer(
        "👋 Вітаю! Я моніторю монети НБУ.\n"
        "📅 Графік: 09:00 та 22:00 за Києвом.",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data == "check_now")
async def process_callback_check(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, text="Завантажую дані...")
    data = get_coins_data()
    await bot.send_message(callback_query.from_user.id, f"📊 **Актуальний стан:**\n\n{data}", parse_mode="Markdown")

async def main():
    # 1. Запуск планувальника
    scheduler.add_job(send_scheduled_report, 'cron', hour=9, minute=0)
    scheduler.add_job(send_scheduled_report, 'cron', hour=22, minute=0)
    scheduler.start()
    
    # 2. Запуск веб-сервера для Render
    await start_web_server()
    
    # 3. Запуск бота
    print("Bot is starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped")
