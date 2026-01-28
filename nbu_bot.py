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

# --- НАЛАШТУВАННЯ ---
API_TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_ID = os.getenv('ADMIN_CHAT_ID')
URL = "https://coins.bank.gov.ua/catalog.html"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
kyiv_tz = pytz.timezone('Europe/Kyiv')
scheduler = AsyncIOScheduler(timezone=kyiv_tz)

def get_coins_data():
    """Парсинг сайту НБУ"""
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
            # Виправлено: назва змінної без пробілу
            name_el = item.find('a', class_='product-item-link')
            name = name_el.text.strip() if name_el else "Без назви"
            
            status_el = item.find('div', class_='stock')
            status = status_el.text.strip() if status_el else "Статус невідомий"
            
            price_el = item.find('span', class_='price')
            price = price_el.text.strip() if price_el else "Ціна не вказана"
            
            report.append(f"🪙 **{name}**\n💰 {price} | 📌 {status}")
        
        return "\n\n".join(report) if report else "Тимчасово немає даних на сайті."
    except Exception as e:
        return f"❌ Помилка зв'язку з сайтом: {str(e)}"

async def send_scheduled_report():
    """Автоматична розсилка"""
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
        "👋 Бот для моніторингу монет НБУ запущений!\n"
        "Графік: 09:00 та 22:00 за Києвом.",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data == "check_now")
async def process_callback_check(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, text="Завантаження...")
    data = get_coins_data()
    await bot.send_message(callback_query.from_user.id, f"📊 **Поточний стан:**\n\n{data}", parse_mode="Markdown")

async def main():
    scheduler.add_job(send_scheduled_report, 'cron', hour=9, minute=0)
    scheduler.add_job(send_scheduled_report, 'cron', hour=22, minute=0)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
