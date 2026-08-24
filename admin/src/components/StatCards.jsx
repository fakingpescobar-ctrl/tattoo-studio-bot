const ACCENTS = {
  total: 'var(--orange)',
  pending: 'var(--st-pending)',
  confirmed: 'var(--st-confirmed)',
  completed: 'var(--purple)',
  rating: 'var(--orange-hi)',
};

export default function StatCards({ stats }) {
  if (!stats) return null;
  const by = stats.bookings_by_status || {};
  const cards = [
    { key: 'total', label: 'Всего записей', value: stats.bookings_total,
      extra: `сегодня: ${stats.today_bookings}` },
    { key: 'pending', label: 'Ожидают', value: by.pending || 0,
      extra: `клиент отказался: ${by.client_cancelled || 0}` },
    { key: 'confirmed', label: 'Подтверждено', value: by.confirmed || 0,
      extra: `отменено: ${by.cancelled || 0}` },
    { key: 'completed', label: 'Завершено', value: by.completed || 0 },
    { key: 'rating', label: 'Рейтинг', value: stats.avg_rating,
      extra: `${stats.reviews_count} отзывов · ${stats.portfolio_count} работ` },
  ];
  return (
    <div className="stats-grid">
      {cards.map((c, i) => (
        <div key={c.key} className="stat-card"
             style={{ '--accent': ACCENTS[c.key], animation: `row-in .45s var(--ease-out) ${i * 0.05}s backwards` }}>
          <div className="stat-label">{c.label}</div>
          <div className="stat-value">{c.value}</div>
          {c.extra && <div className="stat-extra">{c.extra}</div>}
        </div>
      ))}
    </div>
  );
}
