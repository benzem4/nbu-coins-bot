import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import schedule
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# Конфігурація
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
NBU_URL = "https://coins.bank.gov.ua/catalog.html"
DATA_FILE = "coins_data.json"

class NBUCoinMonitor:
    def __init__(self):
        self.subscribers = self.load_subscribers()
        self.previous_coins = self.load_previous_coins()
    
    def load_subscribers(self):
        """Завантажити список підписників"""
        if os.path.exists("subscribers.json"):
            with open("subscribers.json", "r", encoding="utf-8") as f:
                return json.load(f)
        return []
    
    def save_subscribers(self):
        """Зберегти список підписників"""
        with open("subscribers.json", "w", encoding="utf-8") as f:
            json.dump(self.subscribers, f, ensure_ascii=False, indent=2)
    
    def load_previous_coins(self):
        """Завантажити попередній список монет"""
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return []
    
    def save_coins(self, coins):
        """Зберегти поточний список монет"""
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(coins, f, ensure_ascii=False, indent=2)
    
    def fetch_coins(self):
        """Отримати список монет з сайту НБУ"""
        try:
            print(f"[{datetime.now()}] Починаю перевірку каталогу НБУ...")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
            }
            
            response = requests.get(NBU_URL, headers=headers, timeout=30)
            response.raise_for_status()
            print(f"[{datetime.now()}] Каталог НБУ доступний, статус: {response.status_code}")
            
            soup = BeautifulSoup(response.text, 'html.parser')
            coins = []
            
            # На сторінці каталогу продукти мають клас product-layout
            products = soup.find_all('div', class_='product-layout')
            print(f"[{datetime.now()}] Знайдено продуктів у каталозі: {len(products)}")
            
            for idx, product in enumerate(products, 1):
                try:
                    # Назва монети
                    title = None
                    title_link = product.find('a', href=lambda x: x and '/p-' in x)
                    if title_link:
                        title = title_link.get('title') or title_link.text.strip()
                    
                    if not title:
                        print(f"[{datetime.now()}] Продукт #{idx}: не знайдено назву, пропускаю")
                        continue
                    
                    # Ціна
                    price = "Очікується"
                    price_elem = product.find('p', class_='price')
                    if price_elem:
                        price_text = price_elem.text.strip()
                        if price_text and price_text != "":
                            price = price_text
                    
                    # Посилання
                    link = ""
                    if title_link and title_link.get('href'):
                        link = title_link.get('href')
                        if not link.startswith('http'):
                            link = 'https://coins.bank.gov.ua' + link
                    
                    # Статус (в наявності / скоро у продажу / очікується)
                    status = "У продажу"
                    
                    # Перевіряємо чи є маркер "скоро у продажу"
                    soon_marker = product.find('div', class_='sticker-special')
                    if soon_marker and 'скоро у продажу' in soon_marker.text.lower():
                        status = "Скоро у продажу"
                    
                    # Додаткова інформація (метал, тираж)
                    info_text = product.get_text()
                    
                    # Визначаємо метал
                    metal = ""
                    if 'ЗОЛОТО' in info_text:
                        metal = "Золото"
                    elif 'СРІБЛО' in info_text:
                        metal = "Срібло"
                    elif 'ІНША НУМІЗМАТИЧНА ПРОДУКЦІЯ' in info_text:
                        metal = "Інше"
                    
                    # Тираж
                    tirazh = ""
                    import re
                    tirazh_match = re.search(r'ТИРАЖ\s+(\d+)', info_text)
                    if tirazh_match:
                        tirazh = tirazh_match.group(1)
                    
                    coin = {
                        'title': title,
                        'price': price,
                        'link': link,
                        'status': status,
                        'metal': metal,
                        'tirazh': tirazh,
                        'found_date': datetime.now().isoformat()
                    }
                    coins.append(coin)
                    print(f"[{datetime.now()}] Продукт #{idx}: {title} - {price} ({status})")
                    
                except Exception as e:
                    print(f"[{datetime.now()}] Помилка обробки продукту #{idx}: {e}")
                    continue
            
            print(f"[{datetime.now()}] Успішно оброблено {len(coins)} монет/продуктів")
            return coins
            
        except requests.exceptions.RequestException as e:
            print(f"[{datetime.now()}] Помилка з'єднання з сайтом НБУ: {e}")
            return None
        except Exception as e:
            print(f"[{datetime.now()}] Загальна помилка отримання даних: {e}")
            return None
    
    def find_new_coins(self, current_coins):
        """Знайти нові монети"""
        if not self.previous_coins:
            return []
        
        previous_titles = {coin['title'] for coin in self.previous_coins}
        new_coins = [coin for coin in current_coins if coin['title'] not in previous_titles]
        
        return new_coins
    
    def format_coin_message(self, coin):
        """Форматувати повідомлення про монету"""
        message = f"🪙 *{coin['title']}*\n\n"
        message += f"💰 Ціна: {coin['price']}\n"
        message += f"📊 Статус: {coin['status']}\n"
        if coin.get('metal'):
            message += f"⚜️ Метал: {coin['metal']}\n"
        if coin.get('tirazh'):
            message += f"📈 Тираж: {coin['tirazh']}\n"
        if coin['link']:
            message += f"🔗 [Переглянути на сайті]({coin['link']})\n"
        message += f"\n⏰ Знайдено: {datetime.fromisoformat(coin['found_date']).strftime('%d.%m.%Y %H:%M')}"
        return message

# Ініціалізація монітора
monitor = NBUCoinMonitor()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    chat_id = update.effective_chat.id
    
    if chat_id not in monitor.subscribers:
        monitor.subscribers.append(chat_id)
        monitor.save_subscribers()
        await update.message.reply_text(
            "✅ Вітаю! Ти підписаний на сповіщення про нові монети НБУ.\n\n"
            "Я буду перевіряти сайт щодня о 14:00 та сповіщати про нові випуски.\n\n"
            "Доступні команди:\n"
            "/start - Підписатися на сповіщення\n"
            "/stop - Відписатися від сповіщень\n"
            "/check - Перевірити зараз\n"
            "/list - Показати всі поточні монети\n"
            "/status - Статус бота"
        )
    else:
        await update.message.reply_text("Ти вже підписаний на сповіщення! 👍")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stop"""
    chat_id = update.effective_chat.id
    
    if chat_id in monitor.subscribers:
        monitor.subscribers.remove(chat_id)
        monitor.save_subscribers()
        await update.message.reply_text("😢 Ти відписаний від сповіщень. Повертайся!")
    else:
        await update.message.reply_text("Ти не був підписаний.")

async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /check - перевірити зараз"""
    await update.message.reply_text("🔍 Перевіряю сайт НБУ...")
    
    coins = monitor.fetch_coins()
    
    if coins is None:
        await update.message.reply_text(
            "❌ Помилка при перевірці сайту. Можливо, сайт НБУ тимчасово недоступний.\n"
            "Спробуй пізніше або перевір сайт вручну: https://coins.bank.gov.ua/"
        )
        return
    
    if not coins:
        await update.message.reply_text(
            "📭 Не вдалося знайти монети в каталозі.\n"
            "Це може бути через зміну структури сайту або тимчасові проблеми.\n"
            "Перевір каталог вручну: https://coins.bank.gov.ua/catalog.html"
        )
        return
    
    new_coins = monitor.find_new_coins(coins)
    
    if new_coins:
        await update.message.reply_text(f"🎉 Знайдено {len(new_coins)} нову(-их) монету(-и)!")
        for coin in new_coins[:5]:  # Обмежуємо 5 монетами
            message = monitor.format_coin_message(coin)
            await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)
        
        if len(new_coins) > 5:
            await update.message.reply_text(f"... та ще {len(new_coins) - 5} монет(-и)")
    else:
        await update.message.reply_text(
            f"📭 Нових монет не знайдено.\n"
            f"Всього на сайті: {len(coins)} монет(-и)"
        )
    
    monitor.previous_coins = coins
    monitor.save_coins(coins)

async def list_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /list - показати всі монети"""
    coins = monitor.fetch_coins()
    
    if coins is None:
        await update.message.reply_text("❌ Помилка при отриманні даних з каталогу НБУ.")
        return
    
    if not coins:
        await update.message.reply_text(
            "📭 Не вдалося знайти монети в каталозі.\n"
            "Перевір каталог вручну: https://coins.bank.gov.ua/catalog.html"
        )
        return
    
    await update.message.reply_text(f"📋 Знайдено {len(coins)} продуктів у каталозі:\n")
    
    # Показуємо всі монети
    for i, coin in enumerate(coins, 1):
        metal_info = f" | {coin.get('metal', '')}" if coin.get('metal') else ""
        tirazh_info = f" | Тираж: {coin.get('tirazh', '')}" if coin.get('tirazh') else ""
        message = f"{i}. {coin['title']}\n   💰 {coin['price']} | 📊 {coin['status']}{metal_info}{tirazh_info}"
        await update.message.reply_text(message)
        
        # Невелика пауза між повідомленнями
        if i < len(coins):
            await asyncio.sleep(0.3)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status"""
    last_check = "Ще не перевірялося"
    if monitor.previous_coins:
        try:
            last_date = max(coin['found_date'] for coin in monitor.previous_coins)
            last_check = datetime.fromisoformat(last_date).strftime('%d.%m.%Y %H:%M')
        except:
            pass
    
    message = f"🤖 *Статус бота*\n\n"
    message += f"👥 Підписників: {len(monitor.subscribers)}\n"
    message += f"🪙 Відстежується монет: {len(monitor.previous_coins)}\n"
    message += f"🕐 Остання перевірка: {last_check}\n"
    message += f"⏰ Наступна перевірка: щодня о 14:00"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def scheduled_check(application):
    """Запланована перевірка"""
    print(f"[{datetime.now()}] Виконую заплановану перевірку...")
    
    coins = monitor.fetch_coins()
    
    if coins is None:
        print("Помилка при перевірці сайту")
        return
    
    new_coins = monitor.find_new_coins(coins)
    
    if new_coins and monitor.subscribers:
        print(f"Знайдено {len(new_coins)} нових монет. Надсилаю сповіщення...")
        
        for chat_id in monitor.subscribers:
            try:
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=f"🎉 *НОВІ МОНЕТИ НБУ!*\n\nЗнайдено {len(new_coins)} нову(-их) монету(-и):",
                    parse_mode='Markdown'
                )
                
                for coin in new_coins:
                    message = monitor.format_coin_message(coin)
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                
                time.sleep(1)
                
            except Exception as e:
                print(f"Помилка надсилання до {chat_id}: {e}")
    
    monitor.previous_coins = coins
    monitor.save_coins(coins)
    print("Перевірка завершена")

def schedule_checker(application):
    """Налаштування розкладу перевірок"""
    import asyncio
    
    async def run_check():
        await scheduled_check(application)
    
    def job():
        asyncio.run(run_check())
    
    # Перевірка щодня о 14:00
    schedule.every().day.at("14:00").do(job)
    
    print("✅ Розклад налаштовано: перевірка щодня о 14:00")

# Простий HTTP сервер для Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running')
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(('0.0.0.0', 10000), HealthCheckHandler)
    server.serve_forever()

def main():
    """Головна функція"""
    if TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ПОМИЛКА: Потрібно вказати токен бота!")
        print("Встанови змінну оточення TELEGRAM_TOKEN на Render")
        return
    
    # Створення застосунку
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Додавання обробників команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("check", check_now))
    application.add_handler(CommandHandler("list", list_coins))
    application.add_handler(CommandHandler("status", status))
    
    # Налаштування розкладу
    schedule_checker(application)
    
    # Запуск health check сервера
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    print("✅ Health check server started on port 10000")
    
    # Запуск бота
    print("🤖 Бот запущено!")
    print(f"👥 Підписників: {len(monitor.subscribers)}")
    
    # Запуск в окремому потоці для виконання розкладу
    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    schedule_thread = threading.Thread(target=run_schedule, daemon=True)
    schedule_thread.start()
    
    # Запуск бота з обробкою помилок
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True  # Ігнорувати старі оновлення
    )

if __name__ == "__main__":
    import asyncio
    main()
