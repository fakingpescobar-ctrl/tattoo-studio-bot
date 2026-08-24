"""
Нативная админ-панель Windows на tkinter.

Стилистика: чёрно-оранжево-фиолетовая, чистый минимализм.
Запускается отдельным daemon-потоком из main.py / max_main.py.
Читает данные напрямую из database.py (потокобезопасно — каждое соединение своё).

Запуск standalone:  python admin_panel.py
"""
import ctypes
import math
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from config import BOT_CITY, BOT_HANDLE, BOT_MASTER, BOT_NAME
from database import (delete_booking, delete_portfolio_work, get_all_bookings,
                      get_portfolio, get_rating_stats, get_reviews,
                      get_services, update_booking_status)

# Момент старта — для аптайма в шапке
_started_at = time.monotonic()

# Флаги активности ботов. Поднимаются из main.py / max_main.py при запуске.
# В standalone режиме (python admin_panel.py) определяются по наличию токенов в config.
tg_active = False
max_active = False

# Потокобезопасный канал уведомлений
_notify_queue: list = []
_notify_lock = threading.Lock()


def set_tg_active(value=True):
    """Вызывается из main.py при старте Telegram-бота."""
    global tg_active
    tg_active = value


def set_max_active(value=True):
    """Вызывается из max_main.py при старте MAX-бота."""
    global max_active
    max_active = value


def panel_notify(text):
    """Позволяет главному потоку (боту) отправить уведомление в панель."""
    with _notify_lock:
        _notify_queue.append(text)


# ============ ПАЛИТРА ============

class Palette:
    """Чёрно-оранжевая палитра + фиолетовый для цифр и логотипа."""
    BG          = '#000000'   # чистый чёрный
    BG_PANEL    = '#0d0d0d'   # фон панелей/шапки
    BG_CARD     = '#141414'   # фон карточек
    BG_INPUT    = '#0a0a0a'   # фон полей ввода
    BG_HOVER    = '#1e1e1e'   # hover-фон кнопок
    BG_ZEBRA    = '#101010'   # зебра-полосы таблиц
    BORDER      = '#1a1a1a'   # тёмно-серый для ttk рамок
    BORDER_DIM  = '#111111'   # ещё темнее
    DIVIDER     = '#5a5a5a'   # ANSI-разделители (заметный серый)
    DIVIDER_DIM = '#3a3a3a'   # ANSI-разделитель приглушённый

    ORANGE      = '#ff8c42'   # основной оранжевый
    ORANGE_DIM  = '#b85a1a'   # тёмный оранжевый
    ORANGE_HI   = '#ffa563'   # светлый (hover)
    PURPLE      = '#9d4edd'   # цифры статистики + логотип
    PURPLE_DIM  = '#5a189a'
    GRAY        = '#666666'   # подписи-плашки
    GRAY_DIM    = '#3a3a3a'
    TEXT        = '#d4d4d4'   # основной текст таблиц — мягко-белый
    TEXT_DIM    = '#777777'
    WHITE       = '#f0f0f0'
    RED         = '#ff4757'
    GREEN       = '#2ed573'
    BLUE        = '#54a0ff'
    YELLOW      = '#ffd60a'

    # Статусы записей (цветные accent-полосы + badge)
    STATUS_FG = {
        'pending':          '#ffd60a',   # жёлтый
        'confirmed':        '#2ed573',   # зелёный
        'completed':        '#54a0ff',   # голубой
        'cancelled':        '#ff4757',   # красный
        'client_cancelled': '#9d4edd',   # фиолетовый
    }
    STATUS_BG = {
        'pending':          '#1a1810',
        'confirmed':        '#0f1a14',
        'completed':        '#0f1419',
        'cancelled':        '#1a0f10',
        'client_cancelled': '#150f1a',
    }


STATUS_RU = {
    'pending': '⏳ Ожидает',
    'confirmed': '✅ Подтверждена',
    'completed': '✨ Завершена',
    'cancelled': '❌ Отменена',
    'client_cancelled': '🚫 Отказ клиента',
}


def _db_mtime():
    try:
        from config import DB_PATH
        return os.path.getmtime(DB_PATH)
    except OSError:
        return 0


# ============ ШРИФТЫ ============

def _font(size=10, weight='normal'):
    """Segoe UI с fallback на системный дефолт. Чистый современный GUI-шрифт."""
    return ('Segoe UI', size, weight)


def _mono(size=10, weight='normal'):
    """Cascadia Mono / Consolas для цифр и моноширинного контента."""
    return ('Cascadia Mono', size, weight)


def _mono_fallback(size=10, weight='normal'):
    """Consolas — гарантированно есть на Windows."""
    return ('Consolas', size, weight)


# ============ ANSI-РАЗДЕЛИТЕЛЬ ============

def _ansi_divider(parent, char='#', color=Palette.DIVIDER, bg=Palette.BG,
                  font_size=10):
    """Разделитель в ANSI/retro-стиле: строка из символов моноширинным шрифтом.

    Растягивается на всю ширину родителя через <Configure> event.
    char — символ заполнитель ('#', '=', '-', '█', '▓', '/' и т.д.).
    """
    label = tk.Label(parent, text='', fg=color, bg=bg,
                     font=_mono_fallback(font_size), anchor='w', pady=2)
    label.pack(fill='x')

    def _fill(event=None):
        w = event.width if event else parent.winfo_width()
        if w < 10:
            w = parent.winfo_reqwidth() or 800
        # Ширина символа при Consolas font_size=7 ≈ 5px
        char_w = max(3, font_size - 2)
        count = w // char_w + 2
        label.config(text=char * count)

    label.bind('<Configure>', _fill)
    parent.after(50, lambda: _fill())
    return label


# ============ DWM: ТЁМНЫЙ TITLEBAR + ACCENT-РАМКА ============

# DWM атрибуты
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36


def _colorref(hex_color):
    """Конвертирует #RRGGBB → Windows COLORREF (0x00BBGGRR)."""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def _apply_dark_chrome(window):
    """Включает тёмную тему для Windows titlebar + красит рамку/текст в палитру.

    Windows 10 1809+  → тёмный titlebar (DWMWA_USE_IMMERSIVE_DARK_MODE).
    Windows 11 (22000+) → кастомные цвета: caption (фон), text, border.
    На старых сборках тихо пропускает неподдерживаемые атрибуты.
    """
    try:
        user32 = ctypes.windll.user32

        # Окно должно быть полностью отрисовано ДО установки DWM атрибутов
        window.update_idletasks()
        window.update()

        hwnd = user32.GetParent(window.winfo_id())
        if not hwnd or not user32.IsWindow(hwnd):
            return

        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long

        # 1. Тёмный titlebar (пробуем attr 20 — новый, и 19 — старый для Win10 < 19041)
        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(
            hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark), ctypes.sizeof(dark))
        dwm.DwmSetWindowAttribute(
            hwnd, 19,  # fallback для ранних сборок Win10
            ctypes.byref(dark), ctypes.sizeof(dark))

        # 2. Фон titlebar = BG_PANEL
        caption = ctypes.c_uint32(_colorref('#0d0d0d'))
        dwm.DwmSetWindowAttribute(
            hwnd, _DWMWA_CAPTION_COLOR,
            ctypes.byref(caption), ctypes.sizeof(caption))

        # 3. Текст titlebar = оранжевый
        text = ctypes.c_uint32(_colorref('#ff8c42'))
        dwm.DwmSetWindowAttribute(
            hwnd, _DWMWA_TEXT_COLOR,
            ctypes.byref(text), ctypes.sizeof(text))

        # 4. Рамка окна = фиолетовая
        border = ctypes.c_uint32(_colorref('#9d4edd'))
        dwm.DwmSetWindowAttribute(
            hwnd, _DWMWA_BORDER_COLOR,
            ctypes.byref(border), ctypes.sizeof(border))

        # КРИТИЧНО: принудительный redraw рамки — без этого DWM атрибуты
        # установлены (S_OK) но визуально не применятся до следующего resize.
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
    except Exception:
        pass


# ============ TTK СТИЛЬ ============

def apply_retro_style(root):
    """Применяет тёмную минималистичную тему к ttk виджетам.

    clam тема по умолчанию рисует светло-серые 3D-бордеры (bordercolor,
    darkcolor, lightcolor). Все три принудительно затемняются чтобы рамки
    таблиц/вкладок/комбобоксов не были белыми на тёмном фоне.
    """
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except Exception:
        pass

    # Глобальный дефолт — все ttk виджеты наследуют
    style.configure('.', bordercolor=Palette.BORDER, darkcolor=Palette.BORDER,
                    lightcolor=Palette.BORDER, background=Palette.BG,
                    foreground=Palette.TEXT, troughcolor=Palette.BG)

    # --- Treeview (таблицы) ---
    style.configure('Treeview',
                    background=Palette.BG_CARD,
                    foreground=Palette.TEXT,
                    fieldbackground=Palette.BG_CARD,
                    borderwidth=0,
                    relief='flat',
                    bordercolor=Palette.BORDER,
                    rowheight=30)
    style.map('Treeview',
              background=[('selected', '#1a2a3a')],
              foreground=[('selected', Palette.WHITE)])
    # Заголовки таблиц
    style.configure('Treeview.Heading',
                    background=Palette.BG_PANEL,
                    foreground=Palette.ORANGE,
                    font=_font(9, 'bold'),
                    relief='flat',
                    borderwidth=0,
                    bordercolor=Palette.BORDER,
                    padding=(10, 8))
    style.map('Treeview.Heading',
              background=[('active', Palette.BG_HOVER)])

    # --- Scrollbar ---
    style.configure('Vertical.TScrollbar',
                    background=Palette.BG_PANEL,
                    troughcolor=Palette.BG,
                    arrowcolor=Palette.GRAY,
                    borderwidth=0,
                    gripcount=0,
                    bordercolor=Palette.BORDER,
                    darkcolor=Palette.BORDER,
                    lightcolor=Palette.BORDER)
    style.map('Vertical.TScrollbar',
              background=[('active', Palette.BG_HOVER)])

    # --- Notebook (вкладки) ---
    style.configure('TNotebook',
                    background=Palette.BG,
                    borderwidth=0,
                    tabmargins=(0, 0, 0, 0),
                    bordercolor=Palette.BORDER)
    style.configure('TNotebook.Tab',
                    background=Palette.BG,
                    foreground=Palette.TEXT_DIM,
                    padding=(24, 12),
                    font=_font(10, 'bold'),
                    borderwidth=0,
                    bordercolor=Palette.BORDER)
    style.map('TNotebook.Tab',
              background=[('selected', Palette.BG)],
              foreground=[('selected', Palette.ORANGE)],
              expand=[('selected', (0, 0, 0, 0))])

    # --- Combobox ---
    style.configure('TCombobox',
                    background=Palette.BG_INPUT,
                    foreground=Palette.TEXT,
                    fieldbackground=Palette.BG_INPUT,
                    arrowcolor=Palette.ORANGE,
                    borderwidth=1,
                    relief='solid',
                    bordercolor=Palette.BORDER,
                    darkcolor=Palette.BORDER,
                    lightcolor=Palette.BORDER,
                    padding=6)
    style.map('TCombobox',
              fieldbackground=[('readonly', Palette.BG_INPUT)],
              foreground=[('readonly', Palette.TEXT)],
              bordercolor=[('focus', Palette.ORANGE)])


# ============ КНОПКА (минимал с accent-полосой) ============

class AccentButton(tk.Frame):
    """Кнопка: тёмный базовый фон + цветная accent-полоса снизу.
    Минимал, современный вид. accent — hex-цвет полосы."""

    def __init__(self, parent, text, command,
                 accent=Palette.ORANGE, width=None, **kw):
        super().__init__(parent, bg=Palette.BG_CARD,
                         highlightthickness=0, bd=0)
        self._cmd = command
        self._accent = accent
        self._hover = False

        # Основная зона клика
        self._label = tk.Label(
            self, text=text, fg=Palette.TEXT, bg=Palette.BG_CARD,
            font=_font(9, 'bold'), padx=14, pady=8, cursor='hand2')
        self._label.pack(fill='both', expand=True)

        # Accent-полоса снизу (2px)
        self._bar = tk.Frame(self, bg=self._accent, height=2)
        self._bar.pack(fill='x', side='bottom')

        if width:
            self._label.config(width=width)

        for w in (self, self._label):
            w.bind('<Button-1>', self._click)
            w.bind('<Enter>', self._hover_in)
            w.bind('<Leave>', self._hover_out)

    def _click(self, _):
        if self._cmd:
            self._cmd()

    def _hover_in(self, _):
        self._hover = True
        self._label.config(bg=Palette.BG_HOVER)
        self.config(bg=Palette.BG_HOVER)
        self._bar.config(height=3)

    def _hover_out(self, _):
        self._hover = False
        self._label.config(bg=Palette.BG_CARD)
        self.config(bg=Palette.BG_CARD)
        self._bar.config(height=2)


# ============ КАРТОЧКА СТАТИСТИКИ ============

class StatCard(tk.Frame):
    """Карточка метрики: accent-полоса сверху, иконка+лейбл, крупное значение."""

    def __init__(self, parent, icon, label, accent=Palette.PURPLE):
        super().__init__(parent, bg=Palette.BG_CARD,
                         highlightthickness=0, bd=0)

        # Accent-полоса сверху (3px)
        tk.Frame(self, bg=accent, height=3).pack(fill='x')

        # Контент с padding
        body = tk.Frame(self, bg=Palette.BG_CARD)
        body.pack(fill='both', expand=True, padx=16, pady=(14, 16))

        # Лейбл: иконка + текст мелким
        header = tk.Frame(body, bg=Palette.BG_CARD)
        header.pack(fill='x')
        tk.Label(header, text=icon, bg=Palette.BG_CARD, fg=accent,
                 font=_font(11)).pack(side='left')
        tk.Label(header, text=label, bg=Palette.BG_CARD, fg=Palette.GRAY,
                 font=_font(8, 'bold')).pack(side='left', padx=(6, 0), pady=(2, 0))

        # Значение — крупно, фиолетовым
        self.value_var = tk.StringVar(value="—")
        tk.Label(body, textvariable=self.value_var,
                 bg=Palette.BG_CARD, fg=accent,
                 font=_mono_fallback(28, 'bold')).pack(anchor='w', pady=(6, 0))


# ============ ПАНЕЛЬ ============

class AdminPanel(tk.Tk):

    REFRESH_MS = 5000

    def __init__(self):
        super().__init__()
        self.title(f"{BOT_NAME} — ADMIN")
        self.geometry("1020x720+80+60")
        self.minsize(860, 600)
        self.configure(bg=Palette.BG)

        # Поверх всех окон при старте (чтобы не пряталось за консолью батника)
        self.attributes('-topmost', True)
        self.after(2000, lambda: self.attributes('-topmost', False))

        apply_retro_style(self)

        # Тёмный Windows chrome + accent-цвета (DWM API)
        _apply_dark_chrome(self)
        # Подстраховка: повторно через 300мс (в daemon-потоке окно может быть
        # не полностью готово при первом вызове)
        self.after(300, lambda: _apply_dark_chrome(self))

        # Переливающаяся accent-полоса под titlebar
        self._shimmer_phase = 0.0
        self._shimmer_strip = tk.Frame(self, bg=Palette.ORANGE, height=2)
        self._shimmer_strip.pack(fill='x')
        self.after(60, self._animate_shimmer)

        self._build_header()
        self._build_notebook()
        self._build_statusbar()

        self._db_mtime = _db_mtime()
        self._refresh_all()
        self.after(self.REFRESH_MS, self._refresh_loop)

    def _animate_shimmer(self):
        """Переливание полосы: оранжевый → фиолет → голубой → оранжевый."""
        t = self._shimmer_phase
        # 3-точечный градиент: orange(0) → purple(0.33) → cyan(0.66) → orange(1)
        if t < 0.333:
            k = t / 0.333
            r = int(0xff + (0x9d - 0xff) * k)
            g = int(0x8c + (0x4e - 0x8c) * k)
            b = int(0x42 + (0xdd - 0x42) * k)
        elif t < 0.666:
            k = (t - 0.333) / 0.333
            r = int(0x9d + (0x64 - 0x9d) * k)
            g = int(0x4e + (0xe0 - 0x4e) * k)
            b = int(0xdd + (0xff - 0xdd) * k)
        else:
            k = (t - 0.666) / 0.334
            r = int(0x64 + (0xff - 0x64) * k)
            g = int(0xe0 + (0x8c - 0xe0) * k)
            b = int(0xff + (0x42 - 0xff) * k)
        color = f'#{r:02x}{g:02x}{b:02x}'
        self._shimmer_strip.config(bg=color)
        self._shimmer_phase = (self._shimmer_phase + 0.012) % 1.0
        self.after(40, self._animate_shimmer)

    # ---------- ШАПКА ----------

    def _build_header(self):
        header = tk.Frame(self, bg=Palette.BG_PANEL)
        header.pack(fill='x')

        inner = tk.Frame(header, bg=Palette.BG_PANEL)
        inner.pack(fill='x', padx=24, pady=14)

        # --- ЛЕВО: логотип + мастер ---
        left = tk.Frame(inner, bg=Palette.BG_PANEL)
        left.pack(side='left')

        # Логотип-арт из logo.txt
        import os as _os
        _logo_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'logo.txt')
        try:
            with open(_logo_path, encoding='utf-8') as _f:
                logo_lines = [line.rstrip() for line in _f if line.strip()]
        except (OSError, UnicodeDecodeError):
            logo_lines = ['PRIZMA TATTOO STUDIO']

        logo_frame = tk.Frame(left, bg=Palette.BG_PANEL)
        logo_frame.pack(anchor='w')
        for line in logo_lines:
            tk.Label(logo_frame, text=line,
                     bg=Palette.BG_PANEL, fg=Palette.PURPLE,
                     font=_mono_fallback(8, 'bold')).pack(anchor='w')

        # Подпись мастера
        tk.Label(left, text=f"{BOT_MASTER}  ◇  @{BOT_HANDLE}",
                 bg=Palette.BG_PANEL, fg=Palette.GRAY,
                 font=_font(9)).pack(anchor='w', pady=(6, 0))

        # --- ПРАВО: индикаторы + аптайм ---
        right = tk.Frame(inner, bg=Palette.BG_PANEL)
        right.pack(side='right')

        # Индикаторы ботов
        bots = tk.Frame(right, bg=Palette.BG_PANEL)
        bots.pack(anchor='e')

        self.tg_dot_var = tk.StringVar(value="●")
        self.tg_text_var = tk.StringVar(value="Telegram")
        tg_frame = tk.Frame(bots, bg=Palette.BG_PANEL)
        tg_frame.pack(side='left', padx=(0, 16))
        self.tg_dot_label = tk.Label(tg_frame, textvariable=self.tg_dot_var,
                                     bg=Palette.BG_PANEL, fg=Palette.RED,
                                     font=_font(12))
        self.tg_dot_label.pack(side='left')
        tk.Label(tg_frame, textvariable=self.tg_text_var,
                 bg=Palette.BG_PANEL, fg=Palette.TEXT_DIM,
                 font=_font(9)).pack(side='left', padx=(4, 0))

        self.max_dot_var = tk.StringVar(value="●")
        self.max_text_var = tk.StringVar(value="MAX")
        max_frame = tk.Frame(bots, bg=Palette.BG_PANEL)
        max_frame.pack(side='left')
        self.max_dot_label = tk.Label(max_frame, textvariable=self.max_dot_var,
                                      bg=Palette.BG_PANEL, fg=Palette.RED,
                                      font=_font(12))
        self.max_dot_label.pack(side='left')
        tk.Label(max_frame, textvariable=self.max_text_var,
                 bg=Palette.BG_PANEL, fg=Palette.TEXT_DIM,
                 font=_font(9)).pack(side='left', padx=(4, 0))

        # Аптайм + город
        self.uptime_var = tk.StringVar(value="⏱ 0с")
        tk.Label(right, textvariable=self.uptime_var,
                 bg=Palette.BG_PANEL, fg=Palette.GRAY,
                 font=_font(9)).pack(anchor='e', pady=(8, 0))

        # ANSI-разделитель после шапки
        _ansi_divider(self, char='#', color=Palette.DIVIDER, bg=Palette.BG)

    # ---------- ВКЛАДКИ ----------

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill='both', expand=True, padx=12, pady=12)

        f_stats = ttk.Frame(self.nb)
        self.nb.add(f_stats, text="  СТАТИСТИКА  ")
        self._build_stats(f_stats)

        f_book = ttk.Frame(self.nb)
        self.nb.add(f_book, text="  ЗАПИСИ  ")
        self._build_bookings(f_book)

        f_port = ttk.Frame(self.nb)
        self.nb.add(f_port, text="  ПОРТФОЛИО  ")
        self._build_portfolio(f_port)

    # ---------- СТАТИСТИКА ----------

    def _build_stats(self, parent):
        # Сетка карточек
        grid = tk.Frame(parent, bg=Palette.BG)
        grid.pack(fill='x', padx=20, pady=20)

        self.stat_vars = {}
        cards = [
            ('services',        '💰', 'УСЛУГИ',    Palette.ORANGE),
            ('portfolio',       '🎨', 'РАБОТЫ',    Palette.ORANGE),
            ('reviews',         '⭐', 'ОТЗЫВЫ',    Palette.YELLOW),
            ('rating',          '🏆', 'РЕЙТИНГ',   Palette.YELLOW),
            ('bookings_total',  '📅', 'ВСЕГО',     Palette.PURPLE),
            ('bookings_active', '🔔', 'АКТИВНО',   Palette.PURPLE),
        ]
        for i, (key, icon, label, accent) in enumerate(cards):
            row, col = i // 3, i % 3
            card = StatCard(grid, icon, label, accent=accent)
            card.grid(row=row, column=col, sticky='nsew', padx=8, pady=8)
            grid.grid_columnconfigure(col, weight=1)
            self.stat_vars[key] = card.value_var

        # Ближайшие записи
        upc_frame = tk.Frame(parent, bg=Palette.BG)
        upc_frame.pack(fill='both', expand=True, padx=20, pady=(0, 20))

        tk.Label(upc_frame, text="БЛИЖАЙШИЕ ЗАПИСИ",
                 bg=Palette.BG, fg=Palette.GRAY,
                 font=_font(9, 'bold')).pack(anchor='w', pady=(0, 8))

        cols = ('id', 'client', 'service', 'date', 'status')
        self.reviews_tree = ttk.Treeview(upc_frame, columns=cols,
                                          show='headings', height=5)
        self.reviews_tree.heading('id', text='#')
        self.reviews_tree.heading('client', text='КЛИЕНТ')
        self.reviews_tree.heading('service', text='УСЛУГА')
        self.reviews_tree.heading('date', text='ДАТА / ВРЕМЯ')
        self.reviews_tree.heading('status', text='СТАТУС')
        self.reviews_tree.column('id', width=40, anchor='center')
        self.reviews_tree.column('client', width=160)
        self.reviews_tree.column('service', width=220)
        self.reviews_tree.column('date', width=140, anchor='center')
        self.reviews_tree.column('status', width=140)
        sb = ttk.Scrollbar(upc_frame, orient='vertical',
                            command=self.reviews_tree.yview)
        self.reviews_tree.configure(yscrollcommand=sb.set)
        self.reviews_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        # Теги статусов
        for status, bg in Palette.STATUS_BG.items():
            self.reviews_tree.tag_configure(status,
                                            background=bg,
                                            foreground=Palette.STATUS_FG.get(status, Palette.TEXT))

    # ---------- ЗАПИСИ ----------

    def _build_bookings(self, parent):
        # Панель фильтров
        filt = tk.Frame(parent, bg=Palette.BG)
        filt.pack(fill='x', padx=20, pady=(16, 8))

        tk.Label(filt, text="СТАТУС", bg=Palette.BG, fg=Palette.GRAY,
                 font=_font(8, 'bold')).pack(side='left', padx=(0, 8))

        self.status_var = tk.StringVar(value='all')
        cb_values = ['all'] + list(STATUS_RU.keys())
        cb = ttk.Combobox(filt, textvariable=self.status_var,
                          values=cb_values, state='readonly', width=18)
        cb.set('all')
        cb.pack(side='left', padx=(0, 20))
        cb.bind('<<ComboboxSelected>>', lambda e: self._load_bookings())

        tk.Label(filt, text="ПОИСК", bg=Palette.BG, fg=Palette.GRAY,
                 font=_font(8, 'bold')).pack(side='left', padx=(0, 8))
        self.search_var = tk.StringVar()
        entry = tk.Entry(filt, textvariable=self.search_var, width=24,
                         bg=Palette.BG_INPUT, fg=Palette.TEXT,
                         insertbackground=Palette.ORANGE,
                         font=_font(9), relief='solid',
                         bd=0, highlightthickness=1,
                         highlightcolor=Palette.BORDER,
                         highlightbackground=Palette.BORDER)
        entry.pack(side='left', ipady=4)
        entry.bind('<KeyRelease>', lambda e: self._load_bookings())

        AccentButton(filt, "⟳ ОБНОВИТЬ", self._load_bookings,
                     accent=Palette.ORANGE).pack(side='right')

        # Таблица
        cols = ('id', 'client', 'service', 'date', 'status', 'desc')
        self.tree = ttk.Treeview(parent, columns=cols, show='headings')
        self.tree.heading('id', text='#')
        self.tree.heading('client', text='КЛИЕНТ')
        self.tree.heading('service', text='УСЛУГА')
        self.tree.heading('date', text='ДАТА / ВРЕМЯ')
        self.tree.heading('status', text='СТАТУС')
        self.tree.heading('desc', text='ОПИСАНИЕ')
        self.tree.column('id', width=45, anchor='center')
        self.tree.column('client', width=160)
        self.tree.column('service', width=150)
        self.tree.column('date', width=130, anchor='center')
        self.tree.column('status', width=150)
        self.tree.column('desc', width=260)

        sb = ttk.Scrollbar(parent, orient='vertical',
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(fill='both', expand=True, padx=20, pady=4)
        sb.pack(side='right', fill='y', padx=(0, 20))

        # Цветные теги статусов (accent-фон + accent-текст)
        for status, bg in Palette.STATUS_BG.items():
            self.tree.tag_configure(status,
                                    background=bg,
                                    foreground=Palette.STATUS_FG.get(status, Palette.TEXT))

        # Кнопки действий — минимал с accent-полосами
        actions = tk.Frame(parent, bg=Palette.BG)
        actions.pack(fill='x', padx=20, pady=(8, 20))
        AccentButton(actions, "✓ ПОДТВЕРДИТЬ",
                     lambda: self._set_status('confirmed'),
                     accent=Palette.GREEN).pack(side='left', padx=4)
        AccentButton(actions, "✨ ЗАВЕРШИТЬ",
                     lambda: self._set_status('completed'),
                     accent=Palette.BLUE).pack(side='left', padx=4)
        AccentButton(actions, "✗ ОТМЕНИТЬ",
                     lambda: self._set_status('cancelled'),
                     accent=Palette.RED).pack(side='left', padx=4)
        AccentButton(actions, "🗑 УДАЛИТЬ",
                     self._delete_client_cancelled,
                     accent=Palette.PURPLE).pack(side='left', padx=4)

    # ---------- ПОРТФОЛИО ----------

    def _build_portfolio(self, parent):
        top = tk.Frame(parent, bg=Palette.BG)
        top.pack(fill='x', padx=20, pady=(16, 8))

        AccentButton(top, "⟳ ОБНОВИТЬ", None,
                     accent=Palette.ORANGE).pack(side='right')

        cols = ('id', 'title', 'style', 'desc')
        self.port_tree = ttk.Treeview(parent, columns=cols, show='headings')
        self.port_tree.heading('id', text='#')
        self.port_tree.heading('title', text='НАЗВАНИЕ')
        self.port_tree.heading('style', text='СТИЛЬ')
        self.port_tree.heading('desc', text='ОПИСАНИЕ')
        self.port_tree.column('id', width=45, anchor='center')
        self.port_tree.column('title', width=200)
        self.port_tree.column('style', width=140)
        self.port_tree.column('desc', width=350)

        sb = ttk.Scrollbar(parent, orient='vertical',
                            command=self.port_tree.yview)
        self.port_tree.configure(yscrollcommand=sb.set)
        self.port_tree.pack(fill='both', expand=True, padx=20, pady=4)
        sb.pack(side='right', fill='y', padx=(0, 20))

        # Зебра
        self.port_tree.tag_configure('odd', background=Palette.BG_ZEBRA)

        actions = tk.Frame(parent, bg=Palette.BG)
        actions.pack(fill='x', padx=20, pady=(8, 20))
        AccentButton(actions, "🗑 УДАЛИТЬ РАБОТУ",
                     self._delete_work,
                     accent=Palette.RED).pack(side='left', padx=4)

    # ---------- СТАТУСБАР ----------

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=Palette.BG_PANEL)
        bar.pack(fill='x', side='bottom')

        # ANSI-разделитель сверху статусбара
        _ansi_divider(bar, char='#', color=Palette.DIVIDER, bg=Palette.BG_PANEL)

        inner = tk.Frame(bar, bg=Palette.BG_PANEL)
        inner.pack(fill='x', padx=20, pady=8)

        self.bar_var = tk.StringVar(value="● READY")
        tk.Label(inner, textvariable=self.bar_var,
                 bg=Palette.BG_PANEL, fg=Palette.ORANGE,
                 font=_font(9)).pack(side='left')

        self.refresh_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self.refresh_var,
                 bg=Palette.BG_PANEL, fg=Palette.GRAY,
                 font=_font(9)).pack(side='right')

    # ---------- ОБНОВЛЕНИЕ ----------

    def _refresh_loop(self):
        try:
            self._refresh_all()
        except Exception as e:
            self.bar_var.set(f"⚠ ERR: {e}")
        self.after(self.REFRESH_MS, self._refresh_loop)

    def _refresh_all(self):
        now_str = datetime.now().strftime('%H:%M:%S')
        self.refresh_var.set(f"↻ {now_str}")

        # Аптайм
        secs = int(time.monotonic() - _started_at)
        if secs < 60:
            up = f"{secs}с"
        elif secs < 3600:
            up = f"{secs // 60}м {secs % 60}с"
        else:
            h, m = secs // 3600, (secs % 3600) // 60
            up = f"{h}ч {m}м"
        self.uptime_var.set(f"⏱ {up}  ·  📍 {BOT_CITY}")

        # Индикаторы ботов
        tg_ok = tg_active
        max_ok = max_active
        if not tg_ok and not max_ok:
            try:
                from config import BOT_TOKEN, MAX_TOKEN
                tg_ok = bool(BOT_TOKEN and BOT_TOKEN != 'YOUR_TELEGRAM_BOT_TOKEN_HERE')
                max_ok = bool(MAX_TOKEN)
            except Exception:
                pass

        self.tg_dot_label.config(fg=Palette.GREEN if tg_ok else Palette.RED)
        self.max_dot_label.config(fg=Palette.GREEN if max_ok else Palette.RED)

        self._load_stats()
        self._load_bookings()
        self._load_portfolio()
        self._load_reviews()

        with _notify_lock:
            notes = list(_notify_queue)
            _notify_queue.clear()
        if notes:
            self.bar_var.set("● " + " | ".join(notes)[:80])

    def _load_stats(self):
        services = get_services()
        portfolio = get_portfolio()
        reviews = get_reviews()
        avg, cnt = get_rating_stats()
        bookings = get_all_bookings()
        active = [b for b in bookings
                  if b['status'] in ('pending', 'confirmed')]

        self.stat_vars['services'].set(str(len(services)))
        self.stat_vars['portfolio'].set(str(len(portfolio)))
        self.stat_vars['reviews'].set(str(cnt))
        self.stat_vars['rating'].set(f"{avg:.1f}" if cnt else "—")
        self.stat_vars['bookings_total'].set(str(len(bookings)))
        self.stat_vars['bookings_active'].set(str(len(active)))

    def _load_bookings(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        bookings = get_all_bookings()
        status_filter = self.status_var.get()
        search = self.search_var.get().strip().lower()

        for b in bookings:
            status = b['status']
            if status_filter != 'all' and status != status_filter:
                continue
            name = b['first_name'] or 'Клиент'
            if b['username']:
                name += f" @{b['username']}"
            desc = (b['description'] or '')[:60]
            row_text = f"{b['id']} {name} {b['service']} {b['date_time']} {desc}"
            if search and search not in row_text.lower():
                continue
            self.tree.insert('', 'end',
                              values=(b['id'], name, b['service'],
                                      b['date_time'], STATUS_RU.get(status, status),
                                      desc),
                              tags=(status,))

    def _load_portfolio(self):
        if not hasattr(self, 'port_tree'):
            return
        for item in self.port_tree.get_children():
            self.port_tree.delete(item)
        works = get_portfolio()
        for i, w in enumerate(works):
            tags = ('odd',) if i % 2 else ()
            self.port_tree.insert('', 'end',
                                   values=(w['id'], w['title'], w['style'] or '',
                                           (w['description'] or '')[:60]),
                                   tags=tags)

    def _load_reviews(self):
        """Загружает ближайшие активные записи (pending/confirmed) по дате."""
        if not hasattr(self, 'reviews_tree'):
            return
        for item in self.reviews_tree.get_children():
            self.reviews_tree.delete(item)

        bookings = get_all_bookings()
        # Только активные записи
        active = [b for b in bookings
                  if b['status'] in ('pending', 'confirmed')]

        # Сортировка по дате
        def parse_date(b):
            try:
                return datetime.strptime(
                    (b['date_time'] or '').strip(), '%d.%m.%Y %H:%M')
            except (ValueError, TypeError):
                return datetime.max

        active.sort(key=parse_date)

        for b in active[:8]:
            name = b['first_name'] or 'Клиент'
            if b['username']:
                name += f" @{b['username']}"
            status = b['status']
            self.reviews_tree.insert(
                '', 'end',
                values=(b['id'], name, b['service'] or '',
                        b['date_time'], STATUS_RU.get(status, status)),
                tags=(status,))

    # ---------- ДЕЙСТВИЯ ----------

    def _selected_booking_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("ВЫБОР", "Выберите запись в таблице.")
            return None
        vals = self.tree.item(sel[0])['values']
        return int(vals[0])

    def _set_status(self, new_status):
        bid = self._selected_booking_id()
        if bid is None:
            return
        if messagebox.askyesno("ПОДТВЕРЖДЕНИЕ",
                                f"Сменить статус записи #{bid} на «{STATUS_RU.get(new_status, new_status)}»?"):
            update_booking_status(bid, new_status)
            self._load_bookings()
            self._load_stats()
            self.bar_var.set(f"● #{bid} → {STATUS_RU.get(new_status)}")

    def _delete_client_cancelled(self):
        bid = self._selected_booking_id()
        if bid is None:
            return
        if messagebox.askyesno("УДАЛЕНИЕ",
                                f"Удалить запись #{bid} из базы?"):
            delete_booking(bid)
            self._load_bookings()
            self._load_stats()
            self.bar_var.set(f"● #{bid} DELETED")

    def _delete_work(self):
        sel = self.port_tree.selection()
        if not sel:
            messagebox.showinfo("ВЫБОР", "Выберите работу в таблице.")
            return
        vals = self.port_tree.item(sel[0])['values']
        wid = int(vals[0])
        title = vals[1]
        if messagebox.askyesno("УДАЛЕНИЕ", f"Удалить работу «{title}»?"):
            delete_portfolio_work(wid)
            self._load_portfolio()
            self._load_stats()
            self.bar_var.set(f"● «{title}» DELETED")


# ============ ТОЧКА ВХОДА ============

def run_admin_panel():
    """Запускает админ-панель. Блокирует вызывающий поток до закрытия окна."""
    try:
        app = AdminPanel()
        app.mainloop()
    except Exception as e:
        print(f"[AdminPanel] crash: {e}", file=sys.stderr)


if __name__ == '__main__':
    print(f"Запуск {BOT_NAME} админ-панели (standalone)...")
    run_admin_panel()
