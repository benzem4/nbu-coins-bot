# Металл і тираж
                        metal = ""
                        tirazh = ""
                        if parent:
                            parent_text = parent.get_text()
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
            print(f"[{datetime.now()}] Розмір отриманої сторінки: {len(response.text)} символів")
            
            soup = BeautifulSoup(response.text, 'html.parser')
            coins = []
            
            # Спочатку шукаємо текст "Знайдено продукції"
            found_text = soup.find(string=lambda x: x and 'Знайдено продукції' in x)
            if found_text:
                print(f"[{datetime.now()}] Знайдено текст на сторінці: {found_text.strip()}")
            
            # На сторінці каталогу продукти мають клас product-layout
            products = soup.find_all('div', class_='product-layout')
            print(f"[{datetime.now()}] Знайдено product-layout елементів: {len(products)}")
            
            # Якщо не знайшли product-layout, пробуємо інші варіанти
            if not products:
                print(f"[{datetime.now()}] product-layout не знайдено, пробую інші варіанти...")
                
                # Варіант 2: шукаємо всі посилання на продукти
                all_links = soup.find_all('a', href=lambda x: x and '/p-' in x)
                print(f"[{datetime.now()}] Знайдено посилань з /p-: {len(all_links)}")
                
                # Беремо унікальні посилання (кожен продукт може мати кілька посилань)
                seen_hrefs = {}
                for link in all_links:
                    href = link.get('href')
                    if href and href not in seen_hrefs:
                        # Беремо назву з title або text
                        title = link.get('title')
                        if not title or title.strip() == '':
                            # Якщо немає title, беремо текст посилання
                            title = link.get_text(strip=True)
                        
                        if title and title.strip():
                            seen_hrefs[href] = {
                                'title': title.strip(),
                                'link': href if href.startswith('http') else 'https://coins.bank.gov.ua' + href,
                                'element': link.find_parent(['div', 'article'])
                            }
                
                print(f"[{datetime.now()}] Знайдено унікальних продуктів: {len(seen_hrefs)}")
                
                # Тепер обробляємо кожен знайдений продукт
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
                        
                        # Статус - ВАЖЛИВО: визначаємо правильно!
                        status = "У продажу"  # За замовчуванням
                        
                        if parent:
                            parent_text = parent.get_text()
                            
                            # Спочатку перевіряємо найспецифічніші статуси
                            if 'Очікується' in parent_text or price == "Очікується":
                                status = "Очікується"
                            elif 'скоро у продажу' in parent_text.lower():
                                status = "Скоро у продажу"
                            # Якщо є ціна в грн - це означає що в продажу
                            elif 'грн' in price:
                                status = "У продажу"
                            
                            if 'ЗОЛОТО' in parent_text:
                                metal = "Золото"
                            elif 'СРІБЛО' in parent_text:
                                metal = "Срібло"
                            elif 'ІНША НУМІЗМАТИЧНА ПРОДУКЦІЯ' in parent_text:
                                metal = "Інше"
                            
                            import re
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
                        continue
                
                if len(coins) > 0:
                    print(f"[{datetime.now()}] Успішно оброблено {len(coins)} монет/продуктів")
                    return coins
            
            if not products and len(coins) == 0:
                # Останя спроба - зберігаємо частину HTML для діагностики
                print(f"[{datetime.now()}] ❌ Не знайдено жодних продуктів!")
                print(f"[{datetime.now()}] Перші 500 символів HTML:")
                print(response.text[:500])
                return []
            
            for idx, product in enumerate(products, 1):
                try:
                    # Назва монети - шукаємо посилання з /p-
                    title = None
                    title_link = product.find('a', href=lambda x: x and '/p-' in x)
                    
                    if title_link:
                        # Спочатку пробуємо атрибут title
                        title = title_link.get('title')
                        # Якщо немає title, беремо текст
                        if not title or title.strip() == '':
                            title = title_link.text.strip()
                    
                    if not title or title == '':
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
                    product_text = product.get_text().lower()
                    if 'скоро у продажу' in product_text:
                        status = "Скоро у продажу"
                    elif 'очікується' in product_text:
                        status = "Очікується"
                    
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
                    print(f"[{datetime.now()}] ✓ Продукт #{idx}: {title} - {price} ({status})")
                    
                except Exception as e:
                    print(f"[{datetime.now()}] ❌ Помилка обробки продукту #{idx}: {e}")
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
        # Визначаємо емодзі статусу
        if coin['status'] == "У продажу":
            status_emoji = "🟢"
            status_text = "✅ У ПРОДАЖУ - можна замовити!"
        elif "очікується" in coin['status'].lower():
            status_emoji = "⏳"
            status_text = "⏳ Очікується - ще не надійшла у продаж"
        elif "скоро" in coin['status'].lower():
            status_emoji = "🔜"
            status_text = "🔜 Скоро у продажу - анонсовано"
        else:
            status_emoji = "📦"
            status_text = coin['status']
        
        message = f"{status_emoji} *[{coin['title']}]({coin['link']})*\n\n"
        message += f"💰 Ціна: {coin['price']}\n"
        message += f"📊 Статус: {status_text}\n"
        if coin.get('metal'):
            message += f"⚜️ Метал: {coin['metal']}\n"
        if coin.get('tirazh'):
            message += f"📈 Тираж: {coin['tirazh']}\n"
        
        # Додаємо правильне посилання залежно від статусу
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
    
    # Розділяємо монети за статусом
    available = [c for c in coins if c['status'] == "У продажу"]
    coming_soon = [c for c in coins if "скоро" in c['status'].lower()]
    expected = [c for c in coins if "очікується" in c['status'].lower()]
    
    message = f"📋 *Каталог НБУ ({len(coins)} позицій)*\n\n"
    
    if available:
        message += f"🟢 *У ПРОДАЖУ ({len(available)}):*\n"
        for i, coin in enumerate(available, 1):
            metal_info = f" | {coin.get('metal', '')}" if coin.get('metal') else ""
            # Додаємо посилання на замовлення
            message += f"{i}. [{coin['title']}]({coin['link']})\n"
            message += f"   💰 {coin['price']}{metal_info}\n"
            message += f"   🛒 [Замовити]({coin['link']})\n\n"
    
    if coming_soon:
        message += f"🔜 *СКОРО У ПРОДАЖУ ({len(coming_soon)}):*\n"
        for i, coin in enumerate(coming_soon, 1):
            metal_info = f" | {coin.get('metal', '')}" if coin.get('metal') else ""
            message += f"{i}. [{coin['title']}]({coin['link']}){metal_info}\n\n"
    
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
    
    # Перевірка двічі на день
    schedule.every().day.at("09:00").do(job)  # Ранкова перевірка
    schedule.every().day.at("22:00").do(job)  # Вечірня перевірка
    
    print("✅ Розклад налаштовано: перевірка о 9:00 та о 22:00")

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
    
    print("⏳ Чекаю 10 секунд перед запуском...")
    print("   (щоб попередні інстанси бота встигли завершитися)")
    time.sleep(10)
    
    print("🔍 Перевіряю токен бота...")
    try:
        import requests
        response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe")
        if response.status_code == 200:
            bot_info = response.json()
            print(f"✅ Токен валідний! Бот: @{bot_info['result']['username']}")
        else:
            print(f"❌ Помилка токену: {response.text}")
            return
    except Exception as e:
        print(f"❌ Не вдалося перевірити токен: {e}")
    
    # Створення застосунку
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Додавання обробників команд
    print("📝 Реєструю обробники команд...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("check", check_now))
    application.add_handler(CommandHandler("list", list_coins))
    application.add_handler(CommandHandler("status", status))
    
    # Обробник текстових повідомлень (кнопок)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Обробники команд зареєстровано")
    
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
    print("🚀 Запускаю polling...")
    print("⚠️  Якщо бот не реагує на команди, перевір чи правильний username бота в Telegram")
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,  # Ігнорувати старі оновлення
            close_loop=False,  # Не закривати event loop
            poll_interval=1.0,  # Інтервал опитування (секунди)
            timeout=30  # Таймаут запиту
        )
    except Exception as e:
        print(f"❌ Помилка при запуску polling: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import asyncio
    main()
