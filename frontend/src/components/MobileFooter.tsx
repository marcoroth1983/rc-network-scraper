import { useNavigate, useLocation } from 'react-router-dom';

interface Props {
  totalUnread: number;
}

function SearchIcon() {
  return (
    <svg
      className="w-7 h-7"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.75}
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <path strokeLinecap="round" d="M16.5 16.5l4 4" />
    </svg>
  );
}

function StarIcon() {
  return (
    <svg
      className="w-7 h-7"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.75}
      fill="none"
      aria-hidden="true"
    >
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  );
}

function PersonIcon() {
  return (
    <svg
      className="w-7 h-7"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.75}
      aria-hidden="true"
    >
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" strokeLinecap="round" />
    </svg>
  );
}

const ACTIVE_COLOR = '#A78BFA';
const INACTIVE_COLOR = 'rgba(248,250,252,0.35)';

export function MobileFooter({ totalUnread }: Props) {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const isProfile = pathname === '/profile';
  const isFavorites = pathname === '/favorites';
  // Suche is active only on routes that are not /profile or /favorites
  const isSearch = !isProfile && !isFavorites;

  return (
    <div
      className="sm:hidden fixed bottom-0 left-0 right-0 z-50 flex items-stretch"
      style={{
        height: '64px',
        background: 'rgba(15,15,35,0.88)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        borderTop: '1px solid rgba(255,255,255,0.08)',
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
      }}
    >
      {/* Suche tab */}
      <button
        onClick={() => navigate('/')}
        aria-label="Suche"
        className="flex-1 flex flex-col items-center justify-center gap-1 transition-colors duration-150"
        style={{ color: isSearch ? ACTIVE_COLOR : INACTIVE_COLOR }}
      >
        {/* Active indicator pill */}
        <span
          className="rounded-full"
          style={{
            width: '20px',
            height: '3px',
            background: isSearch ? ACTIVE_COLOR : 'transparent',
            marginBottom: '2px',
          }}
          aria-hidden="true"
        />
        <SearchIcon />
        <span className="text-[11px] font-medium leading-none">Suche</span>
      </button>

      {/* Merkliste tab */}
      <button
        onClick={() => navigate('/favorites')}
        aria-label="Merkliste"
        className="flex-1 flex flex-col items-center justify-center gap-1 transition-colors duration-150 relative"
        style={{ color: isFavorites ? ACTIVE_COLOR : INACTIVE_COLOR }}
      >
        <span
          className="rounded-full"
          style={{
            width: '20px',
            height: '3px',
            background: isFavorites ? ACTIVE_COLOR : 'transparent',
            marginBottom: '2px',
          }}
          aria-hidden="true"
        />
        <div className="relative">
          <StarIcon />
          {totalUnread > 0 && (
            <span
              aria-label="Neue Treffer in Merkliste"
              style={{
                position: 'absolute',
                top: -2,
                right: -4,
                width: '9px',
                height: '9px',
                borderRadius: '50%',
                background: '#EC4899',
                pointerEvents: 'none',
                boxShadow: '0 0 0 2px rgba(15,15,35,0.88)',
              }}
            />
          )}
        </div>
        <span className="text-[11px] font-medium leading-none">Merkliste</span>
      </button>

      {/* Profil tab */}
      <button
        onClick={() => navigate('/profile')}
        aria-label="Profil"
        className="flex-1 flex flex-col items-center justify-center gap-1 transition-colors duration-150"
        style={{ color: isProfile ? ACTIVE_COLOR : INACTIVE_COLOR }}
      >
        <span
          className="rounded-full"
          style={{
            width: '20px',
            height: '3px',
            background: isProfile ? ACTIVE_COLOR : 'transparent',
            marginBottom: '2px',
          }}
          aria-hidden="true"
        />
        <PersonIcon />
        <span className="text-[11px] font-medium leading-none">Profil</span>
      </button>
    </div>
  );
}
