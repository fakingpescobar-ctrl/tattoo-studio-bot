import { IconCalendar, IconImage, IconStar } from './icons.jsx';

const NAV = [
  { id: 'bookings', label: 'Записи', Icon: IconCalendar },
  { id: 'portfolio', label: 'Портфолио', Icon: IconImage },
  { id: 'reviews', label: 'Отзывы', Icon: IconStar },
];

export default function Sidebar({ view, onView, connected }) {
  return (
    <aside className="sidebar">
      <div className="logo">
        <div className="logo-word">PRIZMA</div>
        <div className="logo-sub">tattoo studio</div>
        <div className="logo-rule" />
      </div>

      <nav className="nav">
        {NAV.map(({ id, label, Icon }) => (
          <button key={id}
                  className={`nav-item${view === id ? ' active' : ''}`}
                  onClick={() => onView(id)}>
            <Icon />
            {label}
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        <span className={`live-dot${connected ? '' : ' off'}`} />
        {connected ? 'live' : 'offline'}
      </div>
    </aside>
  );
}
