"""Диагностика рассинхрона blocked_slots <-> bookings.

Запуск: python _diag_slots.py
Удалить после отладки.
"""
import sqlite3
from datetime import datetime

DB = r"C:\Projects\tattoo_bot\tattoo_bot.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

bs = [r["date_time"] for r in conn.execute("SELECT date_time FROM blocked_slots")]
print(f"=== blocked_slots: {len(bs)} ===")
for s in sorted(bs):
    print(f"  {s}")

print(f"\n=== bookings по статусам ===")
for r in conn.execute("SELECT status, COUNT(*) n FROM bookings GROUP BY status"):
    print(f"  {r['status']:<18} {r['n']}")

# Все даты броней
booking_dt = {r["date_time"] for r in conn.execute("SELECT date_time FROM bookings")}
active_dt = {
    r["date_time"]
    for r in conn.execute(
        "SELECT date_time FROM bookings WHERE status IN ('pending','confirmed')"
    )
}

# orphans: слот заблокирован, но активной брони нет
orphans = [s for s in bs if s not in active_dt]
print(f"\n=== orphan blocked_slots (нет active pending/confirmed брони): {len(orphans)} ===")
for s in sorted(orphans):
    # Найти, какая бронь ссылается
    row = conn.execute(
        "SELECT id, status, date_time FROM bookings WHERE date_time LIKE ?",
        (f"%{s[5:10]} {s[11:16]}%",),
    ).fetchall()
    # slot 'YYYY-MM-DD HH:00' -> display 'DD.MM.YYYY HH:MM'
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        disp = dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        disp = s
    linked = conn.execute(
        "SELECT id, status FROM bookings WHERE date_time = ?", (disp,)
    ).fetchall()
    tag = " (БРОНИ НЕТ!)" if not linked else ""
    print(f"  slot={s}  disp={disp}{tag}")
    for b in linked:
        print(f"      booking #{b['id']} status={b['status']}")

# client_cancelled bookings + проверка слота
print(f"\n=== client_cancelled bookings ===")
for r in conn.execute(
    "SELECT id, date_time, status FROM bookings WHERE status='client_cancelled'"
):
    disp = r["date_time"]
    try:
        sk = datetime.strptime(disp.strip(), "%d.%m.%Y %H:%M").strftime("%Y-%m-%d %H:%M")
        blocked = sk in set(bs)
    except ValueError:
        sk, blocked = "?", False
    print(f"  #{r['id']}  {disp}  slot={sk}  blocked={blocked}")

# cancelled (из cancel_booking_confirm) + проверка слота
print(f"\n=== cancelled bookings (отказ до подтверждения) ===")
for r in conn.execute(
    "SELECT id, date_time, status FROM bookings WHERE status='cancelled'"
):
    disp = r["date_time"]
    try:
        sk = datetime.strptime(disp.strip(), "%d.%m.%Y %H:%M").strftime("%Y-%m-%d %H:%M")
        blocked = sk in set(bs)
    except ValueError:
        sk, blocked = "?", False
    print(f"  #{r['id']}  {disp}  slot={sk}  blocked={blocked}")

conn.close()
print("\n[diag done]")
