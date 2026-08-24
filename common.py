"""
Общие утилиты и константы для TG и MAX ботов (дедуп handlers/max_handlers).

Содержит:
  • price_text / fmt_dt / slot_key / booking_to_slot_key — форматирование слотов
  • BOOKING_STATUS_RU — маппинг статусов записей для отображения
  • MONTHS_RU / WEEKDAYS_RU — локализация календаря
"""
from datetime import datetime

# ============ СТАТУСЫ ЗАПИСЕЙ ============

BOOKING_STATUS_RU = {
    'pending':          '⏳ Ожидает',
    'confirmed':        '✅ Подтверждена',
    'cancelled':        '❌ Отменена',
    'completed':        '✨ Завершена',
    'client_cancelled': '🚫 Отказ клиента (ожидает мастера)',
}

# Короткие эмодзи-статусы для списков (админ-таблица)
BOOKING_STATUS_SHORT = {
    'pending':          '⏳',
    'confirmed':        '✅',
    'cancelled':        '❌',
    'completed':        '✨',
    'client_cancelled': '🚫',
}

ACTIVE_BOOKING_STATUSES = ('pending', 'confirmed')

# ============ СЛОТЫ ВРЕМЕНИ ============

def fmt_dt(y, m, d, h):
    """Отображаемая дата записи: DD.MM.YYYY HH:00"""
    return f"{d:02d}.{m:02d}.{y} {h:02d}:00"


def slot_key(y, m, d, h):
    """Ключ слота для БД: YYYY-MM-DD HH:00"""
    return f"{y}-{m:02d}-{d:02d} {h:02d}:00"


def booking_to_slot_key(date_time_str):
    """Конвертирует отображаемую дату записи (DD.MM.YYYY HH:MM) в ключ слота.
    Возвращает None, если строку не удалось разобрать."""
    try:
        dt = datetime.strptime(date_time_str.strip(), "%d.%m.%Y %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None


# ============ ЦЕНЫ ============

def price_text(pmin, pmax):
    """Строка цены: договорная / фикс / диапазон."""
    pmin, pmax = int(pmin), int(pmax)
    if pmin == 0 and pmax == 0:
        return "💵 Цена договорная"
    if pmin == pmax:
        return f"💵 {pmin}₽"
    return f"💵 от {pmin} до {pmax}₽"


def price_short(pmin, pmax):
    """Компактная строка цены для кнопок: договорная / фикс / от N₽."""
    pmin, pmax = int(pmin), int(pmax)
    if pmin == 0 and pmax == 0:
        return "договорная"
    if pmin == pmax:
        return f"{pmin}₽"
    return f"от {pmin}₽"


# ============ КАЛЕНДАРЬ ============

MONTHS_RU = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
             "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
