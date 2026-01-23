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
            try:
                with open("subscribers.json", "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def save_subscribers(self):
        """Зберегти список підписників"""
        try:
            with open("subscribers.json", "w", encoding="utf-8") as f:
                json.dump(self.subscribers, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Помилка збереження підписників: {e}")
    
    def load_previous_coins(self):
        """Завантажити попередній список монет"""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def save_coins(self, coins):
        """Зберегти поточний список монет"""
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(coins, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Помилка збереження монет: {e}")
    
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
            print(f"[{datetime.now()}] Розмір отриманої сторінки: {len(response.text)} символів")
            
            soup = BeautifulSoup(response.text, 'html.parser')
            coins = []
            
            # Шукаємо всі посилання на продукти
            all_links = soup.find_all('a', href=lambda x: x and '/p-' in x)
            print(f"[{datetime.now()}] Знайдено посилань з /p-: {len(all_links)}")
            
            # Беремо унікальні посилання
            seen_hrefs = {}
            for link in all_links:
                href = link.get('href')
                if href and href not in seen_hrefs:
                    # Беремо назву
                    title = link.get('title') or link.get_text(strip=True)
                    
                    if title and title.strip():
                        parent = link.find_parent(['div', 'article'])
                        seen_hrefs[href] = {
                            'title': title.strip(),
                            'link': href if href.startswith('http') else 'https://coins.bank.gov.ua' + href,
                            'element': parent
                        }
            
            print(f"[{datetime.now()}] Знайдено унікальних продуктів: {len(seen_hrefs)}")
            
            # Обробляємо кожен продукт
            for idx, (href, data) in enumerate(seen_hrefs.items(), 1):
                try:
                    title = data['title']
                    link = data['link']
                    parent = data['element']
                    
                    # Ціна
                    price = "Очікується"
                    if parent:
                        price_elem = parent.find('p', class_='price')
                        if price_elem:
                            price_text = price_elem.text.strip()
                            if price_text:
                                price = price_text
                    
                    # Статус - визначаємо правильно!
                    status = "Очікується"  # За замовчуванням
                    
                    # Перевіряємо чи є числова ціна
                    if price and price != "Очікується":
                        # Якщо в ціні є цифри і слово "грн" - це У ПРОДАЖУ
                        if re.search(r'\d+', price) and 'грн' in price.lower():
                            status = "У продажу"
                    
                    # Метал і тираж - ВИПРАВЛЕНО!
                    metal = ""
                    tirazh = ""
                    
                    if parent:
                        parent_text = parent.get_text(strip=True).upper()
                        
                        if 'ЗОЛОТО' in parent_text:
                            metal = "Золото"
                        elif 'СРІБЛО' in parent_text:
                            metal = "Срібло"
                        elif 'ІНША НУМІЗМАТИЧНА ПРОДУКЦІЯ' in parent_text or 'НУМІЗМАТИЧНА' in parent_text:
                            metal = "Інше"
                        
                        tirazh_match = re.search(r'ТИРАЖ\s+(\d+)', parent_text)
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
                    print(f"[{datetime.now()}] ✓ Продукт #{idx}: {title} - {price} ({status})")
                    
                except Exception as e:
                    print(f"[{datetime.now()}] ❌ Помилка обробки продукту #{idx}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            print(f"[{datetime.now()}] Успішно оброблено {len(coins)} монет/продуктів")
            return coins
            
        except requests.exceptions.RequestException as e:
            print(f"[{datetime.now()}] ❌ Помилка з'єднання з сайтом НБУ: {e}")
            return None
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Загальна помилка отримання даних: {e}")
            import traceback
            traceback.print_exc()
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
        # Тільки два статуси
        if coin['status'] == "У продажу":
            status_emoji = "🟢"
            status_text = "У ПРОДАЖУ - можна замовити!"
        else:
            status_emoji = "⏳"
            status_text = "ОЧІКУЄТЬСЯ - ще не в продажу"
        
        message = f"{status_emoji} *[{coin['title']}]({coin['link']})*\n\n"
        message += f"💰 Ціна: {coin['price']}\n"
        message += f"📊 Статус: {status_text}\n"
        if coin.get('metal'):
            message += f"⚜️ Метал: {coin['metal']}\n"
        if coin.get('tirazh'):
            message += f"📈 Тираж: {coin['tirazh']}\n"
        
        # Посилання
        if coin['status'] == "У продажу":
            message += f"\n🛒 [ЗАМОВИТИ]({coin['link']})"
        else:
            message += f"\n🔗 [Переглянути деталі]({coin['link']})"
        
        message += f"\n\n⏰ Знайдено: {datetime.fromisoformat(coin['found_date']).strftime('%d.%m.%Y %H:%M')}"
        return message

# Ініціалізація монітора
monitor = NBUCoinMonitor()

# Клавіатура з кнопками
def get_keyboard():
    """Повертає клавіатуру з кнопками"""
    keyboard = [
        [KeyboardButton("🔍 Перевірити зараз"), KeyboardButton("📋 Список монет")],
        [KeyboardButton("📊 Статус бота"), KeyboardButton("🛑 Відписатися")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    print(f"[{datetime.now()}] Отримано команду /start від {update.effective_chat.id}")
    chat_id = update.effective_chat.id
    
    if chat_id not in monitor.subscribers:
        monitor.subscribers.append(chat_id)
        monitor.save_subscribers()
        print(f"[{datetime.now()}] Новий підписник: {chat_id}")
        await update.message.reply_text(
            "✅ Вітаю! Ти підписаний на сповіщення про нові монети НБУ.\n\n"
            "Я буду перевіряти сайт двічі на день:\n"
            "🌅 О 9:00 ранку\n"
            "🌙 О 22:00 вечора\n\n"
            "Використовуй кнопки нижче для керування ботом:",
            reply_markup=get_keyboard()
        )
    else:
        await update.message.reply_text(
            "Ти вже підписаний на сповіщення! 👍\n\n"
            "Використовуй кнопки нижче:",
            reply_markup=get_keyboard()
        )

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
    await update.message.reply_text(
        "🔍 Перевіряю каталог НБУ...\n"
        "🔗 [Переглянути каталог вручну](https://coins.bank.gov.ua/catalog.html)",
        parse_mode='Markdown',
        disable_web_page_preview=True
    )
    
    coins = monitor.fetch_coins()
    
    if coins is None:
        await update.message.reply_text(
            "❌ Помилка при перевірці каталогу. Можливо, сайт НБУ тимчасово недоступний.\n"
            "Спробуй пізніше або перевір каталог вручну:\n"
            "🔗 https://coins.bank.gov.ua/catalog.html"
        )
        return
    
    if not coins:
        await update.message.reply_text(
            "📭 Не вдалося знайти продукцію в каталозі.\n"
            "Це може бути через зміну структури сайту або тимчасові проблеми.\n"
            "Перевір каталог вручну:\n"
            "🔗 https://coins.bank.gov.ua/catalog.html"
        )
        return
    
    new_coins = monitor.find_new_coins(coins)
    
    if new_coins:
        await update.message.reply_text(f"🎉 Знайдено {len(new_coins)} нову(-их) позицію(-ій)!")
        for coin in new_coins[:5]:
            message = monitor.format_coin_message(coin)
            await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)
        
        if len(new_coins) > 5:
            await update.message.reply_text(f"... та ще {len(new_coins) - 5} позицій")
    else:
        await update.message.reply_text(
            f"📭 Нових позицій не знайдено.\n"
            f"Всього в каталозі: {len(coins)} позицій\n\n"
            f"🔗 [Переглянути каталог](https://coins.bank.gov.ua/catalog.html)",
            parse_mode='Markdown',
            disable_web_page_preview=True
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
    
    # Тільки дві категорії
    available = [c for c in coins if c['status'] == "У продажу"]
    expected = [c for c in coins if c['status'] != "У продажу"]
    
    message = f"📋 *Каталог НБУ ({len(coins)} позицій)*\n\n"
    
    if available:
        message += f"🟢 *У ПРОДАЖУ ({len(available)}):*\n"
        for i, coin in enumerate(available, 1):
            metal_info = f" | {coin.get('metal', '')}" if coin.get('metal') else ""
            message += f"{i}. [{coin['title']}]({coin['link']})\n"
            message += f"   💰 {coin['price']}{metal_info}\n"
            message += f"   🛒 [Замовити]({coin['link']})\n\n"
    
    if expected:
        message += f"⏳ *ОЧІКУЄТЬСЯ ({len(expected)}):*\n"
        for i, coin in enumerate(expected, 1):
            metal_info = f" | {coin.get('metal', '')}" if coin.get('metal') else ""
            message += f"{i}. [{coin['title']}]({coin['link']}){metal_info}\n\n"
    
    message += f"\n🔗 [Переглянути весь каталог](https://coins.bank.gov.ua/catalog.html)"
    
    await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)

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
    message += f"⏰ Наступні перевірки:\n"
    message += f"   🌅 О 9:00 ранку\n"
    message += f"   🌙 О 22:00 вечора"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка текстових повідомлень (кнопок)"""
    text = update.message.text
    
    if text == "🔍 Перевірити зараз":
        await check_now(update, context)
    elif text == "📋 Список монет":
        await list_coins(update, context)
    elif text == "📊 Статус бота":
        await status(update, context)
    elif text == "🛑 Відписатися":
        await stop(update, context)

async def scheduled_check(application):
    """Запланована перевірка"""
    print(f"[{datetime.now()}] ⏰ Виконую заплановану перевірку...")
    
    coins = monitor.fetch_coins()
    
    if coins is None:
        print(f"[{datetime.now()}] ❌ Помилка при перевірці сайту")
        return
    
    if not coins:
        print(f"[{datetime.now()}] ⚠️ Не знайдено монет на сайті")
        return
    
    new_coins = monitor.find_new_coins(coins)
    
    if new_coins and monitor.subscribers:
        print(f"[{datetime.now()}] 🎉 Знайдено {len(new_coins)} нових монет. Надсилаю сповіщення...")
        
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
                    time.sleep(0.5)  # Щоб не заспамити
                
            except Exception as e:
                print(f"[{datetime.now()}] ❌ Помилка надсилання до {chat_id}: {e}")
    else:
        print(f"[{datetime.now()}] ℹ️ Нових монет не знайдено. Всього: {len(coins)}")
    
    monitor.previous_coins = coins
    monitor.save_coins(coins)
    print(f"[{datetime.now()}] ✅ Перевірка завершена")

# Глобальна змінна для application
app_instance = None

def schedule_checker(application):
    """Налаштування розкладу перевірок - ВИПРАВЛЕНО!"""
    global app_instance
    app_instance = application
    
    def job():
        """Синхронна обгортка для асинхронної функції"""
        try:
            print(f"[{datetime.now()}] 🔔 Спрацював розклад перевірки")
            # Створюємо нову event loop для цього потоку
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(scheduled_check(app_instance))
            loop.close()
        except Exception as e:
            print(f"[{datetime.now()}] ❌ Помилка в розкладі: {e}")
            import traceback
            traceback.print_exc()
    
    # Перевірка двічі на день
    schedule.every().day.at("09:00").do(job)
    schedule.every().day.at("22:00").do(job)
    
    print(f"[{datetime.now()}] ✅ Розклад налаштовано: перевірка о 9:00 та о 22:00")
    print(f"[{datetime.now()}] ⏰ Поточний час: {datetime.now().strftime('%H:%M:%S')}")

# HTTP сервер для Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        status_html = f"""
        <html>
        <head><meta charset="utf-8"><title>NBU Coin Bot Status</title></head>
        <body>
        <h1>🤖 NBU Coin Monitor Bot</h1>
        <p>✅ Bot is running</p>
        <p>👥 Subscribers: {len(monitor.subscribers)}</p>
        <p>🪙 Tracked coins: {len(monitor.previous_coins)}</p>
        <p>⏰ Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body>
        </html>
        """
        self.wfile.write(status_html.encode('utf-8'))
    
    def log_message(self, format, *args):
        # Логуємо тільки важливі запити
        pass

def run_health_server():
    try:
        server = HTTPServer(('0.0.0.0', 10000), HealthCheckHandler)
        print(f"[{datetime.now()}] 🏥 Health check server running on port 10000")
        server.serve_forever()
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Помилка health server: {e}")

def main():
    """Головна функція"""
    if TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ПОМИЛКА: Потрібно вказати токен бота!")
        print("Встанови змінну оточення TELEGRAM_TOKEN на Render")
        return
    
    print(f"[{datetime.now()}] ⏳ Чекаю 10 секунд перед запуском...")
    print("   (щоб попередні інстанси бота встигли завершитися)")
    time.sleep(10)
    
    print(f"[{datetime.now()}] 🔍 Перевіряю токен бота...")
    try:
        response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=10)
        if response.status_code == 200:
            bot_info = response.json()
            print(f"[{datetime.now()}] ✅ Токен валідний! Бот: @{bot_info['result']['username']}")
        else:
            print(f"[{datetime.now()}] ❌ Помилка токену: {response.text}")
            return
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Не вдалося перевірити токен: {e}")
        return
    
    # Створення застосунку
    print(f"[{datetime.now()}] 🔧 Створюю application...")
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Додавання обробників
    print(f"[{datetime.now()}] 📝 Реєструю обробники команд...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("check", check_now))
    application.add_handler(CommandHandler("list", list_coins))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print(f"[{datetime.now()}] ✅ Обробники команд зареєстровано")
    
    # Налаштування розкладу
    schedule_checker(application)
    
    # Запуск health check сервера
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    print(f"[{datetime.now()}] 🤖 Бот запущено!")
    print(f"[{datetime.now()}] 👥 Підписників: {len(monitor.subscribers)}")
    
    # Запуск розкладу в окремому потоці
    def run_schedule():
        print(f"[{datetime.now()}] ⏰ Розклад перевірок активовано")
        while True:
            try:
                schedule.run_pending()
                time.sleep(30)  # Перевіряємо кожні 30 секунд
            except Exception as e:
                print(f"[{datetime.now()}] ❌ Помилка в schedule loop: {e}")
                time.sleep(60)
    
    schedule_thread = threading.Thread(target=run_schedule, daemon=True)
    schedule_thread.start()
    
    # Запуск бота
    print(f"[{datetime.now()}] 🚀 Запускаю polling...")
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False,
            poll_interval=2.0,
            timeout=60,
            read_timeout=60,
            write_timeout=60,
            connect_timeout=60,
            pool_timeout=60
        )
    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] 🛑 Бот зупинено вручну")
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Помилка при запуску polling: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
