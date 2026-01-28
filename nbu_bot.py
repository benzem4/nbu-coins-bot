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
    return web.Response(text="Bot is running and monitoring NBU!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ПАРСИНГ З ПОКРАЩЕНИМ ПОШУКОМ ---
def get_coins_data():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://coins.bank.gov.ua/"
    }
    try:
        response = requests.get(URL, headers=headers, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Спроба знайти елементи через різні можливі класи НБУ
        items = soup.select('.product-item') or soup.select('.product-item-info')
        
        report = []
        for item in items[:15]:
            # Пошук назви
            name_el = item.select_one('.product-item-link') or item.select_one('strong a')
            name = name_el.get_text(strip=True) if name_el else "Без назви"
            
            # Пошук статусу
            status_el = item.select_one('.stock') or item.select_one('.availability')
            status = status_el.get_text(strip=True) if status_el else "Статус невідомий"
            
            # Пошук ціни
            price_el = item.select_one('.price') or item.select_one('[data-price-type="finalPrice"]')
            price = price_el.get_text(strip=True) if price_el else "--- грн"
            
            # Визначаємо іконку статусу
            icon = "✅" if "наявності" in status.lower() else "⏳"
            
            report.append(f"{icon} **{name}**\n💰 {price} | 📌 {status}")
        
        if not report:
            return "🔍 На сторінці не знайдено товарів. Можливо, сайт тимчасово приховав каталог."
            
        return "\n\n".join(report)
    except Exception as e:
        return f"❌ Помилка зв'язку з сайтом НБУ: {str(e)}"

# --- ЛОГІКА БОТА ---
async def send_scheduled_report():
    data = get_coins_data()
    current_time = datetime.now(kyiv_tz).strftime("%H:%M")
    try:
        await bot.send_message(ADMIN_ID, f"📅 **Звіт НБУ ({current_time}):**\n\n{data}", parse_mode="Markdown")
    except Exception as e:
        print(f"Schedule Error: {e}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Перевірити зараз 🔄", callback_data="check_now"))
    await message.answer(
        "👋 Вітаю! Я моніторю нумізматику НБУ.\n"
        "⏰ Перевірки: **09:00** та **22:00** за Києвом.",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data == "check_now")
async def process_callback_check(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    # Відправляємо проміжне повідомлення, щоб користувач бачив активність
    wait_msg = await bot.send_message(callback_query.from_user.id, "⏳ Отримую дані з сайту НБУ...")
    
    data = get_coins_data()
    
    await bot.edit_message_text(
        f"📊 **Актуальний стан:**\n\n{data}",
        chat_id=callback_query.from_user.id,
        message_id=wait_msg.message_id,
        parse_mode="Markdown"
    )

async def main():
    # 1. Спершу сервер для Render
    await start_web_server()
    
    # 2. Планувальник
    scheduler.add_job(send_scheduled_report, 'cron', hour=9, minute=0)
    scheduler.add_job(send_scheduled_report, 'cron', hour=22, minute=0)
    scheduler.start()
    
    # 3. Полінг
    print("Bot is up and running!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
