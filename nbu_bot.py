import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import schedule
import time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import re
import logging

# Конфігурація
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")  # Твій Telegram chat ID для сповіщень
NBU_URL = "https://coins.bank.gov.ua/catalog.html"
DATA_FILE = "coins_data.json"
LOG_FILE = "bot_log.txt"

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class NBUCoinMonitor:
    def __init__(self):
        self.subscribers = self.load_subscribers()
        self.previous_coins = self.load_previous_coins()
    
    def load_subscribers(self):
        if os.path.exists("subscribers.json"):
            try:
                with open("subscribers.json", "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def save_subscribers(self):
        try:
            with open("subscribers.json", "w", encoding="utf-8") as f:
                json.dump(self.subscribers, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Помилка збереження підписників: {e}")
    
    def load_previous_coins(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def save_coins(self, coins):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(coins, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Помилка збереження монет: {e}")
    
    def extract_date_from_text(self, text):
        date_patterns = [
            r'(\d{1,2}\.\d{1,2}\.\d{4})',
            r'(\d{1,2}\s+\w+\s+\d{4})',
            r'(\w+\s+\d{4})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
    
    def determine_status(self, parent_text, price_text):
        parent_upper = parent_text.upper()
        price_upper = price_text.upper()
        
        # Перевіряємо чи є фрази про очікування
        expecting_keywords = ['ОЧІКУЄТЬСЯ', 'СКОРО У ПРОДАЖУ', 'СКОРО', 'НЕЗАБАРОМ', 'АНОНС']
        is_expecting = any(kw in parent_upper for kw in expecting_keywords)
        
        # У продажу - якщо є конкретна числова ціна в гривнях БЕЗ слів про очікування
        has_price = bool(re.search(r'\d+[\s\d]*\s*ГРН', price_upper))
        
        if has_price and not is_expecting:
            return "У продажу", None
        
        # Очікується - шукаємо дату
        expected_date = self.extract_date_from_text(parent_text)
        return "Очікується", expected_date
    
    def fetch_coins(self):
        try:
            logger.info("Починаю перевірку каталогу НБУ...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
            }
            
            response = requests.get(NBU_URL, headers=headers, timeout=30)
            response.raise_for_status()
            logger.info(f"Каталог НБУ доступний, статус: {response.status_code}")
            
            soup = BeautifulSoup(response.text, 'html.parser')
            coins = []
            
            all_links = soup.find_all('a', href=lambda x: x and '/p-' in x)
            logger.info(f"Знайдено посилань: {len(all_links)}")
            
            seen_hrefs = {}
            for link in all_links:
                href = link.get('href')
                if href and href not in seen_hrefs:
                    title = link.get('title') or link.get_text(strip=True)
                    if title and title.strip():
                        parent = link.find_parent(['div', 'article', 'section'])
                        seen_hrefs[href] = {
                            'title': title.strip(),
                            'link': href if href.startswith('http') else 'https://coins.bank.gov.ua' + href,
                            'element': parent
                        }
            
            logger.info(f"Унікальних продуктів: {len(seen_hrefs)}")
            
            for idx, (href, data) in enumerate(seen_hrefs.items(), 1):
                try:
                    title = data['title']
                    link = data['link']
                    parent = data['element']
                    
                    price = "Очікується"
                    if parent:
                        price_elem = parent.find('p', class_='price')
                        if price_elem:
                            price_text = price_elem.text.strip()
                            if price_text:
                                price = price_text
                    
                    parent_text = parent.get_text(separator=' ', strip=True) if parent else ""
                    status, expected_date = self.determine_status(parent_text, price)
                    
                    metal = ""
                    tirazh = ""
                    if parent_text:
                        parent_upper = parent_text.upper()
                        if 'ЗОЛОТО' in parent_upper:
                            metal = "Золото"
                        elif 'СРІБЛО' in parent_upper:
                            metal = "Срібло"
                        elif 'НУМІЗМАТИЧНА' in parent_upper:
                            metal = "Інше"
                        
                        tirazh_match = re.search(r'ТИРАЖ\s*:?\s*(\d+[\s\d]*)', parent_upper)
                        if tirazh_match:
                            tirazh = tirazh_match.group(1).replace(' ', '')
                    
                    coin = {
                        'title': title,
                        'price': price,
                        'link': link,
                        'status': status,
                        'expected_date': expected_date,
                        'metal': metal,
                        'tirazh': tirazh,
                        'found_date': datetime.now().isoformat()
                    }
                    coins.append(coin)
                    date_info = f" ({expected_date})" if expected_date else ""
                    logger.info(f"✓ #{idx}: {title} - {status}{date_info}")
                except Exception as e:
                    logger.error(f"❌ Помилка #{idx}: {e}")
            
            available = sum(1 for c in coins if c['status'] == "У продажу")
            expected = sum(1 for c in coins if c['status'] == "Очікується")
            logger.info(f"✅ Оброблено {len(coins)}: У продажу={available}, Очікується={expected}")
            return coins
        except Exception as e:
            logger.error(f"❌ Помилка: {e}")
            return None
    
    def find_new_coins(self, current_coins):
        if not self.previous_coins:
            return []
        previous_titles = {coin['title'] for coin in self.previous_coins}
        return [coin for coin in current_coins if coin['title'] not in previous_titles]
    
    def format_coin_message(self, coin):
        if coin['status'] == "У продажу":
            status_emoji = "🟢"
            status_text = "У ПРОДАЖУ - можна замовити!"
        else:
            status_emoji = "⏳"
            status_text = f"ОЧІКУЄТЬСЯ - {coin['expected_date']}" if coin.get('expected_date') else "ОЧІКУЄТЬСЯ"
        
        message = f"{status_emoji} *[{coin['title']}]({coin['link']})*\n\n"
        message += f"💰 Ціна: {coin['price']}\n"
        message += f"📊 Статус: {status_text}\n"
        if coin.get('metal'):
            message += f"⚜️ Метал: {coin['metal']}\n"
        if coin.get('tirazh'):
            message += f"📈 Тираж: {coin['tirazh']}\n"
        
        if coin['status'] == "У продажу":
            message += f"\n🛒 [ЗАМОВИТИ]({coin['link']})"
        else:
            message += f"\n🔗 [Переглянути]({coin['link']})"
        
        message += f"\n\n⏰ {datetime.fromisoformat(coin['found_date']).strftime('%d.%m.%Y %H:%M')}"
        return message

monitor = NBUCoinMonitor()

def get_keyboard():
    keyboard = [
        [KeyboardButton("🔍 Перевірити зараз"), KeyboardButton("📋 Список монет")],
        [KeyboardButton("📊 Статус бота"), KeyboardButton("🛑 Відписатися")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in monitor.subscribers:
        monitor.subscribers.append(chat_id)
        monitor.save_subscribers()
        await update.message.reply_text(
            "✅ Вітаю! Ти підписаний на сповіщення про нові монети НБУ.\n\n"
            "Я буду перевіряти сайт двічі на день:\n🌅 О 9:00\n🌙 О 22:00",
            reply_markup=get_keyboard()
        )
    else:
        await update.message.reply_text("Ти вже підписаний! 👍", reply_markup=get_keyboard())

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in monitor.subscribers:
        monitor.subscribers.remove(chat_id)
        monitor.save_subscribers()
        await update.message.reply_text("😢 Відписано. Повертайся!")
    else:
        await update.message.reply_text("Ти не був підписаний.")

async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Перевіряю каталог НБУ...")
    coins = monitor.fetch_coins()
    
    if coins is None:
        await update.message.reply_text("❌ Помилка перевірки. Спробуй пізніше.")
        return
    
    if not coins:
        await update.message.reply_text("📭 Не знайдено продукцію в каталозі.")
        return
    
    new_coins = monitor.find_new_coins(coins)
    if new_coins:
        await update.message.reply_text(f"🎉 Знайдено {len(new_coins)} нових!")
        for coin in new_coins[:5]:
            await update.message.reply_text(monitor.format_coin_message(coin), parse_mode='Markdown', disable_web_page_preview=True)
        if len(new_coins) > 5:
            await update.message.reply_text(f"...та ще {len(new_coins) - 5}")
    else:
        await update.message.reply_text(f"📭 Нових немає.\nВсього: {len(coins)} позицій")
    
    monitor.previous_coins = coins
    monitor.save_coins(coins)

async def list_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = monitor.fetch_coins()
    if not coins:
        await update.message.reply_text("❌ Помилка отримання даних.")
        return
    
    available = [c for c in coins if c['status'] == "У продажу"]
    expected = [c for c in coins if c['status'] == "Очікується"]
    
    message = f"📋 *Каталог НБУ ({len(coins)})*\n\n"
    
    if available:
        message += f"🟢 *У ПРОДАЖУ ({len(available)}):*\n"
        for i, coin in enumerate(available[:10], 1):
            metal = f" | {coin.get('metal', '')}" if coin.get('metal') else ""
            message += f"{i}. [{coin['title']}]({coin['link']})\n   💰 {coin['price']}{metal}\n"
        if len(available) > 10:
            message += f"\n...ще {len(available) - 10}\n"
        message += "\n"
    
    if expected:
        message += f"⏳ *ОЧІКУЄТЬСЯ ({len(expected)}):*\n"
        for i, coin in enumerate(expected[:10], 1):
            metal = f" | {coin.get('metal', '')}" if coin.get('metal') else ""
            date = f" | {coin['expected_date']}" if coin.get('expected_date') else ""
            message += f"{i}. [{coin['title']}]({coin['link']}){metal}{date}\n"
        if len(expected) > 10:
            message += f"\n...ще {len(expected) - 10}\n"
    
    message += f"\n🔗 [Каталог](https://coins.bank.gov.ua/catalog.html)"
    await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last_check = "Не перевірялося"
    if monitor.previous_coins:
        try:
            last_date = max(coin['found_date'] for coin in monitor.previous_coins)
            last_check = datetime.fromisoformat(last_date).strftime('%d.%m.%Y %H:%M')
        except:
            pass
    
    available = sum(1 for c in monitor.previous_coins if c.get('status') == "У продажу")
    expected = sum(1 for c in monitor.previous_coins if c.get('status') == "Очікується")
    
    message = f"🤖 *Статус*\n\n"
    message += f"👥 Підписників: {len(monitor.subscribers)}\n"
    message += f"🪙 Монет: {len(monitor.previous_coins)}\n"
    message += f"   🟢 У продажу: {available}\n"
    message += f"   ⏳ Очікується: {expected}\n"
    message += f"🕐 Остання перевірка: {last_check}\n"
    message += f"⏰ Наступні: 9:00 та 22:00"
    await update.message.reply_text(message, parse_mode='Markdown')

async def test_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏰ Запускаю тестову перевірку...")
    try:
        await scheduled_check(context.application)
        await update.message.reply_text("✅ Тест завершено!")
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {str(e)[:200]}")

async def get_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_CHAT_ID and str(update.effective_chat.id) != ADMIN_CHAT_ID:
        await update.message.reply_text("🔒 Тільки для адміна.")
        return
    
    try:
        if not os.path.exists(LOG_FILE):
            await update.message.reply_text("📄 Логів немає.")
            return
        
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-50:]
        log_text = ''.join(lines)
        if len(log_text) > 4000:
            log_text = "...\n" + log_text[-4000:]
        await update.message.reply_text(f"📄 *Логи:*\n\n```\n{log_text}\n```", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔍 Перевірити зараз":
        await check_now(update, context)
    elif text == "📋 Список монет":
        await list_coins(update, context)
    elif text == "📊 Статус бота":
        await status(update, context)
    elif text == "🛑 Відписатися":
        await stop(update, context)

async def notify_admin(app, msg):
    if ADMIN_CHAT_ID:
        try:
            await app.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=f"🔔 {msg}", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Не вдалося надіслати адміну: {e}")

async def scheduled_check(app):
    logger.info("⏰ Запланована перевірка...")
    try:
        coins = monitor.fetch_coins()
        if coins is None:
            await notify_admin(app, "❌ Помилка перевірки сайту")
            return
        if not coins:
            await notify_admin(app, "⚠️ Монет не знайдено")
            return
        
        new_coins = monitor.find_new_coins(coins)
        if new_coins and monitor.subscribers:
            logger.info(f"🎉 {len(new_coins)} нових монет")
            for chat_id in monitor.subscribers:
                try:
                    await app.bot.send_message(chat_id=chat_id, text=f"🎉 *НОВІ МОНЕТИ!*\n\n{len(new_coins)} нових", parse_mode='Markdown')
                    for coin in new_coins:
                        await app.bot.send_message(chat_id=chat_id, text=monitor.format_coin_message(coin), parse_mode='Markdown', disable_web_page_preview=True)
                        time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Помилка {chat_id}: {e}")
            await notify_admin(app, f"✅ Надіслано про {len(new_coins)} монет")
        else:
            logger.info(f"ℹ️ Нових немає. Всього: {len(coins)}")
        
        monitor.previous_coins = coins
        monitor.save_coins(coins)
        logger.info("✅ Перевірка завершена")
    except Exception as e:
        logger.error(f"❌ Помилка: {e}")
        await notify_admin(app, f"❌ Критична помилка: {str(e)[:100]}")

app_instance = None

def schedule_checker(app):
    global app_instance
    app_instance = app
    
    def job():
        try:
            logger.info("🔔 Розклад спрацював")
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(scheduled_check(app_instance))
            loop.close()
        except Exception as e:
            logger.error(f"Помилка розкладу: {e}")
    
    schedule.every().day.at("09:00").do(job)
    schedule.every().day.at("22:00").do(job)
    logger.info("✅ Розклад: 9:00 та 22:00")

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        available = sum(1 for c in monitor.previous_coins if c.get('status') == "У продажу")
        expected = sum(1 for c in monitor.previous_coins if c.get('status') == "Очікується")
        html = f"""<html><body style="font-family:Arial;padding:20px;">
        <h1>🤖 NBU Coin Bot</h1>
        <p>✅ Running</p>
        <p>👥 Subscribers: {len(monitor.subscribers)}</p>
        <p>🪙 Coins: {len(monitor.previous_coins)}</p>
        <p>🟢 Available: {available}</p>
        <p>⏳ Expected: {expected}</p>
        <p>⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body></html>"""
        self.wfile.write(html.encode('utf-8'))
    def log_message(self, format, *args):
        pass

def run_health_server():
    try:
        server = HTTPServer(('0.0.0.0', 10000), HealthCheckHandler)
        logger.info("🏥 Health server on :10000")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health error: {e}")

def main():
    if TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ Потрібен TELEGRAM_TOKEN!")
        return
    
    logger.info("⏳ Чекаю 10 сек...")
    time.sleep(10)
    
    logger.info("🔍 Перевіряю токен...")
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=10)
        if r.status_code == 200:
            logger.info(f"✅ Бот: @{r.json()['result']['username']}")
        else:
            logger.error(f"❌ Токен помилка: {r.text}")
            return
    except Exception as e:
        logger.error(f"❌ Токен не перевірено: {e}")
        return
    
    if ADMIN_CHAT_ID:
        logger.info(f"📧 Адмін: {ADMIN_CHAT_ID}")
    else:
        logger.warning("⚠️ ADMIN_CHAT_ID не встановлено")
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("check", check_now))
    app.add_handler(CommandHandler("list", list_coins))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("test_schedule", test_schedule))
    app.add_handler(CommandHandler("logs", get_logs))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    schedule_checker(app)
    
    threading.Thread(target=run_health_server, daemon=True).start()
    
    logger.info("🤖 Бот запущено!")
    
    def run_schedule():
        logger.info("⏰ Розклад активний")
        while True:
            try:
                schedule.run_pending()
                time.sleep(30)
            except Exception as e:
                logger.error(f"Schedule error: {e}")
                time.sleep(60)
    
    threading.Thread(target=run_schedule, daemon=True).start()
    
    logger.info("🚀 Polling...")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, close_loop=False, poll_interval=2.0, timeout=60)
    except KeyboardInterrupt:
        logger.info("🛑 Зупинено")
    except Exception as e:
        logger.error(f"❌ Polling помилка: {e}")

if __name__ == "__main__":
    main()
