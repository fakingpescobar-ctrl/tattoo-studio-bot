import EmptyState from './EmptyState.jsx';

const stars = (n) => '★'.repeat(n) + '☆'.repeat(Math.max(0, 5 - n));

export default function ReviewsView({ reviews }) {
  if (!reviews.length) {
    return <EmptyState title="Отзывов пока нет" text="Клиенты оставляют их через бота после сеанса." />;
  }
  return (
    <div className="reviews-col">
      {reviews.map((r, i) => (
        <div key={r.id} className="review-card" style={{ animationDelay: `${Math.min(i * 0.05, 0.5)}s` }}>
          <div className="review-head">
            <span className="review-name">{r.username || `id ${r.user_id}`}</span>
            <span className="review-stars">{stars(r.rating || 0)}</span>
            <span className="review-date">{(r.created_at || '').slice(0, 10)}</span>
          </div>
          {r.text && <div className="review-text">{r.text}</div>}
        </div>
      ))}
    </div>
  );
}
