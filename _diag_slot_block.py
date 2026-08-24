# -*- coding: utf-8 -*-
"""Диаг: почему слоты 26.08.2026 выглядят занятыми."""
import sqlite3

c = sqlite3.connect('tattoo_bot.db')
c.row_factory = sqlite3.Row

print('=== bookings schema ===')
print([r['name'] for r in c.execute("PRAGMA table_info(bookings)")])

print('\n=== ALL bookings ===')
for r in c.execute('SELECT * FROM bookings ORDER BY id'):
    print(dict(r))

print('\n=== blocked_slots (all rows) ===')
for r in c.execute('SELECT * FROM blocked_slots'):
    print(dict(r))
