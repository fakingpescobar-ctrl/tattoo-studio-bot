# -*- coding: utf-8 -*-
"""Разовая чистка мёртвых слот-блоков + верификация фикса delete/cancel."""
import sqlite3

from database import _CANCELLED_STATUSES

c = sqlite3.connect('tattoo_bot.db')
c.row_factory = sqlite3.Row

# Активные брони -> их слоты должны остаться в blocked_slots
active = {r['slot'] for r in c.execute(
    "SELECT date_time AS raw FROM bookings WHERE status IN ('pending','confirmed')"
) for r in [{'slot': None}]}  # placeholder, считаем ниже честно
active_slots = set()
for r in c.execute("SELECT date_time FROM bookings WHERE status IN ('pending','confirmed')"):
    dt = r['date_time'].strip()
    d, t = dt.split(' ')
    dd, mm, yyyy = d.split('.')
    active_slots.add(f"{yyyy}-{mm}-{dd} {t}")

print('active booking slots:', sorted(active_slots))

dead = [r['date_time'] for r in c.execute('SELECT date_time FROM blocked_slots')
        if r['date_time'] not in active_slots]
print('dead blocks to purge:', dead)
for s in dead:
    c.execute('DELETE FROM blocked_slots WHERE date_time = ?', (s,))
c.commit()

print('\nblocked_slots after purge:')
for r in c.execute('SELECT * FROM blocked_slots ORDER BY date_time'):
    print(' ', dict(r))
c.close()
