"""
Клавиатуры для MAX-бота (порт keyboards.py из Telegram).
Формат MAX: attachments = [{ "type": "inline_keyboard", "payload": { "buttons": [[...]] } }]
Кнопка: {"type": "callback", "text": "...", "payload": "<callback_data>"}
Ограничения: до 7 кнопок в ряд, до 30 рядов, до 210 кнопок всего.
"""
import calendar
from datetime import datetime

from common import MONTHS_RU, WEEKDAYS_RU, BOOKING_STATUS_SHORT, price_short


def kb(rows):
    """Оборачивает список рядов кнопок в attachments MAX."""
    return [{
        "type": "inline_keyboard",
        "payload": {"buttons": rows},
    }]


def _cb(text, data):
    return {"type": "callback", "text": text, "payload": data}


def _link(text, url):
    return {"type": "link", "text": text, "url": url}


# ============ ГЛАВНОЕ МЕНЮ ============

def get_main_menu(is_admin=False):
    rows = [
        [_cb("🎨 Портфолио", "portfolio"), _cb("📅 Записаться", "booking_start")],
        [_cb("💰 Прайс-лист", "price"), _cb("⭐ Отзывы", "reviews")],
        [_cb("👤 Мои записи", "my_bookings"), _cb("ℹ️ О мастере", "about")],
    ]
    if is_admin:
        rows.append([_cb("🔧 Админ-панель", "admin")])
    return kb(rows)


# ============ БАЗОВЫЕ ============

def get_back_keyboard():
    return kb([[_cb("◀️ В меню", "menu")]])


def get_services_keyboard(services):
    rows = []
    for s in services:
        rows.append([_cb(f"{s['name']} — {price_short(s['price_min'], s['price_max'])}",
                         f"service_{s['id']}")])
    rows.append([_cb("◀️ В меню", "menu")])
    return kb(rows)


def get_confirmation_keyboard():
    return kb([
        [_cb("✅ Подтвердить", "booking_confirm"), _cb("❌ Отменить", "booking_cancel")],
    ])


# ============ КАЛЕНДАРЬ ============

def _ign():
    # НЕ пробел: MAX триммит text и отвечает 400 errors.required на пустую
    # кнопку (весь календарь не отправлялся именно из-за этого). Точка ок.
    return _cb("·", "ignore")


def get_calendar_keyboard(year, month):
    rows = []
    rows.append([_cb(f"{MONTHS_RU[month]} {year}", "ignore")])
    rows.append([_cb(d, "ignore") for d in WEEKDAYS_RU])

    today = datetime.now().date()
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(_ign())
            else:
                day_date = datetime(year, month, day).date()
                if day_date <= today:
                    row.append(_cb("·", "ignore"))
                else:
                    row.append(_cb(str(day), f"cal_day_{year}_{month}_{day}"))
        rows.append(row)

    prev_m = month - 1 or 12
    prev_y = year - 1 if month == 1 else year
    next_m = month + 1 if month < 12 else 1
    next_y = year + 1 if month == 12 else year
    rows.append([
        _cb("◀️", f"cal_month_{prev_y}_{prev_m}"),
        _cb("В меню", "booking_start"),
        _cb("▶️", f"cal_month_{next_y}_{next_m}"),
    ])
    return kb(rows)


def get_time_slots_keyboard(year, month, day, blocked_slots=None):
    rows = []
    rows.append([_cb(f"⏰ Время на {day:02d}.{month:02d}.{year}", "ignore")])

    blocked_set = set(blocked_slots or [])
    hours = list(range(10, 21))
    row = []
    for hour in hours:
        slot = f"{year}-{month:02d}-{day:02d} {hour:02d}:00"
        if slot in blocked_set:
            row.append(_cb(f"❌{hour:02d}", "ignore"))
        else:
            row.append(_cb(f"{hour:02d}:00", f"cal_time_{year}_{month}_{day}_{hour}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([_cb("◀️ К календарю", "cal_back")])
    return kb(rows)


def get_admin_calendar_keyboard(year, month):
    """Календарь для блокировки слотов админом"""
    rows = []
    rows.append([_cb(f"🚫 {MONTHS_RU[month]} {year}", "ignore")])
    rows.append([_cb(d, "ignore") for d in WEEKDAYS_RU])

    today = datetime.now().date()
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(_ign())
            else:
                day_date = datetime(year, month, day).date()
                if day_date <= today:
                    row.append(_cb("·", "ignore"))
                else:
                    row.append(_cb(str(day), f"admin_cal_day_{year}_{month}_{day}"))
        rows.append(row)

    prev_m = month - 1 or 12
    prev_y = year - 1 if month == 1 else year
    next_m = month + 1 if month < 12 else 1
    next_y = year + 1 if month == 12 else year
    rows.append([
        _cb("◀️", f"admin_cal_month_{prev_y}_{prev_m}"),
        _cb("В админку", "admin_slots"),
        _cb("▶️", f"admin_cal_month_{next_y}_{next_m}"),
    ])
    return kb(rows)


def get_admin_time_keyboard(year, month, day, blocked_slots=None):
    """Выбор времени для блокировки админом"""
    rows = []
    rows.append([_cb(f"🚫 Время на {day:02d}.{month:02d}.{year}", "ignore")])

    blocked_set = set(blocked_slots or [])
    hours = list(range(10, 21))
    row = []
    for hour in hours:
        slot = f"{year}-{month:02d}-{day:02d} {hour:02d}:00"
        if slot in blocked_set:
            row.append(_cb(f"🔒{hour:02d}:00", "ignore"))
        else:
            row.append(_cb(f"{hour:02d}:00", f"admin_cal_time_{year}_{month}_{day}_{hour}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        _cb("🔒 Весь день", f"admin_block_day_{year}_{month}_{day}"),
        _cb("◀️ К календарю", "admin_cal_back"),
    ])
    return kb(rows)


def get_about_keyboard():
    """Кнопки контактов в разделе О мастере"""
    from config import BOT_VK_LABEL, BOT_VK_URL
    return kb([
        [_link(f"🌐 {BOT_VK_LABEL}", BOT_VK_URL)],
        [_cb("◀️ В меню", "menu")],
    ])


# ============ ОТЗЫВЫ ============

def get_rating_keyboard():
    rows = [[_cb("⭐" * i, f"rating_{i}") for i in range(1, 6)]]
    rows.append([_cb("◀️ В меню", "menu")])
    return kb(rows)


def get_reviews_keyboard():
    return kb([
        [_cb("✍️ Оставить отзыв", "add_review")],
        [_cb("◀️ В меню", "menu")],
    ])


# ============ АДМИН ============

def get_admin_keyboard():
    return kb([
        [_cb("📋 Все записи", "admin_bookings"), _cb("➕ Добавить работу", "admin_add_work")],
        [_cb("🗑 Управление портфолио", "admin_portfolio"), _cb("🚫 Блокировка слотов", "admin_slots")],
        [_cb("◀️ В меню", "menu")],
    ])


def get_admin_bookings_keyboard(bookings):
    rows = []
    for b in bookings[:10]:
        rows.append([_cb(
            f"{BOOKING_STATUS_SHORT.get(b['status'], '⚠️')} #{b['id']} — {b['date_time'][:16]}",
            f"admin_booking_{b['id']}")])
    rows.append([_cb("◀️ В админку", "admin")])
    return kb(rows)


def get_my_bookings_keyboard(bookings):
    """Кнопки отмены для активных записей клиента (pending/confirmed)."""
    rows = []
    for b in bookings:
        if b['status'] in ('pending', 'confirmed'):
            rows.append([_cb(f"❌ Отменить запись #{b['id']}", f"my_cancel_{b['id']}")])
    rows.append([_cb("◀️ В меню", "menu")])
    return kb(rows)


def get_confirm_cancel_keyboard(booking_id):
    """Подтверждение отказа от записи со стороны клиента."""
    return kb([
        [_cb("✅ Да, отказаться", f"confirm_my_cancel_{booking_id}")],
        [_cb("◀️ Назад", "my_bookings")],
    ])


def get_admin_booking_actions(booking_id, status=None):
    rows = []
    if status != 'client_cancelled':
        rows.append([
            _cb("✅ Подтвердить", f"ab_confirm_{booking_id}"),
            _cb("✨ Завершить", f"ab_complete_{booking_id}"),
        ])
    rows.append([
        _cb("❌ Отменить", f"ab_cancel_{booking_id}"),
        _cb("💬 Написать клиенту", f"ab_msg_{booking_id}"),
    ])
    rows.append([_cb("◀️ Назад", "admin_bookings")])
    return kb(rows)


def get_admin_portfolio_keyboard(works):
    rows = []
    for w in works[:10]:
        rows.append([_cb(f"🗑 {w['title']} (#{w['id']})", f"del_work_{w['id']}")])
    rows.append([_cb("◀️ В админку", "admin")])
    return kb(rows)
