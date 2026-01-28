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
    return web.Response(text="NBU Monitoring Bot is active")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ПАРСИНГ ---
def get_coins_data():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "max-age=0",
        "Referer": "https://coins.bank.gov.ua/",
        "Connection": "keep-alive"
    }
    
    try:
        # Використовуємо сесію для імітації браузера
        session = requests.Session()
        response = session.get(URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Шукаємо блоки товарів (класи можуть змінюватися, тому перевіряємо кілька варіантів)
        items = soup.find_all('li', class_='product-item') or soup.find_all('div', class_='product-item-info')
        
        report = []
        for item in items[:15]:
            # Назва монети
            name_tag = item.select_one('.product-item-link') or item.find('a')
            name = name_tag.get_text(strip=True) if name_tag else "Невідома позиція"
            
            # Статус (В наявності / Скоро у продажу)
            status_tag = item.select_one('.stock') or item.select_one('.availability')
            status = status_tag.get_text(strip=True) if status_tag else "Немає даних"
            
            # Ціна
            price_tag = item.select_one('.price')
            price = price_tag.get_text(strip=True) if price_tag else "Ціна за запитом"
            
            # Посилання (якщо хочеш відразу переходити)
            link = name_tag['href'] if name_tag and name_tag.has_attr('href') else URL
            
            icon = "✅" if "наявності" in status.lower() else "⏳"
            report.append(f"{icon} **{name}**\n💰 {price} | {status}\n🔗 [Купити]({link})")
            
        if not report:
            # Якщо нічого не знайдено, можливо сайт віддав порожню сторінку через блок
            return "🔍 На жаль, сайт НБУ не віддав список товарів. Спробуйте пізніше."
            
        return "\n\n".join(report)
        
    except Exception as e:
        return f"❌ Помилка з'єднання: {str(e)}"

# --- ЛОГІКА БОТА ---
async def send_scheduled_report():
    data = get_coins_data()
    current_time = datetime.now(kyiv_tz).strftime("%H:%M")
    try:
        await bot.send_message(ADMIN_ID, f"📅 **Звіт НБУ ({current_time}):**\n\n{data}", parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Error: {e}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Перевірити зараз 🔄", callback_data="check_now"))
    
    await message.answer(
        "👋 Вітаю! Я моніторю нумізматику НБУ.\n"
        "⏰ Авто-перевірка: 09:00 та 22:00 за Києвом.",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data == "check_now")
async def process_callback_check(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id, text="Запитую дані...")
    
    # Редагуємо повідомлення, щоб показати процес
    sent_msg = await bot.send_message(callback_query.from_user.id, "⏳ З'єднуюсь із сервером НБУ...")
    
    data = get_coins_data()
    
    await bot.edit_message_text(
        f"📊 **Актуальний статус:**\n\n{data}",
        chat_id=callback_query.from_user.id,
        message_id=sent_msg.message_id,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

async def main():
    await start_web_server()
    
    scheduler.add_job(send_scheduled_report, 'cron', hour=9, minute=0)
    scheduler.add_job(send_scheduled_report, 'cron', hour=22, minute=0)
    scheduler.start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
