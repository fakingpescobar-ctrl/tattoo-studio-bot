export default function EmptyState({ title, text }) {
  return (
    <div className="empty-state">
      <div className="big">{title}</div>
      {text && <p>{text}</p>}
    </div>
  );
}
