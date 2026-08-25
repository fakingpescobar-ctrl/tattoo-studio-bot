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
  GET    /api/bookings               — все записи (JOIN users), ?status=&search=
  POST   /api/bookings/{id}/status   — {"status": "..."} сменить статус
  DELETE /api/bookings/{id}          — удалить запись
  GET    /api/portfolio              — работы портфолио
  DELETE /api/portfolio/{id}         — удалить работу
  GET    /api/reviews                — последние отзывы
"""
import os
import secrets
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import psutil

import media_bridge
from config import DB_PATH
from database import (delete_booking, delete_portfolio_work, get_all_bookings,
                      get_booking_by_id, get_portfolio, get_rating_stats,
                      get_reviews, get_services, update_booking_status)

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
    return {'ok': True, 'id': booking_id, 'status': body.status}


@app.delete('/api/bookings/{booking_id}')
def remove_booking(booking_id: int, _: None = Depends(require_auth)):
    if get_booking_by_id(booking_id) is None:
        raise HTTPException(status_code=404, detail='Booking not found')
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


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=API_PORT, log_level='warning')
