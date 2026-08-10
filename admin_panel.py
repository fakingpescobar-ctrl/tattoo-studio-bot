"""
Нативная админ-панель Windows на tkinter.

Стилистика: ретро чёрно-жёлто-фиолетовая.
Запускается отдельным daemon-потоком из main.py / max_main.py.
Читает данные напрямую из database.py (потокобезопасно — каждое соединение своё).

Запуск standalone:  python admin_panel.py
"""
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


# ============ РЕТРО ПАЛИТРА ============

class Palette:
    """Чёрно-оранжево-фиолетовая ретро-палитра."""
    BG         = '#000000'  # чистый чёрный
    BG_PANEL   = '#0a0a0a'  # фон панелей (почти чёрный)
    BG_CARD    = '#121212'  # фон карточек
    BG_INPUT   = '#080808'  # фон полей ввода
    ORANGE     = '#ff8c42'  # основной оранжевый (все цифры/буквы статистики)
    YELLOW     = '#ffd60a'  # акцент (кнопки, статусы)
    PURPLE     = '#9d4edd'  # основной фиолетовый
    PURPLE_DIM = '#5a189a'  # тёмный фиолетовый
    TEXT       = '#e0e0e0'  # основной текст
    TEXT_DIM   = '#707080'  # приглушённый текст
    RED        = '#ff4757'  # бот НЕ активен
    GREEN      = '#2ed573'  # бот активен
    # Статусы записей (цветные badge-фоны)
    STATUS_BG = {
        'pending':          '#2a2218',  # тёмно-оранжевый
        'confirmed':        '#1a2a1f',  # тёмно-зелёный
        'completed':        '#1a242a',  # тёмно-голубой
        'cancelled':        '#2a1818',  # тёмно-красный
        'client_cancelled': '#1f182a',  # тёмно-фиолетовый
    }
    STATUS_FG = {
        'pending':          '#ffd60a',  # жёлтый
        'confirmed':        '#2ed573',
        'completed':        '#54a0ff',
        'cancelled':        '#ff4757',
        'client_cancelled': '#9d4edd',
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


# ============ РЕТРО СТИЛЬ ДЛЯ ttk ============

def apply_retro_style(root):
    """Применяет тёмную тему к ttk виджетам (Treeview, Scrollbar, Notebook)."""
    style = ttk.Style(root)
    try:
        style.theme_use('clam')  # clam — самый кастомизируемый
    except Exception:
        pass

    # Treeview — таблицы (текст оранжевый, фон чёрный)
    style.configure('Treeview',
                    background=Palette.BG_CARD,
                    foreground=Palette.ORANGE,
                    fieldbackground=Palette.BG_CARD,
                    borderwidth=1,
                    relief='solid',
                    rowheight=26)
    # Заголовки таблиц — фиолетовые
    style.configure('Treeview.Heading',
                    background=Palette.PURPLE_DIM,
                    foreground=Palette.PURPLE,
                    font=('Consolas', 10, 'bold'),
                    relief='flat',
                    padding=6)
    style.map('Treeview.Heading',
              background=[('active', Palette.PURPLE)])
    style.map('Treeview',
              background=[('selected', Palette.PURPLE_DIM)],
              foreground=[('selected', Palette.ORANGE)])
    style.configure('Vertical.TScrollbar',
                    background=Palette.PURPLE_DIM,
                    troughcolor=Palette.BG_PANEL,
                    arrowcolor=Palette.PURPLE,
                    borderwidth=0)

    # Notebook (вкладки) — фиолетовый текст
    style.configure('TNotebook',
                    background=Palette.BG,
                    borderwidth=0)
    style.configure('TNotebook.Tab',
                    background=Palette.BG_PANEL,
                    foreground=Palette.PURPLE,
                    padding=(16, 8),
                    font=('Consolas', 10, 'bold'))
    style.map('TNotebook.Tab',
              background=[('selected', Palette.PURPLE_DIM)],
              foreground=[('selected', Palette.PURPLE)])

    # LabelFrame — фиолетовые лейблы
    style.configure('TLabelframe',
                    background=Palette.BG_PANEL,
                    foreground=Palette.PURPLE,
                    borderwidth=1,
                    relief='solid')
    style.configure('TLabelframe.Label',
                    background=Palette.BG_PANEL,
                    foreground=Palette.PURPLE,
                    font=('Consolas', 9, 'bold'))

    # Combobox
    style.configure('TCombobox',
                    background=Palette.BG_INPUT,
                    foreground=Palette.ORANGE,
                    fieldbackground=Palette.BG_INPUT,
                    arrowcolor=Palette.PURPLE,
                    borderwidth=1)
    style.map('TCombobox',
              fieldbackground=[('readonly', Palette.BG_INPUT)],
              foreground=[('readonly', Palette.ORANGE)])


# ============ РЕТРО КНОПКА (tk) ============

class RetroButton(tk.Frame):
    """Кастомная кнопка с жёлто-фиолетовым ретро-стилем."""

    def __init__(self, parent, text, command, bg=Palette.PURPLE_DIM,
                 fg=Palette.YELLOW, hover_bg=Palette.PURPLE, width=None, **kw):
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0)
        self._cmd = command
        self._bg = bg
        self._hover_bg = hover_bg
        self.label = tk.Label(
            self, text=text, fg=fg, bg=bg,
            font=('Consolas', 9, 'bold'),
            padx=12, pady=6, cursor='hand2',
            highlightthickness=1,
            highlightbackground=Palette.PURPLE_DIM,
            highlightcolor=Palette.PURPLE,
        )
        self.label.pack(fill='both', expand=True)
        self.label.bind('<Button-1>', self._click)
        self.label.bind('<Enter>', self._hover)
        self.label.bind('<Leave>', self._unhover)

    def _click(self, _):
        if self._cmd:
            self._cmd()

    def _hover(self, _):
        self.label.config(bg=self._hover_bg)
        self.config(bg=self._hover_bg)

    def _unhover(self, _):
        self.label.config(bg=self._bg)
        self.config(bg=self._bg)


# ============ РЕТРО КАРТОЧКА ============

class RetroCard(tk.Frame):
    """Карточка статистики: оранжевые цифры на чёрном фоне."""

    def __init__(self, parent, label, accent=Palette.ORANGE):
        super().__init__(parent, bg=Palette.BG_CARD,
                         highlightthickness=2,
                         highlightbackground=Palette.PURPLE,
                         highlightcolor=Palette.PURPLE,
                         bd=0)
        tk.Label(self, text=label, bg=Palette.BG_CARD,
                 fg=Palette.PURPLE,
                 font=('Consolas', 9, 'bold')).pack(pady=(8, 0))
        self.value_var = tk.StringVar(value="—")
        tk.Label(self, textvariable=self.value_var,
                 bg=Palette.BG_CARD, fg=Palette.ORANGE,
                 font=('Consolas', 24, 'bold')).pack(pady=(0, 8))


# ============ ПАНЕЛЬ ============

class AdminPanel(tk.Tk):

    REFRESH_MS = 5000

    def __init__(self):
        super().__init__()
        self.title(f"{BOT_NAME} — ADMIN")
        self.geometry("980x680")
        self.minsize(820, 560)
        self.configure(bg=Palette.BG)

        apply_retro_style(self)

        self._build_header()
        self._build_notebook()
        self._build_statusbar()

        self._db_mtime = _db_mtime()
        self._refresh_all()
        self.after(self.REFRESH_MS, self._refresh_loop)

    # ---------- ШАПКА ----------

    def _build_header(self):
        header = tk.Frame(self, bg=Palette.BG_PANEL, height=72)
        header.pack(fill='x')
        header.pack_propagate(False)

        # Левая часть: название (фиолетовым)
        left = tk.Frame(header, bg=Palette.BG_PANEL)
        left.pack(side='left', padx=14)

        tk.Label(left, text="▰ ПРИЗМА ТАТУ СТУДИО ▰",
                 bg=Palette.BG_PANEL, fg=Palette.PURPLE,
                 font=('Consolas', 16, 'bold')).pack(anchor='w')
        tk.Label(left, text="МАКСИМ АНДРЕЕВИЧ  ◇  @tatoo_asbest_best_bot",
                 bg=Palette.BG_PANEL, fg=Palette.PURPLE,
                 font=('Consolas', 9)).pack(anchor='w', pady=(0, 0))

        # Правая часть: индикаторы ботов + аптайм
        right = tk.Frame(header, bg=Palette.BG_PANEL)
        right.pack(side='right', padx=14)

        # Индикаторы статуса ботов
        bots_frame = tk.Frame(right, bg=Palette.BG_PANEL)
        bots_frame.pack(anchor='e')

        self.tg_dot_var = tk.StringVar(value="●")
        self.tg_text_var = tk.StringVar(value="Telegram")
        tg_frame = tk.Frame(bots_frame, bg=Palette.BG_PANEL)
        tg_frame.pack(side='left', padx=(0, 12))
        self.tg_dot_label = tk.Label(tg_frame, textvariable=self.tg_dot_var,
                 bg=Palette.BG_PANEL, fg=Palette.RED,
                 font=('Consolas', 12, 'bold'))
        self.tg_dot_label.pack(side='left')
        tk.Label(tg_frame, textvariable=self.tg_text_var,
                 bg=Palette.BG_PANEL, fg=Palette.TEXT_DIM,
                 font=('Consolas', 9)).pack(side='left', padx=3)

        self.max_dot_var = tk.StringVar(value="●")
        self.max_text_var = tk.StringVar(value="MAX")
        max_frame = tk.Frame(bots_frame, bg=Palette.BG_PANEL)
        max_frame.pack(side='left')
        self.max_dot_label = tk.Label(max_frame, textvariable=self.max_dot_var,
                 bg=Palette.BG_PANEL, fg=Palette.RED,
                 font=('Consolas', 12, 'bold'))
        self.max_dot_label.pack(side='left')
        tk.Label(max_frame, textvariable=self.max_text_var,
                 bg=Palette.BG_PANEL, fg=Palette.TEXT_DIM,
                 font=('Consolas', 9)).pack(side='left', padx=3)

        self.uptime_var = tk.StringVar(value="⏱ 0с")
        tk.Label(right, textvariable=self.uptime_var,
                 bg=Palette.BG_PANEL, fg=Palette.ORANGE,
                 font=('Consolas', 9)).pack(anchor='e', pady=(4, 0))

        # Тонкая фиолетово-оранжевая полоса-разделитель
        sep = tk.Frame(self, bg=Palette.PURPLE, height=2)
        sep.pack(fill='x')
        sep2 = tk.Frame(self, bg=Palette.ORANGE, height=1)
        sep2.pack(fill='x')

    # ---------- ВКЛАДКИ ----------

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill='both', expand=True, padx=8, pady=8)

        f_stats = ttk.Frame(self.nb)
        self.nb.add(f_stats, text=" ▓ СТАТИСТИКА ")
        self._build_stats(f_stats)

        f_book = ttk.Frame(self.nb)
        self.nb.add(f_book, text=" ▓ ЗАПИСИ ")
        self._build_bookings(f_book)

        f_port = ttk.Frame(self.nb)
        self.nb.add(f_port, text=" ▓ ПОРТФОЛИО ")
        self._build_portfolio(f_port)

    # ---------- СТАТИСТИКА ----------

    def _build_stats(self, parent):
        # Сетка карточек
        grid = tk.Frame(parent, bg=Palette.BG)
        grid.pack(fill='x', padx=12, pady=12)

        self.stat_vars = {}
        cards = [
            ('services', '💰 УСЛУГИ', Palette.YELLOW),
            ('portfolio', '🎨 РАБОТЫ', Palette.PURPLE),
            ('reviews', '⭐ ОТЗЫВЫ', Palette.YELLOW),
            ('rating', '🏆 РЕЙТИНГ', Palette.PURPLE),
            ('bookings_total', '📅 ВСЕГО', Palette.YELLOW),
            ('bookings_active', '🔔 АКТИВНО', Palette.PURPLE),
        ]
        for i, (key, label, accent) in enumerate(cards):
            row, col = i // 3, i % 3
            card = RetroCard(grid, label, accent=accent)
            card.grid(row=row, column=col, sticky='nsew', padx=5, pady=5)
            grid.grid_columnconfigure(col, weight=1)
            self.stat_vars[key] = card.value_var

        # Последние отзывы
        rev_frame = tk.Frame(parent, bg=Palette.BG)
        rev_frame.pack(fill='both', expand=True, padx=12, pady=(0, 12))

        tk.Label(rev_frame, text="▌ ПОСЛЕДНИЕ ОТЗЫВЫ",
                 bg=Palette.BG, fg=Palette.PURPLE,
                 font=('Consolas', 10, 'bold')).pack(anchor='w', pady=(0, 4))

        tree_frame = tk.Frame(rev_frame, bg=Palette.BG_CARD,
                              highlightthickness=2,
                              highlightbackground=Palette.PURPLE_DIM)
        tree_frame.pack(fill='both', expand=True)

        cols = ('user', 'rating', 'text', 'date')
        self.reviews_tree = ttk.Treeview(tree_frame, columns=cols,
                                          show='headings', height=5)
        self.reviews_tree.heading('user', text='КЛИЕНТ')
        self.reviews_tree.heading('rating', text='ОЦЕНКА')
        self.reviews_tree.heading('text', text='ТЕКСТ')
        self.reviews_tree.heading('date', text='ДАТА')
        self.reviews_tree.column('user', width=120)
        self.reviews_tree.column('rating', width=80, anchor='center')
        self.reviews_tree.column('text', width=400)
        self.reviews_tree.column('date', width=120)
        sb = ttk.Scrollbar(tree_frame, orient='vertical',
                            command=self.reviews_tree.yview)
        self.reviews_tree.configure(yscrollcommand=sb.set)
        self.reviews_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

    # ---------- ЗАПИСИ ----------

    def _build_bookings(self, parent):
        # Фильтр
        filt = tk.Frame(parent, bg=Palette.BG)
        filt.pack(fill='x', padx=12, pady=(10, 6))

        tk.Label(filt, text="ФИЛЬТР:", bg=Palette.BG, fg=Palette.PURPLE,
                 font=('Consolas', 9, 'bold')).pack(side='left')

        self.status_var = tk.StringVar(value='all')
        cb_values = ['all'] + list(STATUS_RU.keys())
        cb = ttk.Combobox(filt, textvariable=self.status_var,
                          values=cb_values, state='readonly', width=18)
        cb.pack(side='left', padx=8)
        cb.bind('<<ComboboxSelected>>', lambda e: self._load_bookings())

        tk.Label(filt, text="  ПОИСК:", bg=Palette.BG, fg=Palette.PURPLE,
                 font=('Consolas', 9, 'bold')).pack(side='left')
        self.search_var = tk.StringVar()
        entry = tk.Entry(filt, textvariable=self.search_var, width=22,
                         bg=Palette.BG_INPUT, fg=Palette.ORANGE,
                         insertbackground=Palette.ORANGE,
                         font=('Consolas', 9), relief='solid',
                         bd=1, highlightthickness=1,
                         highlightbackground=Palette.PURPLE_DIM)
        entry.pack(side='left', padx=8, ipady=3)
        entry.bind('<KeyRelease>', lambda e: self._load_bookings())

        RetroButton(filt, "⟳ ОБНОВИТЬ", self._load_bookings,
                    bg=Palette.PURPLE_DIM, hover_bg=Palette.PURPLE).pack(side='right')

        # Таблица
        tree_frame = tk.Frame(parent, bg=Palette.BG_CARD,
                              highlightthickness=2,
                              highlightbackground=Palette.PURPLE_DIM)
        tree_frame.pack(fill='both', expand=True, padx=12, pady=4)

        cols = ('id', 'client', 'service', 'date', 'status', 'desc')
        self.tree = ttk.Treeview(tree_frame, columns=cols, show='headings')
        self.tree.heading('id', text='#')
        self.tree.heading('client', text='КЛИЕНТ')
        self.tree.heading('service', text='УСЛУГА')
        self.tree.heading('date', text='ДАТА / ВРЕМЯ')
        self.tree.heading('status', text='СТАТУС')
        self.tree.heading('desc', text='ОПИСАНИЕ')
        self.tree.column('id', width=40, anchor='center')
        self.tree.column('client', width=150)
        self.tree.column('service', width=150)
        self.tree.column('date', width=120, anchor='center')
        self.tree.column('status', width=140)
        self.tree.column('desc', width=240)

        sb = ttk.Scrollbar(tree_frame, orient='vertical',
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        # Цветные теги для строк
        for status, bg in Palette.STATUS_BG.items():
            self.tree.tag_configure(status, background=bg)

        # Кнопки действий
        actions = tk.Frame(parent, bg=Palette.BG)
        actions.pack(fill='x', padx=12, pady=(6, 12))
        RetroButton(actions, "✓ ПОДТВЕРДИТЬ",
                    lambda: self._set_status('confirmed'),
                    bg='#1f3d2a', hover_bg=Palette.GREEN).pack(side='left', padx=3)
        RetroButton(actions, "✨ ЗАВЕРШИТЬ",
                    lambda: self._set_status('completed'),
                    bg='#1f2d3d', hover_bg='#54a0ff').pack(side='left', padx=3)
        RetroButton(actions, "✗ ОТМЕНИТЬ",
                    lambda: self._set_status('cancelled'),
                    bg='#3d1f1f', hover_bg=Palette.RED).pack(side='left', padx=3)
        RetroButton(actions, "🗑 УДАЛИТЬ",
                    self._delete_client_cancelled,
                    bg='#2d1f3d', hover_bg=Palette.PURPLE).pack(side='left', padx=3)

    # ---------- ПОРТФОЛИО ----------

    def _build_portfolio(self, parent):
        top = tk.Frame(parent, bg=Palette.BG)
        top.pack(fill='x', padx=12, pady=(10, 6))
        tk.Label(top, text="▌ РАБОТЫ МАСТЕРА",
                 bg=Palette.BG, fg=Palette.PURPLE,
                 font=('Consolas', 10, 'bold')).pack(side='left')
        RetroButton(top, "⟳ ОБНОВИТЬ", self._load_portfolio,
                    bg=Palette.PURPLE_DIM, hover_bg=Palette.PURPLE).pack(side='right')

        tree_frame = tk.Frame(parent, bg=Palette.BG_CARD,
                              highlightthickness=2,
                              highlightbackground=Palette.PURPLE_DIM)
        tree_frame.pack(fill='both', expand=True, padx=12, pady=4)
        cols = ('id', 'title', 'style', 'desc')
        self.port_tree = ttk.Treeview(tree_frame, columns=cols, show='headings')
        self.port_tree.heading('id', text='#')
        self.port_tree.heading('title', text='НАЗВАНИЕ')
        self.port_tree.heading('style', text='СТИЛЬ')
        self.port_tree.heading('desc', text='ОПИСАНИЕ')
        self.port_tree.column('id', width=40, anchor='center')
        self.port_tree.column('title', width=200)
        self.port_tree.column('style', width=120)
        self.port_tree.column('desc', width=380)
        sb = ttk.Scrollbar(tree_frame, orient='vertical',
                            command=self.port_tree.yview)
        self.port_tree.configure(yscrollcommand=sb.set)
        self.port_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        actions = tk.Frame(parent, bg=Palette.BG)
        actions.pack(fill='x', padx=12, pady=(6, 12))
        RetroButton(actions, "🗑 УДАЛИТЬ ВЫБРАННУЮ",
                    self._delete_work,
                    bg='#3d1f1f', hover_bg=Palette.RED).pack(side='left')

    # ---------- СТАТУС-БАР ----------

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=Palette.BG_PANEL, height=24)
        bar.pack(fill='x', side='bottom')
        bar.pack_propagate(False)

        self.status_var = tk.StringVar(value="● READY")
        tk.Label(bar, textvariable=self.status_var,
                 bg=Palette.BG_PANEL, fg=Palette.ORANGE,
                 font=('Consolas', 9)).pack(side='left', padx=10)

        self.refresh_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.refresh_var,
                 bg=Palette.BG_PANEL, fg=Palette.PURPLE,
                 font=('Consolas', 9)).pack(side='right', padx=10)

    # ---------- ОБНОВЛЕНИЕ ----------

    def _refresh_loop(self):
        try:
            self._refresh_all()
        except Exception as e:
            self.status_var.set(f"⚠ ERR: {e}")
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

        # Индикаторы ботов: TG зелёный если активен, MAX — зелёный если активен
        # В standalone режиме (python admin_panel.py) берём из токенов config
        tg_ok = tg_active
        max_ok = max_active
        if not tg_ok and not max_ok:
            # standalone: определяем по токенам
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
            self.status_var.set("● " + " | ".join(notes)[:80])

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
            row_text = f"{name} {b['service']} {desc} {status}".lower()
            if search and search not in row_text:
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
        for w in works:
            self.port_tree.insert('', 'end',
                                   values=(w['id'], w['title'], w['style'] or '',
                                           (w['description'] or '')[:60]))

    def _load_reviews(self):
        if not hasattr(self, 'reviews_tree'):
            return
        for item in self.reviews_tree.get_children():
            self.reviews_tree.delete(item)
        reviews = get_reviews()[:8]
        for r in reviews:
            name = r['username'] or f"ID {r['user_id']}"
            stars = '⭐' * r['rating']
            text = (r['text'] or '')[:70]
            date = (r['created_at'] or '')[:16]
            self.reviews_tree.insert('', 'end',
                                      values=(name, stars, text, date))

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
            self.status_var.set(f"● #{bid} → {STATUS_RU.get(new_status)}")

    def _delete_client_cancelled(self):
        bid = self._selected_booking_id()
        if bid is None:
            return
        if messagebox.askyesno("УДАЛЕНИЕ",
                                f"Удалить запись #{bid} из базы?"):
            delete_booking(bid)
            self._load_bookings()
            self._load_stats()
            self.status_var.set(f"● #{bid} DELETED")

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
            self.status_var.set(f"● «{title}» DELETED")


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
