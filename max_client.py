"""
Тонкий клиент Bot API мессенджера MAX (VK).
Документация: https://dev.max.ru/docs-api
Домен: platform-api2.max.ru, авторизация — заголовок Authorization: <token>.
"""
import logging
import threading
import time

import requests

from config import MAX_TOKEN

API_BASE = "https://platform-api2.max.ru"

logger = logging.getLogger(__name__)


class MaxApiError(Exception):
    """Ошибка API MAX."""


class MaxClient:
    """Обёртка над HTTP API MAX: отправка сообщений, long polling, ответы на колбэки."""

    def __init__(self, token=MAX_TOKEN, base=API_BASE):
        if not token:
            raise MaxApiError("MAX_TOKEN не задан — укажите его в .env")
        self.token = token
        self.base = base.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': token,
            'Content-Type': 'application/json',
        })
        # Per-dialog rate limit: MAX разрешает не более 2 сообщений/сек в один диалог.
        # Держим минимум 0.55с между отправками в один user_id.
        self._last_send = {}  # user_id -> timestamp
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
        with self._lock:
            last = self._last_send.get(user_id, 0.0)
            wait = 0.55 - (time.monotonic() - last)
            if wait > 0:
                self._last_send[user_id] = time.monotonic() + wait
            else:
                self._last_send[user_id] = time.monotonic()
        if wait > 0:
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
        return self._request('POST', '/messages', params={'user_id': user_id}, json=body)

    def edit_message(self, message_id, text=None, attachments=None, fmt='html'):
        """Редактирование существующего сообщения (PUT /messages)."""
        body = {}
        if text is not None:
            body['text'] = text
        if attachments is not None:
            body['attachments'] = attachments
        if fmt:
            body['format'] = fmt
        return self._request('PUT', f'/messages/{message_id}', json=body)

    def delete_message(self, message_id):
        """Удаление сообщения (DELETE /messages/{messageId})."""
        return self._request('DELETE', f'/messages/{message_id}')

    def answer_callback(self, callback_id, message=None):
        """Ответ на нажатие кнопки (POST /answers).
        message — NewMessageBody: текст/вложения, которыми заменится сообщение с кнопками.
        """
        body = {}
        if message is not None:
            body['message'] = message
        return self._request('POST', '/answers', params={'callback_id': callback_id}, json=body)

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
            resp = requests.post(url, files={'data': f}, timeout=120)
        if resp.status_code >= 400:
            raise MaxApiError(f"Upload failed HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        tok = data.get('token')
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
