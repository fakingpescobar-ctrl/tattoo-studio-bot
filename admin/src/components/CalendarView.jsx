import { useEffect, useState } from 'react';
import { getCalendar } from '../api.js';

const MONTHS_RU = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

function daysInMonth(y, m) { return new Date(y, m, 0).getDate(); }
function startDayOfWeek(y, m) {
  // 0=Mon..6=Sun  (JS getDay: 0=Sun..6=Sat)
  const d = new Date(y, m - 1, 1).getDay();
  return d === 0 ? 6 : d - 1;
}

const STATUS_COLORS = {
  pending: 'var(--st-pending)',
  confirmed: 'var(--st-confirmed)',
};

export default function CalendarView({ onDayClick }) {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [data, setData] = useState(null);
  const [selectedDay, setSelectedDay] = useState(null);

  const load = () => getCalendar(year, month).then(setData).catch(console.error);
  useEffect(() => { load(); }, [year, month]);

  // Также обновляем при смене epoch (родитель перерендерит)
  useEffect(() => { load(); }, []);

  const prev = () => {
    if (month === 1) { setMonth(12); setYear(y => y - 1); }
    else setMonth(m => m - 1);
    setSelectedDay(null);
  };
  const next = () => {
    if (month === 12) { setMonth(1); setYear(y => y + 1); }
    else setMonth(m => m + 1);
    setSelectedDay(null);
  };
  const goToday = () => {
    setYear(now.getFullYear());
    setMonth(now.getMonth() + 1);
    setSelectedDay(null);
  };

  const days = data?.days || {};
  const blocked = data?.blocked || {};
  const totalDays = daysInMonth(year, month);
  const offset = startDayOfWeek(year, month);
  const today = (year === now.getFullYear() && month === now.getMonth() + 1)
    ? now.getDate() : null;

  // Клетки календаря (включая пустые до первого дня)
  const cells = [];
  for (let i = 0; i < offset; i++) cells.push(null);
  for (let d = 1; d <= totalDays; d++) cells.push(d);

  // Статистика месяца
  const totalBookings = Object.values(days).reduce((s, arr) => s + arr.length, 0);
  const totalBlocked = Object.values(blocked).reduce((s, arr) => s + arr.length, 0);

  // Детали выбранного дня
  const selBookings = selectedDay ? (days[selectedDay] || []) : [];
  const selBlocked = selectedDay ? (blocked[selectedDay] || []) : [];

  return (
    <div className="cal-wrap">
      {/* ── Шапка ── */}
      <div className="cal-header">
        <div className="cal-nav">
          <button className="cal-nav-btn" onClick={prev}>◀</button>
          <h2 className="cal-title">{MONTHS_RU[month - 1]} {year}</h2>
          <button className="cal-nav-btn" onClick={next}>▶</button>
        </div>
        <button className="cal-today-btn" onClick={goToday}>Сегодня</button>
      </div>

      {/* ── Легенда + счётчики ── */}
      <div className="cal-legend">
        <span className="cal-legend-item">
          <span className="cal-dot cal-dot-booked" /> записи ({totalBookings})
        </span>
        <span className="cal-legend-item">
          <span className="cal-dot cal-dot-blocked" /> заблокировано ({totalBlocked})
        </span>
      </div>

      {/* ── Сетка календаря ── */}
      <div className="cal-grid">
        {WEEKDAYS.map(w => (
          <div key={w} className="cal-weekday">{w}</div>
        ))}
        {cells.map((day, i) => {
          if (day === null) return <div key={`e${i}`} className="cal-cell empty" />;
          const hasBookings = days[day]?.length > 0;
          const hasBlocked = blocked[day]?.length > 0;
          const isPast = (today && day < today) && year === now.getFullYear() && month === now.getMonth() + 1;
          const isToday = day === today;
          const isSelected = day === selectedDay;

          let cls = 'cal-cell';
          if (isPast) cls += ' past';
          if (isToday) cls += ' today';
          if (isSelected) cls += ' selected';
          if (hasBookings) cls += ' has-bookings';
          if (hasBlocked) cls += ' has-blocked';

          return (
            <button key={day} className={cls}
                    onClick={() => setSelectedDay(isSelected ? null : day)}>
              <span className="cal-day-num">{day}</span>
              {(hasBookings || hasBlocked) && (
                <span className="cal-indicators">
                  {hasBookings && <span className="cal-ind-dot booked" />}
                  {hasBlocked && <span className="cal-ind-dot blocked" />}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* ── Детали дня ── */}
      {selectedDay && (
        <div className="cal-detail">
          <div className="cal-detail-head">
            <strong>{selectedDay} {MONTHS_RU[month - 1].toLowerCase()}</strong>
            <button className="cal-detail-close" onClick={() => setSelectedDay(null)}>✕</button>
          </div>

          {selBookings.length > 0 && (
            <div className="cal-detail-section">
              <div className="cal-detail-label">Записи</div>
              {selBookings.map(b => (
                <div key={b.id} className="cal-booking-row">
                  <span className="cal-bk-time">{b.date_time.slice(11, 16)}</span>
                  <span className="cal-bk-name">{b.first_name || 'Клиент'}</span>
                  <span className="cal-bk-service">{b.service}</span>
                  <span className="cal-bk-status" style={{ color: STATUS_COLORS[b.status] || 'var(--muted)' }}>
                    {b.status === 'pending' ? 'Ожидает' : 'Подтверждена'}
                  </span>
                </div>
              ))}
            </div>
          )}

          {selBlocked.length > 0 && (
            <div className="cal-detail-section">
              <div className="cal-detail-label">Блокировки</div>
              <div className="cal-blocked-hours">
                {selBlocked.sort((a, b) => a - b).map(h => (
                  <span key={h} className="cal-blocked-chip">{h}:00</span>
                ))}
              </div>
            </div>
          )}

          {selBookings.length === 0 && selBlocked.length === 0 && (
            <div className="cal-detail-empty">Свободный день</div>
          )}
        </div>
      )}
    </div>
  );
}
