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
# Отримуємо токен та ID адміністратора зі змінних середовища Render
API_TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_ID = os.getenv('ADMIN_CHAT_ID')
URL = "https://coins.bank.gov.ua/catalog.html"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
kyiv_tz = pytz.timezone('Europe/Kyiv')
scheduler = AsyncIOScheduler(timezone=kyiv_tz)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
# Цей сервер відповідає Render, що додаток "живий", на порту 10000
async def handle(request):
    return web.Response(text="NBU Monitoring Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render динамічно призначає порт, за замовчуванням 10000
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

# --- ФУНКЦІЯ ПАРСИНГУ ---
def get_coins_data():
    # Емуляція реального браузера, щоб уникнути блокування
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://coins.bank.gov.ua/",
        "Connection": "keep-alive"
    }
    
    try:
        session = requests.Session()
        # Спочатку заходимо на головну для отримання cookies
        session.get("https://coins.bank.gov.ua/", headers=headers, timeout=15)
        
        # Запит до каталогу
        response = session.get(URL, headers=headers, timeout=20)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Шукаємо контейнери товарів за актуальними CSS-класами
        items = soup.select('.product-item') or soup.select('.product-item-info')
        
        report = []
        for item in items[:15]:  # Беремо перші 15 монет
            # Назва
            name_el = item.select_one('.product-item-link')
            name = name_el.get_text(strip=True) if name_el else "Монета без назви"
            
            # Статус наявності
            status_el = item.select_one('.stock') or item.select_one('.availability')
            status = status_el.get_text(strip=True) if status_el else "Статус невідомий"
            
            # Ціна
            price_el = item.select_one('.price')
            price = price_el.get_text(strip=True) if price_el else "Ціна не вказана"
            
            # Посилання на монету
            link = name_el['href'] if name_el and name_el.has_attr('href') else URL
            
            # Візуальний індикатор
            icon = "✅" if "наявності" in status.lower() else "⏳"
            
            report.append(f"{icon} **[{name}]({link})**\n💰 {price} | 📌 {status}")
            
        if not report:
            return "🔍 На сайті зараз порожньо або доступ до каталогу обмежено."
            
        return "\n\n".join(report)
        
    except Exception as e:
        return f"❌ Помилка з'єднання з сайтом: {str(e)}"

# --- ОБРОБКА КОМАНД ТА ПЛАНУВАЛЬНИК ---
async def send_scheduled_report():
    data = get_coins_data()
    current_time = datetime.now(kyiv_tz).strftime("%H:%M")
    try:
        await bot.send_message(ADMIN_ID, f"⏰ **Автоматичний звіт ({current_time}):**\n\n{data}", parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Error sending scheduled report: {e}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Перевірити зараз 🔄", callback_data="check_now"))
    
    await message.answer(
        "👋 Вітаю! Я моніторю нумізматику НБУ.\n"
        "⏰ Графік перевірок: 09:00 та 22:00 за Києвом.",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data == "check_now")
async def process_callback_check(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, text="Завантажую дані...")
    
    data = get_coins_data()
    
    await bot.send_message(
        callback_query.from_user.id, 
        f"📊 **Актуальний стан каталогу:**\n\n{data}", 
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

async def main():
    # 1. Запуск веб-сервера для Render (запобігає Port Scan Timeout)
    await start_web_server()
    
    # 2. Налаштування розкладу
    scheduler.add_job(send_scheduled_report, 'cron', hour=9, minute=0)
    scheduler.add_job(send_scheduled_report, 'cron', hour=22, minute=0)
    scheduler.start()
    
    # 3. Очищення черги та запуск бота (лікує помилку Conflict)
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot is ready to work!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
