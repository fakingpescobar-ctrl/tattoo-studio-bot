import calendar
from datetime import datetime
from telebot import types

from common import (ACTIVE_BOOKING_STATUSES, BOOKING_STATUS_SHORT,
                    MONTHS_RU, WEEKDAYS_RU, price_short)

# ============ ГЛАВНОЕ МЕНЮ ============

def get_main_menu(is_admin=False):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_admin:
        # Админ видит ТОЛЬКО свои функции — без портфолио/прайса/записи
        markup.add(
            types.InlineKeyboardButton("📋 Все записи", callback_data="admin_bookings"),
            types.InlineKeyboardButton("➕ Добавить работу", callback_data="admin_add_work"),
            types.InlineKeyboardButton("🗑 Управление портфолио", callback_data="admin_portfolio"),
            types.InlineKeyboardButton("🚫 Блокировка слотов", callback_data="admin_slots"),
            types.InlineKeyboardButton("⭐ Отзывы", callback_data="reviews"),
        )
    else:
        markup.add(
            types.InlineKeyboardButton("🎨 Портфолио", callback_data="portfolio"),
            types.InlineKeyboardButton("📅 Записаться", callback_data="booking_start"),
            types.InlineKeyboardButton("💰 Прайс-лист", callback_data="price"),
            types.InlineKeyboardButton("⭐ Отзывы", callback_data="reviews"),
            types.InlineKeyboardButton("👤 Мои записи", callback_data="my_bookings"),
            types.InlineKeyboardButton("ℹ️ О мастере", callback_data="about"),
        )
    return markup

# ============ БАЗОВЫЕ ============

def get_back_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("◀️ В меню", callback_data="menu"))
    return markup

def get_services_keyboard(services):
    markup = types.InlineKeyboardMarkup()
    for s in services:
        markup.add(types.InlineKeyboardButton(
            text=f"{s['name']} — {price_short(s['price_min'], s['price_max'])}",
            callback_data=f"service_{s['id']}"
        ))
    markup.add(types.InlineKeyboardButton("◀️ В меню", callback_data="menu"))
    return markup

def get_confirmation_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data="booking_confirm"),
        types.InlineKeyboardButton("❌ Отменить", callback_data="booking_cancel"),
    )
    return markup

# ============ КАЛЕНДАРЬ ============

def _ign():
    return types.InlineKeyboardButton(text=" ", callback_data="ignore")

def get_calendar_keyboard(year, month):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text=f"{MONTHS_RU[month]} {year}", callback_data="ignore"))

    # Дни недели
    markup.add(*[types.InlineKeyboardButton(text=d, callback_data="ignore")
                 for d in WEEKDAYS_RU])

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
                    row.append(types.InlineKeyboardButton(text="·", callback_data="ignore"))
                else:
                    row.append(types.InlineKeyboardButton(
                        text=str(day), callback_data=f"cal_day_{year}_{month}_{day}"))
        markup.row(*row)

    prev_m = month - 1 or 12
    prev_y = year - 1 if month == 1 else year
    next_m = month + 1 if month < 12 else 1
    next_y = year + 1 if month == 12 else year

    markup.add(
        types.InlineKeyboardButton("◀️", callback_data=f"cal_month_{prev_y}_{prev_m}"),
        types.InlineKeyboardButton("В меню", callback_data="booking_start"),
        types.InlineKeyboardButton("▶️", callback_data=f"cal_month_{next_y}_{next_m}"),
    )
    return markup

def get_time_slots_keyboard(year, month, day, blocked_slots=None):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text=f"⏰ Время на {day:02d}.{month:02d}.{year}", callback_data="ignore"))

    blocked_set = set(blocked_slots or [])
    hours = list(range(10, 21))
    row = []
    for hour in hours:
        slot = f"{year}-{month:02d}-{day:02d} {hour:02d}:00"
        if slot in blocked_set:
            row.append(types.InlineKeyboardButton(text=f"❌{hour:02d}", callback_data="ignore"))
        else:
            row.append(types.InlineKeyboardButton(
                text=f"{hour:02d}:00",
                callback_data=f"cal_time_{year}_{month}_{day}_{hour}"))
        if len(row) == 3:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)

    markup.add(types.InlineKeyboardButton("◀️ К календарю", callback_data="cal_back"))
    return markup

def get_admin_calendar_keyboard(year, month):
    """Календарь для блокировки слотов админом"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text=f"🚫 {MONTHS_RU[month]} {year}", callback_data="ignore"))

    markup.add(*[types.InlineKeyboardButton(text=d, callback_data="ignore")
                 for d in WEEKDAYS_RU])

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
                    row.append(types.InlineKeyboardButton(text="·", callback_data="ignore"))
                else:
                    row.append(types.InlineKeyboardButton(
                        text=str(day), callback_data=f"admin_cal_day_{year}_{month}_{day}"))
        markup.row(*row)

    prev_m = month - 1 or 12
    prev_y = year - 1 if month == 1 else year
    next_m = month + 1 if month < 12 else 1
    next_y = year + 1 if month == 12 else year

    markup.add(
        types.InlineKeyboardButton("◀️", callback_data=f"admin_cal_month_{prev_y}_{prev_m}"),
        types.InlineKeyboardButton("В админку", callback_data="admin_slots"),
        types.InlineKeyboardButton("▶️", callback_data=f"admin_cal_month_{next_y}_{next_m}"),
    )
    return markup

def get_admin_time_keyboard(year, month, day, blocked_slots=None):
    """Выбор времени для блокировки админом"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text=f"🚫 Время на {day:02d}.{month:02d}.{year}", callback_data="ignore"))

    blocked_set = set(blocked_slots or [])
    hours = list(range(10, 21))
    row = []
    for hour in hours:
        slot = f"{year}-{month:02d}-{day:02d} {hour:02d}:00"
        if slot in blocked_set:
            row.append(types.InlineKeyboardButton(text=f"🔒{hour:02d}:00", callback_data="ignore"))
        else:
            row.append(types.InlineKeyboardButton(
                text=f"{hour:02d}:00",
                callback_data=f"admin_cal_time_{year}_{month}_{day}_{hour}"))
        if len(row) == 3:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)

    markup.add(
        types.InlineKeyboardButton("🔒 Весь день", callback_data=f"admin_block_day_{year}_{month}_{day}"),
        types.InlineKeyboardButton("◀️ К календарю", callback_data="admin_cal_back"),
    )
    return markup

def get_admin_dashboard_calendar(year, month, bookings=None, blocked_slots=None):
    """Календарь-дашборд для админа: показывает записи и заблокированные дни.

    Маркеры дней:
      🔴 — есть активные записи (pending/confirmed)
      ⬛ — все слоты заблокированы
      (число) — свободные дни
    """
    bookings = bookings or []
    blocked_slots = blocked_slots or []

    # Агрегация по дням
    from common import slot_key as _sk
    from datetime import datetime as _dt

    booked_days = set()   # дни с активными записями
    blocked_days = set()  # дни, где ВСЕ слоты (10-20) заблокированы

    for b in bookings:
        if b['status'] in ('pending', 'confirmed'):
            try:
                dt = _dt.strptime(b['date_time'].strip(), "%d.%m.%Y %H:%M")
                booked_days.add(dt.day)
            except (ValueError, TypeError):
                pass

    # Считаем заблокированные слоты по дням
    blocked_by_day = {}
    for slot in blocked_slots:
        try:
            # slot = "YYYY-MM-DD HH:00"
            day = int(slot.split('-')[2].split()[0])
            blocked_by_day[day] = blocked_by_day.get(day, 0) + 1
        except (ValueError, IndexError):
            pass
    # День считается полностью заблокированным, если заблокированы все 11 слотов (10:00-20:00)
    for day, count in blocked_by_day.items():
        if count >= 11:
            blocked_days.add(day)

    today = _dt.now().date()

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text=f"📅 {MONTHS_RU[month]} {year}", callback_data="ignore"))

    markup.add(*[types.InlineKeyboardButton(text=d, callback_data="ignore")
                 for d in WEEKDAYS_RU])

    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(_ign())
            else:
                day_date = _dt(year, month, day).date()
                if day_date < today:
                    # Прошедшее — серая точка
                    row.append(types.InlineKeyboardButton(text="·", callback_data="ignore"))
                elif day in blocked_days:
                    # Полностью заблокирован
                    row.append(types.InlineKeyboardButton(text="⬛", callback_data="ignore"))
                elif day in booked_days:
                    # Есть записи
                    row.append(types.InlineKeyboardButton(
                        text=f"🔴{day}", callback_data=f"admin_dash_day_{year}_{month}_{day}"))
                else:
                    # Свободен
                    row.append(types.InlineKeyboardButton(
                        text=str(day), callback_data=f"admin_dash_day_{year}_{month}_{day}"))
        markup.row(*row)

    prev_m = month - 1 or 12
    prev_y = year - 1 if month == 1 else year
    next_m = month + 1 if month < 12 else 1
    next_y = year + 1 if month == 12 else year

    markup.add(
        types.InlineKeyboardButton("◀️", callback_data=f"admin_dash_cal_{prev_y}_{prev_m}"),
        types.InlineKeyboardButton("📋 В записи", callback_data="admin_bookings"),
        types.InlineKeyboardButton("▶️", callback_data=f"admin_dash_cal_{next_y}_{next_m}"),
    )
    # Кнопки админ-панели внизу
    markup.add(
        types.InlineKeyboardButton("🚫 Блокировка", callback_data="admin_slots"),
        types.InlineKeyboardButton("➕ Работа", callback_data="admin_add_work"),
        types.InlineKeyboardButton("⭐ Отзывы", callback_data="reviews"),
    )
    markup.add(
        types.InlineKeyboardButton("🔧 В админку", callback_data="admin"),
    )
    return markup

def get_about_keyboard():
    """Кнопки контактов в разделе О мастере"""
    from config import BOT_VK_LABEL, BOT_VK_URL
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"🌐 {BOT_VK_LABEL}", url=BOT_VK_URL))
    markup.add(types.InlineKeyboardButton("◀️ В меню", callback_data="menu"))
    return markup

# ============ ОТЗЫВЫ ============

def get_rating_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(*[types.InlineKeyboardButton("⭐" * i, callback_data=f"rating_{i}")
                 for i in range(1, 6)])
    markup.add(types.InlineKeyboardButton("◀️ В меню", callback_data="menu"))
    return markup

def get_reviews_keyboard(is_admin=False, reviews=None):
    markup = types.InlineKeyboardMarkup()
    if is_admin and reviews:
        for r in reviews:
            label = f"💬 Ответить на #{r['id']}" if not r['admin_reply'] else f"✅ #{r['id']} (отвечен)"
            markup.add(types.InlineKeyboardButton(label, callback_data=f"admin_reply_review_{r['id']}"))
    markup.add(types.InlineKeyboardButton("✍️ Оставить отзыв", callback_data="add_review"))
    markup.add(types.InlineKeyboardButton("◀️ В меню", callback_data="menu"))
    return markup

# ============ АДМИН ============

def get_admin_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("📋 Все записи", callback_data="admin_bookings"),
        types.InlineKeyboardButton("➕ Добавить работу", callback_data="admin_add_work"),
        types.InlineKeyboardButton("🗑 Управление портфолио", callback_data="admin_portfolio"),
        types.InlineKeyboardButton("🚫 Блокировка слотов", callback_data="admin_slots"),
        types.InlineKeyboardButton("◀️ В меню", callback_data="menu"),
    )
    return markup

def get_my_bookings_keyboard(bookings):
    """Кнопки отмены для активных записей клиента (pending/confirmed)"""
    markup = types.InlineKeyboardMarkup()
    for b in bookings:
        if b['status'] in ACTIVE_BOOKING_STATUSES:
            markup.add(types.InlineKeyboardButton(
                f"❌ Отменить запись #{b['id']}",
                callback_data=f"my_cancel_{b['id']}"))
    markup.add(types.InlineKeyboardButton("◀️ В меню", callback_data="menu"))
    return markup

def get_confirm_cancel_keyboard(booking_id):
    """Подтверждение отказа от записи со стороны клиента"""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Да, отказаться", callback_data=f"confirm_my_cancel_{booking_id}"),
        types.InlineKeyboardButton("◀️ Назад", callback_data="my_bookings"),
    )
    return markup

def get_admin_bookings_keyboard(bookings):
    markup = types.InlineKeyboardMarkup()
    for b in bookings[:10]:
        markup.add(types.InlineKeyboardButton(
            text=f"{BOOKING_STATUS_SHORT.get(b['status'], '⚠️')} #{b['id']} — {b['date_time'][:16]}",
            callback_data=f"admin_booking_{b['id']}"))
    markup.add(types.InlineKeyboardButton("◀️ В админку", callback_data="admin"))
    return markup

def get_admin_booking_actions(booking_id, status=None):
    markup = types.InlineKeyboardMarkup()
    if status != 'client_cancelled':
        markup.add(
            types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"ab_confirm_{booking_id}"),
            types.InlineKeyboardButton("✨ Завершить", callback_data=f"ab_complete_{booking_id}"),
        )
    markup.add(
        types.InlineKeyboardButton("❌ Отменить", callback_data=f"ab_cancel_{booking_id}"),
        types.InlineKeyboardButton("💬 Написать клиенту", callback_data=f"ab_msg_{booking_id}"),
    )
    markup.add(types.InlineKeyboardButton("◀️ Назад", callback_data="admin_bookings"))
    return markup

def get_contact_master_keyboard():
    """Кнопка «Связаться с мастером» — URL-кнопка, ведёт в чат бота."""
    from config import BOT_HANDLE
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📞 Связаться с мастером",
                                          url=f"https://t.me/{BOT_HANDLE}"))
    return markup

def get_admin_portfolio_keyboard(works):
    markup = types.InlineKeyboardMarkup()
    for w in works[:10]:
        markup.add(types.InlineKeyboardButton(
            text=f"🗑 {w['title']} (#{w['id']})",
            callback_data=f"del_work_{w['id']}"))
    markup.add(types.InlineKeyboardButton("◀️ В админку", callback_data="admin"))
    return markup
