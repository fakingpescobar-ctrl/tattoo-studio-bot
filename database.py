import json
import sqlite3
from datetime import datetime, timedelta
import time


from config import DB_PATH


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL: конкурентные чтение+запись (боты TG/MAX пишут из разных процессов)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA foreign_keys=ON')
    except sqlite3.Error:
        pass  # WAL может быть недоступен на сетевых ФС — работаем в дефолтном режиме
    return conn

def init_db():
    """Инициализация базы данных"""
    conn = get_db()
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            phone TEXT
        )
    ''')

    # Таблица записей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service TEXT,
            description TEXT,
            date_time TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Таблица услуг
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            price_min REAL,
            price_max REAL,
            duration INTEGER
        )
    ''')

    # Таблица работ портфолио (file_id - Telegram file_id для фото)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            file_id TEXT,
            style TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица отзывов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            rating INTEGER,
            text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица занятых слотов (чтобы мастер мог блокировать даты/время)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocked_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_time TEXT UNIQUE
        )
    ''')

    # Таблица состояний пользователей (FSM)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_states (
            user_id INTEGER PRIMARY KEY,
            state TEXT,
            data TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Миграции: добавляем колонку notified_24h в bookings, если её ещё нет
    # (для системы напоминаний о записях)
    try:
        cursor.execute('ALTER TABLE bookings ADD COLUMN notified_24h INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # колонка уже существует

    # ponytail: TTL-чистка зависших FSM-состояний старше 7 дней.
    # Потенциальный потолок: при <7-дневной сессии состояние чистится раньше срока.
    # Пользователь просто начнёт заново — допустимо для бота записи.
    cursor.execute(
        "DELETE FROM user_states "
        "WHERE updated_at < datetime('now', '-7 days')"
    )

    conn.commit()
    conn.close()
    print("База данных успешно инициализирована!")

def add_sample_data():
    """Добавление примеров данных"""
    conn = get_db()
    cursor = conn.cursor()

    # Проверяем, есть ли уже услуги
    cursor.execute('SELECT COUNT(*) FROM services')
    if cursor.fetchone()[0] == 0:
        services = [
            ("Миниатюры до 15 см", "Небольшие татуировки", 1500, 1500, 0),
            ("Тату от 20 см", "Средние и большие работы", 4000, 7000, 0),
            ("Перекрытие шрамов", "Перекрытие шрамов, эскиз, подарок", 7000, 7000, 0),
            ("Старые тату и реставрации", "Цена зависит от сложности работы", 0, 0, 0),
        ]
        cursor.executemany('''
            INSERT INTO services (name, description, price_min, price_max, duration)
            VALUES (?, ?, ?, ?, ?)
        ''', services)
        conn.commit()
        print("Примеры услуг добавлены!")

    conn.close()

# Кэш для часто запрашиваемых данных
cache = {}
CACHE_TTL = 300  # 5 минут

def _get_cache_key(func_name, *args):
    return f"{func_name}:{args}"

def invalidate_cache(*keys):
    for k in list(cache):
        if k.split(':')[0] in keys:
            cache.pop(k, None)

def _is_cache_valid(timestamp, ttl=CACHE_TTL):
    return time.time() - timestamp < ttl

def _cached_query(query_func, key, *args, ttl=CACHE_TTL):
    if key in cache:
        result, ts = cache[key]
        if _is_cache_valid(ts, ttl):
            return result
    result = query_func(*args)
    cache[key] = (result, time.time())
    return result

# ============ ПОЛЬЗОВАТЕЛИ ============

def save_user(user_id, username, first_name, last_name, phone=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (id, username, first_name, last_name, phone)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username or '', first_name or '', last_name or '', phone))
    if cursor.rowcount == 0:
        cursor.execute('''
            UPDATE users SET username=?, first_name=?, last_name=?, phone=?
            WHERE id=?
        ''', (username or '', first_name or '', last_name or '', phone, user_id))
    conn.commit()
    conn.close()

# ============ УСЛУГИ ============

def get_services():
    return _cached_query(
        lambda: [dict(row) for row in get_db().execute('SELECT * FROM services ORDER BY id').fetchall()],
        _get_cache_key('get_services')
    )

# ============ ПОРТФОЛИО ============

def get_portfolio():
    return _cached_query(
        lambda: [dict(row) for row in get_db().execute('SELECT * FROM portfolio ORDER BY id DESC').fetchall()],
        _get_cache_key('get_portfolio')
    )

def add_portfolio_work(title, description, file_id, style):
    conn = get_db()
    conn.execute('''
        INSERT INTO portfolio (title, description, file_id, style)
        VALUES (?, ?, ?, ?)
    ''', (title, description, file_id, style))
    conn.commit()
    invalidate_cache('get_portfolio')
    conn.close()

def delete_portfolio_work(work_id):
    conn = get_db()
    conn.execute('DELETE FROM portfolio WHERE id = ?', (work_id,))
    conn.commit()
    conn.close()
    invalidate_cache('get_portfolio')

# ============ ЗАПИСИ ============

def create_booking(user_id, service, description, date_time, status='pending'):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO bookings (user_id, service, description, date_time, status)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, service, description, date_time, status))
    conn.commit()
    booking_id = cursor.lastrowid
    conn.close()
    invalidate_cache('get_all_bookings')
    return booking_id

def create_booking_with_slot(user_id, service, description, date_time, slot_key):
    """Атомарная бронь: запись + захват слота в одной транзакции.

    Защита от гонки: если TG и MAX одновременно бронируют один слот,
    UNIQUE-индекс blocked_slots.date_time пропустит только один INSERT.
    Возвращает booking_id при успехе, None — если слот уже занят.
    """
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        # Захват слота. INSERT (не OR IGNORE!) — конфликт UNIQUE = слот занят
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO blocked_slots (date_time) VALUES (?)', (slot_key,))
        cursor.execute('''
            INSERT INTO bookings (user_id, service, description, date_time)
            VALUES (?, ?, ?, ?)
        ''', (user_id, service, description, date_time))
        booking_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    invalidate_cache('get_all_bookings')
    return booking_id

def get_user_bookings(user_id):
    return _cached_query(
        lambda uid=user_id: get_db().execute(
            'SELECT * FROM bookings WHERE user_id = ? ORDER BY date_time DESC',
            (uid,)
        ).fetchall(),
        _get_cache_key('get_user_bookings', user_id),
        ttl=60
    )

def get_all_bookings():
    return _cached_query(
        lambda: get_db().execute('''
            SELECT b.*, u.username, u.first_name
            FROM bookings b
            LEFT JOIN users u ON b.user_id = u.id
            ORDER BY b.created_at DESC
        ''').fetchall(),
        _get_cache_key('get_all_bookings'),
        ttl=10
    )

def update_booking_status(booking_id, status):
    conn = get_db()
    conn.execute('UPDATE bookings SET status = ? WHERE id = ?', (status, booking_id))
    conn.commit()
    conn.close()
    invalidate_cache('get_all_bookings', 'get_user_bookings')

def delete_booking(booking_id):
    """Полностью удаляет запись из БД.
    После удаления прижимает счётчик AUTOINCREMENT к MAX(id),
    чтобы следующая запись получила следующий по порядку номер
    (без 'дыр' вроде #7 при пустой таблице)."""
    conn = get_db()
    conn.execute('DELETE FROM bookings WHERE id = ?', (booking_id,))
    # Прижимаем sqlite_sequence к реальному максимуму
    max_id = conn.execute('SELECT COALESCE(MAX(id), 0) FROM bookings').fetchone()[0]
    conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'bookings'", (max_id,))
    conn.commit()
    conn.close()
    invalidate_cache('get_all_bookings', 'get_user_bookings')

def get_booking_by_id(booking_id):
    conn = get_db()
    row = conn.execute(
        '''SELECT b.*, u.username, u.first_name
           FROM bookings b
           LEFT JOIN users u ON b.user_id = u.id
           WHERE b.id = ?''', (booking_id,)
    ).fetchone()
    conn.close()
    return row

def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return row

# ============ СЛОТЫ ВРЕМЕНИ ============

def get_blocked_slots():
    conn = get_db()
    rows = conn.execute('SELECT date_time FROM blocked_slots').fetchall()
    conn.close()
    return [r['date_time'] for r in rows]

def add_blocked_slot(date_time):
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('INSERT OR IGNORE INTO blocked_slots (date_time) VALUES (?)', (date_time,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def block_full_day(year, month, day):
    """Блокировка всего рабочего дня (10:00-20:00).

    Возвращает количество заблокированных слотов. Прошедшие даты/часы
    не блокируются (нельзя заблокировать прошлое).
    """
    conn = get_db()
    now = datetime.now()
    blocked_count = 0
    for hour in range(10, 21):
        dt = datetime(year, month, day, hour, 0)
        if dt <= now:
            continue  # прошедший час — не блокируем
        slot = f"{year}-{month:02d}-{day:02d} {hour:02d}:00"
        cursor = conn.execute('INSERT OR IGNORE INTO blocked_slots (date_time) VALUES (?)', (slot,))
        blocked_count += cursor.rowcount
    conn.commit()
    conn.close()
    return blocked_count

def unblock_slot(date_time):
    conn = get_db()
    conn.execute('DELETE FROM blocked_slots WHERE date_time = ?', (date_time,))
    conn.commit()
    conn.close()

def is_slot_blocked(date_time):
    conn = get_db()
    row = conn.execute('SELECT 1 FROM blocked_slots WHERE date_time = ?', (date_time,)).fetchone()
    conn.close()
    return row is not None

# ============ ОТЗЫВЫ ============

def add_review(user_id, username, rating, text):
    conn = get_db()
    conn.execute('''
        INSERT INTO reviews (user_id, username, rating, text)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username or '', rating, text))
    conn.commit()
    conn.close()
    invalidate_cache('get_reviews', 'get_rating_stats')

def get_reviews(limit=20):
    return _cached_query(
        lambda l=limit: get_db().execute(
            'SELECT * FROM reviews ORDER BY created_at DESC LIMIT ?', (l,)
        ).fetchall(),
        _get_cache_key('get_reviews', limit),
        ttl=10
    )

def get_rating_stats():
    row = _cached_query(
        lambda: get_db().execute(
            'SELECT AVG(rating) as avg, COUNT(*) as cnt FROM reviews'
        ).fetchone(),
        _get_cache_key('get_rating_stats'),
        ttl=10
    )
    return (row['avg'] or 0, row['cnt'] or 0)


# ============ FSM ============

def save_state(user_id, state, data=None):
    conn = get_db()
    conn.execute('''
        INSERT OR REPLACE INTO user_states (user_id, state, data)
        VALUES (?, ?, ?)
    ''', (user_id, state, json.dumps(data or {})))
    conn.commit()
    conn.close()

def get_state(user_id):
    """Возвращает только строку состояния (или None)"""
    conn = get_db()
    row = conn.execute('SELECT state, data FROM user_states WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    if row:
        return row['state']
    return None

def get_state_data(user_id):
    """Возвращает данные состояния (dict)"""
    conn = get_db()
    row = conn.execute('SELECT data FROM user_states WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()
    if row:
        return json.loads(row['data'] or '{}')
    return {}

def clear_state(user_id):
    conn = get_db()
    conn.execute('DELETE FROM user_states WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# ============ НАПОМИНАНИЯ ============

def get_bookings_to_notify(within_hours=24):
    """Возвращает активные записи (pending/confirmed), до сеанса которых осталось
    не более `within_hours` часов и которые ещё не получили напоминание (notified_24h=0).
    Формат date_time в БД: 'DD.MM.YYYY HH:MM'."""
    from datetime import datetime as _dt, timedelta as _td
    conn = get_db()
    rows = conn.execute(
        '''SELECT b.*, u.username, u.first_name
           FROM bookings b
           LEFT JOIN users u ON b.user_id = u.id
           WHERE b.status IN ('pending', 'confirmed')
             AND b.notified_24h = 0'''
    ).fetchall()
    conn.close()

    now = _dt.now()
    result = []
    for r in rows:
        try:
            dt = _dt.strptime(r['date_time'].strip(), '%d.%m.%Y %H:%M')
        except (ValueError, TypeError, AttributeError):
            continue
        delta = dt - now
        # 0 <= осталось <= within_hours часов (в будущем, скоро сеанс)
        if _td(0) <= delta <= _td(hours=within_hours):
            result.append(r)
    return result


def mark_booking_notified(booking_id):
    """Помечает запись как получившую напоминание (чтобы не дублировать)."""
    conn = get_db()
    conn.execute('UPDATE bookings SET notified_24h = 1 WHERE id = ?', (booking_id,))
    conn.commit()
    conn.close()


def get_today_bookings():
    """Возвращает записи на сегодня (для сводки админу)."""
    from datetime import datetime as _dt
    conn = get_db()
    rows = conn.execute(
        '''SELECT b.*, u.username, u.first_name
           FROM bookings b
           LEFT JOIN users u ON b.user_id = u.id
           WHERE b.status IN ('pending', 'confirmed')'''
    ).fetchall()
    conn.close()
    today = _dt.now().strftime('%d.%m.%Y')
    return [r for r in rows
            if r['date_time'] and r['date_time'].strip().startswith(today)]