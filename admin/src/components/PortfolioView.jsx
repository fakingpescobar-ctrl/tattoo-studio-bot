import { useState } from 'react';
import { deleteWork } from '../api.js';
import { IconTrash } from './icons.jsx';
import WorkImage from './WorkImage.jsx';
import ConfirmModal from './ConfirmModal.jsx';
import EmptyState from './EmptyState.jsx';
import { useToast } from './Toast.jsx';

export default function PortfolioView({ works, onChanged }) {
  const [toDelete, setToDelete] = useState(null);
  const toast = useToast();

  async function remove() {
    try {
      await deleteWork(toDelete.id);
      setToDelete(null);
      onChanged();
      toast('Работа удалена из портфолио', 'var(--st-cancelled)');
    } catch (e) {
      setToDelete(null);
      toast(`Ошибка: ${e.message}`, 'var(--st-cancelled)');
    }
  }

  if (!works.length) {
    return <EmptyState title="Портфолио пусто" text="Работы добавляются через бота командой /add_work." />;
  }

  return (
    <>
      <div className="cards-grid">
        {works.map((w, i) => (
          <div key={w.id} className="work-card" style={{ animationDelay: `${Math.min(i * 0.04, 0.5)}s` }}>
            <WorkImage workId={w.id} />
            <div className="work-body">
              <div className="work-meta">{w.style || 'стиль не указан'}</div>
              <div className="work-title">{w.title}</div>
              {w.description && <div className="work-desc">{w.description}</div>}
              <div className="work-foot">
                <span className="work-date">{(w.created_at || '').slice(0, 10)}</span>
                <button className="icon-btn del" title="Удалить" onClick={() => setToDelete(w)}><IconTrash /></button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <ConfirmModal
        open={!!toDelete}
        title="Удалить работу?"
        text={toDelete && `«${toDelete.title}» будет удалена из портфолио навсегда.`}
        confirmLabel="Удалить"
        onCancel={() => setToDelete(null)}
        onConfirm={remove}
      />
    </>
  );
}
