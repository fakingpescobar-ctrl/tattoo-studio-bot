"""
MAX-хендлеры: порт handlers.py (Telegram) под события Bot API MAX.
Вместо telebot — MaxClient, вместо edit_message_text — callback_reply (POST /answers).
FSM, БД, оверлей — переиспользуются из database.py / overlay.py без изменений.
"""
import json
import logging
import re
import threading
import time
from datetime import datetime
from functools import wraps
from collections import defaultdict

from config import (MAX_ADMIN_ID, MAX_ADMIN_IDS, BOT_ADDRESS, BOT_PHONE,
                    BOT_VK_LABEL, BOT_VK_URL)
from common import (ACTIVE_BOOKING_STATUSES, BOOKING_STATUS_RU,
                    booking_to_slot_key, fmt_dt, price_text, slot_key)
from database import *
from max_keyboards import *
from media_bridge import fetch_tg_file

logger = logging.getLogger(__name__)

# Оверлей обновляется только для админа
_overlay_lock = threading.Lock()

# Rate-limiting (как в TG-версии)
USER_COMMANDS = defaultdict(list)
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_COUNT = 5
RATE_LIMIT_BLOCK = 10
BLOCKED_USERS = {}


def timing(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start
            if duration > 2.0:
                logger.warning(f"{func.__name__} slow: {duration:.3f}s")
            return result
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            raise
    return wrapper


def refresh_overlay_async():
    try:
        from overlay import refresh_overlay
        with _overlay_lock:
            refresh_overlay()
    except Exception:
        pass


def is_admin(user_id):
    return user_id in MAX_ADMIN_IDS


def _as_int(value):
    """user_id из апдейта MAX -> int (или None). Граница доверия: дальше по
    коду id всегда int, что бы ни прислал API (int в колбэках, str в сообщениях).
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning(f"Unparseable user_id from update: {value!r}")
        return None


# Мемо-кэш моста TG file_id -> MAX payload: {file_id: (payload|None, monotonic_ts)}.
# Успех живёт до рестарта процесса, неудача — TTL_IMG_FAIL секунд (не долбим TG/API).
_MAX_IMG_MEMO: dict = {}
_TTL_IMG_FAIL = 300.0


def _memoized_max_payload(client, tg_file_id):
    """TG file_id -> payload изображения для attachments MAX (или None).

    Путь: media_bridge.fetch_tg_file (дисковый кэш) -> upload_media -> token.
    """
    if not tg_file_id:
        return None
    hit = _MAX_IMG_MEMO.get(tg_file_id)
    if hit:
        payload, ts = hit
        fresh = payload is not None or (time.monotonic() - ts) < _TTL_IMG_FAIL
        if fresh:
            return payload
    payload = None
    try:
        path = fetch_tg_file(tg_file_id)
        if path:
            token = client.upload_media(str(path))
            if token:
                payload = {'token': token}
    except Exception as e:
        logger.warning(f"Image bridge TG->MAX failed ({tg_file_id[:24]}...): {e}")
    _MAX_IMG_MEMO[tg_file_id] = (payload, time.monotonic())
    return payload


class MaxBot:
    """Обработчик событий MAX. client — экземпляр MaxClient."""

    def __init__(self, client):
        self.client = client

    # ---------- вспомогательные ----------

    def notify_admin(self, text):
        """Уведомление админу MAX (если MAX_ADMIN_ID задан)."""
        if MAX_ADMIN_ID:
            try:
                self.client.send_message(MAX_ADMIN_ID, text)
            except Exception as e:
                logger.error(f"notify_admin error: {e}")

    def rate_check(self, user_id):
        """Возвращает True, если пользователь превысил лимит (заблокирован)."""
        now = time.time()
        if user_id in BLOCKED_USERS and now < BLOCKED_USERS[user_id]:
            return True
        USER_COMMANDS[user_id].append(now)
        USER_COMMANDS[user_id] = [t for t in USER_COMMANDS[user_id] if now - t < RATE_LIMIT_WINDOW]
        if len(USER_COMMANDS[user_id]) > RATE_LIMIT_COUNT:
            BLOCKED_USERS[user_id] = now + RATE_LIMIT_BLOCK
            return True
        return False

    def user_full_name(self, user):
        parts = [user.get('first_name', ''), user.get('last_name', '')]
        return ' '.join(p for p in parts if p) or 'Пользователь'

    # ---------- точка входа ----------

    def handle_update(self, update):
        """Диспечер по типу события. update — объект Update из API MAX.

        ВАЖНО: chat_id из апдейта — внутренний id диалога MAX, API НЕ принимает
        его как адресат (POST /messages?user_id=... отвечает Unknown recipient /
        Dialog not found). Для личных диалогов бота адресат — всегда user_id.

        user_id нормализуется к int СРАЗУ на границе: MAX в разных типах апдейтов
        отдаёт то int, то str, а FSM-ключи (user_states) и bookings.user_id
        должны совпадать байт-в-байт, иначе состояние «теряется» и клиент
        вылетает в меню вместо следующего шага.
        """
        utype = update.get('update_type')
        # user у MAX живёт в разных местах апдейта:
        #   bot_started / message_created -> update['user']
        #   message_callback              -> update['callback']['user']
        #   (страховка) сообщение         -> update['message']['sender']
        user = (update.get('user')
                or (update.get('callback') or {}).get('user')
                or (update.get('message') or {}).get('sender')
                or {})
        user_id = _as_int(user.get('user_id'))
        if user_id is None:
            # Без id нечем адресовать ни callback_reply, ни send_message —
            # chat_id из апдейта API адресатом не принимает (см. докстринг).
            # Дампим сырую структуру: у MAX user лежит не во всех типах апдейтов
            # одинаково — по дампу чиним экстракцию.
            try:
                dump = json.dumps(update, ensure_ascii=False)[:600]
            except (TypeError, ValueError):
                dump = str(update)[:600]
            logger.warning(f"Update without usable user_id, dropped: type={utype} raw={dump}")
            return
        chat_id = user_id or update.get('chat_id')

        try:
            if utype == 'message_callback':
                self.handle_callback(update, user_id, chat_id)
            elif utype == 'message_created':
                self.handle_message(update, user_id, chat_id)
            elif utype == 'bot_started':
                self.cmd_start(user_id, chat_id, user)
            else:
                # bot_added, bot_stopped, dialog_* и пр. — не обрабатываем
                logger.info(f"Ignore update type: {utype} (user={user_id})")
        except Exception as e:
            logger.error(f"handle_update error ({utype}): {e}")

    # ---------- сообщения ----------

    def handle_message(self, update, user_id, chat_id):
        message = update.get('message') or {}
        body = message.get('body') or {}
        text = body.get('text') or ''
        if not user_id:
            user_id = _as_int((message.get('sender') or {}).get('user_id'))
            chat_id = user_id  # адресат всегда user_id (см. докстринг handle_update)
        user = update.get('user') or (message.get('sender') or {})

        # Контакт (кнопка request_contact / поделиться номером)
        attachments = body.get('attachments') or []
        contact = next((a for a in attachments if a.get('type') == 'contact'), None)
        if contact:
            self.handle_contact(user_id, chat_id, contact, user)
            return

        # Фото (админ добавляет работу)
        image = next((a for a in attachments if a.get('type') == 'image'), None)
        if image:
            self.handle_photo(user_id, chat_id, image)
            return

        state = get_state(user_id)
        if not text:
            return

        if state == 'review_text':
            data = get_state_data(user_id)
            add_review(user_id, user.get('username'), data.get('rating', 5), text)
            clear_state(user_id)
            self.client.send_message(chat_id,
                f"✅ Спасибо за отзыв! {'⭐' * data.get('rating', 5)}",
                attachments=get_main_menu(is_admin(user_id)))
            threading.Thread(target=refresh_overlay_async, daemon=True).start()
        elif state == 'booking_desc':
            data = get_state_data(user_id)
            data['description'] = text
            save_state(user_id, 'booking_date', data)
            now = datetime.now()
            self.client.send_message(chat_id, "Отлично! Выберите дату в календаре 👇",
                                     attachments=get_calendar_keyboard(now.year, now.month))
        elif state == 'add_title' and is_admin(user_id):
            data = get_state_data(user_id)
            data['title'] = text
            save_state(user_id, 'add_style', data)
            self.client.send_message(chat_id, "Шаг 3/4: укажите стиль\n(например: реализм, олдскул, графика, дотворк)")
        elif state == 'add_style' and is_admin(user_id):
            data = get_state_data(user_id)
            data['style'] = text
            save_state(user_id, 'add_description', data)
            self.client.send_message(chat_id, "Шаг 4/4: краткое описание работы\n(размер, место на теле и т.д.)")
        elif state == 'add_description' and is_admin(user_id):
            data = get_state_data(user_id)
            add_portfolio_work(data.get('title', ''), text, data.get('file_id', ''), data.get('style', ''))
            clear_state(user_id)
            self.client.send_message(chat_id,
                f"✅ Работа «{data.get('title')}» добавлена в портфолио!",
                attachments=get_admin_keyboard())
            threading.Thread(target=refresh_overlay_async, daemon=True).start()
        elif state == 'admin_msg':
            data = get_state_data(user_id)
            target = data.get('target')
            clear_state(user_id)
            try:
                self.client.send_message(target, f"💬 <b>Сообщение от мастера:</b>\n\n{text}")
                self.client.send_message(chat_id, "✅ Сообщение отправлено клиенту.",
                                         attachments=get_admin_keyboard())
            except Exception:
                self.client.send_message(chat_id, "⚠️ Не удалось отправить (клиент остановил бота?).")
        elif text.strip().lower() in ('старт', 'start', '/start', 'привет', 'меню', 'начать'):
            self.welcome(user_id, chat_id, user)
        else:
            # Клиент ввёл текст вне FSM-шага. Логируем контекст: если сюда попадает
            # валидный шаг (например booking_desc) — значит state не нашёлся по uid.
            logger.info(
                f"FSM fallback: uid={user_id!r} state={state!r} "
                f"text={text[:48]!r}")
            self.client.send_message(chat_id,
                "Используйте кнопки меню 👇 Если потеряли меню — напишите «старт» или нажмите /start",
                attachments=get_main_menu(is_admin(user_id)))

    def handle_contact(self, user_id, chat_id, contact, user):
        """Контакт из request_contact: сохраняем телефон пользователю."""
        payload = contact.get('payload') or {}
        vcf = payload.get('vcf_info') or ''
        m = re.search(r'TEL[^:]*:\s*(\+?\d[\d\s()-]*)', vcf)
        phone = m.group(1).strip() if m else None
        save_user(user_id, user.get('username'), user.get('first_name', ''),
                  user.get('last_name', ''), phone)
        if phone:
            self.client.send_message(chat_id, f"📱 Номер получен: {phone}")
        else:
            self.client.send_message(chat_id, "📱 Не удалось разобрать номер.")

    def handle_photo(self, user_id, chat_id, image):
        """Фото от админа — шаг 1 добавления работы. Сохраняем payload (url/token) в file_id."""
        if not is_admin(user_id):
            return
        state = get_state(user_id)
        if state != 'add_photo':
            return
        payload = image.get('payload') or {}
        # Для image payload может содержать token или url — сохраняем как есть
        save_state(user_id, 'add_title', {'file_id': json.dumps(payload, ensure_ascii=False)})
        self.client.send_message(chat_id, "Фото получено! ✅\n\nШаг 2/4: введите название работы")

    # ---------- команды ----------

    def welcome(self, user_id, chat_id, user):
        save_user(user_id, user.get('username'), user.get('first_name', ''),
                  user.get('last_name', ''))
        clear_state(user_id)
        avg, cnt = get_rating_stats()
        rating_line = f"⭐ Рейтинг: {avg:.1f} ({cnt} отзывов)" if cnt else "⭐ Будь первым!"
        # Текст 1:1 как в TG /start (handlers.py), чтобы оба бота выглядели одинаково.
        welcome = (f"👋 Привет, {user.get('first_name', '')}!\n\n"
                   f"Я тату-мастер <b>Максим Андреевич</b>. Добро пожаловать! 🎨\n\n"
                   f"Здесь ты можешь:\n"
                   f"• 🎨 Посмотреть портфолио работ\n"
                   f"• 📅 Записаться на татуировку\n"
                   f"• 💰 Узнать цены\n"
                   f"• ⭐ Читать и оставлять отзывы\n"
                   f"• 👤 Управлять своими записями\n\n"
                   f"{rating_line}\n\nВыбери нужный раздел 👇")
        self.client.send_message(chat_id, welcome, attachments=get_main_menu(is_admin(user_id)))

    @timing
    def cmd_start(self, user_id, chat_id, user):
        if self.rate_check(user_id):
            self.client.send_message(chat_id, "🚫 Слишком много запросов. Вы заблокированы на 10 секунд.")
            return
        self.welcome(user_id, chat_id, user)

    # ---------- колбэки (кнопки) ----------

    def handle_callback(self, update, user_id, chat_id):
        cb = update.get('callback') or {}
        callback_id = cb.get('callback_id')
        data = cb.get('payload') or cb.get('data') or ''
        user = update.get('user') or {}
        if not callback_id:
            logger.warning("callback без callback_id")
            return

        try:
            if data == "ignore":
                self.client.answer_callback(callback_id)
            elif data == "menu":
                clear_state(user_id)
                self.client.callback_reply(callback_id,
                    text="🎨 <b>Главное меню</b>\n\nВыбери раздел:",
                    attachments=get_main_menu(is_admin(user_id)))
            elif data == "portfolio":
                self.show_portfolio(callback_id, user_id, 0)
            elif data.startswith("port_"):
                self.show_portfolio(callback_id, user_id, int(data.split("_")[1]))
            elif data == "price":
                self.show_price(callback_id)
            elif data == "about":
                self.show_about(callback_id)
            elif data == "reviews":
                self.show_reviews(callback_id)
            elif data == "add_review":
                save_state(user_id, 'review_rating')
                self.client.callback_reply(callback_id,
                    text="✍️ <b>Оставить отзыв</b>\n\nОцените работу мастера от 1 до 5 звёзд:",
                    attachments=get_rating_keyboard())
            elif data.startswith("rating_"):
                rating = int(data.split("_")[1])
                save_state(user_id, 'review_text', {'rating': rating})
                self.client.callback_reply(callback_id,
                    text=f"Вы поставили {'⭐' * rating}\n\nНапишите текст отзыва:")
            elif data == "my_bookings":
                self.show_my_bookings(callback_id, user_id)
            elif data.startswith("my_cancel_"):
                self.client_cancel_booking(callback_id, user_id, int(data.split("_")[2]))
            elif data.startswith("confirm_my_cancel_"):
                self.confirm_client_cancel(callback_id, user_id, int(data.split("_")[3]))
            elif data == "booking_start":
                save_state(user_id, 'booking_service')
                self.start_booking(callback_id, user_id)
            elif data.startswith("service_"):
                self.select_service(callback_id, user_id, int(data.split("_")[1]))
            elif data.startswith("cal_month_"):
                parts = data.split("_")
                self.client.callback_reply(callback_id,
                    attachments=get_calendar_keyboard(int(parts[2]), int(parts[3])))
            elif data == "cal_back":
                now = datetime.now()
                self.client.callback_reply(callback_id,
                    attachments=get_calendar_keyboard(now.year, now.month))
            elif data.startswith("cal_day_"):
                parts = data.split("_")
                y, m, d = int(parts[2]), int(parts[3]), int(parts[4])
                blocked = get_blocked_slots()
                self.client.callback_reply(callback_id,
                    text=f"Выберите время на {d:02d}.{m:02d}.{y}:",
                    attachments=get_time_slots_keyboard(y, m, d, blocked))
            elif data.startswith("cal_time_"):
                parts = data.split("_")
                y, m, d, h = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
                self.select_time(callback_id, user_id, y, m, d, h)
            elif data == "booking_confirm":
                self.confirm_booking(callback_id, user_id)
            elif data == "booking_cancel":
                self.cancel_booking_confirm(callback_id, user_id)
            elif data == "admin":
                if is_admin(user_id):
                    self.client.callback_reply(callback_id,
                        text="🔧 <b>Админ-панель</b>\n\nВыберите действие:",
                        attachments=get_admin_keyboard())
                else:
                    self.client.answer_callback(callback_id)
            elif data == "admin_bookings":
                self.admin_show_bookings(callback_id, user_id)
            elif data.startswith("admin_booking_"):
                self.admin_booking_detail(callback_id, user_id, int(data.split("_")[2]))
            elif data.startswith(("ab_confirm_", "ab_cancel_", "ab_complete_", "ab_msg_")):
                self.admin_booking_action(callback_id, user_id, data.split("_")[1], int(data.split("_")[2]))
            elif data == "admin_add_work":
                if is_admin(user_id):
                    save_state(user_id, 'add_photo')
                    self.client.callback_reply(callback_id,
                        text="➕ <b>Добавление работы</b>\n\nШаг 1/4: отправьте фото работы")
                else:
                    self.client.answer_callback(callback_id)
            elif data == "admin_portfolio":
                self.admin_manage_portfolio(callback_id, user_id)
            elif data.startswith("del_work_"):
                self.admin_delete_work(callback_id, user_id, int(data.split("_")[2]))
            elif data == "admin_slots":
                self.admin_show_slots(callback_id, user_id)
            elif data.startswith("admin_cal_month_"):
                parts = data.split("_")
                self.client.callback_reply(callback_id,
                    attachments=get_admin_calendar_keyboard(int(parts[3]), int(parts[4])))
            elif data == "admin_cal_back":
                now = datetime.now()
                self.client.callback_reply(callback_id,
                    attachments=get_admin_calendar_keyboard(now.year, now.month))
            elif data.startswith("admin_cal_day_"):
                parts = data.split("_")
                y, m, d = int(parts[3]), int(parts[4]), int(parts[5])
                blocked = get_blocked_slots()
                self.client.callback_reply(callback_id,
                    text=f"🚫 <b>Блокировка на {d:02d}.{m:02d}.{y}</b>\n\n"
                         f"Свободное время — нажмите, чтобы заблокировать.\n"
                         f"🔒 — уже заблокировано.",
                    attachments=get_admin_time_keyboard(y, m, d, blocked))
            elif data.startswith("admin_cal_time_"):
                parts = data.split("_")
                y, m, d, h = int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6])
                sk = slot_key(y, m, d, h)
                add_blocked_slot(sk)
                blocked = get_blocked_slots()
                self.client.callback_reply(callback_id,
                    attachments=get_admin_time_keyboard(y, m, d, blocked))
            elif data.startswith("admin_block_day_"):
                parts = data.split("_")
                y, m, d = int(parts[3]), int(parts[4]), int(parts[5])
                cnt = block_full_day(y, m, d)
                blocked = get_blocked_slots()
                text = (f"🔒 Заблокировано слотов: {cnt}" if cnt
                        else "⚠️ Нечего блокировать: день/часы уже прошли")
                self.client.callback_reply(callback_id, text=text,
                    attachments=get_admin_time_keyboard(y, m, d, blocked))
            else:
                logger.info(f"Unknown callback: {data}")
                self.client.answer_callback(callback_id)
        except Exception as e:
            logger.error(f"Callback error ({data}): {e}")

    # ---------- разделы ----------

    def show_portfolio(self, callback_id, user_id, index=0):
        works = get_portfolio()
        if not works:
            self.client.callback_reply(callback_id,
                text="📷 <b>Портфолио пусто</b>\n\nМастер ещё не добавил работы.",
                attachments=get_back_keyboard())
            return
        if index >= len(works):
            index = len(works) - 1
        work = works[index]
        caption = (f"🎨 <b>{work['title']}</b>\n"
                   f"🎭 Стиль: {work['style']}\n"
                   f"📝 {work['description']}\n\n"
                   f"📍 Работа {index + 1} из {len(works)}")
        nav = []
        if index > 0:
            nav.append({"type": "callback", "text": "◀️ Назад", "payload": f"port_{index - 1}"})
        if index < len(works) - 1:
            nav.append({"type": "callback", "text": "Далее ▶️", "payload": f"port_{index + 1}"})
        rows = []
        if nav:
            rows.append(nav)
        rows.append([{"type": "callback", "text": "◀️ В меню", "payload": "menu"}])
        attachments = [{"type": "inline_keyboard", "payload": {"buttons": rows}}]

        # file_id: для MAX — JSON с payload изображения (url/token); для TG —
        # старая строка file_id, которую мостим: качаем из TG, заливаем в MAX.
        fid = work.get('file_id') or ''
        img_payload = None
        try:
            img_payload = json.loads(fid)
            if not isinstance(img_payload, dict):  # числовой file_id -> int, не payload
                img_payload = None
        except (ValueError, TypeError):
            pass
        if img_payload is None:
            img_payload = _memoized_max_payload(self.client, fid)
        if img_payload:
            attachments.insert(0, {"type": "image", "payload": img_payload})
        self.client.callback_reply(callback_id, text=caption, attachments=attachments)

    def show_price(self, callback_id):
        services = get_services()
        if not services:
            text = "💰 Прайс пуст"
        else:
            text = "💰 <b>Прайс-лист</b>\n\n"
            for s in services:
                text += f"▫️ <b>{s['name']}</b>\n   {price_text(s['price_min'], s['price_max'])}\n   📝 {s['description']}\n\n"
            text += "Уточнить точную стоимость можно при консультации 💬"
        self.client.callback_reply(callback_id, text=text, attachments=get_back_keyboard())

    def show_about(self, callback_id):
        text = (f"ℹ️ <b>О мастере</b>\n\nПриветствую любителей искусства тела и тех, кто мечтает выразить себя через татуировку! 🎨\n\nВоплощаю ваши самые смелые идеи в реальность ✨\n\n<b>Что я предлагаю:</b>\n✔️ <b>Индивидуальный дизайн</b> — создаю эскизы специально для вас\n✔️ <b>Высококачественные материалы</b> — только проверенные краски и инструменты\n✔️ <b>Комфортная атмосфера</b> — стерильно, уютно, дружелюбно\n\nЗапишитесь на консультацию прямо сейчас! 🔥\n\n<b>📍 Адрес:</b> {BOT_ADDRESS}\n<b>📞 Телефон:</b> {BOT_PHONE}\n<b>🌐 {BOT_VK_LABEL}:</b> {BOT_VK_URL}")
        self.client.callback_reply(callback_id, text=text, attachments=get_about_keyboard())

    def show_reviews(self, callback_id):
        reviews = get_reviews()
        avg, cnt = get_rating_stats()
        if cnt:
            header = f"⭐ <b>Отзывы</b>\n\nРейтинг: {avg:.1f}/5 ({cnt} отзывов)\n\n"
        else:
            header = "⭐ <b>Отзывы</b>\n\nПока нет отзывов.\n\n"
        body = ""
        for r in reviews[:10]:
            body += f"{'⭐' * r['rating']}\n💬 {r['text']}\n— @{r['username'] or 'Аноним'}\n\n"
        self.client.callback_reply(callback_id, text=header + body, attachments=get_reviews_keyboard())

    def show_my_bookings(self, callback_id, user_id):
        bookings = get_user_bookings(user_id)
        # Скрываем от клиента заявки, отменённые им на этапе подтверждения (status='cancelled'):
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
        self.client.callback_reply(callback_id, text=text,
                                   attachments=get_my_bookings_keyboard(bookings))

    def client_cancel_booking(self, callback_id, user_id, booking_id):
        """Клиент отменяет свою запись — статус client_cancelled, висит у мастера."""
        b = get_booking_by_id(booking_id)
        if not b or b['user_id'] != user_id:
            self.client.callback_reply(callback_id, text="Запись не найдена")
            return
        if b['status'] not in ('pending', 'confirmed'):
            self.client.callback_reply(callback_id, text="Эту запись уже нельзя отменить")
            return
        text = (f"❓ <b>Отказаться от записи #{booking_id}?</b>\n\n"
                f"📝 {b['service']}\n📅 {b['date_time']}\n\n"
                f"Мастер увидит ваш отказ. Запись удалится только после подтверждения мастером.")
        self.client.callback_reply(callback_id, text=text,
                                   attachments=get_confirm_cancel_keyboard(booking_id))

    def confirm_client_cancel(self, callback_id, user_id, booking_id):
        b = get_booking_by_id(booking_id)
        if not b or b['user_id'] != user_id:
            self.client.callback_reply(callback_id, text="Запись не найдена")
            return
        if b['status'] not in ('pending', 'confirmed'):
            self.client.callback_reply(callback_id, text="Эту запись уже нельзя отменить")
            return
        update_booking_status(booking_id, 'client_cancelled')
        u = get_user_by_id(user_id)
        uname = f"@{u['username']}" if u and u['username'] else f"ID:{user_id}"
        self.notify_admin(f"🚫 <b>Клиент отказался от записи #{booking_id}!</b>\n\n"
                          f"👤 {uname}\n📝 {b['service']}\n📅 {b['date_time']}\n\n"
                          f"Запись висит до вашего подтверждения. Нажмите «❌ Отменить» в карточке записи, чтобы удалить её и освободить слот.")
        self.client.callback_reply(callback_id,
            text=f"🚫 <b>Запись #{booking_id} отменена</b>\n\n"
                 f"📝 {b['service']}\n📅 {b['date_time']}\n\n"
                 f"Мастер уведомлён. Запись будет удалена после подтверждения мастером.",
            attachments=get_main_menu(is_admin(user_id)))
        threading.Thread(target=refresh_overlay_async, daemon=True).start()

    # ---------- бронирование ----------

    def start_booking(self, callback_id, user_id):
        services = get_services()
        if not services:
            self.client.callback_reply(callback_id, text="Услуги недоступны")
            return
        save_state(user_id, 'booking_service')
        self.client.callback_reply(callback_id,
            text="📅 <b>Запись на тату</b>\n\nВыберите услугу:",
            attachments=get_services_keyboard(services))

    def select_service(self, callback_id, user_id, service_id):
        services = get_services()
        sel = None
        for s in services:
            if s['id'] == service_id:
                sel = s
                break
        if not sel:
            self.client.answer_callback(callback_id)
            return
        save_state(user_id, 'booking_desc', {
            'service_name': sel['name'],
            'price_min': sel['price_min'],
            'price_max': sel['price_max'],
        })
        self.client.callback_reply(callback_id,
            text=f"Вы выбрали: <b>{sel['name']}</b>\n{price_text(sel['price_min'], sel['price_max'])}\n\nОпишите вашу идею:\n• Рисунок?\n• Часть тела?\n• Размер?\n\nНапишите ниже 👇",
            attachments=get_back_keyboard())

    def select_time(self, callback_id, user_id, y, m, d, h):
        try:
            dt = datetime(y, m, d, h, 0)
            if dt <= datetime.now():
                blocked = get_blocked_slots()
                self.client.callback_reply(callback_id,
                    text="⏰ Это время уже прошло. Выберите другое 👇",
                    attachments=get_time_slots_keyboard(y, m, d, blocked))
                return
        except ValueError:
            self.client.callback_reply(callback_id, text="Некорректная дата/время")
            return
        sk = slot_key(y, m, d, h)
        if is_slot_blocked(sk):
            blocked = get_blocked_slots()
            self.client.callback_reply(callback_id,
                text="⏰ Это время занято. Выберите другое 👇",
                attachments=get_time_slots_keyboard(y, m, d, blocked))
            return
        pretty = fmt_dt(y, m, d, h)
        data = get_state_data(user_id)
        data['date_time'] = pretty
        data['slot_key'] = sk
        save_state(user_id, 'booking_confirm', data)
        d2 = get_state_data(user_id)
        text = ("✅ <b>Подтвердите запись:</b>\n\n"
                f"📝 Услуга: {d2['service_name']}\n"
                f"{price_text(d2['price_min'], d2['price_max'])}\n"
                f"💡 {d2.get('description', '')}\n"
                f"📅 {pretty}\n\nВсё верно?")
        self.client.callback_reply(callback_id, text=text, attachments=get_confirmation_keyboard())

    def confirm_booking(self, callback_id, user_id):
        d = get_state_data(user_id)
        if not d.get('service_name') or not d.get('date_time') or not d.get('slot_key'):
            clear_state(user_id)
            self.client.callback_reply(callback_id, text="⚠️ Данные записи не найдены. Начните заново.",
                                       attachments=get_main_menu(is_admin(user_id)))
            return
        booking_id = create_booking_with_slot(
            user_id, d['service_name'], d.get('description', ''), d['date_time'], d['slot_key'],
            platform='max')
        if booking_id is None:
            clear_state(user_id)
            self.client.callback_reply(callback_id,
                text="⏰ <b>Слот занят</b>\n\nЭто время только что забронировали. Выберите другое:",
                attachments=get_main_menu(is_admin(user_id)))
            return
        clear_state(user_id)
        text = (f"🎉 <b>Запись создана!</b>\n\nНомер: #{booking_id}\n📝 {d['service_name']}\n📅 {d['date_time']}\n\n📞 Мастер свяжется с вами. Приходите за 15 мин до записи!")
        self.client.callback_reply(callback_id, text=text, attachments=get_main_menu(is_admin(user_id)))
        u = get_user_by_id(user_id)
        uname = f"@{u['username']}" if u and u['username'] else f"ID:{user_id}"
        self.notify_admin(f"🔔 <b>Новая запись #{booking_id}!</b>\n\n👤 {uname}\n📝 {d['service_name']}\n💡 {d.get('description', '')}\n📅 {d['date_time']}")
        threading.Thread(target=refresh_overlay_async, daemon=True).start()

    def cancel_booking_confirm(self, callback_id, user_id):
        """Клиент отменяет запись на этапе подтверждения.
        Заявка фиксируется у мастера со статусом cancelled (попадает в «отменённые»),
        клиент возвращается в главное меню. Слот НЕ блокируется."""
        d = get_state_data(user_id)
        if d.get('service_name') and d.get('date_time'):
            create_booking(user_id, d['service_name'], d.get('description', ''),
                           d['date_time'], status='cancelled', platform='max')
            threading.Thread(target=refresh_overlay_async, daemon=True).start()
        clear_state(user_id)
        self.client.callback_reply(callback_id,
            text="❌ Запись отменена.",
            attachments=get_main_menu(is_admin(user_id)))

    # ---------- админ ----------

    def admin_show_bookings(self, callback_id, user_id):
        if not is_admin(user_id):
            self.client.answer_callback(callback_id)
            return
        bookings = get_all_bookings()
        if not bookings:
            self.client.callback_reply(callback_id, text="📋 Записей нет.",
                                       attachments=get_admin_keyboard())
            return
        self.client.callback_reply(callback_id, text="📋 <b>Все записи</b>\n\nВыберите запись:",
                                   attachments=get_admin_bookings_keyboard(bookings))

    def admin_booking_detail(self, callback_id, user_id, booking_id):
        if not is_admin(user_id):
            self.client.answer_callback(callback_id)
            return
        b = get_booking_by_id(booking_id)
        if not b:
            self.client.answer_callback(callback_id)
            return
        user = get_user_by_id(b['user_id'])
        uname = f"@{user['username']}" if user and user['username'] else f"ID:{b['user_id']}"
        status_line = BOOKING_STATUS_RU.get(b['status'], '⚠️')
        if b['status'] == 'client_cancelled':
            status_line += " — ждёт отмены мастером"
        text = (f"🎫 <b>Запись #{b['id']}</b>\n\n👤 {uname} ({user['first_name'] if user else ''})\n📝 {b['service']}\n💡 {b['description']}\n📅 {b['date_time']}\nСтатус: {status_line}")
        self.client.callback_reply(callback_id, text=text,
                                   attachments=get_admin_booking_actions(booking_id, b['status']))

    def admin_booking_action(self, callback_id, user_id, action, booking_id):
        if not is_admin(user_id):
            self.client.answer_callback(callback_id)
            return
        b = get_booking_by_id(booking_id)
        if not b:
            self.client.answer_callback(callback_id)
            return
        if action in ("confirm", "complete") and b['status'] == 'client_cancelled':
            self.client.callback_reply(callback_id,
                text="Клиент уже отказался. Используйте «❌ Отменить»")
            return
        if action == "confirm":
            update_booking_status(booking_id, 'confirmed')
            try:
                self.client.send_message(b['user_id'],
                    f"✅ Запись #{booking_id} на {b['date_time']} <b>подтверждена</b>!")
            except Exception as e:
                logger.warning(f"confirm notify failed: {e}")
        elif action == "complete":
            update_booking_status(booking_id, 'completed')
            try:
                self.client.send_message(b['user_id'],
                    f"✨ Сеанс #{booking_id} завершён! Оставьте отзыв в меню «⭐ Отзывы».")
            except Exception as e:
                logger.warning(f"complete notify failed: {e}")
        elif action == "cancel":
            b_slot_key = booking_to_slot_key(b['date_time'])
            if b_slot_key and is_slot_blocked(b_slot_key):
                unblock_slot(b_slot_key)
            delete_booking(booking_id)
            try:
                self.client.send_message(b['user_id'],
                    f"❌ Запись #{booking_id} на {b['date_time']} отменена мастером.")
            except Exception as e:
                logger.warning(f"cancel notify failed: {e}")
            self.admin_show_bookings(callback_id, user_id)
            threading.Thread(target=refresh_overlay_async, daemon=True).start()
            return
        elif action == "msg":
            save_state(user_id, 'admin_msg', {'target': b['user_id'], 'booking_id': booking_id})
            self.client.callback_reply(callback_id, text="💬 Напишите сообщение для клиента:")
            return
        self.admin_booking_detail(callback_id, user_id, booking_id)
        threading.Thread(target=refresh_overlay_async, daemon=True).start()

    def admin_manage_portfolio(self, callback_id, user_id):
        if not is_admin(user_id):
            self.client.answer_callback(callback_id)
            return
        works = get_portfolio()
        if not works:
            self.client.callback_reply(callback_id, text="Портфолио пусто.",
                                       attachments=get_admin_keyboard())
            return
        self.client.callback_reply(callback_id, text="🗑 Нажмите на работу, чтобы удалить:",
                                   attachments=get_admin_portfolio_keyboard(works))

    def admin_delete_work(self, callback_id, user_id, work_id):
        if not is_admin(user_id):
            self.client.answer_callback(callback_id)
            return
        delete_portfolio_work(work_id)
        works = get_portfolio()
        if works:
            self.client.callback_reply(callback_id,
                text="🗑 Нажмите на работу, чтобы удалить:",
                attachments=get_admin_portfolio_keyboard(works))
        else:
            self.client.callback_reply(callback_id, text="Портфолио пусто.",
                                       attachments=get_admin_keyboard())
        threading.Thread(target=refresh_overlay_async, daemon=True).start()

    def admin_show_slots(self, callback_id, user_id):
        if not is_admin(user_id):
            self.client.answer_callback(callback_id)
            return
        blocked = get_blocked_slots()
        info = "" if not blocked else f"\n\nСейчас заблокировано слотов: {len(blocked)}"
        now = datetime.now()
        self.client.callback_reply(callback_id,
            text=f"🚫 <b>Блокировка слотов</b>\n\nВыберите день в календаре, затем:\n• Нажмите на время — заблокировать 1 слот\n• Нажмите «🔒 Весь день» — заблокировать весь день{info}",
            attachments=get_admin_calendar_keyboard(now.year, now.month))
