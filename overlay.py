"""
Красивый оверлей запуска бота:
- ASCII-баннер
- Проверка системы (база данных, библиотеки, токен)
- Ближайшие записи клиентов
"""
import os
import sys
import threading
from datetime import datetime

from database import get_all_bookings, get_portfolio, get_services, get_reviews, get_rating_stats

# Блокировка, чтобы автообновление и ручное обновление не конфликтовали
_overlay_lock = threading.Lock()


# Цвета для Windows консоли
class C:
    R = '\033[91m'     # красный
    G = '\033[92m'     # зелёный
    Y = '\033[93m'     # жёлтый
    B = '\033[94m'     # синий
    M = '\033[95m'     # пурпурный
    CY = '\033[96m'    # голубой
    W = '\033[97m'     # белый
    BOLD = '\033[1m'   # жирный
    DIM = '\033[2m'    # тусклый
    RST = '\033[0m'    # сброс


def _ok(msg):
    return f"{C.G}✓{C.RST} {msg}"


def _err(msg):
    return f"{C.R}✗{C.RST} {msg}"


def _warn(msg):
    return f"{C.Y}!{C.RST} {msg}"


def _line(char='─', width=56):
    return char * width


def show_banner():
    """ASCII-баннер PRIZMA — призма-треугольник"""
    banner = f"""{C.CY}{C.BOLD}
    ╔══════════════════════════════════════════╗
    ║                                          ║
    ║                    /\\                   ║
    ║                   /  \\                  ║
    ║                  / /\\ \\                 ║
    ║                 / /  \\ \\                ║
    ║                / /    \\ \\               ║
    ║               / /      \\ \\              ║
    ║              /__________\\               ║
    ║                                          ║
    ║            P  R  I  Z  M  A             ║
    ║                                          ║
    ║   Максим Андреевич · Асбест              ║
    ╚══════════════════════════════════════════╝
{C.RST}"""
    print(banner)


def check_system():
    """Проверка компонентов системы"""
    print(f"{C.BOLD}{' ПРОВЕРКА СИСТЕМЫ ':=^56}{C.RST}")
    print()

    checks = []

    # 1. Python
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(_ok(f"Python {ver}"))

    # 2. Библиотеки
    try:
        import telebot
        import importlib.metadata
        ver = importlib.metadata.version('pytelegrambotapi')
        checks.append(_ok(f"pyTelegramBotAPI v{ver}"))
    except Exception:
        try:
            import telebot
            checks.append(_ok("pyTelegramBotAPI установлен"))
        except ImportError:
            checks.append(_err("pyTelegramBotAPI не установлен!"))

    try:
        from dotenv import dotenv_values
        checks.append(_ok("python-dotenv установлен"))
    except ImportError:
        checks.append(_err("python-dotenv не установлен!"))

    # 3. Токен
    from config import BOT_TOKEN, ADMIN_ID
    if BOT_TOKEN and BOT_TOKEN != 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
        checks.append(_ok(f"Токен бота установлен ({BOT_TOKEN[:8]}...)"))
    else:
        checks.append(_err("Токен бота НЕ установлен!"))

    # 4. Админ ID
    if ADMIN_ID:
        checks.append(_ok(f"ADMIN_ID: {ADMIN_ID}"))
    else:
        checks.append(_warn("ADMIN_ID не указан"))

    # 5. База данных
    db_path = 'tattoo_bot.db'
    if os.path.exists(db_path):
        size = os.path.getsize(db_path)
        checks.append(_ok(f"База данных ({size // 1024} КБ)"))
    else:
        checks.append(_warn("База данных будет создана"))

    # 6. Файл .env
    if os.path.exists('.env'):
        checks.append(_ok("Файл .env найден"))
    else:
        checks.append(_err("Файл .env НЕ найден!"))

    for c in checks:
        print(f"  {c}")

    print()
    return all('✓' in c for c in checks)


def show_stats():
    """Статистика базы данных"""
    from database import invalidate_cache
    # Сбрасываем кэш, чтобы получить свежие данные
    invalidate_cache('get_services', 'get_portfolio', 'get_reviews', 'get_rating_stats', 'get_all_bookings', 'get_user_bookings')

    print(f"{C.BOLD}{' СТАТИСТИКА ':=^56}{C.RST}")
    print()

    services = get_services()
    portfolio = get_portfolio()
    reviews = get_reviews()
    avg, cnt = get_rating_stats()
    bookings = get_all_bookings()

    # Считаем активные записи (не отменённые)
    active = [b for b in bookings if b['status'] in ('pending', 'confirmed')]

    stats = [
        (f"💰 Услуги в прайсе", len(services), C.Y),
        (f"🎨 Работ в портфолио", len(portfolio), C.M),
        (f"⭐ Отзывов", cnt, C.Y),
        (f"📊 Средний рейтинг", f"{avg:.1f}/5" if cnt else "—", C.G),
        (f"📅 Всего записей", len(bookings), C.B),
        (f"🔔 Активных записей", len(active), C.G),
    ]

    for label, value, color in stats:
        print(f"  {label}: {color}{C.BOLD}{value}{C.RST}")

    print()


def show_upcoming_bookings():
    """Ближайшие записи клиентов"""
    from database import invalidate_cache
    invalidate_cache('get_all_bookings')

    print(f"{C.BOLD}{' БЛИЖАЙШИЕ ЗАПИСИ ':=^56}{C.RST}")
    print()

    bookings = get_all_bookings()
    now = datetime.now()

    # Парсим дату и фильтруем будущие + активные
    upcoming = []
    for b in bookings:
        if b['status'] in ('cancelled', 'completed'):
            continue
        try:
            dt = datetime.strptime(b['date_time'], "%d.%m.%Y %H:%M")
            if dt >= now:
                upcoming.append((dt, b))
        except (ValueError, TypeError):
            continue

    if not upcoming:
        print(f"  {C.DIM}Нет предстоящих записей{C.RST}")
        print()
        return

    # Сортируем по дате
    upcoming.sort(key=lambda x: x[0])

    status_icon = {
        'pending': f"{C.Y}⏳{C.RST}",
        'confirmed': f"{C.G}✅{C.RST}",
    }

    for dt, b in upcoming[:5]:
        name = b['first_name'] or 'Клиент'
        uname = f"@{b['username']}" if b['username'] else ""

        # Сколько осталось дней
        delta = dt - now
        days = delta.days
        if days == 0:
            when = f"{C.R}{C.BOLD}СЕГОДНЯ в {dt.strftime('%H:%M')}!{C.RST}"
        elif days == 1:
            when = f"{C.Y}Завтра в {dt.strftime('%H:%M')}{C.RST}"
        else:
            when = f"через {days} дн. ({dt.strftime('%d.%m %H:%M')})"

        icon = status_icon.get(b['status'], '📋')
        print(f"  {icon} {C.BOLD}#{b['id']}{C.RST} {name} {C.DIM}{uname}{C.RST}")
        print(f"      📝 {b['service']}")
        print(f"      📅 {b['date_time']}  →  {when}")
        if b['description']:
            desc = b['description'][:50] + ('...' if len(b['description']) > 50 else '')
            print(f"      💡 {desc}")
        print()

    if len(upcoming) > 5:
        print(f"  {C.DIM}...и ещё {len(upcoming) - 5} записей{C.RST}")
        print()


def show_ready():
    """Финальное сообщение готовности"""
    print(f"{C.G}{C.BOLD}{' БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ! ':=^56}{C.RST}")
    print()
    print(f"  {C.CY}Бот: {C.BOLD}@tatoo_asbest_best_bot{C.RST}")
    print(f"  {C.CY}Мастер: {C.BOLD}Максим Андреевич{C.RST}")
    print(f"  {C.CY}Город: {C.BOLD}Асбест, ул. Заводская, 4{C.RST}")
    print()
    print(f"  {C.DIM}Окно не закрывайте! Ctrl+C — остановка.{C.RST}")
    print(f"{C.DIM}{'─' * 56}{C.RST}")
    print()


def show_overlay():
    """Полный оверлей запуска"""
    # Инициализация ANSI-цветов для Windows
    if os.name == 'nt':
        os.system('')  # активируем обработку ANSI-кодов

    show_banner()
    check_system()
    show_stats()
    show_upcoming_bookings()
    show_ready()


def refresh_overlay():
    """Обновление оверлея после действий (добавление работы, новая запись и т.д.)
    Очищает экран и перерисовывает только статистику и записи.
    Потокобезопасно — использует блокировку."""
    with _overlay_lock:
        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')

        show_banner()
        show_stats()
        show_upcoming_bookings()
        show_ready()
