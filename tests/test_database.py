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
