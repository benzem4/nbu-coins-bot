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

# --- НАЛАШТУВАННЯ ЗІ ЗМІННИХ СЕРЕДОВИЩА ---
API_TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_ID = os.getenv('ADMIN_CHAT_ID')
URL = "https://coins.bank.gov.ua/catalog.html"

# Ініціалізація бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
# Налаштування часового поясу Києва
kyiv_tz = pytz.timezone('Europe/Kyiv')
scheduler = AsyncIOScheduler(timezone=kyiv_tz)

def get_coins_data():
    """Парсинг сайту НБУ"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(URL, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Пошук товарів (класи можуть змінюватися НБУ, це базовий селектор)
        items = soup.find_all('div', class_='product-item-info')
        report = []
        
        for item in items[:15]:  # Беремо перші 15, щоб не спамити
            name_ element = item.find('a', class_='product-item-link')
            name = name_element.text.strip() if name_element else "Без назви"
            
            status_element = item.find('div', class_='stock')
            status = status_element.text.strip() if status_element else "Статус не вказано"
            
            price_element = item.find('span', class_='price')
            price = price_element.text.strip() if price_element else "Ціна відсутня"
            
            report.append(f"🪙 **{name}**\n💰 {price} | 📌 {status}")
        
        if not report:
            return "На сторінці не знайдено монет. Можливо, структура сайту змінилася."
        
        return "\n\n".join(report)
    except Exception as e:
        return f"❌ Помилка при парсингу: {str(e)}"

async def send_scheduled_report():
    """Автоматична розсилка"""
    data = get_coins_data()
    current_time = datetime.now(kyiv_tz).strftime("%H:%M")
    message_text = f"⏰ **Плановий звіт ({current_time}):**\n\n{data}"
    
    # Відправляємо адміну
    try:
        await bot.send_message(ADMIN_ID, message_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Помилка розсилки: {e}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Перевірити зараз 🔍", callback_data="check_now"))
    
    await message.answer(
        "👋 Вітаю! Я моніторю нумізматику НБУ.\n\n"
        "📅 Графік перевірок: **09:00** та **22:00** (Київ).\n"
        "Ви також можете оновити дані вручну кнопкою нижче.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "check_now")
async def process_callback_check(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, text="Запитую дані з банку...")
    data = get_coins_data()
    await bot.send_message(
        callback_query.from_user.id, 
        f"📊 **Актуальний статус:**\n\n{data}", 
        parse_mode="Markdown"
    )

async def main():
    # Додаємо завдання в планувальник
    scheduler.add_job(send_scheduled_report, 'cron', hour=9, minute=0)
    scheduler.add_job(send_scheduled_report, 'cron', hour=22, minute=0)
    scheduler.start()
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
