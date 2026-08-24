import { createContext, useCallback, useContext, useRef, useState } from 'react';

// Тосты: единая точка обратной связи. accent — css-цвет (статусные переменные).
const ToastCtx = createContext(() => {});

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const idRef = useRef(0);

  const push = useCallback((text, accent) => {
    const id = ++idRef.current;
    setItems(list => [...list, { id, text, accent }]);
    setTimeout(() => {
      setItems(list => list.map(t => t.id === id ? { ...t, leaving: true } : t));
      setTimeout(() => setItems(list => list.filter(t => t.id !== id)), 260);
    }, 3200);
  }, []);

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">
        {items.map(t => (
          <div key={t.id}
               className={`toast${t.leaving ? ' leaving' : ''}`}
               style={{ '--toast-accent': t.accent || 'var(--orange)' }}>
            <span className="t-dot" />
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
