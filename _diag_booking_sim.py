# -*- coding: utf-8 -*-
"""Оффлайн-симуляция флоу записи MAX-бота (без сети и реального API).

Проверяет фикс бага «выкидывает в меню после ввода описания»:
  1) колбэк выбора услуги приходит с user_id=int,
  2) текстовое сообщение — с user_id=str (MAX отдаёт типы по-разному).

Старый код терял состояние (str != int в user_states) -> fallback в меню.
Новый код нормализует id на границе -> календарь уходит.

Также проверяет мост фото портфолио TG file_id -> MAX payload (upload_media
замокан, файл-заглушка вместо скачивания).
"""
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# --- временная БД до импортов database ---
fd, db_path = tempfile.mkstemp(suffix='.db')
os.close(fd)
import database  # noqa: E402

def _connect():
    c = sqlite3.connect(db_path, timeout=30)
    c.row_factory = sqlite3.Row
    return c

database.DB_PATH = db_path
database.get_db = _connect   # ВАЖНО: до init_db, иначе сид уйдёт в реальную БД
database.init_db()
database.add_sample_data()   # сеидит 4 услуги (init_db только схему)

from max_handlers import MaxBot, _as_int, _MAX_IMG_MEMO  # noqa: E402
import max_handlers  # noqa: E402


class FakeClient:
    """Записывает отправки; upload_media отдаёт фейковый токен."""
    def __init__(self):
        self.sent = []       # (kind, target, text_or_none, attachments)
        self.uploads = []

    def callback_reply(self, callback_id, text=None, attachments=None, fmt='html'):
        self.sent.append(('callback', callback_id, text, attachments))

    def send_message(self, user_id, text=None, attachments=None, fmt='html', notify=True):
        self.sent.append(('message', user_id, text, attachments))

    def answer_callback(self, callback_id, message=None):
        self.sent.append(('answer', callback_id, None, message))

    def upload_media(self, file_path, media_type='image'):
        self.uploads.append(str(file_path))
        return 'MAXTOKEN_simulated_1'


def has_calendar(atts):
    return any(a.get('type') == 'inline_keyboard' for a in (atts or []))


def last_menu_fallback(client):
    return any('кнопки меню' in (s[2] or '') for s in client.sent)


def main():
    ok = True

    # --- sanity: _as_int ---
    assert _as_int(123) == 123 and _as_int('456') == 456 and _as_int(None) is None
    assert _as_int('garbage') is None
    print('[OK] _as_int normalization')

    # --- сервис для брони (init_db сеидит «Миниатюры до 15 см» как id=1) ---
    svc = database.get_services()[0]
    assert 'Миниатюры' in svc['name'], f"unexpected seeded service: {svc['name']}"
    sid = svc['id']

    bot = MaxBot(FakeClient())

    UID = 999001

    def cb_update(callback_id, payload, uid=UID):
        """Реальная структура message_callback из дампа MAX (02:15 лог):
        user лежит ВНУТРИ callback, наверху его нет."""
        return {'update_type': 'message_callback',
                'callback': {'callback_id': callback_id, 'payload': payload,
                             'user': {'user_id': uid, 'first_name': 'Sim'}},
                'message': {'recipient': {'chat_id': 363473516, 'chat_type': 'dialog',
                                          'user_id': uid},
                            'sender': {'user_id': uid}}}

    # --- шаги: старт -> выбор услуги (колбэк, uid только внутри callback) ---
    bot.handle_update(cb_update('c0', 'booking_start'))

    bot.handle_update(cb_update('c1', f'service_{sid}'))
    assert database.get_state(UID) == 'booking_desc', \
        f"state after service select: {database.get_state(UID)!r}"
    print('[OK] service select saved booking_desc')

    # --- описание приходит как СТРОКА (сценарий бага) ---
    client = bot.client
    msg_desc = {'update_type': 'message_created',
                'user': {'user_id': str(UID)},   # <-- str!
                'message': {'sender': {'user_id': str(UID), 'username': 'sim'},
                            'body': {'text': 'череп на плече, 10 см'}}}
    bot.handle_update(msg_desc)

    assert not last_menu_fallback(client), 'FAIL: fell back to menu (bug reproduced)'
    assert database.get_state(UID) == 'booking_date', \
        f"state after description: {database.get_state(UID)!r}"
    cal = [s for s in client.sent if s[0] == 'message' and has_calendar(s[3])]
    assert cal, 'FAIL: no calendar keyboard sent'
    print('[OK] str user_id normalized -> calendar sent instead of menu')

    # --- выбор дня и слота из календаря -> подтверждение -> создание брони ---
    from datetime import datetime, timedelta
    future = datetime.now() + timedelta(days=7)
    y, mo, d = future.year, future.month, future.day
    h = 18 if future.hour < 18 else 12
    cb_day = cb_update('c2a', f'cal_day_{y}_{mo}_{d}')
    bot.handle_update(cb_day)
    assert database.get_state(UID) == 'booking_date', \
        f"state after cal_day: {database.get_state(UID)!r}"

    bot.handle_update(cb_update('c2', f'cal_time_{y}_{mo}_{d}_{h:02d}'))
    assert database.get_state(UID) == 'booking_confirm', \
        f"state after slot: {database.get_state(UID)!r}"

    bot.handle_update(cb_update('c3', 'booking_confirm'))
    bk = [b for b in database.get_user_bookings(UID) if b['platform'] == 'max']
    assert bk and bk[-1]['service'] == svc['name'], \
        f"booking row missing: {bk}"
    print(f"[OK] booking created via sim: #{bk[-1]['id']} {bk[-1]['date_time']}")

    # --- мост фото портфолио: TG file_id (не JSON) -> payload с токеном ---
    tg_fid = 'AgACAgIAAx0CApi4simulated_file_id'
    real_fetch = max_handlers.fetch_tg_file
    fake_img = Path(db_path + '.fake.jpg')
    fake_img.write_bytes(b'\xff\xd8\xff\xe0FAKEJPEG')
    max_handlers.fetch_tg_file = lambda fid: fake_img
    try:
        database.add_portfolio_work('Sim Work', 'desc', tg_fid, 'графика')
        bot.client = FakeClient()
        bot.handle_update(cb_update('c4', 'port_0'))
        atts = bot.client.sent[-1][3]
        img = next((a for a in atts if a.get('type') == 'image'), None)
        assert img and img['payload'].get('token') == 'MAXTOKEN_simulated_1', \
            f'image payload wrong: {img}'
        assert bot.client.uploads, 'upload_media was not called'
        # повторный показ — из мемо, без нового аплоада
        n_up = len(bot.client.uploads)
        bot.handle_update(cb_update('c5', 'port_0'))
        assert len(bot.client.uploads) == n_up, 'memo failed: re-uploaded'
        print('[OK] TG file_id bridged to MAX image payload + memoized')
    finally:
        max_handlers.fetch_tg_file = real_fetch
        fake_img.unlink(missing_ok=True)

    print('\nALL SIM CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
