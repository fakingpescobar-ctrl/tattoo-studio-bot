import { useState } from 'react';
import { deleteReview, editReview, likeReview, replyToReview, toggleFeatured } from '../api.js';
import { IconEdit, IconHeart, IconReply, IconShare, IconTrash } from './icons.jsx';
import ConfirmModal from './ConfirmModal.jsx';
import EmptyState from './EmptyState.jsx';
import { useToast } from './Toast.jsx';

const stars = (n) => '★'.repeat(n) + '☆'.repeat(Math.max(0, 5 - n));

function ReviewCard({ review: r, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(r.text || '');
  const [editRating, setEditRating] = useState(r.rating || 5);
  const [replying, setReplying] = useState(false);
  const [replyText, setReplyText] = useState('');
  const [toDelete, setToDelete] = useState(false);
  const toast = useToast();

  async function handleSave() {
    try {
      await editReview(r.id, { rating: editRating, text: editText });
      setEditing(false);
      onChanged();
      toast('Отзыв обновлён', 'var(--st-confirmed)');
    } catch (e) {
      toast(`Ошибка: ${e.message}`, 'var(--st-cancelled)');
    }
  }

  async function handleDelete() {
    try {
      await deleteReview(r.id);
      setToDelete(false);
      onChanged();
      toast('Отзыв удалён', 'var(--st-cancelled)');
    } catch (e) {
      setToDelete(false);
      toast(`Ошибка: ${e.message}`, 'var(--st-cancelled)');
    }
  }

  async function handleReply() {
    if (!replyText.trim()) return;
    try {
      await replyToReview(r.id, replyText.trim());
      setReplying(false);
      setReplyText('');
      onChanged();
      toast('Ответ отправлен', 'var(--st-confirmed)');
    } catch (e) {
      toast(`Ошибка: ${e.message}`, 'var(--st-cancelled)');
    }
  }

  async function handleLike() {
    try {
      await likeReview(r.id);
      onChanged();
    } catch (e) {
      toast(`Ошибка: ${e.message}`, 'var(--st-cancelled)');
    }
  }

  async function handleFeatured() {
    try {
      await toggleFeatured(r.id);
      onChanged();
    } catch (e) {
      toast(`Ошибка: ${e.message}`, 'var(--st-cancelled)');
    }
  }

  function handleShare() {
    const text = `⭐ ${r.rating}/5 — ${r.username || `id ${r.user_id}`}\n${r.text || ''}`;
    navigator.clipboard.writeText(text).then(
      () => toast('Скопировано в буфер', 'var(--st-confirmed)'),
      () => toast('Не удалось скопировать', 'var(--st-cancelled)')
    );
  }

  return (
    <>
      <div className={`review-card${r.is_featured ? ' featured' : ''}`}
           style={{ animationDelay: `${Math.min(r._idx * 0.05, 0.5)}s` }}>
        <div className="review-head">
          <span className="review-name">{r.username || `id ${r.user_id}`}</span>
          <span className="review-stars">{stars(r.rating || 0)}</span>
          <span className="review-date">{(r.created_at || '').slice(0, 10)}</span>
        </div>

        {editing ? (
          <div className="review-edit">
            <div className="review-edit-stars">
              {[1,2,3,4,5].map(s => (
                <button key={s} className={`star-btn${s <= editRating ? ' active' : ''}`}
                        onClick={() => setEditRating(s)}>
                  ★
                </button>
              ))}
            </div>
            <textarea className="review-edit-text" value={editText}
                      onChange={e => setEditText(e.target.value)} rows={3} />
            <div className="review-edit-actions">
              <button className="btn btn-sm" onClick={() => setEditing(false)}>Отмена</button>
              <button className="btn btn-sm primary" onClick={handleSave}>Сохранить</button>
            </div>
          </div>
        ) : (
          <>
            {r.text && <div className="review-text">{r.text}</div>}

            {r.admin_reply && (
              <div className="review-reply">
                <span className="review-reply-label">💬 Ответ мастера:</span>
                <div className="review-reply-text">{r.admin_reply}</div>
                {r.admin_reply_at && (
                  <span className="review-reply-date">{r.admin_reply_at.slice(0, 16).replace('T', ' ')}</span>
                )}
              </div>
            )}
          </>
        )}

        <div className="review-actions">
          <button className={`icon-btn like${r.likes ? ' liked' : ''}`}
                  title={`Лайк${r.likes ? ` (${r.likes})` : ''}`}
                  onClick={handleLike}>
            <IconHeart filled={!!r.likes} />{r.likes ? <span className="like-count">{r.likes}</span> : null}
          </button>
          <button className={`icon-btn feat${r.is_featured ? ' active' : ''}`}
                  title={r.is_featured ? 'Убрать из избранного' : 'В избранное'}
                  onClick={handleFeatured}>
            ★
          </button>
          <button className="icon-btn share" title="Копировать" onClick={handleShare}>
            <IconShare />
          </button>
          <button className="icon-btn reply" title="Ответить" onClick={() => setReplying(!replying)}>
            <IconReply />
          </button>
          <button className="icon-btn edit" title="Редактировать" onClick={() => setEditing(true)}>
            <IconEdit />
          </button>
          <button className="icon-btn del" title="Удалить" onClick={() => setToDelete(true)}>
            <IconTrash />
          </button>
        </div>

        {replying && (
          <div className="review-reply-input">
            <textarea placeholder="Ответ мастера…" value={replyText}
                      onChange={e => setReplyText(e.target.value)} rows={2} />
            <div className="review-edit-actions">
              <button className="btn btn-sm" onClick={() => { setReplying(false); setReplyText(''); }}>Отмена</button>
              <button className="btn btn-sm primary" onClick={handleReply}>Отправить</button>
            </div>
          </div>
        )}
      </div>

      <ConfirmModal
        open={toDelete}
        title="Удалить отзыв?"
        text={`Отзыв от ${r.username || `id ${r.user_id}`}: «${(r.text || '').slice(0, 60)}…» Действие необратимо.`}
        confirmLabel="Удалить"
        onCancel={() => setToDelete(false)}
        onConfirm={handleDelete}
      />
    </>
  );
}

export default function ReviewsView({ reviews, onChanged }) {
  if (!reviews.length) {
    return <EmptyState title="Отзывов пока нет" text="Клиенты оставляют их через бота после сеанса." />;
  }
  return (
    <div className="reviews-col">
      {reviews.map((r, i) => (
        <ReviewCard key={r.id} review={{ ...r, _idx: i }} onChanged={onChanged} />
      ))}
    </div>
  );
}
