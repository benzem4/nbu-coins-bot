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

# --- НАЛАШТУВАННЯ ---
API_TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_ID = os.getenv('ADMIN_CHAT_ID')
URL = "https://coins.bank.gov.ua/catalog.html"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
kyiv_tz = pytz.timezone('Europe/Kyiv')
scheduler = AsyncIOScheduler(timezone=kyiv_tz)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="Bot is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ПОКРАЩЕНИЙ ПАРСИНГ ---
def get_coins_data():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://coins.bank.gov.ua/"
    }
    try:
        # Використовуємо сесію для кращої обробки cookies
        session = requests.Session()
        response = session.get(URL, headers=headers, timeout=20)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Шукаємо всі контейнери товарів
        items = soup.find_all('li', class_='item product product-item') 
        # Якщо список порожній, спробуємо загальніший клас
        if not items:
            items = soup.find_all('div', class_='product-item-info')
            
        report = []
        
        for item in items[:15]:
            # Назва
            name_el = item.select_one('.product-item-link')
            name = name_el.get_text(strip=True) if name_el else "Монета без назви"
            
            # Статус (Наявність)
            status_el = item.select_one('.stock')
            status = status_el.get_text(strip=True) if status_el else "Статус невідомий"
            
            # Ціна
            price_el = item.select_one('.price')
            price = price_el.get_text(strip=True) if price_el else "Ціна не вказана"
            
            # Стрілочка для візуалізації статусу
            icon = "✅" if "наявності" in status.lower() else "⏳"
            
            report.append(f"{icon} **{name}**\n💰 {price} | 📌 {status}")
        
        if not report:
            # Лог для відладки, якщо нічого не знайдено
            print(f"Debug: HTML length {len(response.text)}")
            return "🔍 На сайті зараз порожньо або структура змінилася. Перевірте: " + URL
            
        return "\n\n".join(report)
    except Exception as e:
        return f"❌ Помилка парсингу: {str(e)}"

# --- ОБРОБКА КОМАНД ---
async def send_scheduled_report():
    data = get_coins_data()
    current_time = datetime.now(kyiv_tz).strftime("%H:%M")
    try:
        await bot.send_message(ADMIN_ID, f"📅 **Звіт НБУ ({current_time}):**\n\n{data}", parse_mode="Markdown")
    except Exception as e:
        print(f"Error: {e}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Оновити зараз 🔄", callback_data="check_now"))
    await message.answer(
        "👋 Вітаю! Я моніторю нумізматику НБУ.\n"
        "Перевірки: 09:00 та 22:00 за Києвом.",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data == "check_now")
async def process_callback_check(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    data = get_coins_data()
    await bot.send_message(callback_query.from_user.id, f"📊 **Поточний стан:**\n\n{data}", parse_mode="Markdown")

async def main():
    # Стартуємо сервер першим для Render
    await start_web_server()
    
    scheduler.add_job(send_scheduled_report, 'cron', hour=9, minute=0)
    scheduler.add_job(send_scheduled_report, 'cron', hour=22, minute=0)
    scheduler.start()
    
    print("Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
