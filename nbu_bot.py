import os
import json
import requests
import asyncio
import threading
from bs4 import BeautifulSoup
from datetime import datetime, time as dt_time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- Configuration ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
NBU_URL = "https://coins.bank.gov.ua/catalog.html"
DATA_FILE = "coins_data.json"
SUBSCRIBERS_FILE = "subscribers.json"

class NBUCoinMonitor:
    def __init__(self):
        self.subscribers = self.load_subscribers()
        self.previous_coins = self.load_previous_coins()
    
    def load_subscribers(self):
        if os.path.exists(SUBSCRIBERS_FILE):
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return []
    
    def save_subscribers(self):
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.subscribers, f, ensure_ascii=False, indent=2)
    
    def load_previous_coins(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return []
    
    def save_coins(self, coins):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(coins, f, ensure_ascii=False, indent=2)
    
    def fetch_coins(self):
        try:
            print(f"[{datetime.now()}] Починаю перевірку каталогу НБУ...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
            response = requests.get(NBU_URL, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            coins = []
            
            # Use unique links as the primary scraping method
            all_links = soup.find_all('a', href=lambda x: x and '/p-' in x)
            seen_hrefs = {}
            for link in all_links:
                href = link.get('href')
                if href and href not in seen_hrefs:
                    title = link.get('title') or link.get_text(strip=True)
                    if title:
                        seen_hrefs[href] = {
                            'title': title.strip(),
                            'link': href if href.startswith('http') else 'https://coins.bank.gov.ua' + href,
                            'element': link.find_parent(['div', 'article', 'div', 'class_="product-layout"'])
                        }
            
            for idx, (href, data) in enumerate(seen_hrefs.items(), 1):
                try:
                    metal, tirazh = "", "" # Reset for each coin
                    title = data['title']
                    link = data['link']
                    parent = data['element']
                    
                    price = "Очікується"
                    status = "У продажу"
                    
                    if parent:
                        parent_text = parent.get_text()
                        price_elem = parent.find('p', class_='price')
                        if price_elem:
                            price = price_elem.text.strip() or "Очікується"
                        
                        # Status Logic
                        if 'Очікується' in parent_text or price == "Очікується":
                            status = "Очікується"
                        elif 'скоро у продажу' in parent_text.lower():
                            status = "Скоро у продажу"
                        elif 'грн' in price:
                            status = "У продажу"

                        # Metal and Tirazh
                        if 'ЗОЛОТО' in parent_text: metal = "Золото"
                        elif 'СРІБЛО' in parent_text: metal = "Срібло"
                        
                        import re
                        tirazh_match = re.search(r'ТИРАЖ\s+(\d+)', parent_text)
                        if tirazh_match:
                            tirazh = tirazh_match.group(1)

                    coins.append({
                        'title': title, 'price': price, 'link': link,
                        'status': status, 'metal': metal, 'tirazh': tirazh,
                        'found_date': datetime.now().isoformat()
                    })
                except Exception as e:
                    continue
            
            return coins
        except Exception as e:
            print(f"Помилка: {e}")
            return None

    def find_new_coins(self, current_coins):
        if not self.previous_coins:
            return []
        previous_titles = {coin['title'] for coin in self.previous_coins}
        return [coin for coin in current_coins if coin['title'] not in previous_titles]

    def format_coin_message(self, coin):
        emoji = "🟢" if coin['status'] == "У продажу" else "⏳"
        msg = f"{emoji} *[{coin['title']}]({coin['link']})*\n\n"
        msg += f"💰 Ціна: {coin['price']}\n📊 Статус: {coin['status']}\n"
        if coin.get('metal'): msg += f"⚜️ Метал: {coin['metal']}\n"
        if coin.get('tirazh'): msg += f"📈 Тираж: {coin['tirazh']}\n"
        msg += f"\n🔗 [Відкрити на сайті]({coin['link']})"
        return msg

monitor = NBUCoinMonitor()

# --- Handlers ---
def get_keyboard():
    keyboard = [[KeyboardButton("🔍 Перевірити зараз"), KeyboardButton("📋 Список монет")],
                [KeyboardButton("📊 Статус бота"), KeyboardButton("🛑 Відписатися")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in monitor.subscribers:
        monitor.subscribers.append(chat_id)
        monitor.save_subscribers()
        await update.message.reply_text("✅ Підписку оформлено! Перевіряю сайт о 9:00 та 22:00.", reply_markup=get_keyboard())
    else:
        await update.message.reply_text("Ви вже підписані!", reply_markup=get_keyboard())

async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Перевіряю...")
    coins = monitor.fetch_coins()
    if not coins:
        await update.message.reply_text("Не вдалося отримати дані.")
        return
    
    new_coins = monitor.find_new_coins(coins)
    if new_coins:
        for coin in new_coins[:5]:
            await update.message.reply_text(monitor.format_coin_message(coin), parse_mode='Markdown')
    else:
        await update.message.reply_text(f"Нових монет немає. Всього в каталозі: {len(coins)}")
    
    monitor.previous_coins = coins
    monitor.save_coins(coins)

async def list_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = monitor.fetch_coins()
    if not coins:
        await update.message.reply_text("Помилка каталогу.")
        return
    
    available = [c for c in coins if c['status'] == "У продажу"][:10]
    message = f"📋 *Останні монети у продажу:*\n\n"
    for i, c in enumerate(available, 1):
        message += f"{i}. [{c['title']}]({c['link']}) - {c['price']}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔍 Перевірити зараз": await check_now(update, context)
    elif text == "📋 Список монет": await list_coins(update, context)
    elif text == "📊 Статус бота":
        msg = f"👥 Підписників: {len(monitor.subscribers)}\n🪙 Монет в базі: {len(monitor.previous_coins)}"
        await update.message.reply_text(msg)
    elif text == "🛑 Відписатися":
        if update.effective_chat.id in monitor.subscribers:
            monitor.subscribers.remove(update.effective_chat.id)
            monitor.save_subscribers()
            await update.message.reply_text("Відписано.")

# --- Scheduled Task ---
async def scheduled_check_job(context: ContextTypes.DEFAULT_TYPE):
    print("Виконую заплановану перевірку...")
    coins = monitor.fetch_coins()
    if not coins: return
    
    new_coins = monitor.find_new_coins(coins)
    if new_coins:
        for chat_id in monitor.subscribers:
            try:
                await context.bot.send_message(chat_id, "🎉 *Знайдено нові монети!*", parse_mode='Markdown')
                for coin in new_coins[:3]:
                    await context.bot.send_message(chat_id, monitor.format_coin_message(coin), parse_mode='Markdown')
            except: continue
            
    monitor.previous_coins = coins
    monitor.save_coins(coins)

# --- Health Check Server ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b'OK')

def run_health_server():
    HTTPServer(('0.0.0.0', 10000), HealthCheckHandler).serve_forever()

# --- Main ---
def main():
    if TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("Вкажіть токен!"); return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Setup Schedule using built-in JobQueue
    job_queue = application.job_queue
    job_queue.run_daily(scheduled_check_job, time=dt_time(9, 0))
    job_queue.run_daily(scheduled_check_job, time=dt_time(22, 0))
    
    # Start Health Server
    threading.Thread(target=run_health_server, daemon=True).start()
    
    print("Бот запускається...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
