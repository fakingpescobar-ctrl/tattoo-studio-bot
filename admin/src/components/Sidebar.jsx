import { IconCalendar, IconCalendarGrid, IconImage, IconStar } from './icons.jsx';

const NAV = [
  { id: 'bookings', label: 'Записи', Icon: IconCalendar },
  { id: 'calendar', label: 'Календарь', Icon: IconCalendarGrid },
  { id: 'portfolio', label: 'Портфолио', Icon: IconImage },
  { id: 'reviews', label: 'Отзывы', Icon: IconStar },
];

export default function Sidebar({ view, onView, connected, services }) {
  const bots = [
    { label: 'Telegram', up: !!services?.telegram },
    { label: 'MAX', up: !!services?.max },
  ];
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
        {bots.map(({ label, up }) => (
          <span key={label} className="svc-item" title={`${label}-бот ${up ? 'работает' : 'не запущен'}`}>
            <span className={`live-dot svc-dot${up ? '' : ' off'}`} />
            {label}
          </span>
        ))}
      </div>
    </aside>
  );
}
