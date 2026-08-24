"""Одноразовая диагностика: ловим первые апдейты MAX-бота и печатаем user_id.

Запуск: python _diag_max_updates.py
Использование: отправь боту /start в MAX — скрипт поймает событие и покажет
твой user_id для .env (MAX_ADMIN_ID).
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from max_client import MaxClient  # noqa: E402

ATTEMPTS = 3
TYPES = "message_created,message_callback,bot_started"

c = MaxClient()
marker = None
for attempt in range(1, ATTEMPTS + 1):
    print(f"poll #{attempt}/{ATTEMPTS} ...")
    updates, marker = c.poll_once(marker=marker, types=TYPES)
    if not updates:
        continue
    for u in updates:
        usr = u.get("user") or {}
        uid = usr.get("user_id")
        fname = usr.get("first_name", "")
        lname = usr.get("last_name", "")
        uname = usr.get("username")
        print(f"type={u.get('update_type')} | user_id={uid} | "
              f"name={fname} {lname} | username={uname}")
    break
else:
    print("EMPTY: никто не написал за 3 опроса. Отправь боту /start и запусти снова.")
