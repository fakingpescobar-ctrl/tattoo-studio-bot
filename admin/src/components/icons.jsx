// Инлайновые SVG-иконки (stroke, 16px) — без внешних зависимостей.
const base = {
  width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round',
  strokeLinejoin: 'round',
};

export const IconCalendar = () => (
  <svg {...base}><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
);
export const IconImage = ({ size = 16 }) => (
  <svg {...base} width={size} height={size}><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
);
export const IconStar = ({ size = 14, filled = false }) => (
  <svg {...base} width={size} height={size} fill={filled ? 'currentColor' : 'none'}>
    <path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
  </svg>
);
export const IconSearch = ({ size = 14 }) => (
  <svg {...base} width={size} height={size}><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
);
export const IconRefresh = ({ size = 15 }) => (
  <svg {...base} width={size} height={size}><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>
);
export const IconCheck = ({ size = 14 }) => (
  <svg {...base} width={size} height={size}><path d="m20 6-11 11-5-5"/></svg>
);
export const IconDone = ({ size = 14 }) => (
  <svg {...base} width={size} height={size}><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
);
export const IconX = ({ size = 14 }) => (
  <svg {...base} width={size} height={size}><path d="M18 6 6 18M6 6l12 12"/></svg>
);
export const IconTrash = ({ size = 14 }) => (
  <svg {...base} width={size} height={size}><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
);
export const IconEdit = ({ size = 14 }) => (
  <svg {...base} width={size} height={size}><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/></svg>
);
export const IconReply = ({ size = 14 }) => (
  <svg {...base} width={size} height={size}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
);
export const IconHeart = ({ size = 14, filled = false }) => (
  <svg {...base} width={size} height={size} fill={filled ? 'currentColor' : 'none'}>
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
  </svg>
);
export const IconShare = ({ size = 14 }) => (
  <svg {...base} width={size} height={size}><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.59 13.51 6.83 3.98M15.41 6.51l-6.82 3.98"/></svg>
);
