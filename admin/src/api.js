// Тонкий клиент локального API. Токен приходит из preload-моста Electron;
// в браузерном dev-режиме (vite без электрона) — из localStorage.
const BASE = 'http://127.0.0.1:8765';

function token() {
  try {
    const t = window.prizma?.getToken?.();
    if (t) return t;
  } catch { /* не в electron */ }
  return localStorage.getItem('prizma-token') || '';
}

export async function api(path, options = {}) {
  const res = await fetch(BASE + path, {
    ...options,
    headers: {
      'Authorization': `Bearer ${token()}`,
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* не JSON */ }
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json();
}

// Blob-вариант для <img>-кейсов (img не умеет Authorization-заголовки).
export async function apiBlob(path, signal) {
  const res = await fetch(BASE + path, {
    headers: { Authorization: `Bearer ${token()}` },
    signal,
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.blob();
}

export const getHealth   = () => api('/api/health');
export const getStats    = () => api('/api/stats');
export const getBookings = () => api('/api/bookings');
export const setStatus   = (id, status) =>
  api(`/api/bookings/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) });
export const deleteBooking = (id) => api(`/api/bookings/${id}`, { method: 'DELETE' });
export const getPortfolio  = () => api('/api/portfolio');
export const deleteWork    = (id) => api(`/api/portfolio/${id}`, { method: 'DELETE' });
export const getReviews    = () => api('/api/reviews');

export const STATUS_LABELS = {
  pending: 'Ожидает',
  confirmed: 'Подтверждена',
  completed: 'Завершена',
  cancelled: 'Отменена',
  client_cancelled: 'Клиент отказался',
};

export const STATUS_ORDER = ['pending', 'confirmed', 'completed', 'cancelled', 'client_cancelled'];
