import asyncio
import os
import requests
import re
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
# Змінено: бот тепер може працювати з багатьма користувачами, 
# але ADMIN_ID залишається для системних логів, якщо потрібно.
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

# --- ЛОГІКА ПАРСИНГУ (Метод Клода + покращення) ---
def get_coins_data():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    
    try:
        response = requests.get(URL, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Шукаємо посилання на товари за маскою /p-
        all_links = soup.find_all('a', href=lambda x: x and '/p-' in x)
        
        seen_hrefs = {}
        for link in all_links:
            href = link.get('href')
            if href and href not in seen_hrefs:
                title = link.get('title') or link.get_text(strip=True)
                if title and len(title) > 5:  # Відсікаємо порожні або короткі посилання
                    parent = link.find_parent(['div', 'li'])
                    seen_hrefs[href] = {'title': title.strip(), 'parent': parent}

        report = []
        for href, data in seen_hrefs.items():
            title = data['title']
            parent = data['parent']
            parent_text = parent.get_text() if parent else ""
            
            # Визначаємо ціну
            price = "Очікується"
            price_match = re.search(r'(\d[\d\s]*грн)', parent_text)
            if price_match:
                price = price_match.group(1)

            # Визначаємо статус
            status = "У продажу"
            if 'Очікується' in parent_text or "немає" in parent_text.lower():
                status = "Очікується"
            elif 'скоро' in parent_text.lower():
                status = "Скоро у продажу"
            
            # Формуємо посилання
            full_link = href if href.startswith('http') else 'https://coins.bank.gov.ua' + href
            icon = "✅" if status == "У продажу" else "⏳"
            
            report.append(f"{icon} **[{title}]({full_link})**\n💰 {price} | {status}")

        if not report:
            return "🔍 Каталог НБУ віддав сторінку, але товарів на ній не знайдено."
            
        return "\n\n".join(report[:15]) # Повертаємо топ-15
        
    except Exception as e:
        return f"❌ Помилка парсингу: {str(e)}"

# --- ОБРОБКА КОМАНД ---
async def send_report(chat_id):
    data = get_coins_data()
    await bot.send_message(chat_id, f"📊 **Стан каталогу НБУ:**\n\n{data}", 
                           parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Оновити зараз 🔄", callback_data="check_now"))
    await message.answer("👋 Бот для моніторингу монет НБУ готовий!\nПеревірки автоматично о 09:00 та 22:00.", 
                         reply_markup=builder.as_markup())

@dp.callback_query(lambda c: c.data == "check_now")
async def process_callback_check(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, text="Отримую дані...")
    data = get_coins_data()
    await bot.send_message(callback_query.from_user.id, f"📊 **Поточний стан:**\n\n{data}", 
                           parse_mode="Markdown", disable_web_page_preview=True)

async def main():
    await start_web_server()
    
    # Автоматична відправка адміну (можна додати список розсилки)
    if ADMIN_ID:
        scheduler.add_job(send_report, 'cron', hour=9, minute=0, args=[ADMIN_ID])
        scheduler.add_job(send_report, 'cron', hour=22, minute=0, args=[ADMIN_ID])
    
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
