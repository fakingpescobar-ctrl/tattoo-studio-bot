"""Мост медиа Telegram -> MAX.

TG-бот хранит фото портфолио как file_id Telegram. MAX API принимает только
свои токены/URL, поэтому перед отправкой в MAX файл скачивается из Telegram
на диск и дальше загружается через POST /uploads (MaxClient.upload_media).

Используется двумя процессами:
  - admin_api.py   (прокси фото в Electron-панель)
  - max_handlers.py (мост TG file_id -> MAX payload)

Дисковый кэш: _img_cache/<sha256[:16]>.jpg, атомарная запись через уникальный
.part-файл. Negative-cache: неудачные file_id не долбят TG API TTL_NEGATIVE
секунд.
"""
import hashlib
import logging
import os
import threading
import time
from pathlib import Path

import requests

from config import BOT_TOKEN

logger = logging.getLogger(__name__)

IMG_CACHE = Path(__file__).parent / '_img_cache'
TTL_NEGATIVE = 300.0  # сек — сколько помним, что file_id не качается

_negative: dict[str, float] = {}
_neg_lock = threading.Lock()


def _cached_path(file_id: str) -> Path:
    digest = hashlib.sha256(file_id.encode('utf-8')).hexdigest()[:16]
    return IMG_CACHE / f'{digest}.jpg'


def _is_recently_failed(file_id: str) -> bool:
    now = time.monotonic()
    with _neg_lock:
        failed_at = _negative.get(file_id)
        if failed_at is None:
            return False
        if now - failed_at < TTL_NEGATIVE:
            return True
        del _negative[file_id]  # TTL истёк — даём ещё попытку
        return False


def fetch_tg_file(file_id: str) -> Path | None:
    """Скачать фото из Telegram по file_id в дисковый кэш.

    Возвращает путь к локальному файлу или None при ошибке.
    Повторные вызовы отдают кэш; свежие неудачи гасятся negative-кэшем.
    """
    if not file_id or not BOT_TOKEN:
        return None

    cached = _cached_path(file_id)
    if cached.exists() and cached.stat().st_size > 0:
        return cached
    if _is_recently_failed(file_id):
        return None

    try:
        r = requests.get(
            f'https://api.telegram.org/bot{BOT_TOKEN}/getFile',
            params={'file_id': file_id}, timeout=15)
        r.raise_for_status()
        tg_path = (r.json() or {}).get('result', {}).get('file_path')
        if not tg_path:
            raise ValueError('getFile: пустой file_path')
        f = requests.get(
            f'https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_path}',
            timeout=60)
        f.raise_for_status()

        IMG_CACHE.mkdir(exist_ok=True)
        part = IMG_CACHE / f'.{cached.stem}.{os.getpid()}.{time.monotonic_ns()}.part'
        part.write_bytes(f.content)
        part.replace(cached)  # атомарно даже при параллельных читателях
        return cached
    except Exception as e:
        with _neg_lock:
            _negative[file_id] = time.monotonic()
        logger.warning(f"fetch_tg_file failed ({file_id[:24]}...): {e}")
        return None
