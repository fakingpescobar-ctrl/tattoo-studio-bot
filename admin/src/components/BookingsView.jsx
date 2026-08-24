import { useMemo, useState } from 'react';
import { deleteBooking, setStatus, STATUS_LABELS, STATUS_ORDER } from '../api.js';
import { IconCheck, IconDone, IconTrash, IconX } from './icons.jsx';
import { useToast } from './Toast.jsx';
import ConfirmModal from './ConfirmModal.jsx';
import EmptyState from './EmptyState.jsx';

const fmtDate = (s) => {
  // 'DD.MM.YYYY HH:MM' -> 'DD.MM · HH:MM'
  if (!s) return '—';
  const [d, t] = s.split(' ');
  return `${d ? d.slice(0, 5) : ''} · ${t || ''}`;
};

export default function BookingsView({ bookings, search, onChanged }) {
  const [filter, setFilter] = useState('all');
  const [toDelete, setToDelete] = useState(null);
  const [flashId, setFlashId] = useState(null);
  const toast = useToast();

  const rows = useMemo(() => {
    let r = bookings;
    if (search) {
      const q = search.toLowerCase();
      r = r.filter(b =>
        (b.username || '').toLowerCase().includes(q) ||
        (b.first_name || '').toLowerCase().includes(q) ||
        String(b.user_id).includes(q) ||
        (b.service || '').toLowerCase().includes(q));
    }
    if (filter !== 'all') r = r.filter(b => b.status === filter);
    return r;
  }, [bookings, search, filter]);

  const counts = useMemo(() => {
    const c = { all: bookings.length };
    for (const s of STATUS_ORDER) c[s] = bookings.filter(b => b.status === s).length;
    return c;
  }, [bookings]);

  async function change(id, status) {
    try {
      await setStatus(id, status);
      setFlashId(`${id}:${status}`);
      setTimeout(() => setFlashId(null), 900);
      onChanged();
      toast(`Статус → «${STATUS_LABELS[status]}»`, 'var(--st-confirmed)');
    } catch (e) {
      toast(`Ошибка: ${e.message}`, 'var(--st-cancelled)');
    }
  }

  async function remove() {
    if (!toDelete) return;
    try {
      await deleteBooking(toDelete.id);
      setToDelete(null);
      onChanged();
      toast('Запись удалена', 'var(--st-cancelled)');
    } catch (e) {
      setToDelete(null);
      toast(`Ошибка: ${e.message}`, 'var(--st-cancelled)');
    }
  }

  return (
    <>
      <div className="chips">
        <button className={`chip${filter === 'all' ? ' active' : ''}`} onClick={() => setFilter('all')}>
          Все<span className="chip-count">{counts.all}</span>
        </button>
        {STATUS_ORDER.map(s => (
          <button key={s}
                  className={`chip st-${s}${filter === s ? ' active' : ''}`}
                  style={filter === s ? { background: `var(--st-${s})`, borderColor: `var(--st-${s})` } : undefined}
                  onClick={() => setFilter(s)}>
            {STATUS_LABELS[s]}<span className="chip-count">{counts[s]}</span>
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <div className="table-wrap">
          <EmptyState title="Записей нет" text="Здесь появятся брони из Telegram и MAX." />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Клиент</th><th>Услуга</th><th>Когда</th><th>Канал</th>
                <th>Статус</th><th style={{ textAlign: 'right' }}>Действия</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b, i) => (
                <tr key={b.id} style={{ animationDelay: `${Math.min(i * 0.03, 0.4)}s` }}>
                  <td className="td-client">
                    <strong>{b.first_name || b.username || 'Без имени'}</strong>
                    <span>{b.username ? '@' + b.username : `id ${b.user_id}`}</span>
                  </td>
                  <td className="td-service">
                    <div className="svc">{b.service}</div>
                    {b.description && <div className="desc">{b.description}</div>}
                  </td>
                  <td className="td-time">{fmtDate(b.date_time)}</td>
                  <td><span className={`td-platform ${b.platform || 'telegram'}`}>{b.platform || 'telegram'}</span></td>
                  <td>
                    <span className={`badge st-${b.status}${flashId === `${b.id}:${b.status}` ? ' flash' : ''}`}>
                      <span className="dot" />{STATUS_LABELS[b.status] || b.status}
                    </span>
                  </td>
                  <td>
                    <div className="row-actions">
                      {b.status === 'pending' && (
                        <button className="icon-btn ok" title="Подтвердить" onClick={() => change(b.id, 'confirmed')}><IconCheck /></button>
                      )}
                      {(b.status === 'pending' || b.status === 'confirmed') && (
                        <button className="icon-btn done" title="Завершить" onClick={() => change(b.id, 'completed')}><IconDone /></button>
                      )}
                      {['pending', 'confirmed'].includes(b.status) && (
                        <button className="icon-btn no" title="Отменить" onClick={() => change(b.id, 'cancelled')}><IconX /></button>
                      )}
                      <button className="icon-btn del" title="Удалить" onClick={() => setToDelete(b)}><IconTrash /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmModal
        open={!!toDelete}
        title="Удалить запись?"
        text={toDelete && `«${toDelete.service}» — ${toDelete.date_time || ''} (${toDelete.first_name || toDelete.username || toDelete.user_id}). Действие необратимо.`}
        confirmLabel="Удалить"
        onCancel={() => setToDelete(null)}
        onConfirm={remove}
      />
    </>
  );
}
