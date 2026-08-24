"""Одноразовая диагностика: дамп сырого JSON апдейтов MAX для отладки полей.

Запуск: python _diag_max_raw.py
Использование: отправь боту любое сообщение в MAX — скрипт напечатает полный
JSON апдейта (смотрим chat_id vs user_id vs sender).
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from max_client import MaxClient  # noqa: E402

ATTEMPTS = 6
TYPES = "message_created,message_callback,bot_started"

c = MaxClient()
marker = None
for attempt in range(1, ATTEMPTS + 1):
    print(f"poll #{attempt}/{ATTEMPTS} ...")
    updates, marker = c.poll_once(marker=marker, types=TYPES)
    for u in updates:
        print("=" * 60)
        print(json.dumps(u, ensure_ascii=False, indent=2))
    if updates:
        break
else:
    print("EMPTY: никто не написал за 6 опросов. Отправь боту сообщение и запусти снова.")
