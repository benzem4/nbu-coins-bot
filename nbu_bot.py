import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import schedule
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Конфігурація
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")  # Отримаєш від @BotFather
NBU_URL = "https://coins.bank.gov.ua/"
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
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(NBU_URL, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            coins = []
            
            # Шукаємо всі продукти на головній сторінці
            products = soup.find_all('div', class_='product-layout')
            
            for product in products:
                try:
                    title_elem = product.find('div', class_='name')
                    if title_elem and title_elem.find('a'):
                        title = title_elem.find('a').text.strip()
                        
                        # Ціна
                        price_elem = product.find('p', class_='price')
                        price = price_elem.text.strip() if price_elem else "Не вказано"
                        
                        # Посилання
                        link_elem = product.find('a')
                        link = link_elem['href'] if link_elem and 'href' in link_elem.attrs else ""
                        
                        # Статус (в наявності, скоро у продажу тощо)
                        status_elem = product.find('span', class_='stock')
                        status = status_elem.text.strip() if status_elem else "У продажу"
                        
                        coin = {
                            'title': title,
                            'price': price,
                            'link': link,
                            'status': status,
                            'found_date': datetime.now().isoformat()
                        }
                        coins.append(coin)
                except Exception as e:
                    print(f"Помилка обробки продукту: {e}")
                    continue
            
            return coins
            
        except Exception as e:
            print(f"Помилка отримання даних: {e}")
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
            "Я буду перевіряти сайт щодня о 10:00 та сповіщати про нові випуски.\n\n"
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
        await update.message.reply_text("❌ Помилка при перевірці сайту. Спробуй пізніше.")
        return
    
    new_coins = monitor.find_new_coins(coins)
    
    if new_coins:
        await update.message.reply_text(f"🎉 Знайдено {len(new_coins)} нову(-их) монету(-и)!")
        for coin in new_coins:
            message = monitor.format_coin_message(coin)
            await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)
    else:
        await update.message.reply_text("📭 Нових монет не знайдено.")
    
    monitor.previous_coins = coins
    monitor.save_coins(coins)

async def list_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /list - показати всі монети"""
    coins = monitor.fetch_coins()
    
    if coins is None:
        await update.message.reply_text("❌ Помилка при отриманні даних.")
        return
    
    if not coins:
        await update.message.reply_text("📭 Монет не знайдено на сайті.")
        return
    
    await update.message.reply_text(f"📋 Знайдено {len(coins)} монет(-и) на сайті:\n")
    
    # Показуємо по 5 монет за раз
    for i, coin in enumerate(coins[:10], 1):
        message = f"{i}. {coin['title']}\n   💰 {coin['price']} | 📊 {coin['status']}"
        await update.message.reply_text(message)
    
    if len(coins) > 10:
        await update.message.reply_text(f"... та ще {len(coins) - 10} монет(-и)")

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
                
                time.sleep(1)  # Пауза між повідомленнями
                
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
    
    # Також можна додати додаткові перевірки:
    # schedule.every().day.at("10:00").do(job)
    # schedule.every().day.at("18:00").do(job)
    
    print("✅ Розклад налаштовано: перевірка щодня о 14:00")

def main():
    """Головна функція"""
    if TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ПОМИЛКА: Потрібно вказати токен бота!")
        print("Отримай токен від @BotFather і вкажи його в змінній TELEGRAM_TOKEN")
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
    
    # Запуск бота
    print("🤖 Бот запущено!")
    print(f"👥 Підписників: {len(monitor.subscribers)}")
    
    # Запуск в окремому потоці для виконання розкладу
    import threading
    
    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    schedule_thread = threading.Thread(target=run_schedule, daemon=True)
    schedule_thread.start()
    
    # Запуск бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
