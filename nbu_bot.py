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
import random
import time
from aiohttp import web

# --- CONFIG ---
API_TOKEN = os.getenv('TELEGRAM_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
PROXY_URL = os.getenv('PROXY_URL')
ADMIN_ID = int(os.getenv('ADMIN_CHAT_ID', 0))
URL = "https://coins.bank.gov.ua/catalog.html"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone='Europe/Kyiv')

def get_coins_data():
    # Налаштування проксі для сесії
    proxies = {
        "http": PROXY_URL,
        "https": PROXY_URL
    } if PROXY_URL else None
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
    }

    try:
        session = requests.Session()
        # Робимо паузу, щоб не лякати сайт
        time.sleep(random.uniform(2, 4))
        
        # Спроба отримати дані
        response = session.get(URL, headers=headers, proxies=proxies, timeout=30)
        
        if response.status_code != 200:
            print(f"Помилка сайту: {response.status_code}")
            return None, [], [], []

        soup = BeautifulSoup(response.text, 'html.parser')
        # Шукаємо всі посилання на товари
        all_links = soup.find_all('a', href=re.compile(r'/p-'))
        
        if not all_links:
            return None, [], [], []

        coins_map, newly, available, waiting = {}, [], [], []
        seen = set()

        for link in all_links:
            href = link.get('href')
            if not href or href in seen: continue
            seen.add(href)
            
            title = (link.get('title') or link.get_text(strip=True)).strip()
            if len(title) < 5: continue
            
            # Витягуємо ціну та статус з батьківського блоку
            parent = link.find_parent(['div', 'li', 'td'])
            p_text = parent.get_text(separator=' ', strip=True).lower() if parent else ""
            
            price_match = re.search(r'(\d[\d\s]*грн)', p_text)
            price = price_match.group(1).replace('\xa0', ' ').strip() if price_match else "Очікується"
            
            is_in_stock = "наявності" in p_text or ("грн" in price and "очікується" not in p_text)
            status = "AVAILABLE" if is_in_stock else "WAITING"
            
            coins_map[title] = {"status": status, "price": price}
            full_link = f"https://coins.bank.gov.ua{href}"
            entry = f"🔹 **[{title}]({full_link})**\n💰 {price}"

            if "грн" in price and not is_in_stock:
                newly.append(entry)
            elif is_in_stock:
                available.append(entry)
            else:
                waiting.append(entry)
                
        return coins_map, newly, available, waiting
    except Exception as e:
        print(f"Помилка проксі або запиту: {e}")
        return None, [], [], []

# --- HANDLERS (стандартні) ---

@dp.message(F.text == "🌐 Всі позиції (Direct)")
async def direct_list(message: types.Message):
    if message.chat.id != ADMIN_ID: return
    m = await message.answer("📡 Львівський проксі виходить на зв'язок...")
    _, newly, av, wt = get_coins_data()
    all_items = newly + av + wt
    
    if not all_items:
        await m.edit_text("❌ Сайт не відповів. Перевір, чи в requirements.txt є `requests[socks]`.")
    else:
        await m.delete()
        text = "✅ **ПРОКСІ СПРАЦЮВАВ! СПИСОК:**\n\n" + "\n\n".join(all_items)
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000], parse_mode="Markdown", disable_web_page_preview=True)

# ... (інший код бота залишаємо як був)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
