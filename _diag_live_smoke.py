# -*- coding: utf-8 -*-
"""Живой smoke: полный календарь + мост фото на тестовый аккаунт Big Brother."""
import logging
logging.basicConfig(level=logging.ERROR)

from datetime import datetime

from max_client import MaxClient
from max_keyboards import get_calendar_keyboard

UID = 56219682  # Big Brother

c = MaxClient()

try:
    c.send_message(UID, 'тест: полный календарь',
                   attachments=get_calendar_keyboard(datetime.now().year, datetime.now().month))
    print('[OK] full calendar sent')
except Exception as e:
    print(f'[FAIL] calendar: {str(e)[:140]}')

import json as j
from database import get_portfolio
from media_bridge import fetch_tg_file

w = next((x for x in get_portfolio()
          if x['file_id'] and not x['file_id'].lstrip().startswith('{')), None)
if w:
    path = fetch_tg_file(w['file_id'])
    print('[OK] tg file cached:', bool(path))
    if path:
        try:
            tok = c.upload_media(str(path))
            c.send_message(UID, "тест фото: %s" % w['title'],
                           attachments=[{'type': 'image', 'payload': {'token': tok}}])
            print('[OK] image uploaded + sent, token len:', len(tok))
        except Exception as e:
            print(f'[FAIL] upload/send: {str(e)[:160]}')
else:
    print('no TG-file_id works found')
