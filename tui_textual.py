"""
Textual TUI приложение — полноценный интерфейс в терминале с вкладками и мышкой.

Запуск: python tui_textual.py

Управление:
  Tab / Shift+Tab — переключение фокуса
  1, 2, 3 — переключение вкладок
  q — выход
"""
import os
import time
from datetime import datetime

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (Button, DataTable, Footer, Header, Label,
                             TabbedContent, TabPane)
from textual.widgets._tabbed_content import ContentTabs

from config import BOT_CITY, BOT_HANDLE, BOT_MASTER, BOT_NAME
from database import (delete_booking, get_all_bookings, get_booking_by_id,
                      get_portfolio, get_rating_stats, get_reviews,
                      get_services, update_booking_status)

_started = time.monotonic()

STATUS_RU = {
    'pending': '⏳ Ожидает',
    'confirmed': '✅ Подтверждена',
    'completed': '✨ Завершена',
    'cancelled': '❌ Отменена',
    'client_cancelled': '🚫 Отказ клиента',
}


class BookingActionScreen(ModalScreen):
    """Модальный экран с действиями для выбранной записи."""

    CSS = """
    BookingActionScreen {
        align: center middle;
    }
    BookingActionScreen > Vertical {
        background: #000000;
        border: round #9d4edd;
        padding: 1 2;
        width: 60;
        height: auto;
    }
    BookingActionScreen Label {
        color: #ff8c42;
        text-style: bold;
        padding: 0 1;
    }
    BookingActionScreen Label.detail {
        color: #888888;
        text-style: none;
        padding: 0 1;
    }
    BookingActionScreen Horizontal {
        height: 3;
        padding: 1 0 0 0;
    }
    BookingActionScreen Button {
        margin: 0 1;
        background: #1a1a1a;
        color: #ff8c42;
        border: solid #888888;
    }
    BookingActionScreen Button:hover {
        background: #2a2a2a;
    }
    BookingActionScreen Button.confirm {
        border: solid #2ed573;
    }
    BookingActionScreen Button.danger {
        border: solid #ff4757;
    }
    """

    BINDINGS = [Binding('escape', 'dismiss', 'Отмена')]

    def __init__(self, booking_id):
        super().__init__()
        self.booking_id = booking_id

    def compose(self) -> ComposeResult:
        b = get_booking_by_id(self.booking_id)
        with Vertical():
            if not b:
                yield Label('Запись не найдена')
                with Horizontal():
                    yield Button('Закрыть', id='close')
                return

            name = b['first_name'] or 'Клиент'
            if b['username']:
                name += f" @{b['username']}"
            status = STATUS_RU.get(b['status'], b['status'])

            yield Label(f'ЗАПИСЬ #{b["id"]}')
            yield Label(f'Клиент: {name}', classes='detail')
            yield Label(f'Услуга: {b["service"] or "—"}', classes='detail')
            yield Label(f'Дата: {b["date_time"]}', classes='detail')
            yield Label(f'Статус: {status}', classes='detail')
            yield Label(f'Описание: {b["description"] or "—"}', classes='detail')

            with Horizontal():
                yield Button('✅ Подтвердить', id='confirm', classes='confirm')
                yield Button('✨ Завершить', id='complete')
            with Horizontal():
                yield Button('❌ Отменить', id='cancel', classes='danger')
                yield Button('🗑 Удалить', id='delete', classes='danger')
            with Horizontal():
                yield Button('◀ Закрыть', id='close')

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = self.booking_id
        action = event.button.id

        if action == 'confirm':
            update_booking_status(bid, 'confirmed')
        elif action == 'complete':
            update_booking_status(bid, 'completed')
        elif action == 'cancel':
            update_booking_status(bid, 'cancelled')
        elif action == 'delete':
            delete_booking(bid)

        self.dismiss(action)


def _uptime():
    secs = int(time.monotonic() - _started)
    if secs < 60:
        return f"{secs}с"
    if secs < 3600:
        return f"{secs // 60}м {secs % 60}с"
    h, m = secs // 3600, (secs % 3600) // 60
    return f"{h}ч {m}м"


class PrizmaTUI(App):
    """PRIZMA TATTOO STUDIO — админ-панель в терминале."""

    CSS = """
    Screen {
        background: #000000;
        color: #ff8c42;
    }
    Header {
        background: #0a0a0a;
        color: #9d4edd;
    }
    Label.logo {
        color: #9d4edd;
        text-style: bold;
        padding: 0 1;
    }
    Label.subtitle {
        color: #9d4edd;
        padding: 0 1;
    }
    Horizontal.metrics-row {
        height: 3;
        padding: 0 1;
    }
    Label.metric {
        color: #ff8c42;
        padding: 0 2;
        text-style: bold;
        border: round #888888;
        margin: 0 1;
        content-align: center middle;
    }
    Label.stat-label {
        color: #ff8c42;
        text-style: bold;
        padding: 1;
    }
    TabbedContent ContentTabs {
        display: none;
    }
    TabbedContent ContentTabs Tab {
        display: none;
    }
    DataTable {
        background: #121212;
        color: #ff8c42;
    }
    DataTable > .datatable--header {
        background: #888888;
        color: #ff8c42;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: #888888;
        color: #ff8c42;
    }
    DataTable > .datatable--hover {
        background: #1a1a1a;
    }
    """

    BINDINGS = [
        Binding('1', 'switch_tab("home")', 'Главная'),
        Binding('2', 'switch_tab("bookings")', 'Записи'),
        Binding('3', 'switch_tab("portfolio")', 'Портфолио'),
        Binding('r', 'refresh', 'Обновить'),
        Binding('q', 'quit', 'Выход'),
        Binding('enter', 'open_selected', 'Действие'),
    ]

    uptime = reactive('0с')

    def __init__(self):
        super().__init__()
        self._logo_text = self._load_logo()

    def _load_logo(self):
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'logo.txt')
        try:
            with open(logo_path, encoding='utf-8') as f:
                lines = [l.rstrip() for l in f if l.strip()]
                return lines
        except (OSError, UnicodeDecodeError):
            return [BOT_NAME]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        # Шапка: логотип + метрики в одну строку
        with Vertical():
            self._logo_labels = []
            for line in self._logo_text:
                lbl = Label(line, classes='logo')
                self._logo_labels.append(lbl)
                yield lbl

            # Строка метрик рядом с вкладками
            with Horizontal(classes='metrics-row'):
                yield Label(id='m-rating', classes='metric')
                yield Label(id='m-reviews', classes='metric')
                yield Label(id='m-total', classes='metric')
                yield Label(id='m-active', classes='metric')
                yield Label(self._bot_status_line(), classes='metric')
                yield Label(id='uptime-label', classes='metric')

            # Вкладки
            with TabbedContent(initial='home'):
                with TabPane('▌ ГЛАВНАЯ', id='home'):
                    yield from self._compose_home()
                with TabPane('▌ ЗАПИСИ', id='bookings'):
                    yield DataTable(id='bookings-table')
                with TabPane('▌ ПОРТФОЛИО', id='portfolio'):
                    yield DataTable(id='portfolio-table')

        yield Footer()

    def _bot_status_line(self):
        from config import BOT_TOKEN, MAX_TOKEN
        tg = '✅ TG' if (BOT_TOKEN and BOT_TOKEN != 'YOUR_TELEGRAM_BOT_TOKEN_HERE') else '❌ TG'
        mx = '✅ MAX' if MAX_TOKEN else '❌ MAX'
        return f'{tg} {mx}'

    def _compose_home(self) -> ComposeResult:
        """Главная — ближайшие записи."""
        yield Label('▌ БЛИЖАЙШИЕ ЗАПИСИ', classes='stat-label')
        yield DataTable(id='upcoming-table')

    def on_mount(self) -> None:
        self.title = 'PRIZMA TATTOO STUDIO'
        self.sub_title = f'{BOT_MASTER}  ◇  @{BOT_HANDLE}'
        # Кликабельные строки в таблицах
        self.query_one('#bookings-table', DataTable).cursor_type = 'row'
        self.query_one('#portfolio-table', DataTable).cursor_type = 'row'
        self.query_one('#upcoming-table', DataTable).cursor_type = 'row'
        self._refresh_all()
        self.set_interval(5, self._refresh_all)
        # Анимация логотипа — переливание цвета каждые 150мс
        self._logo_phase = 0
        self.set_interval(0.15, self._animate_logo)

    def _animate_logo(self) -> None:
        """Цветовая волна слева направо по символам логотипа."""
        import math
        phase = self._logo_phase
        labels = getattr(self, '_logo_labels', [])

        # Длина самой широкой строки — для расчёта ширины волны
        max_w = max(len(line) for line in self._logo_text) if self._logo_text else 1

        for i, lbl in enumerate(labels):
            line = self._logo_text[i] if i < len(self._logo_text) else ''
            text = Text()
            for col, char in enumerate(line):
                # Волна: sin(time + col * 0.4) — движется слева направо
                wave = (math.sin(phase + col * 0.4) + 1) / 2  # 0..1
                # Пик волны — ярко-голубой #64e0ff, впадина — фиолетовый #9d4edd
                r = int(0x9d + (0x64 - 0x9d) * wave)
                g = int(0x4e + (0xe0 - 0x4e) * wave)
                b = int(0xdd + (0xff - 0xdd) * wave)
                color = f'#{r:02x}{g:02x}{b:02x}'
                # Жирный на пике волны, обычный в впадине
                style = color + ' bold' if wave > 0.7 else color
                text.append(char, style=style)
            lbl.update(text)
        self._logo_phase += 0.25

    def watch_uptime(self, val: str) -> None:
        label = self.query_one('#uptime-label', Label)
        label.update(f'⏱ {val}')

    def _refresh_all(self) -> None:
        self.uptime = _uptime()
        self._load_metrics()
        self._load_upcoming()
        self._load_bookings()
        self._load_portfolio()

    def _load_metrics(self):
        """Метрики в шапке: рейтинг / отзывы / всего / активно."""
        reviews = get_reviews()
        avg, cnt = get_rating_stats()
        bookings = get_all_bookings()
        active = [b for b in bookings if b['status'] in ('pending', 'confirmed')]
        rating = f'{avg:.1f}' if cnt else '—'

        self.query_one('#m-rating', Label).update(f'🏆 {rating}')
        self.query_one('#m-reviews', Label).update(f'⭐ {cnt}')
        self.query_one('#m-total', Label).update(f'📅 {len(bookings)}')
        self.query_one('#m-active', Label).update(f'🔔 {len(active)}')

    def _load_upcoming(self):
        """Ближайшие записи на главной вкладке."""
        table = self.query_one('#upcoming-table', DataTable)
        table.clear(columns=True)
        table.add_columns('#', 'Клиент', 'Услуга', 'Дата', 'Время', 'Статус')

        bookings = get_all_bookings()
        active = [b for b in bookings if b['status'] in ('pending', 'confirmed')]

        # Сортировка по дате
        def parse_date(b):
            try:
                return datetime.strptime((b['date_time'] or '').strip(), '%d.%m.%Y %H:%M')
            except (ValueError, TypeError):
                return datetime.max

        active.sort(key=parse_date)
        for b in active[:10]:
            name = b['first_name'] or 'Клиент'
            if b['username']:
                name += f' @{b["username"]}'
            dt_str = b['date_time'] or ''
            date_part = dt_str[:10] if len(dt_str) >= 10 else dt_str
            time_part = dt_str[11:16] if len(dt_str) >= 16 else ''
            status = STATUS_RU.get(b['status'], b['status'])
            table.add_row(str(b['id']), name, b['service'] or '',
                          date_part, time_part, status)

    def _load_bookings(self):
        table = self.query_one('#bookings-table', DataTable)
        table.clear(columns=True)
        table.add_columns('#', 'Клиент', 'Услуга', 'Дата', 'Статус', 'Описание')
        self._booking_row_ids = {}  # row_key → booking_id
        for b in get_all_bookings():
            name = b['first_name'] or 'Клиент'
            if b['username']:
                name += f" @{b['username']}"
            status = STATUS_RU.get(b['status'], b['status'])
            desc = (b['description'] or '')[:40]
            row_key = table.add_row(str(b['id']), name, b['service'] or '',
                                    b['date_time'], status, desc)
            self._booking_row_ids[row_key] = b['id']

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Клик по строке записей → открыть модал действий."""
        table_id = event.data_table.id
        if table_id != 'bookings-table':
            return
        row_key = event.row_key
        booking_id = getattr(self, '_booking_row_ids', {}).get(row_key)
        if booking_id is None:
            return
        def _on_dismiss(action):
            if action and action != 'close':
                self._refresh_all()
        self.push_screen(BookingActionScreen(booking_id), _on_dismiss)

    def _load_portfolio(self):
        table = self.query_one('#portfolio-table', DataTable)
        table.clear(columns=True)
        table.add_columns('#', 'Название', 'Стиль', 'Описание')
        for w in get_portfolio():
            table.add_row(str(w['id']), w['title'] or '', w['style'] or '',
                          (w['description'] or '')[:40])

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_refresh(self) -> None:
        self._refresh_all()

    def action_open_selected(self) -> None:
        """Enter на записи → открыть модал действий."""
        focused = self.focused
        if isinstance(focused, DataTable) and focused.id == 'bookings-table':
            row_key = focused.coordinate_to_row_key(focused.cursor_coordinate)
            booking_id = getattr(self, '_booking_row_ids', {}).get(row_key)
            if booking_id is not None:
                def _on_dismiss(action):
                    if action and action != 'close':
                        self._refresh_all()
                self.push_screen(BookingActionScreen(booking_id), _on_dismiss)


def run_textual():
    app = PrizmaTUI()
    app.run()


if __name__ == '__main__':
    run_textual()
