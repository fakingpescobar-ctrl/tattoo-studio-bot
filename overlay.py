"""
Оверлей запуска бота в стиле neofetch:
  слева — ASCII-арт тату-машинки (truecolor-градиент cyan→magenta),
  справа — колонка с информацией о системе, статистикой и ближайшими записями.

Особенности редизайна:
  • truecolor (24-бит) градиент для арта
  • вертикальное центрирование арта относительно инфо-колонки
  • компактная компоновка без пустых дыр
  • UTF-8 stdout reconfigure — не падает на cp1251/cp866 консолях
  •的品牌-параметры из config.py (BOT_NAME, BOT_MASTER, ...)

Внешний арт: положите рядом `ascii-art.txt` или `art.txt`.

API не менялся: show_overlay() при старте, refresh_overlay() при перерисовке.
"""
import io
import os
import re
import sys
import threading
import time
from datetime import datetime

from config import BOT_NAME, BOT_MASTER, BOT_HANDLE, BOT_CITY, DB_PATH
from database import (get_all_bookings, get_portfolio, get_services,
                      get_reviews, get_rating_stats)

# Блокировка, чтобы автообновление и ручное обновление не конфликтовали
_overlay_lock = threading.Lock()

# Момент старта бота (для расчёта uptime)
_started_at = time.monotonic()


# ============ ЦВЕТА ============

class C:
    """Truecolor ANSI-коды. Работают в Windows Terminal / modern terminals."""
    R = '\033[91m'     # красный (fallback 8-бит)
    G = '\033[92m'     # зелёный
    Y = '\033[93m'     # жёлтый
    B = '\033[94m'     # синий
    M = '\033[95m'     # пурпурный
    CY = '\033[96m'    # голубой
    W = '\033[97m'     # белый
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    RST = '\033[0m'


def _rgb(r, g, b):
    """Truecolor 24-бит escape."""
    return f'\033[38;2;{r};{g};{b}m'


def _gradient_color(t):
    """Градиент cyan (0) → magenta (1). t ∈ [0, 1]."""
    t = max(0.0, min(1.0, t))
    r = int( 64 + (220 -  64) * t)
    g = int(224 + ( 80 - 224) * t)
    b = int(240 + (200 - 240) * t)
    return _rgb(r, g, b)


# ============ ASCII-АРТ ============

# Компактная тату-машинка (coil machine): катушка сверху → grip → игла.
# ~16 строк, хорошо ложится рядом с инфо-колонкой.
ART_RAW = r"""
         _.-._
        / o o \
       |   ◆   |
        \ ___ /
       __|   |__
      |  |   |  |
      |  |___|  |
       \|_|_|_|/
        |     |
       [=======]
        |     |
        |  |  |
        |  |  |
         \ | /
          \|/
           ◆
"""

ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _vlen(s):
    """Длина строки без ANSI-кодов (для выравнивания)."""
    return len(ANSI_RE.sub('', s))


def _trim_art(lines):
    """Обрезает пустые строки сверху/снизу и общий левый отступ.
    Если арт слишком широкий/высокий — сжимает."""
    MAX_ART_W = 52
    MAX_ART_H = 22

    lines = [l.expandtabs(4).rstrip() for l in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return []

    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    indent = min(indents) if indents else 0
    if indent:
        lines = [l[indent:] if len(l) >= indent else l for l in lines]

    width = max((len(l) for l in lines), default=0)
    if width > MAX_ART_W:
        shift = 1 if width % 2 else 0
        lines = [l[shift::2] if len(l) > shift else l for l in lines]

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
    """Раскрашивает арт truecolor-градиентом cyan→magenta (сверху вниз)."""
    if not lines:
        return []
    n = len(lines)
    out = []
    for i, line in enumerate(lines):
        t = i / max(1, n - 1)
        out.append(_gradient_color(t) + line + C.RST)
    return out


# ============ СБОРКА БЛОКОВ ============

def _side_by_side(left_lines, right_lines, gap=4):
    """Склеивает два блока. Левый арт вертикально центрирован относительно правого."""
    h = max(len(left_lines), len(right_lines))
    left_w = max((_vlen(l) for l in left_lines), default=0)
    rows = []

    # Вертикальное центрирование левого блока
    left_offset = max(0, (h - len(left_lines)) // 2)

    for i in range(h):
        li = i - left_offset
        l = left_lines[li] if 0 <= li < len(left_lines) else ''
        r = right_lines[i] if i < len(right_lines) else ''
        if r:
            pad = max(0, left_w - _vlen(l) + gap)
            rows.append(l + ' ' * pad + r)
        elif l:
            # строка только с артом (правая колонка короче)
            rows.append(l)
        else:
            rows.append('')
    return rows


def _kv(label, value, color=C.CY):
    """Строка 'label: value' в стиле neofetch."""
    return f"{C.BOLD}{color}{label}{C.RST} {C.W}{value}{C.RST}"


def _section(title):
    """Заголовок секции с подчёркиванием."""
    return f"{C.BOLD}{C.M}◇ {title}{C.RST}"


def _hr(width=44):
    """Тонкий разделитель."""
    return f"{C.DIM}{'─' * width}{C.RST}"


# ============ ИНФОРМАЦИЯ ============

def _system_lines():
    """Проверка системы: Python, библиотеки, токен, БД, .env."""
    lines = []

    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    lines.append(_kv("ОС", "Windows", C.Y))
    lines.append(_kv("Py", ver, C.Y))

    try:
        import importlib.metadata
        tbot_ver = importlib.metadata.version('pytelegrambotapi')
        lines.append(_kv("API", f"telebot v{tbot_ver}", C.Y))
    except Exception:
        lines.append(_kv("API", "telebot (?)", C.Y))

    from config import BOT_TOKEN, ADMIN_IDS
    if BOT_TOKEN and BOT_TOKEN != 'YOUR_TELEGRAM_BOT_TOKEN_HERE':
        lines.append(_kv("Токен", f"✓ {BOT_TOKEN[:6]}…", C.G))
    else:
        lines.append(_kv("Токен", "✗ нет!", C.R))

    if ADMIN_IDS:
        ids = ", ".join(str(i) for i in ADMIN_IDS)
        label = "Админ" if len(ADMIN_IDS) == 1 else "Админы"
        lines.append(_kv(label, f"✓ {ids}", C.G))
    else:
        lines.append(_kv("Админ", "—", C.Y))

    if os.path.exists(DB_PATH):
        size = os.path.getsize(DB_PATH)
        size_str = f"{size // 1024} КБ" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} МБ"
        lines.append(_kv("БД", f"✓ {DB_PATH} ({size_str})", C.G))
    else:
        lines.append(_kv("БД", "будет создана", C.Y))

    if os.path.exists('.env'):
        lines.append(_kv(".env", "✓", C.G))
    else:
        lines.append(_kv(".env", "✗ нет!", C.R))

    return lines


def _stats_lines(bookings):
    """Статистика базы данных."""
    services = get_services()
    portfolio = get_portfolio()
    reviews = get_reviews()
    avg, cnt = get_rating_stats()

    active = [b for b in bookings if b['status'] in ('pending', 'confirmed')]
    rating = f"{avg:.1f} ⭐ ({cnt})" if cnt else "—"

    return [
        _kv("Услуги", len(services), C.Y),
        _kv("Работы", len(portfolio), C.M),
        _kv("Отзывы", rating, C.Y),
        _kv("Записи", f"{len(bookings)} ({len(active)} акт.)", C.B),
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
        return [f"{C.DIM}  нет записей{C.RST}"]

    upcoming.sort(key=lambda x: x[0])
    lines = []
    for dt, b in upcoming[:4]:
        name = b['first_name'] or 'Клиент'
        uname = f" @{b['username']}" if b['username'] else ""
        if dt.date() == now.date():
            when = f"{C.R}{C.BOLD}сегодня {dt.strftime('%H:%M')}{C.RST}"
        elif (dt.date() - now.date()).days == 1:
            when = f"{C.Y}завтра {dt.strftime('%H:%M')}{C.RST}"
        else:
            when = dt.strftime('%d.%m %H:%M')
        service = (b['service'] or '')[:20]
        lines.append(f"  {C.BOLD}#{b['id']}{C.RST} {when} {name}{C.DIM}{uname}{C.RST}")
        lines.append(f"     {C.DIM}{service}{C.RST}")
    return lines


def _uptime():
    """Строка аптайма бота."""
    secs = int(time.monotonic() - _started_at)
    if secs < 60:
        return f"{secs}с"
    if secs < 3600:
        return f"{secs // 60}м {secs % 60}с"
    h, m = secs // 3600, (secs % 3600) // 60
    return f"{h}ч {m}м"


# ============ ПОЛНАЯ КОЛОНКА ============

def build_info_lines():
    """Собирает всю правую колонку."""
    lines = []
    bookings = get_all_bookings()

    # Шапка: БОТ @ handle + город
    lines.append(f"{C.BOLD}{C.CY}{BOT_NAME}{C.RST}"
                 f" {C.DIM}·{C.RST} "
                 f"{C.W}{BOT_MASTER}{C.RST}")
    lines.append(f"{C.DIM}@{BOT_HANDLE}{C.RST}")
    lines.append(_hr())
    lines.append(f"{C.DIM}📍 {BOT_CITY}{C.RST}")

    lines.append("")
    lines.append(_section("СИСТЕМА"))
    lines.extend(_system_lines())

    lines.append("")
    lines.append(_section("СТАТИСТИКА"))
    lines.extend(_stats_lines(bookings))

    lines.append("")
    lines.append(_section("ЗАПИСИ"))
    lines.extend(_upcoming_lines(bookings))

    lines.append("")
    lines.append(_hr())
    lines.append(f"{C.DIM}↻ {datetime.now().strftime('%H:%M:%S')}"
                 f"  ⏱ аптайм {_uptime()}{C.RST}")

    return lines


def _render():
    """Полный рендер: арт слева (центрирован) + инфо справа."""
    art = _colorize_art(_get_art())
    info = build_info_lines()
    block = _side_by_side(art, info)
    print('\n'.join(block))
    print(f"\n{C.DIM}Ctrl+C — остановка. Окно не закрывайте.{C.RST}")
    print()


# ============ UTF-8 БЕЗОПАСНОСТЬ ============

def _ensure_utf8_stdout():
    """Переключает stdout/stderr на UTF-8.
    Без этого эмодзи/ Unicode падают с UnicodeEncodeError на cp1251/cp866 консолях."""
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (ValueError, io.UnsupportedOperation):
        pass  # уже reconfigure'd или не поддерживается


# ============ ПУБЛИЧНЫЙ API ============

def show_overlay():
    """Полный оверлей запуска (неочищающий первый рендер)."""
    if os.name == 'nt':
        os.system('')  # активируем обработку ANSI-кодов
    _ensure_utf8_stdout()
    with _overlay_lock:
        _render()


def refresh_overlay():
    """Перерисовка оверлея после действий. Очищает экран, потокобезопасно."""
    with _overlay_lock:
        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')
        _render()


# Обратная совместимость
def show_banner():
    _render()


def show_stats():
    _render()


def check_system():
    return True
