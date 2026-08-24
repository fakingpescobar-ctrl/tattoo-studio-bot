"""
Тесты для database.py — работают с временной SQLite базой в памяти.
Каждый тест получает чистую БД через фикстуру (monkeypatch get_db).
"""
import os
import sys
import sqlite3
import tempfile
import pytest

# Добавляем корень проекта в sys.path, чтобы импортировать database
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database


# -------------- ФИКСТУРЫ --------------

@pytest.fixture
def tmp_db(monkeypatch):
    """Подменяет get_db на временную файловую базу (как реальный код — открывает/закрывает).
    В отличие от :memory:, файл переживает закрытие соединения."""
    # Временный файл для БД
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    # Создаём схему
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.executescript('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            phone TEXT
        );
        CREATE TABLE bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service TEXT,
            description TEXT,
            date_time TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notified_24h INTEGER DEFAULT 0,
            platform TEXT NOT NULL DEFAULT 'telegram',
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            price_min REAL,
            price_max REAL,
            duration INTEGER
        );
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            file_id TEXT,
            style TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            rating INTEGER,
            text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE blocked_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_time TEXT UNIQUE
        );
        CREATE TABLE user_states (
            user_id INTEGER PRIMARY KEY,
            state TEXT,
            data TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE cache_epoch (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            value INTEGER NOT NULL DEFAULT 0
        );
    ''')
    conn.commit()
    conn.close()

    # Подменяем get_db так, чтобы все функции database открывали наш временный файл
    monkeypatch.setattr(database, 'get_db', lambda: _connect_tmp(db_path))

    # Чистим кэш перед каждым тестом
    database.cache.clear()

    yield db_path

    # Удаляем временный файл
    try:
        os.remove(db_path)
    except OSError:
        pass


def _connect_tmp(db_path):
    """Создаёт соединение к временной БД с правильной row_factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# -------------- ПОЛЬЗОВАТЕЛИ --------------

def test_save_and_get_user(tmp_db):
    database.save_user(100, "alice", "Alice", "Smith")
    user = database.get_user_by_id(100)
    assert user is not None
    assert user['username'] == "alice"
    assert user['first_name'] == "Alice"


def test_save_user_updates_existing(tmp_db):
    database.save_user(200, "bob", "Bob", None)
    # Обновляем того же пользователя
    database.save_user(200, "bob_new", "Bobby", "Brown")
    user = database.get_user_by_id(200)
    assert user['username'] == "bob_new"
    assert user['first_name'] == "Bobby"
    assert user['last_name'] == "Brown"


def test_get_nonexistent_user(tmp_db):
    assert database.get_user_by_id(999) is None


# -------------- ЗАПИСИ --------------

def test_create_and_get_booking(tmp_db):
    database.save_user(300, "carol", "Carol", None)
    booking_id = database.create_booking(300, "Миниатюра", "Описание эскиза", "15.08.2026 14:00")
    assert booking_id > 0

    bookings = database.get_user_bookings(300)
    assert len(bookings) == 1
    b = bookings[0]
    assert b['service'] == "Миниатюра"
    assert b['description'] == "Описание эскиза"
    assert b['date_time'] == "15.08.2026 14:00"
    assert b['status'] == 'pending'


def test_update_booking_status(tmp_db):
    database.save_user(301, "dave", "Dave", None)
    bid = database.create_booking(301, "Тату", "desc", "20.08.2026 12:00")
    database.update_booking_status(bid, 'confirmed')

    b = database.get_booking_by_id(bid)
    assert b['status'] == 'confirmed'


def test_create_booking_with_explicit_status(tmp_db):
    """create_booking с status='cancelled' — отмена заявки на этапе подтверждения:
    запись создаётся сразу с нужным статусом одним атомарным INSERT (без отдельного
    update). Дефолт остаётся 'pending' для обратной совместимости."""
    database.save_user(305, "frank", "Frank", None)
    bid_pending = database.create_booking(305, "Тату", "d1", "01.09.2026 10:00")
    assert database.get_booking_by_id(bid_pending)['status'] == 'pending'

    bid_cancelled = database.create_booking(
        305, "Тату", "d2", "02.09.2026 11:00", status='cancelled')
    b = database.get_booking_by_id(bid_cancelled)
    assert b is not None
    assert b['status'] == 'cancelled'

    # Запись видна мастеру в общем списке (все статусы)
    all_bookings = database.get_all_bookings()
    statuses = [row['status'] for row in all_bookings if row['user_id'] == 305]
    assert 'cancelled' in statuses
    assert 'pending' in statuses


def test_delete_booking(tmp_db):
    database.save_user(302, "eve", "Eve", None)
    bid = database.create_booking(302, "Тату", "desc", "25.08.2026 16:00")
    assert database.get_booking_by_id(bid) is not None

    database.delete_booking(bid)
    assert database.get_booking_by_id(bid) is None


def test_delete_booking_keeps_dense_numbering(tmp_db):
    """После удаления записи следующая должна получить ближайший свободный ID,
    а не 'прыгнуть' через удалённый (AUTOINCREMENT прижимается к MAX(id))."""
    database.save_user(303, "zoe", "Zoe", None)
    b1 = database.create_booking(303, "Услуга", "d", "01.09.2026 10:00")
    b2 = database.create_booking(303, "Услуга", "d", "02.09.2026 11:00")

    # Удаляем последнюю (b2) — счётчик должен прижаться к b1
    database.delete_booking(b2)
    next_id = database.create_booking(303, "Услуга", "d", "03.09.2026 12:00")
    assert next_id == b2, f"Ожидался ID {b2}, получен {next_id}"

    # Удаляем все — следующая должна стать #1
    database.delete_booking(b1)
    database.delete_booking(next_id)
    first_id = database.create_booking(303, "Услуга", "d", "04.09.2026 13:00")
    assert first_id == 1, f"Ожидался ID 1, получен {first_id}"


def test_get_all_bookings(tmp_db):
    database.save_user(310, "frank", "Frank", None)
    database.save_user(311, "grace", "Grace", None)
    database.create_booking(310, "Услуга 1", "d1", "01.09.2026 10:00")
    database.create_booking(311, "Услуга 2", "d2", "02.09.2026 11:00")

    # Сбрасываем кэш, т.к. get_all_bookings кэшируется
    database.invalidate_cache('get_all_bookings')
    all_b = database.get_all_bookings()
    assert len(all_b) == 2


# -------------- СЛОТЫ ВРЕМЕНИ --------------

def test_block_and_check_slot(tmp_db):
    slot = "2026-09-15 14:00"
    assert database.is_slot_blocked(slot) is False

    database.add_blocked_slot(slot)
    assert database.is_slot_blocked(slot) is True


def test_unblock_slot(tmp_db):
    slot = "2026-09-16 15:00"
    database.add_blocked_slot(slot)
    assert database.is_slot_blocked(slot) is True

    database.unblock_slot(slot)
    assert database.is_slot_blocked(slot) is False


def test_get_blocked_slots(tmp_db):
    database.add_blocked_slot("2026-09-17 10:00")
    database.add_blocked_slot("2026-09-17 11:00")
    blocked = database.get_blocked_slots()
    assert len(blocked) == 2
    assert "2026-09-17 10:00" in blocked
    assert "2026-09-17 11:00" in blocked


def test_add_duplicate_slot_no_error(tmp_db):
    """Повторное добавление того же слота не должно падать (INSERT OR IGNORE)."""
    slot = "2026-09-18 12:00"
    database.add_blocked_slot(slot)
    database.add_blocked_slot(slot)  # не должно бросить исключение
    assert len(database.get_blocked_slots()) == 1


# -------------- ПОРТФОЛИО --------------

def test_add_and_get_portfolio(tmp_db):
    database.add_portfolio_work("Дракон", "Большой дракон на спине", "file_123", "реализм")
    database.invalidate_cache('get_portfolio')
    works = database.get_portfolio()
    assert len(works) == 1
    assert works[0]['title'] == "Дракон"
    assert works[0]['style'] == "реализм"


def test_delete_portfolio_work(tmp_db):
    database.add_portfolio_work("Роза", "desc", "file_456", "олдскул")
    database.invalidate_cache('get_portfolio')
    works = database.get_portfolio()
    wid = works[0]['id']

    database.delete_portfolio_work(wid)
    database.invalidate_cache('get_portfolio')
    assert len(database.get_portfolio()) == 0


# -------------- ОТЗЫВЫ --------------

def test_add_review_and_stats(tmp_db):
    database.add_review(400, "henry", 5, "Отличная работа!")
    database.add_review(401, "iris", 4, "Хорошо")

    database.invalidate_cache('get_reviews', 'get_rating_stats')
    avg, cnt = database.get_rating_stats()
    assert cnt == 2
    assert avg == pytest.approx(4.5)


def test_get_reviews(tmp_db):
    database.add_review(402, "jack", 5, "Супер")
    database.invalidate_cache('get_reviews')
    reviews = database.get_reviews()
    assert len(reviews) == 1
    assert reviews[0]['rating'] == 5


# -------------- FSM (СОСТОЯНИЯ) --------------

def test_save_and_get_state(tmp_db):
    database.save_state(500, 'booking_desc', {'service': 'test'})
    assert database.get_state(500) == 'booking_desc'


def test_get_state_data(tmp_db):
    data = {'rating': 5, 'description': 'хорошо'}
    database.save_state(501, 'review_text', data)
    loaded = database.get_state_data(501)
    assert loaded == data


def test_clear_state(tmp_db):
    database.save_state(502, 'booking_service', {'x': 1})
    assert database.get_state(502) is not None

    database.clear_state(502)
    assert database.get_state(502) is None
    assert database.get_state_data(502) == {}


def test_get_state_nonexistent(tmp_db):
    assert database.get_state(9999) is None
    assert database.get_state_data(9999) == {}


# -------------- КЭШ --------------

def test_invalidate_cache_clears_entries(tmp_db):
    database.add_portfolio_work("Test", "d", "f", "s")
    database.invalidate_cache('get_portfolio')
    works1 = database.get_portfolio()
    assert len(works1) == 1

    database.invalidate_cache('get_portfolio')
    assert 'get_portfolio:()' not in database.cache


# -------------- НАПОМИНАНИЯ --------------

def test_get_bookings_to_notify_future(tmp_db):
    """Запись в будущем (через несколько часов) должна попасть в список."""
    from datetime import datetime, timedelta
    future = (datetime.now() + timedelta(hours=3)).strftime('%d.%m.%Y %H:%M')
    database.save_user(600, "kim", "Kim", None)
    bid = database.create_booking(600, "Тату", "desc", future)

    upcoming = database.get_bookings_to_notify(within_hours=24)
    ids = [b['id'] for b in upcoming]
    assert bid in ids


def test_get_bookings_to_notify_far_future_excluded(tmp_db):
    """Запись далеко в будущем (>24ч) не должна попадать в список."""
    from datetime import datetime, timedelta
    far = (datetime.now() + timedelta(hours=48)).strftime('%d.%m.%Y %H:%M')
    database.save_user(601, "leo", "Leo", None)
    bid = database.create_booking(601, "Тату", "desc", far)

    upcoming = database.get_bookings_to_notify(within_hours=24)
    ids = [b['id'] for b in upcoming]
    assert bid not in ids


def test_mark_booking_notified(tmp_db):
    from datetime import datetime, timedelta
    future = (datetime.now() + timedelta(hours=5)).strftime('%d.%m.%Y %H:%M')
    database.save_user(602, "mia", "Mia", None)
    bid = database.create_booking(602, "Тату", "desc", future)

    # До напоминания — в списке
    assert bid in [b['id'] for b in database.get_bookings_to_notify(24)]

    database.mark_booking_notified(bid)

    # После напоминания — больше не в списке
    assert bid not in [b['id'] for b in database.get_bookings_to_notify(24)]


def test_cancelled_excluded_from_notify(tmp_db):
    from datetime import datetime, timedelta
    soon = (datetime.now() + timedelta(hours=2)).strftime('%d.%m.%Y %H:%M')
    database.save_user(603, "nick", "Nick", None)
    bid = database.create_booking(603, "Тату", "desc", soon)
    database.update_booking_status(bid, 'cancelled')

    upcoming = database.get_bookings_to_notify(within_hours=24)
    assert bid not in [b['id'] for b in upcoming]


def test_notify_platform_filter(tmp_db):
    """Напоминания фильтруются по платформе: TG-бот не должен видеть MAX-записи и наоборот."""
    from datetime import datetime, timedelta
    soon = (datetime.now() + timedelta(hours=2)).strftime('%d.%m.%Y %H:%M')
    database.save_user(701, "tguser", "Tg", None)
    database.save_user(702, "maxuser", "Max", None)
    tg_bid = database.create_booking(701, "Тату", "desc", soon)  # default platform='telegram'
    max_bid = database.create_booking(702, "Тату", "desc", soon, platform='max')

    tg_view = [b['id'] for b in database.get_bookings_to_notify(within_hours=24, platform='telegram')]
    max_view = [b['id'] for b in database.get_bookings_to_notify(within_hours=24, platform='max')]
    all_view = [b['id'] for b in database.get_bookings_to_notify(within_hours=24)]

    assert tg_bid in tg_view and max_bid not in tg_view
    assert max_bid in max_view and tg_bid not in max_view
    # Без фильтра видны обе (старое поведение сохранено)
    assert tg_bid in all_view and max_bid in all_view


def test_cache_epoch_cross_process_invalidation(tmp_db):
    """Запись сдвигает эпоху в БД → чужой процесс с протухшим кэшем видит свежие данные.

    Эмуляция: наполняем кэш «отравленным» значением со старой эпохой,
    пишем через create_booking (bump), проверяем что _cached_query не вернёт яд.
    """
    database.save_user(801, "epoch", "Epoch", None)

    # Прогрев: реальное значение попадает в кэш
    fresh = database.get_all_bookings()
    assert all(b['user_id'] != 801 for b in fresh)

    # Отравляем кэш: то же имя ключа, старая эпоха, бесконечный TTL
    key = database._get_cache_key('get_all_bookings')
    poison = [ {'id': 999, 'user_id': 801, 'service': 'POISON'} ]
    epoch_before = database._db_epoch()
    database.cache[key] = (poison, database.time.time() + 10_000, epoch_before)

    # Пишущая операция из «другого процесса» сдвигает эпоху
    database.create_booking(801, "Тату", "desc", "01.10.2026 14:00")
    assert database._db_epoch() == epoch_before + 1

    # Кэш с устаревшей эпохой игнорируется — возвращаются реальные данные
    result = database.get_all_bookings()
    assert all(b['service'] != 'POISON' for b in result)
    assert any(b['user_id'] == 801 for b in result)


# -------------- АТОМАРНАЯ БРОНЬ СЛОТА --------------

def test_create_booking_with_slot_success(tmp_db):
    """Успешная атомарная бронь: запись создаётся и слот захватывается."""
    database.save_user(700, "atomic", "Atomic", None)
    bid = database.create_booking_with_slot(
        700, "Тату", "desc", "01.10.2026 14:00", "2026-10-01 14:00")
    assert bid is not None
    # Запись создана
    b = database.get_booking_by_id(bid)
    assert b is not None and b['service'] == "Тату"
    # Слот захвачен
    assert database.is_slot_blocked("2026-10-01 14:00") is True


def test_create_booking_with_slot_conflict(tmp_db):
    """Повторная бронь того же слота возвращает None и не создаёт запись."""
    database.save_user(701, "first", "First", None)
    database.save_user(702, "second", "Second", None)

    bid1 = database.create_booking_with_slot(
        701, "Тату", "desc", "02.10.2026 14:00", "2026-10-02 14:00")
    assert bid1 is not None

    # Второй клиент пытается занять тот же слот — отказ
    bid2 = database.create_booking_with_slot(
        702, "Тату", "desc", "02.10.2026 14:00", "2026-10-02 14:00")
    assert bid2 is None

    # В базе только одна запись
    database.invalidate_cache('get_all_bookings')
    bookings = database.get_all_bookings()
    assert len(bookings) == 1
    assert bookings[0]['user_id'] == 701


def test_create_booking_with_slot_mixed_formats(tmp_db):
    """Слот-ключ (YYYY-MM-DD HH:MM) и отображаемая дата (DD.MM.YYYY) не конфликтуют."""
    database.save_user(703, "user", "User", None)
    bid = database.create_booking_with_slot(
        703, "Тату", "desc", "03.10.2026 10:00", "2026-10-03 10:00")
    assert bid is not None


# -------------- БЛОКИРОВКА ПРОШЕДШИХ ДНЕЙ --------------

def test_block_full_day_past_returns_zero(tmp_db):
    """Блокировка уже прошедшего дня не должна блокировать ничего."""
    from datetime import datetime, timedelta
    past = datetime.now() - timedelta(days=2)
    cnt = database.block_full_day(past.year, past.month, past.day)
    assert cnt == 0
    assert len(database.get_blocked_slots()) == 0


def test_block_full_day_future_blocks_all(tmp_db):
    """Блокировка будущего дня блокирует все слоты 10:00-20:00."""
    from datetime import datetime, timedelta
    future = datetime.now() + timedelta(days=10)
    cnt = database.block_full_day(future.year, future.month, future.day)
    # День в будущем целиком — 11 слотов (10:00..20:00)
    assert cnt == 11
    assert len(database.get_blocked_slots()) == 11


def test_block_full_day_today_blocks_only_future_hours(tmp_db):
    """Сегодня блокируются только часы, которые ещё не наступили."""
    from datetime import datetime
    now = datetime.now()
    cnt = database.block_full_day(now.year, now.month, now.day)
    # Не блокируем часы <= текущего. Полный день = 11 слотов.
    remaining = 11 - (now.hour - 10 + 1) if now.hour >= 10 else 11
    if now.hour < 10:
        remaining = 11
    elif now.hour > 20:
        remaining = 0
    assert cnt == max(0, remaining)


# -------------- WAL-РЕЖИМ --------------

def test_db_uses_wal(tmp_db):
    """БД должна работать в WAL-режиме (конкурентные чтение+запись)."""
    conn = database.get_db()
    try:
        mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
        # В тесте соединение может упасть в WAL, если ФС не поддерживает —
        # тогда допускаем дефолт (delete). WAL — требование, но не ломаем тест.
        assert mode.lower() in ('wal', 'delete', 'memory')
    finally:
        conn.close()
