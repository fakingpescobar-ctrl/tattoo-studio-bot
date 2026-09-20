"""
Telegram Bot for Tattoo Studio
Built with pyTelegramBotAPI (telebot) + requests
"""
import logging
import threading
import time
from datetime import datetime

import telebot
from telebot import types
from telebot.apihelper import ApiException

from config import BOT_TOKEN, ADMIN_ID, BOT_ADDRESS
from collections import defaultdict
from database import *
from keyboards import *
from logging.handlers import RotatingFileHandler

# Настройка логирования — только в файл (консоль зарезервирована под оверлей)
file_handler = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
file_handler.setFormatter(file_formatter)

logging.basicConfig(level=logging.INFO, handlers=[file_handler])
logger = logging.getLogger(__name__)

# Подавляем логи telebot
logging.getLogger('telebot').setLevel(logging.WARNING)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# Rate-limiting
USER_COMMANDS = defaultdict(list)  # user_id -> список времени вызовов
RATE_LIMIT_WINDOW = 60  # сек
RATE_LIMIT_COUNT = 5
RATE_LIMIT_BLOCK = 10  # сек
BLOCKED_USERS = {}  # user_id -> время разблокировки

# Импорт и регистрация хендлеров
from handlers import register_callbacks
register_callbacks(bot, USER_COMMANDS, RATE_LIMIT_WINDOW, RATE_LIMIT_COUNT, RATE_LIMIT_BLOCK, BLOCKED_USERS)

# Состояния (FSM через user_data)
# FSM теперь в базе данных — см. database.py
# set_state → save_state
# get_state, get_data → get_state
# clear_state → clear_state
# Все хендлеры перенесены в handlers.py

# Все функции перенесены в handlers.py


# Все хендлеры перенесены в handlers.py


# ============ ЗАПУСК ============

if __name__ == "__main__":
    init_db()
    add_sample_data()
    # Прогрев кэша
    logger.info("Warming cache...")
    get_services()
    get_portfolio()
    get_rating_stats()
    get_reviews()
    get_user_bookings(ADMIN_ID)
    logger.info("Cache warmed!")
    # Консольный оверлей (neofetch-баннер) + фоновый поток автообновления.
    # Админка теперь — отдельное Electron-приложение (admin/), данные через admin_api.py.
    try:
        from overlay import show_overlay
        show_overlay()
    except Exception as e:
        logger.error(f"Overlay error: {e}")

    def overlay_refresh_loop():
        time.sleep(10)
        while True:
            try:
                from overlay import refresh_overlay
                refresh_overlay()
            except Exception as e:
                logger.error(f"Overlay refresh error: {e}")
            time.sleep(30)

    refresh_thread = threading.Thread(target=overlay_refresh_loop, daemon=True)
    refresh_thread.start()
    logger.info("Overlay auto-refresh started (every 30s)")

    # Фоновый поток напоминаний о записях (проверяет каждые 10 минут)
    def reminders_loop():
        from datetime import datetime
        time.sleep(20)  # даём боту стартовать
        last_today_summary = None  # дата последней отправленной сводки (YYYY-MM-DD)
        while True:
            try:
                now = datetime.now()
                # 1. Напоминания клиентам: запись в течение 24ч и ещё не уведомлена
                upcoming = get_bookings_to_notify(within_hours=24, platform='telegram')
                for b in upcoming:
                    try:
                        dt = datetime.strptime(b['date_time'].strip(), '%d.%m.%Y %H:%M')
                        if now.date() == dt.date():
                            when = f"сегодня в {dt.strftime('%H:%M')}"
                        else:
                            when = f"завтра в {dt.strftime('%H:%M')}"
                        msg = (f"🔔 <b>Напоминание о записи!</b>\n\n"
                               f"📝 {b['service']}\n"
                               f"📅 {when}\n\n"
                               f"📍 {BOT_ADDRESS}\n"
                               f"Пожалуйста, приходите за 15 минут до сеанса! 💛")
                        bot.send_message(b['user_id'], msg)
                        mark_booking_notified(b['id'])
                        logger.info(f"Reminder sent: booking #{b['id']} -> user {b['user_id']}")
                    except Exception as e:
                        # Не помечаем notified при фейле — попробуем в следующем проходе
                        logger.error(f"Reminder error for booking #{b['id']}: {e}")

                # 2. Утренняя сводка админу о сегодняшних записях (один раз в день)
                today_key = now.strftime('%Y-%m-%d')
                if last_today_summary != today_key and 8 <= now.hour < 12:
                    todays = get_today_bookings()
                    if todays:
                        lines = [f"📋 <b>Записи на сегодня ({now.strftime('%d.%m.%Y')}):</b>\n"]
                        for t in sorted(todays, key=lambda x: x['date_time']):
                            name = t['first_name'] or 'Клиент'
                            uname = f"@{t['username']}" if t['username'] else ""
                            lines.append(f"• #{t['id']} {t['date_time'][11:16]} — {name} {uname} ({t['service']})")
                        try:
                            bot.send_message(ADMIN_ID, "\n".join(lines))
                            last_today_summary = today_key
                            logger.info("Daily summary sent to admin")
                        except Exception as e:
                            logger.error(f"Daily summary error: {e}")
            except Exception as e:
                logger.error(f"Reminders loop error: {e}")
            time.sleep(600)  # проверяем каждые 10 минут

    reminders_thread = threading.Thread(target=reminders_loop, daemon=True)
    reminders_thread.start()
    logger.info("Reminders thread started (check every 10 min)")

    # Фоновый поток обновления закреплённых календарей админа (при смене epoch)
    def admin_cal_refresh_loop():
        from handlers import refresh_admin_calendars, _admin_cal_msg
        from database import _db_epoch
        time.sleep(15)
        last_epoch = _db_epoch()
        while True:
            try:
                current_epoch = _db_epoch()
                if current_epoch and current_epoch != last_epoch and _admin_cal_msg:
                    refresh_admin_calendars()
                    logger.info("Admin calendars refreshed (epoch change)")
                    last_epoch = current_epoch
            except Exception as e:
                logger.error(f"Admin cal refresh error: {e}")
            time.sleep(15)

    admin_cal_thread = threading.Thread(target=admin_cal_refresh_loop, daemon=True)
    admin_cal_thread.start()
    logger.info("Admin calendar auto-refresh started (every 15s, epoch-based)")

    # infinity_polling с авто-восстановлением при сбое сети
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
        except KeyboardInterrupt:
            # Чистый выход по Ctrl+C — без пугающего трейса из ssl.read()
            logger.info("Бот остановлен (Ctrl+C)")
            print("\n[OK] Бот остановлен. Пока!")
            break
        except Exception as e:
            logger.error(f"Polling crashed: {e}. Restarting in 5 seconds...")
            time.sleep(5)
