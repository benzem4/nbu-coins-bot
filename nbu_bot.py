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
ADMIN_ID = int(os.getenv('ADMIN_CHAT_ID', 0))
URL = "https://coins.bank.gov.ua/catalog.html"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone='Europe/Kyiv')

# --- ФУНКЦІЯ ОТРИМАННЯ БЕЗКОШТОВНОГО ПРОКСІ ---
def get_free_proxy():
    try:
        # Запит до API безкоштовних проксі (тільки HTTP, щоб було простіше)
        # Параметри: тип http, країни UA, PL, DE (ближче до нас)
        api_url = "https://pubproxy.com/api/proxy?type=http&limit=1&country=UA,PL,DE"
        resp = requests.get(api_url, timeout=5).json()
        if resp.get('data'):
            proxy = resp['data'][0]['ipPort']
            print(f"DEBUG: Використовую проксі {proxy}")
            return {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    except Exception as e:
        print(f"DEBUG: Не вдалося знайти проксі: {e}")
    return None

# --- ПАРСИНГ З ПРОКСІ ТА ЗАТРИМКОЮ ---
def get_coins_data():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    }
    
    # Спробуємо отримати проксі
    proxies = get_free_proxy()
    
    try:
        # Невелика випадкова пауза перед запитом
        time.sleep(random.randint(3, 7))
        
        # Спроба запиту
        response = requests.get(URL, headers=headers, proxies=proxies, timeout=25)
        
        if response.status_code != 200:
            print(f"DEBUG: Сайт відповів кодом {response.status_code}")
            return None, [], [], []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        all_links = soup.find_all('a', href=re.compile(r'/p-'))
        
        coins_map, newly, available, waiting = {}, [], [], []
        seen = set()

        for link in all_links:
            href = link.get('href')
            if not href or href in seen: continue
            seen.add(href)
            
            title = (link.get('title') or link.get_text(strip=True)).strip()
            if len(title) < 5: continue
            
            parent = link.find_parent(['div', 'li', 'td'])
            p_text = parent.get_text(separator=' ', strip=True).lower() if parent else ""
            
            price_match = re.search(r'(\d[\d\s]*грн)', p_text)
            price = price_match.group(1).replace('\xa0', ' ').strip() if price_match else "Очікується"
            
            is_in_stock = "наявності" in p_text or ("грн" in price and "очікується" not in p_text)
            status = "AVAILABLE" if is_in_stock else "WAITING"
            
            coins_map[title] = {"status": status, "price": price}
            full_link = f"https://coins.bank.gov.ua{href}"
            entry = f"🔹 **[{title}]({full_link})**\n💰 {price}"

            if "грн" in price and not is_in_stock: newly.append(entry)
            elif is_in_stock: available.append(entry)
            else: waiting.append(entry)
                
        return coins_map, newly, available, waiting
    except Exception as e:
        print(f"DEBUG: Помилка при запиті: {e}")
        return None, [], [], []

# --- РЕШТА ФУНКЦІОНАЛУ (БЕЗ ЗМІН) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = ReplyKeyboardBuilder()
    kb.button(text="🔍 Перевірити каталог")
    if message.chat.id == ADMIN_ID:
        kb.button(text="🌐 Всі позиції (Direct)")
        kb.button(text="📊 Статистика")
    kb.adjust(1, 2)
    await message.answer("✅ Бот запущений з підтримкою Proxy. Спробуйте Direct запит.", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "🌐 Всі позиції (Direct)")
async def direct_list(message: types.Message):
    if message.chat.id != ADMIN_ID: return
    await message.answer("📡 Шукаю вільний проксі та роблю запит...")
    _, newly, av, wt = get_coins_data()
    all_items = newly + av + wt
    if not all_items:
        await message.answer("❌ Навіть через проксі сайт не повернув позицій. Можливо, зараз ведуться техроботи або всі проксі в списку теж забанені.")
    else:
        text = "🌐 **СПИСОК (PROXY MODE):**\n\n" + "\n\n".join(all_items)
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000], parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(F.text == "🔍 Перевірити каталог")
async def manual_check(message: types.Message):
    data, newly, av, wt = get_coins_data()
    if data is None:
        await message.answer("⚠️ Не вдалося зв'язатися з сайтом.")
        return
    res = []
    if newly: res.append("🆕 **ОНОВЛЕННЯ:**\n" + "\n\n".join(newly))
    if av: res.append("🟢 **В НАЯВНОСТІ:**\n" + "\n\n".join(av[:15]))
    if wt: res.append("⏳ **ОЧІКУЮТЬСЯ:**\n" + "\n\n".join(wt[:10]))
    await message.answer(("\n\n⎯⎯⎯⎯⎯\n\n".join(res) if res else "🔍 Порожньо"), parse_mode="Markdown", disable_web_page_preview=True)

async def handle(request): return web.Response(text="Bot is running")

async def main():
    app = web.Application(); app.router.add_get('/', handle)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 10000))).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
