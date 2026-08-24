# -*- coding: utf-8 -*-
"""Верификация: delete_booking / update_booking_status освобождают слот."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

fd, db_path = tempfile.mkstemp(suffix='.db')
os.close(fd)
import database

def _connect():
    cc = sqlite3.connect(db_path, timeout=30)
    cc.row_factory = sqlite3.Row
    return cc

database.DB_PATH = db_path
database.get_db = _connect
database.init_db()
database.add_sample_data()

uid = 777001
bid1 = database.create_booking_with_slot(uid, 'Тест', '', '01.10.2026 15:00', '2026-10-01 15:00')
assert bid1, 'create #1 failed'
assert database.is_slot_blocked('2026-10-01 15:00'), 'slot not captured'

# Удаление -> слот освобождён
database.delete_booking(bid1)
assert not database.is_slot_blocked('2026-10-01 15:00'), 'FAIL: slot still blocked after delete'
bid2 = database.create_booking_with_slot(uid, 'Тест2', '', '01.10.2026 15:00', '2026-10-01 15:00')
assert bid2, 'FAIL: re-book same slot after delete failed'
print('[OK] delete releases slot; slot is bookable again')

# Отмена клиентом -> слот освобождён
database.update_booking_status(bid2, 'client_cancelled')
assert not database.is_slot_blocked('2026-10-01 15:00'), 'FAIL: slot blocked after cancel'
bid3 = database.create_booking_with_slot(999002, 'Другой', '', '01.10.2026 15:00', '2026-10-01 15:00')
assert bid3, 'FAIL: other client cannot book cancelled slot'
print('[OK] client_cancel releases slot; another user can take it')

# Возврат из отмены -> слот захвачен обратно (или честно занят другим)
database.update_booking_status(bid3, 'cancelled')          # мастер отменил #3 -> слот свободен
database.update_booking_status(bid2, 'pending')            # возврат #2 из отмены
assert database.is_slot_blocked('2026-10-01 15:00'), 'FAIL: re-activate did not capture slot'
print('[OK] un-cancel recaptures slot')

# Двойная бронь одного слота по-прежнему невозможна
dup = database.create_booking_with_slot(999003, 'Дубль', '', '01.10.2026 15:00', '2026-10-01 15:00')
assert dup is None, 'FAIL: double booking allowed'
print('[OK] double booking still rejected')

print('\nALL SLOT LIFECYCLE CHECKS PASSED')
