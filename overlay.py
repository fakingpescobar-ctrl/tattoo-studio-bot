"""
Оверлей запуска бота в стиле neofetch/screenfetch:
  слева — ASCII-картинка тату-машинки (градиентная раскраска),
  справа — колонка с информацией о системе, боте, статистикой и ближайшими записями.

Если рядом с ботом лежит файл `art.txt` — он используется вместо встроенной
картинки (для кастомного ASCII-арта).

API не менялся: show_overlay() при старте, refresh_overlay() при перерисовке.
"""
import os
import re
import sys
import threading
from datetime import datetime

from database import (get_all_bookings, get_portfolio, get_services,
                      get_reviews, get_rating_stats)

# Блокировка, чтобы автообновление и ручное обновление не конфликтовали
_overlay_lock = threading.Lock()

# ============ ЦВЕТА ============

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

# ============ ASCII-КАРТИНКА ============

ART_RAW = r"""              /\
             /  \
            /    \
           /      \
          /        \
         /          \
        /            \
       /              \
      /                \
     /                  \
    /                    \
   /                      \
  /                        \
 /                          \
/____________________________\
"""

# Палитра раскраски строк арта. Один белый = ч/б арт (по запросу).
ART_PALETTE = [C.W]

ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _vlen(s):
    """Длина строки без ANSI-кодов (для выравнивания)."""
    return len(ANSI_RE.sub('', s))


def _trim_art(lines):
    """Обрезает пустые строки сверху/снизу и общий левый отступ.
    Если арт шире MAX_ART_W или выше MAX_ART_H — сжимает по X/Y в 2 раза
    (каждый 2-й символ / каждая 2-я строка), чтобы влезть рядом с колонкой."""
    MAX_ART_W = 42
    MAX_ART_H = 26

    # Табы → пробелы, убираем хвостовые пробелы, пустые строки сверху/снизу
    lines = [l.expandtabs(4).rstrip() for l in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return []

    # Левый отступ — МИНИМУМ по строкам: он всегда безопасен, ни одна
    # строка не обрежется (у основания пирамиды отступ меньше, чем у вершины).
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    indent = min(indents) if indents else 0
    if indent:
        lines = [l[indent:] if len(l) >= indent else l for l in lines]

    # Сжатие по X, если слишком широко. Единый сдвиг для всех строк
    # сохраняет вертикальную ось арта (по самой широкой строке).
    width = max((len(l) for l in lines), default=0)
    if width > MAX_ART_W:
        shift = 1 if width % 2 else 0
        lines = [l[shift::2] if len(l) > shift else l for l in lines]

    # Сжатие по Y, если слишком высоко
    if len(lines) > MAX_ART_H:
        lines = lines[::2]

    return lines


def _get_art():
    """Возвращает список строк арта. Приоритет: ascii-art.txt → art.txt → ART_RAW."""
    for name in ('ascii-art.txt', 'art.txt'):
        if os.path.exists(name):
            try:
                with open(name, encoding='utf-8') as f:
                    content = f.read()
                if content.strip():
                    return _trim_art(content.split('\n'))
            except (OSError, UnicodeDecodeError):
                pass
    return _trim_art(ART_RAW.split('\n'))


def _colorize_art(lines):
    """Раскрашивает строки арта градиентом (палитра повторяется)."""
    out = []
    for i, line in enumerate(lines):
        color = ART_PALETTE[i % len(ART_PALETTE)]
        out.append(color + line + C.RST)
    return out


# ============ СБОРКА БЛОКОВ ============

def _side_by_side(left_lines, right_lines, gap=6):
    """Склеивает два многострочных блока в один: левый арт + правая колонка.
    Учитывает ANSI-коды: отступ считается по видимой длине строки."""
    h = max(len(left_lines), len(right_lines))
    left_w = max((_vlen(l) for l in left_lines), default=0)
    rows = []
    for i in range(h):
        l = left_lines[i] if i < len(left_lines) else ''
        r = right_lines[i] if i < len(right_lines) else ''
        if r:
            pad = max(0, left_w - _vlen(l) + gap)
            rows.append(l + ' ' * pad + r)
        else:
            rows.append(l)
    return rows


def _kv(label, value, color=C.CY):
    """Строка 'label: value' в стиле neofetch (цветной ключ, белое значение)."""
    return f"{C.BOLD}{color}{label}:{C.RST} {C.W}{value}{C.RST}"


def _section(title):
    """Заголовок секции в правой колонке."""
    return f"{C.BOLD}{C.Y}{title}{C.RST}"


# ============ ИНФОРМАЦИЯ ============

def _system_lines():
    """Проверка системы: Python, библиотеки, токен, БД, .env."""
    lines = []

    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    lines.append(_kv("ОС", "Windows", C.Y))
    lines.append(_kv("Python", ver, C.Y))

    # Библиотеки
    try:
        import importlib.metadata
        tbot_ver = importlib.metadata.version('pytelegrambotapi')
        lines.append(_kv("BotAPI", f"pyTelegramBotAPI v{tbot_ver}", C.Y))
    except Exception:
        lines.append(_kv("BotAPI", "pyTelegramBotAPI (не определена)", C.Y))

    # Токен и админ
    from config import BOT_TOKEN, ADMIN_IDS
    if BOT_TOKEN and BOT_TOKEN != 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
        lines.append(_kv("Токен", f"✓ установлен ({BOT_TOKEN[:8]}...)", C.G))
    else:
        lines.append(_kv("Токен", f"✗ НЕ установлен!", C.R))

    if ADMIN_IDS:
        label = "Админ" if len(ADMIN_IDS) == 1 else "Админы"
        ids = ", ".join(str(i) for i in ADMIN_IDS)
        lines.append(_kv(label, f"✓ ID {ids}", C.G))
    else:
        lines.append(_kv("Админ", "не указан", C.Y))

    # База данных
    db_path = 'tattoo_bot.db'
    if os.path.exists(db_path):
        size = os.path.getsize(db_path)
        lines.append(_kv("БД", f"✓ tattoo_bot.db ({size // 1024} КБ)", C.G))
    else:
        lines.append(_kv("БД", "будет создана", C.Y))

    # Файл .env
    if os.path.exists('.env'):
        lines.append(_kv(".env", "✓ найден", C.G))
    else:
        lines.append(_kv(".env", "✗ НЕ найден!", C.R))

    return lines


def _stats_lines(bookings):
    """Статистика базы данных."""
    services = get_services()
    portfolio = get_portfolio()
    reviews = get_reviews()
    avg, cnt = get_rating_stats()

    active = [b for b in bookings if b['status'] in ('pending', 'confirmed')]
    rating = f"{avg:.1f}/5" if cnt else "—"

    return [
        _kv("💰 Услуги", len(services), C.Y),
        _kv("🎨 Работ", len(portfolio), C.M),
        _kv("⭐ Отзывы", f"{cnt}  (рейтинг {rating})", C.Y),
        _kv("📅 Всего записей", len(bookings), C.B),
        _kv("🔔 Активных", len(active), C.G),
    ]


def _upcoming_lines(bookings):
    """Ближайшие активные записи (до 4)."""
    now = datetime.now()
    upcoming = []
    for b in bookings:
        if b['status'] not in ('pending', 'confirmed'):
            continue
        try:
            dt = datetime.strptime((b['date_time'] or '').strip(), "%d.%m.%Y %H:%M")
        except (ValueError, TypeError):
            continue
        if dt >= now:
            upcoming.append((dt, b))

    if not upcoming:
        return [f"{C.DIM}  Нет предстоящих записей{C.RST}"]

    upcoming.sort(key=lambda x: x[0])
    lines = []
    for dt, b in upcoming[:4]:
        name = b['first_name'] or 'Клиент'
        uname = f"@{b['username']}" if b['username'] else ""
        when = dt.strftime('%d.%m %H:%M')
        if dt.date() == now.date():
            when = f"{C.R}{C.BOLD}СЕГОДНЯ {dt.strftime('%H:%M')}{C.RST}"
        elif (dt.date() - now.date()).days == 1:
            when = f"{C.Y}завтра {dt.strftime('%H:%M')}{C.RST}"
        service = (b['service'] or '')[:18]
        lines.append(f"  {C.BOLD}• #{b['id']}{C.RST} {when} — {name} {C.DIM}{uname}{C.RST}")
        lines.append(f"      {C.DIM}{service}{C.RST}")
    return lines


# ============ ПОЛНАЯ КОЛОНКА ============

def build_info_lines():
    """Собирает всю правую колонку neofetch-стиля."""
    lines = []
    bookings = get_all_bookings()  # один запрос для статистики и ближайших записей

    # Шапка как user@host
    lines.append(f"{C.BOLD}{C.G}Максим Андреевич{C.RST} {C.W}@{C.RST} {C.BOLD}{C.CY}tatoo_asbest_best_bot{C.RST}")
    lines.append(f"{C.DIM}{'─' * 40}{C.RST}")

    lines.extend(_system_lines())
    lines.append("")
    lines.append(_section("СТАТИСТИКА"))
    lines.extend(_stats_lines(bookings))
    lines.append("")
    lines.append(_section("БЛИЖАЙШИЕ ЗАПИСИ"))
    lines.extend(_upcoming_lines(bookings))
    lines.append("")
    lines.append(_kv("Статус", "✅ БОТ ЗАПУЩЕН", C.G))

    return lines


def _render():
    """Полный рендер: арт слева + инфо справа."""
    art = _colorize_art(_get_art())
    info = build_info_lines()
    block = _side_by_side(art, info)
    print('\n'.join(block))
    print(f"\n{C.DIM}Окно не закрывайте! Ctrl+C — остановка.{C.RST}")
    print()


# ============ ПУБЛИЧНЫЙ API ============

def show_overlay():
    """Полный оверлей запуска (неочищающий первый рендер)."""
    # Инициализация ANSI-цветов для Windows
    if os.name == 'nt':
        os.system('')
    with _overlay_lock:
        _render()


def refresh_overlay():
    """Перерисовка оверлея после действий (новая запись, добавление работы и т.д.).
    Очищает экран и рисует заново. Потокобезопасно."""
    with _overlay_lock:
        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')
        _render()


# Для обратной совместимости (если что-то вызывало старые функции)
def show_banner():
    _render()


def show_stats():
    info = build_info_lines()
    print('\n'.join(_side_by_side(_colorize_art(_get_art()), info)))


def check_system():
    return True
