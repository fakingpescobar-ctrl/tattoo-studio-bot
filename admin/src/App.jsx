import { useCallback, useEffect, useRef, useState } from 'react';
import { getBookings, getHealth, getPortfolio, getReviews, getServices, getStats } from './api.js';
import { useToast } from './components/Toast.jsx';
import Sidebar from './components/Sidebar.jsx';
import StatCards from './components/StatCards.jsx';
import BookingsView from './components/BookingsView.jsx';
import PortfolioView from './components/PortfolioView.jsx';
import ReviewsView from './components/ReviewsView.jsx';
import EmptyState from './components/EmptyState.jsx';
import { IconRefresh, IconSearch } from './components/icons.jsx';

const VIEW_TITLES = { bookings: 'Записи', portfolio: 'Портфолио', reviews: 'Отзывы' };

export default function App() {
  const [view, setView] = useState('bookings');
  const [search, setSearch] = useState('');
  const [stats, setStats] = useState(null);
  const [bookings, setBookings] = useState([]);
  const [works, setWorks] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [connected, setConnected] = useState(false);
  const [services, setServices] = useState({ telegram: false, max: false });
  const [loaded, setLoaded] = useState(false);
  const epochRef = useRef(undefined);
  const toast = useToast();

  // Первичная и повторная загрузка всех данных.
  const loadAll = useCallback(async ({ silent = false } = {}) => {
    try {
      const [h, s, b, w, r] = await Promise.all([
        getHealth(), getStats(), getBookings(), getPortfolio(), getReviews(),
      ]);
      const prevEpoch = epochRef.current;
      epochRef.current = h.epoch;
      setConnected(true);
      setStats(s);
      setBookings(b);
      setWorks(w);
      setReviews(r);
      setLoaded(true);
      if (!silent && prevEpoch !== undefined && prevEpoch !== h.epoch) {
        toast('Данные обновились', 'var(--purple)');
      }
    } catch (e) {
      setConnected(false);
      if (!silent) toast(`API недоступен: ${e.message}`, 'var(--st-cancelled)');
    }
  }, [toast]);

  // Live-режим: поллинг health + статусов ботов каждые 4с; смена эпохи -> тихая перезагрузка.
  useEffect(() => {
    loadAll({ silent: true });
    getServices().then(setServices).catch(() => setServices({ telegram: false, max: false }));
    const iv = setInterval(async () => {
      try {
        const h = await getHealth();
        setConnected(true);
        if (h.epoch !== epochRef.current) loadAll({ silent: true });
      } catch {
        setConnected(false);
      }
      getServices().then(setServices).catch(() => setServices({ telegram: false, max: false }));
    }, 4000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <div className="atmosphere" />
      <div className="app">
        <Sidebar view={view} onView={setView} connected={connected} services={services} />

        <header className="topbar">
          <h1>{VIEW_TITLES[view]}</h1>
          {view === 'bookings' && (
            <label className="search">
              <IconSearch />
              <input placeholder="Поиск: имя, @юзернейм, id, услуга…"
                     value={search}
                     onChange={e => setSearch(e.target.value)} />
            </label>
          )}
          <button className="refresh-btn" title="Обновить" onClick={() => loadAll()}>
            <IconRefresh />
          </button>
        </header>

        <main className="main">
          {!loaded ? (
            <EmptyState title="Подключение…" text="Ждём локальный API (127.0.0.1:8765)." />
          ) : (
            <>
              {view === 'bookings' && (
                <>
                  <StatCards stats={stats} />
                  <BookingsView bookings={bookings} search={search} onChanged={() => loadAll({ silent: true })} />
                </>
              )}
              {view === 'portfolio' && <PortfolioView works={works} onChanged={() => loadAll({ silent: true })} />}
              {view === 'reviews' && <ReviewsView reviews={reviews} />}
            </>
          )}
        </main>
      </div>
    </>
  );
}
