"""
Локальный HTTP API для Electron-админки PRIZMA.

Обёртка над database.py: вся бизнес-логика и кэши остаются в питоне,
UI только читает/пишет через этот сервер. Биндится на 127.0.0.1 —
доступ только с той же машины.

Запуск: python admin_api.py            (или автоматически из Electron)
Порт:   8765 (зашит, должен совпадать с admin/src/api.js)
Токен:  ADMIN_API_TOKEN из .env, иначе генерируется и хранится в .api-token

Эндпоинты (все требуют заголовок Authorization: Bearer <token>):
  GET    /api/health                 — статус + текущая эпоха кэша
  GET    /api/stats                  — сводка для карточек статистики
  GET    /api/calendar               — данные календаря (записи + блокировки по дням)
  GET    /api/bookings               — все записи (JOIN users), ?status=&search=
  POST   /api/bookings/{id}/status   — {"status": "..."} сменить статус
  DELETE /api/bookings/{id}          — удалить запись
  GET    /api/portfolio              — работы портфолио
  DELETE /api/portfolio/{id}         — удалить работу
  GET    /api/reviews                — последние отзывы
  PUT    /api/reviews/{id}           — редактировать отзыв (rating, text)
  DELETE /api/reviews/{id}           — удалить отзыв
  POST   /api/reviews/{id}/reply     — ответ админа на отзыв
  POST   /api/reviews/{id}/like      — лайк отзыву
  POST   /api/reviews/{id}/featured  —.toggle избранного
"""
import json
import os
import secrets
from pathlib import Path

import requests as http_requests
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import psutil

import media_bridge
from config import DB_PATH, BOT_TOKEN, BOT_HANDLE, MAX_TOKEN, MAX_BOT_HANDLE
from database import (delete_booking, delete_portfolio_work, delete_review,
                      edit_review, get_all_bookings, get_booking_by_id,
                      get_blocked_slots, get_portfolio, get_rating_stats,
                      get_review_by_id, get_reviews, get_services, like_review,
                      reply_to_review, toggle_featured, update_booking_status)


# ── Уведомления клиентам (прямые HTTP-вызовы, т.к. admin_api работает отдельно от ботов) ──

def _notify_cancelled_tg(user_id, booking_id, service, date_time):
    """Telegram: отправить сообщение об отмене с кнопкой «Связаться с мастером»."""
    if not BOT_TOKEN or not user_id:
        return
    keyboard = {"inline_keyboard": [
        [{"text": "📞 Связаться с мастером", "url": f"https://t.me/{BOT_HANDLE}"}]
    ]}
    try:
        http_requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": user_id,
                "text": (f"❌ Запись #{booking_id} ({service}) на {date_time} "
                         f"отменена мастером.\n\n"
                         f"Если хотите уточнить причину, нажмите кнопку ниже 👇"),
                "reply_markup": keyboard,
            },
            timeout=10,
        )
    except Exception:
        pass  # тихо — сеть может моргнуть


def _notify_cancelled_max(user_id, booking_id, service, date_time):
    """MAX: отправить сообщение об отмене с кнопкой «Связаться с мастером» (message → /start)."""
    if not MAX_TOKEN or not user_id:
        return
    from max_client import MaxClient
    try:
        client = MaxClient(token=MAX_TOKEN)
        contact_btn = [{"type": "callback", "text": "📞 Связаться с мастером",
                        "payload": "contact_master"}]
        client.send_message(
            user_id,
            text=(f"❌ Запись #{booking_id} ({service}) на {date_time} "
                  f"отменена мастером.\n\n"
                  f"Если хотите уточнить причину, нажмите кнопку ниже 👇"),
            attachments=[{"type": "inline_keyboard", "payload": {"buttons": [contact_btn]}}],
        )
    except Exception:
        pass


def _notify_confirmed_tg(user_id, booking_id, date_time):
    """Telegram: уведомить клиента о подтверждении записи."""
    if not BOT_TOKEN or not user_id:
        return
    try:
        http_requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": user_id,
                "text": f"✅ Запись #{booking_id} на {date_time} подтверждена мастером!",
            },
            timeout=10,
        )
    except Exception:
        pass


def _notify_confirmed_max(user_id, booking_id, date_time):
    """MAX: уведомить клиента о подтверждении записи."""
    if not MAX_TOKEN or not user_id:
        return
    from max_client import MaxClient
    try:
        client = MaxClient(token=MAX_TOKEN)
        client.send_message(
            user_id,
            text=f"✅ Запись #{booking_id} на {date_time} подтверждена мастером!",
        )
    except Exception:
        pass


def _notify_completed_tg(user_id, booking_id):
    """Telegram: уведомить клиента о завершении сеанса + просьба оставить отзыв."""
    if not BOT_TOKEN or not user_id:
        return
    try:
        http_requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": user_id,
                "text": f"✨ Сеанс #{booking_id} завершён! Оставьте отзыв в меню «⭐ Отзывы».",
            },
            timeout=10,
        )
    except Exception:
        pass


def _notify_completed_max(user_id, booking_id):
    """MAX: уведомить клиента о завершении сеанса + просьба оставить отзыв."""
    if not MAX_TOKEN or not user_id:
        return
    from max_client import MaxClient
    try:
        client = MaxClient(token=MAX_TOKEN)
        client.send_message(
            user_id,
            text=f"✨ Сеанс #{booking_id} завершён! Оставьте отзыв в меню «⭐ Отзывы».",
        )
    except Exception:
        pass

# Порт зашит с двух сторон (здесь и в admin/src/api.js) НАРОЧНО: один
# источник конфигурации меньше, чем рассинхрон env-оверрайдов.
API_PORT = 8765
_TOKEN_FILE = Path(__file__).parent / '.api-token'


def _load_or_create_token() -> str:
    """Токен из .env, иначе сгенерировать один раз и сохранить рядом.

    Эффективный токен ВСЕГДА пишется в .api-token: его читает Electron
    (preload), чтобы прокинуть значение в UI. Иначе токен из env остался бы
    недоступен панели и все запросы падали бы с 401.
    """
    env_token = os.getenv('ADMIN_API_TOKEN')
    token = None
    if env_token:
        token = env_token
    elif _TOKEN_FILE.exists():
        token = _TOKEN_FILE.read_text(encoding='utf-8').strip()
    if not token:
        token = secrets.token_urlsafe(24)
        print(f"[OK] Сгенерирован API-токен: {_TOKEN_FILE.name}")
    if not (_TOKEN_FILE.exists() and _TOKEN_FILE.read_text(encoding='utf-8').strip() == token):
        _TOKEN_FILE.write_text(token, encoding='utf-8')
    return token


API_TOKEN = _load_or_create_token()

app = FastAPI(title='PRIZMA Admin API', docs_url=None, redoc_url=None)

# Renderer в dev-режиме живёт на localhost:5173, в проде — file:// (Origin: null).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f'http://localhost:{p}' for p in range(5173, 5181)] + ['null'],
    allow_methods=['*'],
    allow_headers=['*'],
)


def require_auth(authorization: str = Header(default='')):
    """Guard: только Bearer <API_TOKEN>. Fail loud — 401 сразу."""
    expected = f'Bearer {API_TOKEN}'
    if not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail='Unauthorized')


@app.get('/api/health')
def health(_: None = Depends(require_auth)):
    from database import _db_epoch
    return {'ok': True, 'db': DB_PATH, 'epoch': _db_epoch()}


def _bot_alive(script: str, unique: bool) -> bool:
    """Жив ли процесс бота. Для main.py (неуникальное имя) дополнительно
    требуем cwd проекта или путь к нему в cmdline — чужие main.py не считаем."""
    # DB_PATH может быть относительным ('tattoo_bot.db') — резолвим к абсолютному.
    root = Path(DB_PATH).resolve().parent.as_posix().lower()
    for proc in psutil.process_iter(['cmdline']):
        try:
            cl = proc.info['cmdline'] or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if not any(str(a).replace('/', '\\').lower().endswith(script) for a in cl):
            continue
        if unique:
            return True
        try:
            if Path(proc.cwd()).resolve().as_posix().lower() == root:
                return True
            if any('tattoo_bot' in str(a).lower() for a in cl):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


@app.get('/api/services')
def services_status(_: None = Depends(require_auth)):
    """Живость ботов для индикаторов сайдбара."""
    return {
        'telegram': _bot_alive('main.py', unique=False),
        'max': _bot_alive('max_main.py', unique=True),
    }


@app.get('/api/stats')
def stats(_: None = Depends(require_auth)):
    bookings = get_all_bookings()
    from datetime import datetime as _dt
    today_prefix = _dt.now().strftime('%d.%m.%Y')
    by_status = {}
    for b in bookings:
        st = b['status']
        by_status[st] = by_status.get(st, 0) + 1
    avg, cnt = get_rating_stats()
    return {
        'bookings_total': len(bookings),
        'bookings_by_status': by_status,
        'today_bookings': sum(
            1 for b in bookings
            if b['date_time'] and b['date_time'].strip().startswith(today_prefix)
            and b['status'] in ('pending', 'confirmed')),
        'avg_rating': round(avg or 0, 2),
        'reviews_count': cnt,
        'portfolio_count': len(get_portfolio()),
        'services_count': len(get_services()),
    }


@app.get('/api/calendar')
def calendar(year: int = 0, month: int = 0, _: None = Depends(require_auth)):
    """Данные для календаря: записи и блокировки по дням.

    Возвращает для каждого дня месяца:
      - bookings: список активных записей (pending/confirmed)
      - blocked_hours: список заблокированных часов (int)
    year/month — год и месяц (1-12). Если не переданы — текущий месяц.
    """
    from datetime import datetime as _dt
    now = _dt.now()
    y = year or now.year
    m = month or now.month

    # Активные записи на месяц
    active_statuses = {'pending', 'confirmed'}
    by_day = {}  # day -> [{id, user_id, username, first_name, service, date_time, status}]
    for b in get_all_bookings():
        try:
            dt = _dt.strptime(b['date_time'].strip(), '%d.%m.%Y %H:%M')
        except Exception:
            continue
        if dt.year == y and dt.month == m and b['status'] in active_statuses:
            day = dt.day
            by_day.setdefault(day, []).append({
                'id': b['id'],
                'user_id': b['user_id'],
                'username': b['username'],
                'first_name': b['first_name'],
                'service': b['service'],
                'date_time': b['date_time'],
                'status': b['status'],
            })

    # Блокировки на месяц
    blocked_by_day = {}  # day -> [10, 11, 14, ...]
    month_prefix = f'{y}-{m:02d}'
    for slot in get_blocked_slots():
        # slot format: "YYYY-MM-DD HH:00"
        if not slot.startswith(month_prefix):
            continue
        try:
            parts = slot.split(' ')[0].split('-')  # ['YYYY', 'MM', 'DD']
            day = int(parts[2])
            hour = int(slot.split(' ')[1].split(':')[0])
            blocked_by_day.setdefault(day, []).append(hour)
        except Exception:
            continue

    return {
        'year': y,
        'month': m,
        'days': by_day,
        'blocked': blocked_by_day,
    }


@app.get('/api/bookings')
def bookings(status: str = '', search: str = '', _: None = Depends(require_auth)):
    rows = [dict(r) for r in get_all_bookings()]
    if status:
        rows = [r for r in rows if r['status'] == status]
    if search:
        q = search.strip().lower()
        rows = [r for r in rows if q in (r['username'] or '').lower()
                or q in (r['first_name'] or '').lower()
                or q in str(r['user_id'])
                or q in (r['service'] or '').lower()]
    return rows


class StatusBody(BaseModel):
    status: str


ALLOWED_STATUSES = {'pending', 'confirmed', 'completed', 'cancelled', 'client_cancelled'}


@app.post('/api/bookings/{booking_id}/status')
def change_status(booking_id: int, body: StatusBody, _: None = Depends(require_auth)):
    if body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail=f'status must be one of {ALLOWED_STATUSES}')
    row = get_booking_by_id(booking_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Booking not found')
    update_booking_status(booking_id, body.status)
    # Уведомляем клиента при смене статуса
    if row['user_id']:
        platform = row.get('platform', 'telegram')
        if body.status == 'cancelled':
            if platform == 'max':
                _notify_cancelled_max(row['user_id'], booking_id,
                                      row['service'], row['date_time'])
            else:
                _notify_cancelled_tg(row['user_id'], booking_id,
                                     row['service'], row['date_time'])
        elif body.status == 'confirmed':
            if platform == 'max':
                _notify_confirmed_max(row['user_id'], booking_id, row['date_time'])
            else:
                _notify_confirmed_tg(row['user_id'], booking_id, row['date_time'])
        elif body.status == 'completed':
            if platform == 'max':
                _notify_completed_max(row['user_id'], booking_id)
            else:
                _notify_completed_tg(row['user_id'], booking_id)
    return {'ok': True, 'id': booking_id, 'status': body.status}


@app.delete('/api/bookings/{booking_id}')
def remove_booking(booking_id: int, _: None = Depends(require_auth)):
    row = get_booking_by_id(booking_id)
    if row is None:
        raise HTTPException(status_code=404, detail='Booking not found')
    # Уведомляем клиента перед удалением
    if row['user_id']:
        platform = row.get('platform', 'telegram')
        if platform == 'max':
            _notify_cancelled_max(row['user_id'], booking_id,
                                  row['service'], row['date_time'])
        else:
            _notify_cancelled_tg(row['user_id'], booking_id,
                                 row['service'], row['date_time'])
    delete_booking(booking_id)
    return {'ok': True}


@app.get('/api/portfolio')
def portfolio(_: None = Depends(require_auth)):
    return [dict(r) for r in get_portfolio()]


@app.delete('/api/portfolio/{work_id}')
def remove_work(work_id: int, _: None = Depends(require_auth)):
    works = {w['id'] for w in get_portfolio()}
    if work_id not in works:
        raise HTTPException(status_code=404, detail='Work not found')
    delete_portfolio_work(work_id)
    return {'ok': True}


def _fetch_tg_photo(file_id: str) -> Path | None:
    """Скачивает фото из Telegram по file_id, кэширует на диск. None при ошибке.

    Тонкая обёртка над общим media_bridge (используется и MAX-ботом).
    """
    return media_bridge.fetch_tg_file(file_id)


@app.get('/api/portfolio/{work_id}/image')
def work_image(work_id: int, _: None = Depends(require_auth)):
    work = next((w for w in get_portfolio() if w['id'] == work_id), None)
    if not work or not work['file_id']:
        raise HTTPException(status_code=404, detail='No image for this work')
    img = _fetch_tg_photo(work['file_id'])
    if img is None:
        raise HTTPException(status_code=502, detail='Telegram fetch failed')
    return FileResponse(img, media_type='image/jpeg')


@app.get('/api/reviews')
def reviews(_: None = Depends(require_auth)):
    return [dict(r) for r in get_reviews(limit=100)]


class ReviewEditBody(BaseModel):
    rating: int | None = None
    text: str | None = None


@app.put('/api/reviews/{review_id}')
def update_review(review_id: int, body: ReviewEditBody, _: None = Depends(require_auth)):
    if get_review_by_id(review_id) is None:
        raise HTTPException(status_code=404, detail='Review not found')
    if body.rating is not None and not (1 <= body.rating <= 5):
        raise HTTPException(status_code=422, detail='rating must be 1-5')
    edit_review(review_id, rating=body.rating, text=body.text)
    return {'ok': True, 'id': review_id}


@app.delete('/api/reviews/{review_id}')
def remove_review(review_id: int, _: None = Depends(require_auth)):
    if get_review_by_id(review_id) is None:
        raise HTTPException(status_code=404, detail='Review not found')
    delete_review(review_id)
    return {'ok': True}


class ReplyBody(BaseModel):
    text: str


@app.post('/api/reviews/{review_id}/reply')
def review_reply(review_id: int, body: ReplyBody, _: None = Depends(require_auth)):
    if get_review_by_id(review_id) is None:
        raise HTTPException(status_code=404, detail='Review not found')
    if not body.text.strip():
        raise HTTPException(status_code=422, detail='Reply text required')
    reply_to_review(review_id, body.text.strip())
    return {'ok': True, 'id': review_id}


@app.post('/api/reviews/{review_id}/like')
def review_like(review_id: int, _: None = Depends(require_auth)):
    if get_review_by_id(review_id) is None:
        raise HTTPException(status_code=404, detail='Review not found')
    like_review(review_id)
    return {'ok': True, 'id': review_id}


@app.post('/api/reviews/{review_id}/featured')
def review_featured(review_id: int, _: None = Depends(require_auth)):
    if get_review_by_id(review_id) is None:
        raise HTTPException(status_code=404, detail='Review not found')
    val = toggle_featured(review_id)
    return {'ok': True, 'id': review_id, 'is_featured': val}


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=API_PORT, log_level='warning')
