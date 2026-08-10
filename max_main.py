"""
MAX-бот (мессенджер VK): long polling + те же напоминания/сводки, что у TG-версии.
Запуск: python max_main.py
Требует MAX_TOKEN в .env (платформа business.max.ru -> Чат-боты -> Расширенные настройки).
"""
import logging
import threading
import time
from datetime import datetime

from config import MAX_TOKEN, MAX_ADMIN_ID
from database import *
from logging.handlers import RotatingFileHandler

# Логирование — только в файл (консоль зарезервирована под оверлей)
file_handler = RotatingFileHandler('max_bot.log', maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
file_handler.setFormatter(file_formatter)

logging.basicConfig(level=logging.INFO, handlers=[file_handler])
logger = logging.getLogger(__name__)

from max_client import MaxClient, MaxApiError
from max_handlers import MaxBot

# Типы событий, которые нас интересуют (остальные игнорируем на сервере)
UPDATE_TYPES = "message_created,message_callback,bot_started"


def main():
    if not MAX_TOKEN:
        print("[ERROR] MAX_TOKEN не найден в .env — укажите токен бота MAX")
        return

    init_db()
    add_sample_data()
    logger.info("MAX bot starting...")

    # Прогрев кэша
    try:
        get_services()
        get_portfolio()
        get_rating_stats()
        get_reviews()
    except Exception as e:
        logger.error(f"Cache warm error: {e}")

    client = MaxClient()
    bot = MaxBot(client)

    # Проверка токена ДО оверлея: нет смысла рисовать баннер, если бот не валиден.
    try:
        me = client.get_me()
        logger.info(f"Connected as: {me.get('name') or me.get('username') or '?'} (id={me.get('user_id')})")
        print(f"[OK] MAX-бот подключён: {me.get('name') or me.get('username') or '?'}")
    except MaxApiError as e:
        logger.error(f"Auth check failed: {e}")
        print(f"[ERROR] Не удалось подключиться к MAX API: {e}")
        return

    try:
        show_overlay()
    except Exception as e:
        logger.error(f"Overlay error: {e}")

    # Фоновый поток автообновления оверлея (как в TG-версии)
    def overlay_refresh_loop():
        time.sleep(10)
        while True:
            try:
                from overlay import refresh_overlay
                refresh_overlay()
            except Exception as e:
                logger.error(f"Overlay refresh error: {e}")
            time.sleep(30)

    threading.Thread(target=overlay_refresh_loop, daemon=True).start()

    # Фоновый поток напоминаний о записях (копия из main.py, отправка через MAX)
    def reminders_loop():
        time.sleep(20)
        last_today_summary = None
        while True:
            try:
                now = datetime.now()
                upcoming = get_bookings_to_notify(within_hours=24)
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
                               f"📍 г. Асбест, ул. Заводская, 4\n"
                               f"Пожалуйста, приходите за 15 минут до сеанса! 💛")
                        client.send_message(b['user_id'], msg)
                        mark_booking_notified(b['id'])
                        logger.info(f"MAX reminder sent: booking #{b['id']} -> user {b['user_id']}")
                    except Exception as e:
                        logger.error(f"MAX reminder error for booking #{b['id']}: {e}")
                        mark_booking_notified(b['id'])

                today_key = now.strftime('%Y-%m-%d')
                if last_today_summary != today_key and 8 <= now.hour < 12:
                    todays = get_today_bookings()
                    if todays and MAX_ADMIN_ID:
                        lines = [f"📋 <b>Записи на сегодня ({now.strftime('%d.%m.%Y')}):</b>\n"]
                        for t in sorted(todays, key=lambda x: x['date_time']):
                            name = t['first_name'] or 'Клиент'
                            uname = f"@{t['username']}" if t['username'] else ""
                            lines.append(f"• #{t['id']} {t['date_time'][11:16]} — {name} {uname} ({t['service']})")
                        try:
                            client.send_message(MAX_ADMIN_ID, "\n".join(lines))
                            last_today_summary = today_key
                            logger.info("MAX daily summary sent to admin")
                        except Exception as e:
                            logger.error(f"MAX daily summary error: {e}")
            except Exception as e:
                logger.error(f"MAX reminders loop error: {e}")
            time.sleep(600)

    threading.Thread(target=reminders_loop, daemon=True).start()
    logger.info("MAX reminders thread started (check every 10 min)")

    # Long polling с авто-восстановлением при сбое сети
    marker = None
    while True:
        try:
            updates, marker = client.poll_once(marker=marker, types=UPDATE_TYPES)
            for upd in updates:
                try:
                    bot.handle_update(upd)
                except Exception as e:
                    logger.error(f"Update handling error: {e}")
        except KeyboardInterrupt:
            logger.info("MAX-бот остановлен (Ctrl+C)")
            print("\n[OK] MAX-бот остановлен. Пока!")
            break
        except MaxApiError as e:
            logger.error(f"Polling crashed: {e}. Restarting in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Polling crashed (generic): {e}. Restarting in 5 seconds...")
            time.sleep(5)


if __name__ == "__main__":
    main()
