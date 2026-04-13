import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { AuthUser } from '../hooks/useAuth';
import { resolvePlz } from '../api/client';
import { ApiError } from '../types/api';

const PLZ_STORAGE_KEY = 'rcn_ref_plz';
const PLZ_CITY_STORAGE_KEY = 'rcn_ref_plz_city';
const PLZ_LAT_KEY = 'rcn_ref_lat';
const PLZ_LON_KEY = 'rcn_ref_lon';

interface Props {
  user: AuthUser;
  onLogout: () => void;
}

function getInitials(email: string): string {
  const local = email.split('@')[0] ?? '';
  return local.slice(0, 2).toUpperCase();
}

function ChevronLeftIcon() {
  return (
    <svg
      className="w-5 h-5"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
    </svg>
  );
}

export function ProfilePage({ user, onLogout }: Props) {
  const navigate = useNavigate();

  // On sm+ viewports this page is irrelevant — redirect to home.
  // We check via a media query on mount so the redirect is instant on desktop
  // without waiting for a render cycle.
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 640px)');
    if (mq.matches) {
      navigate('/', { replace: true });
      return;
    }
    const handler = (e: MediaQueryListEvent) => {
      if (e.matches) navigate('/', { replace: true });
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [navigate]);

  // PLZ state — mirrors PlzBar logic but writes only to localStorage (no URL params on this page)
  const [plzInput, setPlzInput] = useState(() => localStorage.getItem(PLZ_STORAGE_KEY) ?? '');
  const [plzCity, setPlzCity] = useState<string | null>(
    () => localStorage.getItem(PLZ_CITY_STORAGE_KEY),
  );
  const [plzError, setPlzError] = useState<string | null>(null);
  const [plzValidating, setPlzValidating] = useState(false);

  async function validateAndApplyPlz(value: string) {
    if (!value) {
      setPlzCity(null);
      setPlzError(null);
      return;
    }
    setPlzValidating(true);
    setPlzError(null);
    setPlzCity(null);
    try {
      const result = await resolvePlz(value);
      setPlzCity(result.city);
      localStorage.setItem(PLZ_STORAGE_KEY, value);
      localStorage.setItem(PLZ_CITY_STORAGE_KEY, result.city);
      localStorage.setItem(PLZ_LAT_KEY, String(result.lat));
      localStorage.setItem(PLZ_LON_KEY, String(result.lon));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setPlzError('PLZ nicht gefunden');
      } else {
        setPlzError('Fehler');
      }
    } finally {
      setPlzValidating(false);
    }
  }

  function handlePlzClear() {
    setPlzInput('');
    setPlzCity(null);
    setPlzError(null);
    localStorage.removeItem(PLZ_STORAGE_KEY);
    localStorage.removeItem(PLZ_CITY_STORAGE_KEY);
    localStorage.removeItem(PLZ_LAT_KEY);
    localStorage.removeItem(PLZ_LON_KEY);
  }

  const initials = getInitials(user.email);

  return (
    <div className="flex flex-col" style={{ color: '#F8FAFC' }}>
      {/* Top bar with back button */}
      <div
        className="flex items-center px-4"
        style={{
          height: '56px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
          background: 'rgba(15, 15, 35, 0.5)',
          backdropFilter: 'blur(12px)',
        }}
      >
        <button
          onClick={() => navigate(-1)}
          aria-label="Zurück"
          className="flex items-center justify-center rounded-full transition-all duration-150"
          style={{
            width: '36px',
            height: '36px',
            background: 'rgba(255, 255, 255, 0.04)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            color: 'rgba(248, 250, 252, 0.7)',
          }}
        >
          <ChevronLeftIcon />
        </button>
        <span
          className="ml-3 text-sm font-medium"
          style={{ color: 'rgba(248, 250, 252, 0.85)' }}
        >
          Profil
        </span>
      </div>

      {/* Centered card */}
      <div className="flex-1 flex items-start justify-center px-4 pt-10">
        <div
          className="w-full max-w-sm rounded-2xl p-6"
          style={{
            background: 'rgba(15, 15, 35, 0.6)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            backdropFilter: 'blur(16px)',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
          }}
        >
          {/* Avatar */}
          <div className="flex flex-col items-center gap-3 pb-5">
            <div
              className="flex items-center justify-center rounded-full select-none"
              style={{
                width: '72px',
                height: '72px',
                background: 'rgba(167, 139, 250, 0.15)',
                border: '2px solid rgba(167, 139, 250, 0.40)',
                color: '#A78BFA',
              }}
            >
              {initials.length > 0 ? (
                <span className="text-xl font-semibold leading-none">{initials}</span>
              ) : (
                // Fallback person icon when initials cannot be derived
                <svg
                  className="w-8 h-8"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                  aria-hidden="true"
                >
                  <circle cx="12" cy="8" r="4" />
                  <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" strokeLinecap="round" />
                </svg>
              )}
            </div>

            {/* Email */}
            <p
              className="text-sm text-center break-all"
              style={{ color: 'rgba(248, 250, 252, 0.65)' }}
            >
              {user.email}
            </p>
          </div>

          {/* Divider */}
          <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.08)' }} className="mb-5" />

          {/* PLZ / Standort section */}
          <div className="mb-5">
            <p
              className="text-xs font-medium mb-2"
              style={{ color: 'rgba(248, 250, 252, 0.35)' }}
            >
              Mein Standort
            </p>
            <div className="flex items-center gap-3">
              <div className="relative">
                <input
                  type="text"
                  aria-label="Meine PLZ"
                  placeholder="Meine PLZ"
                  value={plzInput}
                  onChange={(e) => setPlzInput(e.target.value)}
                  onBlur={() => validateAndApplyPlz(plzInput)}
                  onKeyDown={(e) => e.key === 'Enter' && validateAndApplyPlz(plzInput)}
                  maxLength={5}
                  className={`w-28 px-3 py-1.5 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-aurora-indigo/50 transition text-white placeholder:text-white/30 ${
                    plzCity
                      ? 'border-2 border-aurora-teal/60'
                      : plzError
                      ? 'border-2 border-aurora-pink/60'
                      : 'border border-white/15'
                  }`}
                  style={{ background: 'rgba(255, 255, 255, 0.05)' }}
                />
                {plzValidating && (
                  <span
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-xs pointer-events-none"
                    style={{ color: 'rgba(248, 250, 252, 0.35)' }}
                  >
                    …
                  </span>
                )}
                {plzInput && !plzValidating && (
                  <button
                    type="button"
                    onClick={handlePlzClear}
                    className="absolute right-0 top-1/2 -translate-y-1/2 p-2 text-xs leading-none transition"
                    style={{ color: 'rgba(248, 250, 252, 0.35)' }}
                    aria-label="PLZ löschen"
                  >
                    ✕
                  </button>
                )}
              </div>
              {plzCity && (
                <span
                  className="text-sm font-medium"
                  style={{ color: 'rgba(248, 250, 252, 0.65)' }}
                >
                  {plzCity}
                </span>
              )}
              {plzError && (
                <span className="text-xs font-medium text-aurora-pink/80">{plzError}</span>
              )}
            </div>
          </div>

          {/* Divider before logout */}
          <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.08)' }} className="mb-5" />

          {/* Logout button */}
          <button
            onClick={onLogout}
            className="w-full rounded-xl py-2.5 text-sm font-medium transition-all duration-150"
            style={{
              background: 'rgba(167, 139, 250, 0.08)',
              border: '1px solid rgba(167, 139, 250, 0.35)',
              color: '#A78BFA',
            }}
            onPointerEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background =
                'rgba(167, 139, 250, 0.16)';
            }}
            onPointerLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background =
                'rgba(167, 139, 250, 0.08)';
            }}
          >
            Abmelden
          </button>
        </div>
      </div>
    </div>
  );
}
