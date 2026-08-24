"""
Тонкий клиент Bot API мессенджера MAX (VK).
Документация: https://dev.max.ru/docs-api
Домен: platform-api2.max.ru, авторизация — заголовок Authorization: <token>.
"""
import logging
import threading
import time
from pathlib import Path

import certifi
import requests

from config import MAX_TOKEN

API_BASE = "https://platform-api2.max.ru"

# Домен *.max.ru подписан цепочкой Минцифры (Russian Trusted Root CA), которой
# нет в бандле certifi — без расширения любой запрос падает с
# CERTIFICATE_VERIFY_FAILED. Корни лежат в certs/ и подмешиваются к certifi.
_CERTS_DIR = Path(__file__).parent / "certs"


def _ca_bundle_path():
    """CA-бандл для requests: certifi + все certs/*.pem.

    Возвращает путь к merged-бандлу (пересобирается при изменении исходников)
    или True, если в certs/ нет дополнительных корней.
    """
    extra = sorted(p for p in _CERTS_DIR.glob("*.pem") if not p.name.startswith("_"))
    if not extra:
        return True
    bundle_path = _CERTS_DIR / "_bundle.pem"
    merged = Path(certifi.where()).read_text(encoding="utf-8")
    for pem in extra:
        merged += "\n" + pem.read_text(encoding="utf-8")
    if not bundle_path.exists() or bundle_path.read_text(encoding="utf-8") != merged:
        bundle_path.write_text(merged, encoding="utf-8")
    return str(bundle_path)


CA_BUNDLE = _ca_bundle_path()

logger = logging.getLogger(__name__)


class MaxApiError(Exception):
    """Ошибка API MAX."""


class MaxClient:
    """Обёртка над HTTP API MAX: отправка сообщений, long polling, ответы на колбэки."""

    SEND_INTERVAL = 0.55  # сек между отправками в один диалог
    SEND_TIMEOUT = 10     # сек на HTTP-запрос отправки (не даём зависнуть потоку апдейтов)

    def __init__(self, token=MAX_TOKEN, base=API_BASE):
        if not token:
            raise MaxApiError("MAX_TOKEN не задан — укажите его в .env")
        self.token = token
        self.base = base.rstrip('/')
        self.session = requests.Session()
        self.session.verify = CA_BUNDLE
        self.session.headers.update({
            'Authorization': token,
            'Content-Type': 'application/json',
        })
        # Per-dialog rate limit: MAX разрешает не более 2 сообщений/сек в один диалог.
        # Держим минимум SEND_INTERVAL между отправками в один user_id.
        self._last_send = {}  # user_id -> timestamp (monotonic, момент прошлой отправки)
        self._lock = threading.Lock()

    # ---------- низкоуровневый HTTP ----------

    def _request(self, method, path, params=None, json=None, timeout=30):
        url = f"{self.base}{path}"
        try:
            resp = self.session.request(method, url, params=params, json=json, timeout=timeout)
        except requests.exceptions.RequestException as e:
            raise MaxApiError(f"Network error {method} {path}: {e}") from e
        if resp.status_code >= 400:
            raise MaxApiError(f"HTTP {resp.status_code} {method} {path}: {resp.text[:300]}")
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    def _rate_wait(self, user_id):
        """Пауза перед отправкой: не более SEND_INTERVAL сообщений в диалог.

        Фикс прежнего бага: раньше в _last_send писали monotonic()+wait
        («время в будущем»), из-за чего каждая следующая отправка добавляла
        ещё ~0.55с — задержки накапливались при активном кликанье по меню.

        Слот резервируется под локом до сна: два потока одного диалога
        (thread-per-update) не должны проснуться синхронно и уйти в API вместе.
        """
        while True:
            with self._lock:
                last = self._last_send.get(user_id, 0.0)
                wait = self.SEND_INTERVAL - (time.monotonic() - last)
                if wait <= 0:
                    self._last_send[user_id] = time.monotonic()
                    return
            time.sleep(wait)

    # ---------- сообщения ----------

    def send_message(self, user_id, text=None, attachments=None, fmt='html', notify=True):
        """Отправить сообщение пользователю (диалог бота с user_id)."""
        self._rate_wait(user_id)
        body = {}
        if text is not None:
            body['text'] = text
        if attachments:
            body['attachments'] = attachments
        if fmt:
            body['format'] = fmt
        body['notify'] = notify
        return self._request('POST', '/messages', params={'user_id': user_id}, json=body, timeout=self.SEND_TIMEOUT)

    def edit_message(self, message_id, text=None, attachments=None, fmt='html'):
        """Редактирование существующего сообщения (PUT /messages)."""
        body = {}
        if text is not None:
            body['text'] = text
        if attachments is not None:
            body['attachments'] = attachments
        if fmt:
            body['format'] = fmt
        return self._request('PUT', f'/messages/{message_id}', json=body, timeout=self.SEND_TIMEOUT)

    def delete_message(self, message_id):
        """Удаление сообщения (DELETE /messages/{messageId})."""
        return self._request('DELETE', f'/messages/{message_id}', timeout=self.SEND_TIMEOUT)

    def answer_callback(self, callback_id, message=None):
        """Ответ на нажатие кнопки (POST /answers).
        message — NewMessageBody: текст/вложения, которыми заменится сообщение с кнопками.
        """
        body = {}
        if message is not None:
            body['message'] = message
        return self._request('POST', '/answers', params={'callback_id': callback_id}, json=body, timeout=self.SEND_TIMEOUT)

    def callback_reply(self, callback_id, text=None, attachments=None, fmt='html'):
        """Удобная обёртка: заменить сообщение с кнопками на новый текст/клавиатуру."""
        msg = {}
        if text is not None:
            msg['text'] = text
        if attachments is not None:
            msg['attachments'] = attachments
        if fmt:
            msg['format'] = fmt
        return self.answer_callback(callback_id, message=msg)

    # ---------- long polling ----------

    def get_updates(self, marker=None, types=None, limit=100, timeout=30):
        """GET /updates — long polling. Возвращает (updates, next_marker)."""
        params = {'limit': limit, 'timeout': timeout}
        if marker is not None:
            params['marker'] = marker
        if types:
            params['types'] = types
        data = self._request('GET', '/updates', params=params, timeout=timeout + 10)
        updates = data.get('updates', []) if isinstance(data, dict) else []
        next_marker = data.get('marker') if isinstance(data, dict) else None
        return updates, next_marker

    def poll_once(self, marker=None, types=None):
        """Один цикл long polling: получить события, вернуть (updates, next_marker)."""
        return self.get_updates(marker=marker, types=types)

    # ---------- загрузка медиа ----------

    def upload_media(self, file_path, media_type='image'):
        """Загрузка медиафайла: POST /uploads -> url -> загрузка файла -> token."""
        up = self._request('POST', '/uploads', params={'type': media_type})
        url = up.get('url')
        if not url:
            raise MaxApiError("POST /uploads не вернул url")
        token = up.get('token')  # для video/audio возвращается сразу
        if token:
            return token
        with open(file_path, 'rb') as f:
            resp = requests.post(url, files={'data': f}, timeout=120, verify=CA_BUNDLE)
        if resp.status_code >= 400:
            raise MaxApiError(f"Upload failed HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        tok = data.get('token')
        if not tok:
            # Для image MAX возвращает словарь размеров: {'photos': {'<id>': {'token': ...}}}
            photos = data.get('photos') or {}
            if isinstance(photos, dict) and photos:
                first = next(iter(photos.values()))
                if isinstance(first, dict):
                    tok = first.get('token')
        if not tok:
            raise MaxApiError(f"Upload не вернул token: {data}")
        return tok

    def upload_image_from_url(self, url):
        """Для изображений можно вместо токена использовать прямую ссылку."""
        return url

    # ---------- бот ----------

    def get_me(self):
        """GET /me — информация о боте."""
        return self._request('GET', '/me')
