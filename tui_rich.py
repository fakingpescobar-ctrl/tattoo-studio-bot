"""
Rich TUI дашборд — автообновляемый в консоли.

Чёрный фон, оранжевый текст, фиолетовые цифры.
Обновляется каждые 5 секунд. Без интерактива — только просмотр.

Запуск: python tui_rich.py
"""
import time
from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from config import BOT_CITY, BOT_HANDLE, BOT_MASTER, BOT_NAME
from database import (get_all_bookings, get_portfolio, get_rating_stats,
                      get_reviews, get_services)

# Запоминаем старт
_started = time.monotonic()

# Тема: оранжевый текст, фиолетовые акценты, серый для рамок
theme = Theme({
    'orange':     '#ff8c42',
    'orange_dim': '#b85a1a',
    'purple':     '#9d4edd',
    'purple_dim': '#5a189a',
    'gray':       '#888888',
    'green':      '#2ed573',
    'red':        '#ff4757',
    'yellow':     '#ffd60a',
    'blue':       '#54a0ff',
})

console = Console(theme=theme)

STATUS_RU = {
    'pending':          '[yellow]⏳ Ожидает[/yellow]',
    'confirmed':        '[green]✅ Подтверждена[/green]',
    'completed':        '[blue]✨ Завершена[/blue]',
    'cancelled':        '[red]❌ Отменена[/red]',
    'client_cancelled': '[orange]🚫 Отказ клиента[/orange]',
}

# Читаем логотип
import os
_logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logo.txt')
try:
    with open(_logo_path, encoding='utf-8') as f:
        LOGO = f.read().rstrip()
except (OSError, UnicodeDecodeError):
    LOGO = BOT_NAME


def _uptime():
    secs = int(time.monotonic() - _started)
    if secs < 60:
        return f"{secs}с"
    if secs < 3600:
        return f"{secs // 60}м {secs % 60}с"
    h, m = secs // 3600, (secs % 3600) // 60
    return f"{h}ч {m}м"


def _bot_status():
    """Индикаторы ботов."""
    from config import BOT_TOKEN, MAX_TOKEN
    tg_ok = bool(BOT_TOKEN and BOT_TOKEN != 'YOUR_TELEGRAM_BOT_TOKEN_HERE')
    max_ok = bool(MAX_TOKEN)
    tg = '[green]●[/green] Telegram' if tg_ok else '[red]●[/red] Telegram'
    mx = '[green]●[/green] MAX' if max_ok else '[red]●[/red] MAX'
    return f"{tg}  {mx}"


def build_header():
    """Шапка с логотипом + индикаторы."""
    layout = Table.grid(padding=(0, 2))
    layout.add_column(justify='left', style='purple')
    layout.add_column(justify='right')

    logo_text = Text(LOGO, style='purple bold')
    subtitle = Text(f"{BOT_MASTER}  ◇  @{BOT_HANDLE}", style='purple')

    uptime_text = Text(f"⏱ {_uptime()}  ◇  📍 {BOT_CITY}\n{_bot_status()}",
                       style='orange')

    layout.add_row(logo_text, uptime_text)
    layout.add_row(subtitle, Text(f"↻ {datetime.now().strftime('%H:%M:%S')}",
                                   style='gray'))
    return Panel(layout, style='gray', border_style='gray', padding=(0, 1))


def build_stats():
    """Карточки статистики."""
    services = get_services()
    portfolio = get_portfolio()
    reviews = get_reviews()
    avg, cnt = get_rating_stats()
    bookings = get_all_bookings()
    active = [b for b in bookings if b['status'] in ('pending', 'confirmed')]
    rating = f"{avg:.1f}" if cnt else "—"

    grid = Table.grid(padding=(1, 2))
    for _ in range(3):
        grid.add_column(justify='center')

    cards = [
        ('💰 УСЛУГИ', str(len(services))),
        ('🎨 РАБОТЫ', str(len(portfolio))),
        ('⭐ ОТЗЫВЫ', str(cnt)),
        ('🏆 РЕЙТИНГ', rating),
        ('📅 ВСЕГО', str(len(bookings))),
        ('🔔 АКТИВНО', str(len(active))),
    ]

    for i in range(0, len(cards), 3):
        row = []
        for label, val in cards[i:i+3]:
            cell = Table.grid(padding=(0, 0))
            cell.add_row(Text(label, style='orange bold', justify='center'))
            cell.add_row(Text(val, style='purple bold', justify='center'))
            row.append(Panel(cell, style='gray', border_style='gray'))
        grid.add_row(*row)

    return Panel(grid, title='[orange]▌ СТАТИСТИКА[/orange]',
                 border_style='gray', padding=(0, 0))


def build_bookings():
    """Таблица записей."""
    table = Table(border_style='gray', row_styles=['', 'dim'],
                  header_style='orange bold', expand=True)
    table.add_column('#', justify='center', width=4)
    table.add_column('Клиент', width=20)
    table.add_column('Услуга', width=20)
    table.add_column('Дата', width=14)
    table.add_column('Статус', width=18)
    table.add_column('Описание')

    bookings = get_all_bookings()
    for b in bookings:
        name = b['first_name'] or 'Клиент'
        if b['username']:
            name += f" @{b['username']}"
        status = STATUS_RU.get(b['status'], b['status'])
        desc = (b['description'] or '')[:40]
        table.add_row(str(b['id']), name, b['service'] or '', b['date_time'],
                      status, desc)

    if not bookings:
        table.add_row('—', 'Нет записей', '', '', '', '')

    return Panel(table, title='[orange]▌ ЗАПИСИ[/orange]',
                 border_style='gray', padding=(0, 0))


def build_portfolio():
    """Таблица портфолио."""
    table = Table(border_style='gray', row_styles=['', 'dim'],
                  header_style='orange bold', expand=True)
    table.add_column('#', justify='center', width=4)
    table.add_column('Название', width=25)
    table.add_column('Стиль', width=15)
    table.add_column('Описание')

    works = get_portfolio()
    for w in works:
        table.add_row(str(w['id']), w['title'] or '', w['style'] or '',
                      (w['description'] or '')[:40])

    if not works:
        table.add_row('—', 'Нет работ', '', '')

    return Panel(table, title='[orange]▌ ПОРТФОЛИО[/orange]',
                 border_style='gray', padding=(0, 0))


def build_reviews():
    """Последние отзывы."""
    table = Table(border_style='gray', row_styles=['', 'dim'],
                  header_style='orange bold', expand=True)
    table.add_column('Клиент', width=15)
    table.add_column('Оценка', justify='center', width=8)
    table.add_column('Текст')
    table.add_column('Дата', width=12)

    reviews = get_reviews()[:5]
    for r in reviews:
        name = r['username'] or f"ID {r['user_id']}"
        stars = '⭐' * r['rating']
        text = (r['text'] or '')[:50]
        date = (r['created_at'] or '')[:10]
        table.add_row(name, stars, text, date)

    if not reviews:
        table.add_row('Нет отзывов', '', '', '')

    return Panel(table, title='[orange]▌ ОТЗЫВЫ[/orange]',
                 border_style='gray', padding=(0, 0))


def build_layout():
    """Полный лейаут дашборда."""
    layout = Layout()
    layout.split(
        Layout(build_header(), name='header', size=10),
        Layout(name='body'),
    )
    layout['body'].split_row(
        Layout(name='left'),
        Layout(name='right'),
    )
    layout['left'].split(
        Layout(build_stats(), name='stats'),
        Layout(build_bookings(), name='bookings'),
    )
    layout['right'].split(
        Layout(build_portfolio(), name='portfolio'),
        Layout(build_reviews(), name='reviews'),
    )
    return layout


def run_rich_dashboard():
    """Запускает live-дашборд. Обновление каждые 5 секунд."""
    console.clear()
    with Live(build_layout(), console=console, refresh_per_second=0.2,
              screen=False) as live:
        try:
            while True:
                time.sleep(5)
                live.update(build_layout())
        except KeyboardInterrupt:
            console.print('\n[orange]Остановка дашборда.[/orange]')


if __name__ == '__main__':
    run_rich_dashboard()
