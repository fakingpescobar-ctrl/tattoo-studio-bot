"""Разовая операция: сброс счётчика AUTOINCREMENT для bookings.

Если все записи удалены — следующая получит #1.
Если есть записи — следующая получит max(id)+1.

Важно: это не предотвращает будущие «дыры» в нумерации при delete_booking().
Чтобы гарантировать плотную нумерацию, нужно либо:
  - отказаться от AUTOINCREMENT, либо
  - заменить физическое удаление на soft-delete (status='cancelled').
"""
import sqlite3

conn = sqlite3.connect('tattoo_bot.db')
max_id = conn.execute('SELECT COALESCE(MAX(id), 0) FROM bookings').fetchone()[0]
before = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='bookings'").fetchone()
print(f"Текущий max(id) в bookings: {max_id}")
print(f"Счётчик ДО сброса: {before[0] if before else 'нет записи'}")

conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'bookings'", (max_id,))
conn.commit()

after = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='bookings'").fetchone()
print(f"Счётчик ПОСЛЕ сброса: {after[0] if after else 'нет записи'}")
print(f"Следующая запись получит номер: {(after[0] if after else 0) + 1}")
conn.close()
