import { useEffect, useState } from 'react';
import { apiBlob } from '../api.js';
import { IconImage } from './icons.jsx';

// Фото работы через API-прокси (file_id -> bytes). Blob тянем с
// Authorization-заголовком и делаем objectURL. Отмена через AbortController:
// StrictMode монтирует эффект дважды — без флага cancelled первый fetch
// утечёт blob навсегда.
export default function WorkImage({ workId }) {
  const [url, setUrl] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = null;
    const ctrl = new AbortController();
    setUrl(null);
    setFailed(false);
    (async () => {
      try {
        const blob = await apiBlob(`/api/portfolio/${workId}/image`, ctrl.signal);
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      ctrl.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [workId]);

  if (failed || !url) {
    return (
      <div className="work-thumb">
        <IconImage size={22} />
      </div>
    );
  }
  return <img className="work-thumb work-img" src={url} alt="" loading="lazy" />;
}
