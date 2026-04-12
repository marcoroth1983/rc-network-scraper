import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { resolvePlz } from '../api/client';
import { ApiError } from '../types/api';
import { readFiltersFromParams, writeFiltersToParams } from '../hooks/useListings';

const PLZ_STORAGE_KEY = 'rcn_ref_plz';
const PLZ_CITY_STORAGE_KEY = 'rcn_ref_plz_city';
const PLZ_LAT_KEY = 'rcn_ref_lat';
const PLZ_LON_KEY = 'rcn_ref_lon';

interface Props {
  onOpenFavorites: () => void;
  totalUnread: number;
  suppressPlzRestore: boolean;
}

export default function PlzBar({ onOpenFavorites, totalUnread, suppressPlzRestore }: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filter = readFiltersFromParams(searchParams);

  const [plzInput, setPlzInput] = useState(() => localStorage.getItem(PLZ_STORAGE_KEY) ?? '');
  const [plzCity, setPlzCity] = useState<string | null>(() => localStorage.getItem(PLZ_CITY_STORAGE_KEY));
  const [plzError, setPlzError] = useState<string | null>(null);
  const [plzValidating, setPlzValidating] = useState(false);

  // Restore PLZ from localStorage whenever it's missing from the URL.
  // Covers: initial page load AND back-navigation from detail page (which drops URL params).
  // Skip restore when a saved search is active — it may intentionally have no PLZ.
  useEffect(() => {
    if (suppressPlzRestore) return;
    if (!filter.plz) {
      const saved = localStorage.getItem(PLZ_STORAGE_KEY);
      const savedCity = localStorage.getItem(PLZ_CITY_STORAGE_KEY);
      if (saved && savedCity) {
        setPlzInput(saved);
        setPlzCity(savedCity);
        writeFiltersToParams({ ...filter, plz: saved, page: 1 }, setSearchParams);
        // Silently fetch lat/lon if not yet cached (needed for distance computation in DetailPage)
        if (!localStorage.getItem(PLZ_LAT_KEY)) {
          resolvePlz(saved).then((result) => {
            localStorage.setItem(PLZ_LAT_KEY, String(result.lat));
            localStorage.setItem(PLZ_LON_KEY, String(result.lon));
          }).catch(() => {});
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter.plz, suppressPlzRestore]);

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
      writeFiltersToParams({ ...filter, plz: value, page: 1 }, setSearchParams);
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
    writeFiltersToParams(
      {
        ...filter,
        plz: '',
        sort: filter.sort === 'distance' ? 'date' : filter.sort,
        max_distance: '',
        page: 1,
      },
      setSearchParams,
    );
  }

  const badgeLabel = totalUnread > 99 ? '99+' : String(totalUnread);

  return (
    <div
      className="sticky top-14 z-30 backdrop-blur shadow-sm"
      style={{ background: 'rgba(15, 15, 35, 0.7)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}
    >
      <div className="max-w-6xl mx-auto px-4 h-11 flex items-center justify-between gap-4">
        {/* PLZ input + city label */}
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
              className="text-xs sm:text-sm font-medium"
              style={{ color: 'rgba(248, 250, 252, 0.65)' }}
            >
              {plzCity}
            </span>
          )}
          {plzError && (
            <span className="text-xs font-medium text-aurora-pink/80">{plzError}</span>
          )}
        </div>

        {/* Merkliste button with unread badge */}
        <div className="relative inline-flex">
          <button
            onClick={onOpenFavorites}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition"
            style={{
              color: '#A78BFA',
              background: 'rgba(167, 139, 250, 0.08)',
              border: '1px solid rgba(167, 139, 250, 0.3)',
            }}
            aria-label="Merkliste öffnen"
          >
            <svg
              className="w-4 h-4"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              fill="none"
              aria-hidden="true"
            >
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
            </svg>
            <span className="hidden sm:inline">Merkliste</span>
          </button>
          {totalUnread > 0 && (
            <span
              aria-label={`${badgeLabel} neue Treffer`}
              style={{
                position: 'absolute',
                top: -6,
                right: -6,
                minWidth: 18,
                height: 18,
                padding: '0 4px',
                borderRadius: 9,
                background: '#EC4899',
                color: '#F8FAFC',
                fontSize: 10,
                fontWeight: 700,
                lineHeight: '18px',
                textAlign: 'center',
                pointerEvents: 'none',
                boxShadow: '0 0 0 2px rgba(15,15,35,0.85)',
              }}
            >
              {badgeLabel}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
