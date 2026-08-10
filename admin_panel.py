"""
Нативная админ-панель Windows на tkinter.

Запускается отдельным daemon-потоком из main.py / max_main.py.
Читает данные напрямую из database.py (потокобезопасно — каждое соединение своё).
Только этот поток трогает tk-виджеты; обновление через root.after(мс, callback).

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
from database import (delete_portfolio_work, get_all_bookings,
                      get_portfolio, get_rating_stats, get_reviews,
                      get_services, update_booking_status)

# Момент старта — для аптайма в шапке
_started_at = time.monotonic()

# Потокобезопасный канал: внешние потоки (bot) могут push-уведомления
# через panel_notify(), GUI подхватит через after().
_notify_queue: list = []
_notify_lock = threading.Lock()


# ============ ВОТЧЕР ФАЙЛА БД (живое обновление) ============

def _db_mtime():
    try:
        from config import DB_PATH
        return os.path.getmtime(DB_PATH)
    except OSError:
        return 0


# ============ КАНAЛ УВЕДОМЛЕНИЙ ============

def panel_notify(text):
    """Позволяет главному потоку (боту) отправить уведомление в панель.
    Безопасно вызывать из любого потока."""
    with _notify_lock:
        _notify_queue.append(text)


# ============ ЦВЕТА СТАТУСОВ ============

STATUS_RU = {
    'pending': '⏳ Ожидает',
    'confirmed': '✅ Подтверждена',
    'completed': '✨ Завершена',
    'cancelled': '❌ Отменена',
    'client_cancelled': '🚫 Отказ клиента',
}

STATUS_TAGS = {
    'pending': 'pending',
    'confirmed': 'confirmed',
    'completed': 'completed',
    'cancelled': 'cancelled',
    'client_cancelled': 'client_cancelled',
}


# ============ ПАНЕЛЬ ============

class AdminPanel(tk.Tk):
    """Главное окно админ-панели."""

    REFRESH_MS = 5000  # автообновление каждые 5 сек

    def __init__(self):
        super().__init__()
        self.title(f"{BOT_NAME} — Админ-панель")
        self.geometry("960x640")
        self.minsize(800, 500)

        # Тёмная акцентная полоса (Windows нативный ttk этого не даст — берём tk.Frame)
        try:
            self.configure(bg='#1e1e2e')
        except Exception:
            pass

        self._build_header()
        self._build_notebook()
        self._build_statusbar()

        # Теги раскраски строк
        self.tree.tag_configure('pending', background='#fff3cd')
        self.tree.tag_configure('confirmed', background='#d4edda')
        self.tree.tag_configure('completed', background='#d1ecf1')
        self.tree.tag_configure('cancelled', background='#f8d7da')
        self.tree.tag_configure('client_cancelled', background='#e2d6f3')

        # Кеш времени модификации БД — чтобы не перечитывать без нужды
        self._db_mtime = _db_mtime()

        self._refresh_all()
        self.after(self.REFRESH_MS, self._refresh_loop)

    # ---------- ШАПКА ----------

    def _build_header(self):
        header = ttk.Frame(self)
        header.pack(fill='x', padx=12, pady=(10, 4))

        # Левая часть: бренд
        left = ttk.Frame(header)
        left.pack(side='left')
        ttk.Label(left, text=BOT_NAME,
                  font=('Segoe UI', 18, 'bold')).pack(side='left')
        ttk.Label(left, text=f"  ·  {BOT_MASTER}  ·  @{BOT_HANDLE}",
                  font=('Segoe UI', 10), foreground='gray').pack(side='left', padx=4)

        # Правая часть: аптайм
        self.uptime_var = tk.StringVar(value="аптайм 0с")
        ttk.Label(header, textvariable=self.uptime_var,
                  font=('Segoe UI', 9), foreground='gray').pack(side='right')

    # ---------- ВКЛАДКИ ----------

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill='both', expand=True, padx=12, pady=4)

        # Статистика
        f_stats = ttk.Frame(self.nb)
        self.nb.add(f_stats, text="📊  Статистика")
        self._build_stats(f_stats)

        # Записи
        f_book = ttk.Frame(self.nb)
        self.nb.add(f_book, text="📅  Записи")
        self._build_bookings(f_book)

        # Портфолио
        f_port = ttk.Frame(self.nb)
        self.nb.add(f_port, text="🎨  Портфолио")
        self._build_portfolio(f_port)

    # ---------- СТАТИСТИКА ----------

    def _build_stats(self, parent):
        # Сетка карточек
        grid = ttk.Frame(parent)
        grid.pack(fill='both', expand=True, padx=12, pady=12)

        self.stat_vars = {}
        cards = [
            ('services', '💰 Услуги', '#0d6efd'),
            ('portfolio', '🎨 Работы', '#6f42c1'),
            ('reviews', '⭐ Отзывы', '#ffc107'),
            ('rating', '🏆 Рейтинг', '#198754'),
            ('bookings_total', '📅 Всего записей', '#0dcaf0'),
            ('bookings_active', '🔔 Активных', '#fd7e14'),
        ]
        for i, (key, label, color) in enumerate(cards):
            row, col = i // 3, i % 3
            card = ttk.LabelFrame(grid, text=label, padding=14)
            card.grid(row=row, column=col, sticky='nsew', padx=6, pady=6)
            grid.grid_columnconfigure(col, weight=1)
            var = tk.StringVar(value="—")
            self.stat_vars[key] = var
            ttk.Label(card, textvariable=var,
                      font=('Segoe UI', 22, 'bold')).pack()

        # Последние отзывы
        reviews_frame = ttk.LabelFrame(parent, text="Последние отзывы", padding=8)
        reviews_frame.pack(fill='both', expand=True, padx=12, pady=(0, 12))

        cols = ('user', 'rating', 'text', 'date')
        self.reviews_tree = ttk.Treeview(reviews_frame, columns=cols,
                                          show='headings', height=5)
        self.reviews_tree.heading('user', text='Клиент')
        self.reviews_tree.heading('rating', text='Оценка')
        self.reviews_tree.heading('text', text='Текст')
        self.reviews_tree.heading('date', text='Дата')
        self.reviews_tree.column('user', width=120)
        self.reviews_tree.column('rating', width=60, anchor='center')
        self.reviews_tree.column('text', width=400)
        self.reviews_tree.column('date', width=120)
        sb = ttk.Scrollbar(reviews_frame, orient='vertical',
                            command=self.reviews_tree.yview)
        self.reviews_tree.configure(yscrollcommand=sb.set)
        self.reviews_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

    # ---------- ЗАПИСИ ----------

    def _build_bookings(self, parent):
        # Фильтр
        filt = ttk.Frame(parent)
        filt.pack(fill='x', padx=12, pady=(8, 4))

        ttk.Label(filt, text="Фильтр:").pack(side='left')
        self.status_var = tk.StringVar(value='all')
        cb_values = ['all'] + list(STATUS_RU.keys())
        cb = ttk.Combobox(filt, textvariable=self.status_var,
                          values=cb_values, state='readonly', width=18)
        cb.pack(side='left', padx=6)
        cb.bind('<<ComboboxSelected>>', lambda e: self._load_bookings())

        ttk.Label(filt, text="  Поиск:").pack(side='left')
        self.search_var = tk.StringVar()
        entry = ttk.Entry(filt, textvariable=self.search_var, width=20)
        entry.pack(side='left', padx=6)
        entry.bind('<KeyRelease>', lambda e: self._load_bookings())

        ttk.Button(filt, text="🔄 Обновить",
                    command=self._load_bookings).pack(side='right')

        # Таблица
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill='both', expand=True, padx=12, pady=4)

        cols = ('id', 'client', 'service', 'date', 'status', 'desc')
        self.tree = ttk.Treeview(tree_frame, columns=cols, show='headings')
        self.tree.heading('id', text='#')
        self.tree.heading('client', text='Клиент')
        self.tree.heading('service', text='Услуга')
        self.tree.heading('date', text='Дата / время')
        self.tree.heading('status', text='Статус')
        self.tree.heading('desc', text='Описание')
        self.tree.column('id', width=40, anchor='center')
        self.tree.column('client', width=140)
        self.tree.column('service', width=160)
        self.tree.column('date', width=120, anchor='center')
        self.tree.column('status', width=130)
        self.tree.column('desc', width=240)

        sb = ttk.Scrollbar(tree_frame, orient='vertical',
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        # Кнопки действий
        actions = ttk.Frame(parent)
        actions.pack(fill='x', padx=12, pady=(4, 10))
        ttk.Button(actions, text="✅ Подтвердить",
                    command=lambda: self._set_status('confirmed')).pack(side='left', padx=3)
        ttk.Button(actions, text="✨ Завершить",
                    command=lambda: self._set_status('completed')).pack(side='left', padx=3)
        ttk.Button(actions, text="❌ Отменить",
                    command=lambda: self._set_status('cancelled')).pack(side='left', padx=3)
        ttk.Button(actions, text="🗑 Удалить отказ",
                    command=self._delete_client_cancelled).pack(side='left', padx=3)

    # ---------- ПОРТФОЛИО ----------

    def _build_portfolio(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill='x', padx=12, pady=(8, 4))
        ttk.Label(top, text="Работы мастера",
                  font=('Segoe UI', 11, 'bold')).pack(side='left')
        ttk.Button(top, text="🔄 Обновить",
                    command=self._load_portfolio).pack(side='right')

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill='both', expand=True, padx=12, pady=4)
        cols = ('id', 'title', 'style', 'desc')
        self.port_tree = ttk.Treeview(tree_frame, columns=cols, show='headings')
        self.port_tree.heading('id', text='#')
        self.port_tree.heading('title', text='Название')
        self.port_tree.heading('style', text='Стиль')
        self.port_tree.heading('desc', text='Описание')
        self.port_tree.column('id', width=40, anchor='center')
        self.port_tree.column('title', width=200)
        self.port_tree.column('style', width=120)
        self.port_tree.column('desc', width=380)
        sb = ttk.Scrollbar(tree_frame, orient='vertical',
                            command=self.port_tree.yview)
        self.port_tree.configure(yscrollcommand=sb.set)
        self.port_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        actions = ttk.Frame(parent)
        actions.pack(fill='x', padx=12, pady=(4, 10))
        ttk.Button(actions, text="🗑 Удалить выбранную",
                    command=self._delete_work).pack(side='left')

    # ---------- СТАТУС-БАР ----------

    def _build_statusbar(self):
        bar = ttk.Frame(self, relief='sunken', padding=(8, 3))
        bar.pack(fill='x', side='bottom')
        self.status_var = tk.StringVar(value="● Готово")
        ttk.Label(bar, textvariable=self.status_var,
                  font=('Segoe UI', 9), foreground='gray').pack(side='left')
        self.refresh_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.refresh_var,
                  font=('Segoe UI', 9), foreground='gray').pack(side='right')

    # ---------- ОБНОВЛЕНИЕ ДАННЫХ ----------

    def _db_changed(self):
        """Проверяет, изменилась ли БД с последнего чека."""
        mtime = _db_mtime()
        if mtime != self._db_mtime:
            self._db_mtime = mtime
            return True
        return False

    def _refresh_loop(self):
        """Главный цикл автообновления."""
        try:
            # Перечитываем только если БД изменилась ИЛИ вкладка активно просматривается
            # ponytail: для простоты — всегда перечитываем, это дёшево
            self._refresh_all()
        except Exception as e:
            self.status_var.set(f"⚠ Ошибка обновления: {e}")
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
        self.uptime_var.set(f"⏱ аптайм {up}  ·  📍 {BOT_CITY}")

        self._load_stats()
        self._load_bookings()
        self._load_portfolio()
        self._load_reviews()

        # Подхватываем уведомления из очереди
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
            tag = STATUS_TAGS.get(status, '')
            self.tree.insert('', 'end',
                              values=(b['id'], name, b['service'],
                                      b['date_time'], STATUS_RU.get(status, status),
                                      desc),
                              tags=(tag,) if tag else ())

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
            messagebox.showinfo("Выбор", "Выберите запись в таблице.")
            return None
        vals = self.tree.item(sel[0])['values']
        return int(vals[0])

    def _set_status(self, new_status):
        bid = self._selected_booking_id()
        if bid is None:
            return
        if messagebox.askyesno("Подтверждение",
                                f"Изменить статус записи #{bid} на «{STATUS_RU.get(new_status, new_status)}»?"):
            update_booking_status(bid, new_status)
            self._load_bookings()
            self._load_stats()
            self.status_var.set(f"● Запись #{bid} → {STATUS_RU.get(new_status)}")

    def _delete_client_cancelled(self):
        bid = self._selected_booking_id()
        if bid is None:
            return
        if messagebox.askyesno("Удаление",
                                f"Удалить запись #{bid} из базы?\n(используйте для очистки отказов)"):
            from database import delete_booking
            delete_booking(bid)
            self._load_bookings()
            self._load_stats()
            self.status_var.set(f"● Запись #{bid} удалена")

    def _delete_work(self):
        sel = self.port_tree.selection()
        if not sel:
            messagebox.showinfo("Выбор", "Выберите работу в таблице.")
            return
        vals = self.port_tree.item(sel[0])['values']
        wid = int(vals[0])
        title = vals[1]
        if messagebox.askyesno("Удаление", f"Удалить работу «{title}»?"):
            delete_portfolio_work(wid)
            self._load_portfolio()
            self._load_stats()
            self.status_var.set(f"● Работа «{title}» удалена")


# ============ ТОЧКА ВХОДА ============

def run_admin_panel():
    """Запускает админ-панель. Блокирует вызывающий поток до закрытия окна.
    Предназначена для запуска в daemon-потоке."""
    try:
        app = AdminPanel()
        app.mainloop()
    except Exception as e:
        # В daemon-потоке исключения тихие — выводим в stderr
        print(f"[AdminPanel] crash: {e}", file=sys.stderr)


if __name__ == '__main__':
    # Standalone запуск: для разработки панели без запуска бота
    print(f"Запуск {BOT_NAME} админ-панели (standalone)...")
    run_admin_panel()
