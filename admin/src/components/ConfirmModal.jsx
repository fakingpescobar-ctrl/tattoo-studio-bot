export default function ConfirmModal({ open, title, text, confirmLabel, danger = true, onCancel, onConfirm }) {
  if (!open) return null;
  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="modal">
        <h3>{title}</h3>
        <p>{text}</p>
        <div className="modal-actions">
          <button className="btn" onClick={onCancel}>Отмена</button>
          <button className={`btn ${danger ? 'danger' : 'primary'}`} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
