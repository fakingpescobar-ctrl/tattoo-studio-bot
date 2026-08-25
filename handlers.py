import logging
from datetime import datetime
import time
from functools import wraps

import telebot
from telebot import types
from telebot.apihelper import ApiException

def timing(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start
            if duration > 2.0:  # Логируем только если дольше 2 секунд
                logger.warning(f"{func.__name__} slow: {duration:.3f}s")
            return result
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            raise
    return wrapper

from config import (ADMIN_ID, ADMIN_IDS, BOT_ADDRESS, BOT_PHONE,
                    BOT_VK_LABEL, BOT_VK_URL)
from common import (ACTIVE_BOOKING_STATUSES, BOOKING_STATUS_RU,
                    booking_to_slot_key, fmt_dt, price_text, slot_key)
from database import *
from keyboards import *

import database

# Оверлей обновляется только для админа
import threading
_overlay_lock = threading.Lock()

def refresh_overlay_async():
    """Обновляет оверлей в отдельном потоке (чтобы не блокировать обработку)"""
    try:
        from overlay import refresh_overlay
        with _overlay_lock:
            refresh_overlay()
    except Exception:
        pass

logger = logging.getLogger(__name__)

# Rate-limiting будет передан через параметры при регистрации

def is_admin(user_id):
    return user_id in ADMIN_IDS


def register_callbacks(bot, user_commands, rate_limit_window, rate_limit_count, rate_limit_block, blocked_users):

    def notify_admin(text):
        """Отправляет уведомление админу"""
        if ADMIN_ID:
            try:
                bot.send_message(ADMIN_ID, text)
            except Exception as e:
                logger.error(f"notify_admin error: {e}")

    @bot.message_handler(commands=['start'])
    @timing
    def cmd_start(message):
        user = message.from_user
        now = time.time()

        if user.id in blocked_users and now < blocked_users[user.id]:
            bot.send_message(message.chat.id, "🚫 Вы временно заблокированы за спам. Попробуйте позже.")
            return

        user_commands[user.id].append(now)
        user_commands[user.id] = [t for t in user_commands[user.id] if now - t < rate_limit_window]

        if len(user_commands[user.id]) > rate_limit_count:
            blocked_users[user.id] = now + rate_limit_block
            bot.send_message(message.chat.id, "🚫 Слишком много запросов. Вы заблокированы на 10 секунд.")
            return

        save_user(user.id, user.username, user.first_name, user.last_name)
        database.clear_state(user.id)

        avg, cnt = get_rating_stats()
        rating_line = f"⭐ Рейтинг: {avg:.1f} ({cnt} отзывов)" if cnt else "⭐ Будь первым!"

        welcome = (f"👋 Привет, {user.first_name}!\n\n"
                    f"Я тату-мастер <b>Максим Андреевич</b>. Добро пожаловать! 🎨\n\n"
                    f"Здесь ты можешь:\n"
                    f"• 🎨 Посмотреть портфолио работ\n"
                    f"• 📅 Записаться на татуировку\n"
                    f"• 💰 Узнать цены\n"
                    f"• ⭐ Читать и оставлять отзывы\n"
                    f"• 👤 Управлять своими записями\n\n"
                    f"{rating_line}\n\nВыбери нужный раздел 👇")
        bot.send_message(message.chat.id, welcome, reply_markup=get_main_menu(is_admin(user.id)))

    @bot.callback_query_handler(func=lambda c: True)
    @timing
    def callback_handler(call):
        user_id = call.from_user.id
        data = call.data

        try:
            if data == "menu":
                database.clear_state(user_id)
                try:
                    bot.edit_message_text("🎨 <b>Главное меню</b>\n\nВыбери раздел:",
                                        call.message.chat.id, call.message.message_id,
                                        reply_markup=get_main_menu(is_admin(user_id)))
                except Exception:
                    # Не удалось отредактировать (фото-сообщение) — удаляем старое и шлём новое
                    try:
                        bot.delete_message(call.message.chat.id, call.message.message_id)
                    except Exception:
                        pass
                    bot.send_message(call.message.chat.id,
                                     "🎨 <b>Главное меню</b>\n\nВыбери раздел:",
                                     reply_markup=get_main_menu(is_admin(user_id)))
            elif data == "portfolio":
                show_portfolio(call)
            elif data.startswith("port_"):
                show_portfolio(call, int(data.split("_")[1]))
            elif data == "price":
                show_price(call)
            elif data == "about":
                show_about(call)
            elif data == "reviews":
                show_reviews(call)
            elif data == "add_review":
                save_state(user_id, 'review_rating')
                bot.edit_message_text("✍️ <b>Оставить отзыв</b>\n\nОцените работу мастера от 1 до 5 звёзд:",
                                    call.message.chat.id, call.message.message_id,
                                    reply_markup=get_rating_keyboard())
            elif data.startswith("rating_"):
                rating = int(data.split("_")[1])
                save_state(user_id, 'review_text', {'rating': rating})
                bot.edit_message_text(f"Вы поставили {'⭐' * rating}\n\nНапишите текст отзыва:",
                                    call.message.chat.id, call.message.message_id)
            elif data == "my_bookings":
                show_my_bookings(call)
            elif data.startswith("my_cancel_"):
                client_cancel_booking(call, int(data.split("_")[2]))
            elif data.startswith("confirm_my_cancel_"):
                confirm_client_cancel(call, int(data.split("_")[3]))
                return
            elif data == "booking_start":
                save_state(user_id, 'booking_service')
                start_booking(call)
            elif data.startswith("service_"):
                select_service(call, int(data.split("_")[1]))
            elif data.startswith("cal_month_"):
                parts = data.split("_")
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                            reply_markup=get_calendar_keyboard(int(parts[2]), int(parts[3])))
            elif data == "cal_back":
                now = datetime.now()
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                            reply_markup=get_calendar_keyboard(now.year, now.month))
            elif data.startswith("cal_day_"):
                parts = data.split("_")
                y, m, d = int(parts[2]), int(parts[3]), int(parts[4])
                blocked = get_blocked_slots()
                bot.edit_message_text(f"Выберите время на {d:02d}.{m:02d}.{y}:",
                                    call.message.chat.id, call.message.message_id,
                                    reply_markup=get_time_slots_keyboard(y, m, d, blocked))
            elif data.startswith("cal_time_"):
                parts = data.split("_")
                y, m, d, h = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
                select_time(call, y, m, d, h)
            elif data == "booking_confirm":
                confirm_booking(call)
            elif data == "booking_cancel":
                cancel_booking_confirm(call)
            elif data == "admin":
                if is_admin(user_id):
                    bot.edit_message_text("🔧 <b>Админ-панель</b>\n\nВыберите действие:",
                                        call.message.chat.id, call.message.message_id,
                                        reply_markup=get_admin_keyboard())
            elif data == "admin_bookings":
                admin_show_bookings(call)
            elif data.startswith("admin_booking_"):
                admin_booking_detail(call, int(data.split("_")[2]))
            elif data.startswith(("ab_confirm_", "ab_cancel_", "ab_complete_", "ab_msg_")):
                admin_booking_action(call, data.split("_")[1], int(data.split("_")[2]))
            elif data == "admin_add_work":
                if is_admin(user_id):
                    save_state(user_id, 'add_photo')
                    bot.edit_message_text("➕ <b>Добавление работы</b>\n\nШаг 1/4: отправьте фото работы",
                                        call.message.chat.id, call.message.message_id)
            elif data == "admin_portfolio":
                admin_manage_portfolio(call)
            elif data.startswith("del_work_"):
                admin_delete_work(call, int(data.split("_")[2]))
            elif data == "admin_slots":
                admin_show_slots(call)
            elif data.startswith("admin_cal_month_"):
                parts = data.split("_")
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                            reply_markup=get_admin_calendar_keyboard(int(parts[3]), int(parts[4])))
            elif data == "admin_cal_back":
                now = datetime.now()
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                            reply_markup=get_admin_calendar_keyboard(now.year, now.month))
            elif data.startswith("admin_cal_day_"):
                parts = data.split("_")
                y, m, d = int(parts[3]), int(parts[4]), int(parts[5])
                blocked = get_blocked_slots()
                bot.edit_message_text(f"🚫 <b>Блокировка на {d:02d}.{m:02d}.{y}</b>\n\n"
                                    f"Свободное время — нажмите, чтобы заблокировать.\n"
                                    f"🔒 — уже заблокировано.",
                             call.message.chat.id, call.message.message_id,
                             reply_markup=get_admin_time_keyboard(y, m, d, blocked))
            elif data.startswith("admin_cal_time_"):
                parts = data.split("_")
                y, m, d, h = int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6])
                sk = slot_key(y, m, d, h)
                add_blocked_slot(sk)
                blocked = get_blocked_slots()
                bot.answer_callback_query(call.id, f"🚫 Заблокировано: {h:02d}:00", show_alert=True)
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                            reply_markup=get_admin_time_keyboard(y, m, d, blocked))
            elif data.startswith("admin_block_day_"):
                parts = data.split("_")
                y, m, d = int(parts[3]), int(parts[4]), int(parts[5])
                cnt = block_full_day(y, m, d)
                if cnt:
                    bot.answer_callback_query(call.id,
                        f"🔒 День {d:02d}.{m:02d}.{y} заблокирован ({cnt} слотов)!", show_alert=True)
                else:
                    bot.answer_callback_query(call.id,
                        "⚠️ Нечего блокировать: день/часы уже прошли", show_alert=True)
                blocked = get_blocked_slots()
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                            reply_markup=get_admin_time_keyboard(y, m, d, blocked))
            elif data.startswith("admin_reply_review_"):
                review_id = int(data.split("_")[3])
                save_state(user_id, 'admin_review_reply', {'review_id': review_id})
                bot.edit_message_text("💬 <b>Ответ на отзыв</b>\n\nНапишите текст ответа:",
                                     call.message.chat.id, call.message.message_id)
            elif data == "ignore":
                pass
        except ApiException as e:
            # Ошибки Telegram API (сообщение не найдено, протухло и т.д.) — тихо логируем
            logger.warning(f"API: {e}")
        except Exception as e:
            # Сетевые ошибки — тихо, без трейсбека (интернет моргнул)
            import requests.exceptions
            if isinstance(e, (requests.exceptions.ConnectionError,
                              requests.exceptions.Timeout,
                              requests.exceptions.ConnectTimeout)):
                logger.warning(f"Network timeout (will retry): {type(e).__name__}")
            else:
                logger.error(f"Callback error: {e}")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    def show_portfolio(call, index=0):
        works = get_portfolio()
        if not works:
            bot.edit_message_text("📷 <b>Портфолио пусто</b>\n\nМастер ещё не добавил работы.",
                                call.message.chat.id, call.message.message_id,
                                reply_markup=get_back_keyboard())
            return
        if index >= len(works):
            index = len(works) - 1
        work = works[index]
        caption = (f"🎨 <b>{work['title']}</b>\n"
                   f"🎭 Стиль: {work['style']}\n"
                   f"📝 {work['description']}\n\n"
                   f"📍 Работа {index + 1} из {len(works)}")
        markup = types.InlineKeyboardMarkup()
        nav = []
        if index > 0:
            nav.append(types.InlineKeyboardButton("◀️ Назад", callback_data=f"port_{index - 1}"))
        if index < len(works) - 1:
            nav.append(types.InlineKeyboardButton("Далее ▶️", callback_data=f"port_{index + 1}"))
        if nav:
            markup.row(*nav)
        markup.add(types.InlineKeyboardButton("◀️ В меню", callback_data="menu"))
        try:
            if work['file_id']:
                bot.edit_message_media(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    media=types.InputMediaPhoto(media=work['file_id'], caption=caption),
                    reply_markup=markup
                )
            else:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=caption,
                    reply_markup=markup
                )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            # Если не получилось — удаляем и шлём новое
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            if work['file_id']:
                bot.send_photo(call.message.chat.id, work['file_id'], caption=caption, reply_markup=markup)
            else:
                bot.send_message(call.message.chat.id, caption, reply_markup=markup)

    def show_price(call):
        services = get_services()
        if not services:
            text = "💰 Прайс пуст"
        else:
            text = "💰 <b>Прайс-лист</b>\n\n"
            for s in services:
                text += (f"▫️ <b>{s['name']}</b>\n"
                         f"   {price_text(s['price_min'], s['price_max'])}\n"
                         f"   📝 {s['description']}\n\n")
            text += "Уточнить точную стоимость можно при консультации 💬"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              reply_markup=get_back_keyboard())

    def show_about(call):
        text = (f"ℹ️ <b>О мастере</b>\n\nПриветствую любителей искусства тела и тех, кто мечтает выразить себя через татуировку! 🎨\n\nВоплощаю ваши самые смелые идеи в реальность ✨\n\n<b>Что я предлагаю:</b>\n✔️ <b>Индивидуальный дизайн</b> — создаю эскизы специально для вас, учитывая ваши предпочтения и особенности тела\n✔️ <b>Высококачественные материалы</b> — работаю исключительно с проверенными красками и инструментами, обеспечивая безопасность и долговечность ваших татуировок\n✔️ <b>Комфортная атмосфера</b> — стерильно, уютно, дружелюбно\n\nНе упустите возможность стать обладателем уникальной татуировки! Запишитесь на консультацию прямо сейчас и сделайте первый шаг навстречу своему новому образу! 🔥\n\n<b>📍 Адрес:</b> {BOT_ADDRESS}\n<b>📞 Телефон:</b> {BOT_PHONE}\n<b>🌐 {BOT_VK_LABEL}:</b> {BOT_VK_URL}")
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              reply_markup=get_about_keyboard())

    def show_reviews(call):
        reviews = get_reviews()
        avg, cnt = get_rating_stats()
        if cnt:
            header = f"⭐ <b>Отзывы</b>\n\nРейтинг: {avg:.1f}/5 ({cnt} отзывов)\n\n"
        else:
            header = "⭐ <b>Отзывы</b>\n\nПока нет отзывов.\n\n"
        body = ""
        for r in reviews[:10]:
            body += f"{'⭐' * r['rating']}\n💬 {r['text']}\n— @{r['username'] or 'Аноним'}"
            if r.get('admin_reply'):
                body += f"\n\n💬 <b>Ответ мастера:</b> {r['admin_reply']}"
            if r.get('likes'):
                body += f"\n❤️ {r['likes']}"
            body += "\n\n"
        bot.edit_message_text(header + body, call.message.chat.id, call.message.message_id,
                              reply_markup=get_reviews_keyboard())

    def show_my_bookings(call):
        bookings = get_user_bookings(call.from_user.id)
        # Скрываем от клиента заявки, отменённые им на этапе подтверждения (status='cancelled'):
        # мастер отменяет через delete_booking (запись исчезает), клиент отменяет активную
        # через 'client_cancelled'. Статус 'cancelled' — только от отказа до подтверждения,
        # для клиента это мусор, но виден мастеру в админ-панели.
        bookings = [b for b in bookings if b['status'] != 'cancelled']
        if not bookings:
            text = "👤 <b>Мои записи</b>\n\nЗаписей нет."
        else:
            text = "👤 <b>Мои записи</b>\n\n"
            for b in bookings:
                text += f"🎫 #{b['id']} | {b['service']}\n💡 {b['description']}\n📅 {b['date_time']}\nСтатус: {BOOKING_STATUS_RU.get(b['status'], '⚠️')}\n\n"
            if any(b['status'] in ACTIVE_BOOKING_STATUSES for b in bookings):
                text += "Нажмите ❌ чтобы отказаться от активной записи:"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              reply_markup=get_my_bookings_keyboard(bookings))

    def client_cancel_booking(call, booking_id):
        """Клиент отменяет свою запись — статус client_cancelled, висит у мастера"""
        b = get_booking_by_id(booking_id)
        if not b or b['user_id'] != call.from_user.id:
            bot.answer_callback_query(call.id, "Запись не найдена", show_alert=True)
            return
        if b['status'] not in ('pending', 'confirmed'):
            bot.answer_callback_query(call.id, "Эту запись уже нельзя отменить", show_alert=True)
            return
        text = (f"❓ <b>Отказаться от записи #{booking_id}?</b>\n\n"
                f"📝 {b['service']}\n📅 {b['date_time']}\n\n"
                f"Мастер увидит ваш отказ. Запись удалится только после подтверждения мастером.")
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              reply_markup=get_confirm_cancel_keyboard(booking_id))

    def confirm_client_cancel(call, booking_id):
        b = get_booking_by_id(booking_id)
        if not b or b['user_id'] != call.from_user.id:
            bot.answer_callback_query(call.id, "Запись не найдена", show_alert=True)
            return
        if b['status'] not in ('pending', 'confirmed'):
            bot.answer_callback_query(call.id, "Эту запись уже нельзя отменить", show_alert=True)
            return
        update_booking_status(booking_id, 'client_cancelled')
        user = call.from_user
        notify_admin(f"🚫 <b>Клиент отказался от записи #{booking_id}!</b>\n\n"
                     f"👤 @{user.username or 'без ника'} ({user.full_name})\n"
                     f"📝 {b['service']}\n📅 {b['date_time']}\n\n"
                     f"Запись висит до вашего подтверждения. Нажмите «❌ Отменить» в карточке записи, чтобы удалить её и освободить слот.")
        bot.answer_callback_query(call.id, "Отказ отправлен мастеру", show_alert=True)
        bot.edit_message_text(f"🚫 <b>Запись #{booking_id} отменена</b>\n\n"
                              f"📝 {b['service']}\n📅 {b['date_time']}\n\n"
                              f"Мастер уведомлён. Запись будет удалена после подтверждения мастером.",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=get_main_menu(is_admin(call.from_user.id)))
        threading.Thread(target=refresh_overlay_async, daemon=True).start()

    def start_booking(call):
        services = get_services()
        if not services:
            bot.answer_callback_query(call.id, "Услуги недоступны", show_alert=True)
            return
        save_state(call.from_user.id, 'booking_service')
        bot.edit_message_text("📅 <b>Запись на тату</b>\n\nВыберите услугу:",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=get_services_keyboard(services))

    def select_service(call, service_id):
        services = get_services()
        sel = None
        for s in services:
            if s['id'] == service_id:
                sel = s
                break
        if not sel:
            return
        save_state(call.from_user.id, 'booking_desc', {
            'service_name': sel['name'],
            'price_min': sel['price_min'],
            'price_max': sel['price_max'],
        })
        bot.edit_message_text(f"Вы выбрали: <b>{sel['name']}</b>\n{price_text(sel['price_min'], sel['price_max'])}\n\nОпишите вашу идею:\n• Рисунок?\n• Часть тела?\n• Размер?\n\nНапишите ниже 👇",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=get_back_keyboard())

    def select_time(call, y, m, d, h):
        try:
            dt = datetime(y, m, d, h, 0)
            if dt <= datetime.now():
                bot.answer_callback_query(call.id, "Нельзя выбрать прошлое время", show_alert=True)
                return
        except ValueError:
            bot.answer_callback_query(call.id, "Некорректная дата/время", show_alert=True)
            return
        sk = slot_key(y, m, d, h)
        if is_slot_blocked(sk):
            bot.answer_callback_query(call.id, "Время занято", show_alert=True)
            return
        pretty = fmt_dt(y, m, d, h)
        data = get_state_data(call.from_user.id)
        data['date_time'] = pretty
        data['slot_key'] = sk
        save_state(call.from_user.id, 'booking_confirm', data)
        d2 = get_state_data(call.from_user.id)
        text = ("✅ <b>Подтвердите запись:</b>\n\n"
                f"📝 Услуга: {d2['service_name']}\n"
                f"{price_text(d2['price_min'], d2['price_max'])}\n"
                f"💡 {d2.get('description', '')}\n"
                f"📅 {pretty}\n\nВсё верно?")
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              reply_markup=get_confirmation_keyboard())

    def confirm_booking(call):
        user_id = call.from_user.id
        d = get_state_data(user_id)
        if not d.get('service_name') or not d.get('date_time'):
            database.clear_state(user_id)
            bot.answer_callback_query(call.id, "Данные записи устарели. Начните заново.", show_alert=True)
            bot.edit_message_text("⚠️ Данные записи не найдены. Начните заново.",
                                  call.message.chat.id, call.message.message_id,
                                  reply_markup=get_main_menu(is_admin(user_id)))
            return
        slot_key = d.get('slot_key')
        if not slot_key:
            database.clear_state(user_id)
            bot.answer_callback_query(call.id, "Время не выбрано. Начните заново.", show_alert=True)
            bot.edit_message_text("⚠️ Не выбран слот времени. Начните заново.",
                                  call.message.chat.id, call.message.message_id,
                                  reply_markup=get_main_menu(is_admin(user_id)))
            return
        booking_id = create_booking_with_slot(
            user_id, d['service_name'], d.get('description', ''), d['date_time'], slot_key,
            platform='telegram')
        if booking_id is None:
            database.clear_state(user_id)
            bot.answer_callback_query(call.id, "Это время только что заняли! Выберите другое.", show_alert=True)
            bot.edit_message_text("⏰ <b>Слот занят</b>\n\nЭто время только что забронировали. Выберите другое:",
                                  call.message.chat.id, call.message.message_id,
                                  reply_markup=get_main_menu(is_admin(user_id)))
            return
        database.clear_state(user_id)
        text = (f"🎉 <b>Запись создана!</b>\n\nНомер: #{booking_id}\n📝 {d['service_name']}\n📅 {d['date_time']}\n\n📞 Мастер свяжется с вами. Приходите за 15 мин до записи!")
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              reply_markup=get_main_menu(is_admin(user_id)))
        u = call.from_user
        notify_admin(f"🔔 <b>Новая запись #{booking_id}!</b>\n\n👤 @{u.username or 'без ника'} ({u.full_name})\n📝 {d['service_name']}\n💡 {d.get('description', '')}\n📅 {d['date_time']}")
        threading.Thread(target=refresh_overlay_async, daemon=True).start()

    def cancel_booking_confirm(call):
        """Клиент отменяет запись на этапе подтверждения.
        Заявка фиксируется у мастера со статусом cancelled (попадает в «отменённые»),
        клиент возвращается в главное меню. Слот НЕ блокируется."""
        user_id = call.from_user.id
        d = get_state_data(user_id)
        if d.get('service_name') and d.get('date_time'):
            create_booking(user_id, d['service_name'], d.get('description', ''),
                           d['date_time'], status='cancelled', platform='telegram')
            threading.Thread(target=refresh_overlay_async, daemon=True).start()
        database.clear_state(user_id)
        bot.edit_message_text("❌ Запись отменена.",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=get_main_menu(is_admin(user_id)))

    def admin_show_bookings(call):
        if not is_admin(call.from_user.id):
            return
        bookings = get_all_bookings()
        if not bookings:
            bot.edit_message_text("📋 Записей нет.", call.message.chat.id, call.message.message_id,
                                  reply_markup=get_admin_keyboard())
            return
        bot.edit_message_text("📋 <b>Все записи</b>\n\nВыберите запись:",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=get_admin_bookings_keyboard(bookings))

    def admin_booking_detail(call, booking_id):
        if not is_admin(call.from_user.id):
            return
        b = get_booking_by_id(booking_id)
        if not b:
            return
        user = get_user_by_id(b['user_id'])
        uname = f"@{user['username']}" if user and user['username'] else f"ID:{b['user_id']}"
        status_line = BOOKING_STATUS_RU.get(b['status'], '⚠️')
        if b['status'] == 'client_cancelled':
            status_line += " — ждёт отмены мастером"
        text = (f"🎫 <b>Запись #{b['id']}</b>\n\n👤 {uname} ({user['first_name'] if user else ''})\n📝 {b['service']}\n💡 {b['description']}\n📅 {b['date_time']}\nСтатус: {status_line}")
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              reply_markup=get_admin_booking_actions(booking_id, b['status']))

    def admin_booking_action(call, action, booking_id):
        if not is_admin(call.from_user.id):
            return
        b = get_booking_by_id(booking_id)
        if not b:
            return
        if action in ("confirm", "complete") and b['status'] == 'client_cancelled':
            bot.answer_callback_query(call.id, "Клиент уже отказался. Используйте «❌ Отменить»", show_alert=True)
            return
        if action == "confirm":
            update_booking_status(booking_id, 'confirmed')
            bot.send_message(b['user_id'], f"✅ Запись #{booking_id} на {b['date_time']} <b>подтверждена</b>!")
            bot.answer_callback_query(call.id, "Подтверждено", show_alert=True)
        elif action == "complete":
            update_booking_status(booking_id, 'completed')
            bot.send_message(b['user_id'], f"✨ Сеанс #{booking_id} завершён! Оставьте отзыв в меню «⭐ Отзывы».")
            bot.answer_callback_query(call.id, "Завершено", show_alert=True)
        elif action == "cancel":
            # Полностью удаляем запись из БД и освобождаем слот
            slot_key = booking_to_slot_key(b['date_time'])
            if slot_key and is_slot_blocked(slot_key):
                unblock_slot(slot_key)
            delete_booking(booking_id)
            bot.send_message(b['user_id'], f"❌ Запись #{booking_id} на {b['date_time']} отменена мастером.")
            bot.answer_callback_query(call.id, "Отменено и удалено", show_alert=True)
            return
        elif action == "msg":
            save_state(call.from_user.id, 'admin_msg', {'target': b['user_id'], 'booking_id': booking_id})
            bot.send_message(call.message.chat.id, "💬 Напишите сообщение для клиента:")
            return
        admin_booking_detail(call, booking_id)
        threading.Thread(target=refresh_overlay_async, daemon=True).start()

    def admin_manage_portfolio(call):
        if not is_admin(call.from_user.id):
            return
        works = get_portfolio()
        if not works:
            bot.edit_message_text("Портфолио пусто.", call.message.chat.id, call.message.message_id,
                                  reply_markup=get_admin_keyboard())
            return
        bot.edit_message_text("🗑 Нажмите на работу, чтобы удалить:",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=get_admin_portfolio_keyboard(works))

    def admin_delete_work(call, work_id):
        if not is_admin(call.from_user.id):
            return
        delete_portfolio_work(work_id)
        bot.answer_callback_query(call.id, "Удалено", show_alert=True)
        works = get_portfolio()
        if works:
            bot.edit_message_text("🗑 Нажмите на работу, чтобы удалить:",
                                  call.message.chat.id, call.message.message_id,
                                  reply_markup=get_admin_portfolio_keyboard(works))
        else:
            bot.edit_message_text("Портфолио пусто.", call.message.chat.id, call.message.message_id,
                                  reply_markup=get_admin_keyboard())
        threading.Thread(target=refresh_overlay_async, daemon=True).start()

    def admin_show_slots(call):
        if not is_admin(call.from_user.id):
            return
        blocked = get_blocked_slots()
        info = "" if not blocked else f"\n\nСейчас заблокировано слотов: {len(blocked)}"
        now = datetime.now()
        bot.edit_message_text(f"🚫 <b>Блокировка слотов</b>\n\nВыберите день в календаре, затем:\n• Нажмите на время — заблокировать 1 слот\n• Нажмите «🔒 Весь день» — заблокировать весь день{info}",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=get_admin_calendar_keyboard(now.year, now.month))

    @bot.message_handler(content_types=['text'])
    def text_handler(message):
        user_id = message.from_user.id
        state = get_state(user_id)
        if state == 'review_text':
            data = get_state_data(user_id)
            add_review(user_id, message.from_user.username, data['rating'], message.text)
            database.clear_state(user_id)
            bot.send_message(message.chat.id, f"✅ Спасибо за отзыв! {'⭐' * data['rating']}", reply_markup=get_main_menu(is_admin(user_id)))
            threading.Thread(target=refresh_overlay_async, daemon=True).start()
        elif state == 'booking_desc':
            data = get_state_data(user_id)
            data['description'] = message.text
            save_state(user_id, 'booking_date', data)
            now = datetime.now()
            bot.send_message(message.chat.id, "Отлично! Выберите дату в календаре 👇", reply_markup=get_calendar_keyboard(now.year, now.month))
        elif state == 'add_title' and is_admin(user_id):
            data = get_state_data(user_id)
            data['title'] = message.text
            save_state(user_id, 'add_style', data)
            bot.send_message(message.chat.id, "Шаг 3/4: укажите стиль\n(например: реализм, олдскул, графика, дотворк)")
        elif state == 'add_style' and is_admin(user_id):
            data = get_state_data(user_id)
            data['style'] = message.text
            save_state(user_id, 'add_description', data)
            bot.send_message(message.chat.id, "Шаг 4/4: краткое описание работы\n(размер, место на теле и т.д.)")
        elif state == 'add_description' and is_admin(user_id):
            data = get_state_data(user_id)
            add_portfolio_work(data['title'], message.text, data['file_id'], data['style'])
            database.clear_state(user_id)
            bot.send_message(message.chat.id, f"✅ Работа «{data['title']}» добавлена в портфолио!", reply_markup=get_admin_keyboard())
            threading.Thread(target=refresh_overlay_async, daemon=True).start()
        elif state == 'admin_msg':
            data = get_state_data(user_id)
            target = data.get('target')
            database.clear_state(user_id)
            try:
                bot.send_message(target, f"💬 <b>Сообщение от мастера:</b>\n\n{message.text}")
                bot.send_message(message.chat.id, "✅ Сообщение отправлено клиенту.", reply_markup=get_admin_keyboard())
            except Exception:
                bot.send_message(message.chat.id, "⚠️ Не удалось отправить (клиент заблокировал бота?).")
        elif state == 'admin_review_reply' and is_admin(user_id):
            data = get_state_data(user_id)
            review_id = data.get('review_id')
            database.clear_state(user_id)
            from database import reply_to_review, get_review_by_id
            review = get_review_by_id(review_id)
            if review:
                reply_to_review(review_id, message.text)
                bot.send_message(message.chat.id,
                    f"✅ Ответ на отзыв #{review_id} отправлен!\n\n"
                    f"💬 <b>Отзыв:</b> {(review['text'] or '')[:80]}…\n"
                    f"📝 <b>Ваш ответ:</b> {message.text}",
                    reply_markup=get_admin_keyboard())
            else:
                bot.send_message(message.chat.id, "⚠️ Отзыв не найден.", reply_markup=get_admin_keyboard())
        elif message.text.strip().lower() in ('старт', 'start', '/start', 'привет', 'меню', 'начать'):
            user = message.from_user
            save_user(user.id, user.username, user.first_name, user.last_name)
            database.clear_state(user.id)
            avg, cnt = get_rating_stats()
            rating_line = f"⭐ Рейтинг: {avg:.1f} ({cnt} отзывов)" if cnt else "⭐ Будь первым!"
            welcome = (f"👋 Привет, {user.first_name}!\n\n"
                        f"Я тату-мастер <b>Максим Андреевич</b>. Добро пожаловать! 🎨\n\n"
                        f"Выбери нужный раздел 👇")
            bot.send_message(message.chat.id, welcome, reply_markup=get_main_menu(is_admin(user_id)))
        else:
            bot.send_message(message.chat.id, "Используйте кнопки меню 👇 Если потеряли меню — напишите «старт» или нажмите /start", reply_markup=get_main_menu(is_admin(user_id)))

    @bot.message_handler(content_types=['photo'])
    def photo_handler(message):
        user_id = message.from_user.id
        state = get_state(user_id)
        if state == 'add_photo' and is_admin(user_id):
            file_id = message.photo[-1].file_id
            save_state(user_id, 'add_title', {'file_id': file_id})
            bot.send_message(message.chat.id, "Фото получено! ✅\n\nШаг 2/4: введите название работы")
        elif state == 'booking_desc':
            pass