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

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (DataTable, Footer, Header, Label, TabbedContent,
                             TabPane)
from textual.widgets._tabbed_content import ContentTabs

from config import BOT_CITY, BOT_HANDLE, BOT_MASTER, BOT_NAME
from database import (get_all_bookings, get_portfolio, get_rating_stats,
                      get_reviews, get_services)

_started = time.monotonic()

STATUS_RU = {
    'pending': '⏳ Ожидает',
    'confirmed': '✅ Подтверждена',
    'completed': '✨ Завершена',
    'cancelled': '❌ Отменена',
    'client_cancelled': '🚫 Отказ клиента',
}


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
    Label.status {
        color: #ff8c42;
        padding: 0 1;
        text-align: right;
    }
    Label.stat-label {
        color: #ff8c42;
        text-style: bold;
        text-align: center;
        padding: 1;
    }
    Label.stat-value {
        color: #9d4edd;
        text-style: bold;
        text-align: center;
        padding: 0 1 1 1;
    }
    TabbedContent ContentTabs {
        background: #0a0a0a;
    }
    TabbedContent ContentTabs Tab {
        color: #ff8c42;
        background: #0a0a0a;
    }
    TabbedContent ContentTabs Tab.-active {
        color: #ff8c42;
        background: #222222;
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
        Binding('q', 'quit', 'Выход'),
        Binding('1', 'switch_tab("stats")', 'Статистика'),
        Binding('2', 'switch_tab("bookings")', 'Записи'),
        Binding('3', 'switch_tab("portfolio")', 'Портфолио'),
        Binding('r', 'refresh', 'Обновить'),
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

        # Шапка с логотипом
        with Vertical():
            for line in self._logo_text:
                yield Label(line, classes='logo')
            yield Label(f'{BOT_MASTER}  ◇  @{BOT_HANDLE}',
                        classes='subtitle')
            yield Label(self._bot_status_line(), classes='status')
            yield Label(id='uptime-label', classes='status')

            # Вкладки
            with TabbedContent(initial='stats'):
                with TabPane('▌ СТАТИСТИКА', id='stats'):
                    yield from self._compose_stats()
                with TabPane('▌ ЗАПИСИ', id='bookings'):
                    yield DataTable(id='bookings-table')
                with TabPane('▌ ПОРТФОЛИО', id='portfolio'):
                    yield DataTable(id='portfolio-table')

        yield Footer()

    def _bot_status_line(self):
        from config import BOT_TOKEN, MAX_TOKEN
        tg = '✅ TG' if (BOT_TOKEN and BOT_TOKEN != 'YOUR_TELEGRAM_BOT_TOKEN_HERE') else '❌ TG'
        mx = '✅ MAX' if MAX_TOKEN else '❌ MAX'
        return f'{tg}  {mx}'

    def _compose_stats(self) -> ComposeResult:
        labels = [
            ('stat-services', '💰 УСЛУГИ'),
            ('stat-portfolio', '🎨 РАБОТЫ'),
            ('stat-reviews', '⭐ ОТЗЫВЫ'),
            ('stat-rating', '🏆 РЕЙТИНГ'),
            ('stat-total', '📅 ВСЕГО'),
            ('stat-active', '🔔 АКТИВНО'),
        ]
        # Сетка 2x3
        with Horizontal():
            with Vertical():
                yield Label('💰 УСЛУГИ', classes='stat-label')
                yield Label('—', id='stat-services', classes='stat-value')
                yield Label('⭐ ОТЗЫВЫ', classes='stat-label')
                yield Label('—', id='stat-reviews', classes='stat-value')
                yield Label('📅 ВСЕГО', classes='stat-label')
                yield Label('—', id='stat-total', classes='stat-value')
            with Vertical():
                yield Label('🎨 РАБОТЫ', classes='stat-label')
                yield Label('—', id='stat-portfolio', classes='stat-value')
                yield Label('🏆 РЕЙТИНГ', classes='stat-label')
                yield Label('—', id='stat-rating', classes='stat-value')
                yield Label('🔔 АКТИВНО', classes='stat-label')
                yield Label('—', id='stat-active', classes='stat-value')

    def on_mount(self) -> None:
        self.title = 'PRIZMA TATTOO STUDIO'
        self.sub_title = f'{BOT_MASTER}  ◇  @{BOT_HANDLE}'
        self._refresh_all()
        self.set_interval(5, self._refresh_all)

    def watch_uptime(self, val: str) -> None:
        label = self.query_one('#uptime-label', Label)
        label.update(f'⏱ {val}  ◇  📍 {BOT_CITY}  ◇  ↻ {datetime.now().strftime("%H:%M:%S")}')

    def _refresh_all(self) -> None:
        self.uptime = _uptime()
        self._load_stats()
        self._load_bookings()
        self._load_portfolio()

    def _load_stats(self):
        services = get_services()
        portfolio = get_portfolio()
        reviews = get_reviews()
        avg, cnt = get_rating_stats()
        bookings = get_all_bookings()
        active = [b for b in bookings if b['status'] in ('pending', 'confirmed')]
        rating = f'{avg:.1f}' if cnt else '—'

        self.query_one('#stat-services', Label).update(str(len(services)))
        self.query_one('#stat-portfolio', Label).update(str(len(portfolio)))
        self.query_one('#stat-reviews', Label).update(str(cnt))
        self.query_one('#stat-rating', Label).update(rating)
        self.query_one('#stat-total', Label).update(str(len(bookings)))
        self.query_one('#stat-active', Label).update(str(len(active)))

    def _load_bookings(self):
        table = self.query_one('#bookings-table', DataTable)
        table.clear(columns=True)
        table.add_columns('#', 'Клиент', 'Услуга', 'Дата', 'Статус', 'Описание')
        for b in get_all_bookings():
            name = b['first_name'] or 'Клиент'
            if b['username']:
                name += f" @{b['username']}"
            status = STATUS_RU.get(b['status'], b['status'])
            desc = (b['description'] or '')[:40]
            table.add_row(str(b['id']), name, b['service'] or '',
                          b['date_time'], status, desc)

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


def run_textual():
    app = PrizmaTUI()
    app.run()


if __name__ == '__main__':
    run_textual()
