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
}

export default function PlzBar({ onOpenFavorites }: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filter = readFiltersFromParams(searchParams);

  const [plzInput, setPlzInput] = useState(() => localStorage.getItem(PLZ_STORAGE_KEY) ?? '');
  const [plzCity, setPlzCity] = useState<string | null>(() => localStorage.getItem(PLZ_CITY_STORAGE_KEY));
  const [plzError, setPlzError] = useState<string | null>(null);
  const [plzValidating, setPlzValidating] = useState(false);

  // Restore PLZ from localStorage whenever it's missing from the URL.
  // Covers: initial page load AND back-navigation from detail page (which drops URL params).
  useEffect(() => {
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
  }, [filter.plz]);

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

  return (
    <div className="sticky top-14 z-30 bg-brand shadow-sm">
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
              className={`w-28 px-3 py-1 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-white/50 transition text-gray-900 ${
                plzCity
                  ? 'bg-green-50 border-2 border-green-400'
                  : plzError
                  ? 'bg-red-50 border-2 border-red-400'
                  : 'bg-white/90 border border-white/30'
              }`}
            />
            {plzValidating && (
              <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">
                …
              </span>
            )}
            {plzInput && !plzValidating && (
              <button
                type="button"
                onClick={handlePlzClear}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700 text-xs leading-none"
                aria-label="PLZ löschen"
              >
                ✕
              </button>
            )}
          </div>
          {plzCity && (
            <span className="text-sm text-white font-medium drop-shadow-sm">{plzCity}</span>
          )}
          {plzError && (
            <span className="text-xs text-red-200 font-medium">{plzError}</span>
          )}
        </div>

        {/* Merkliste button */}
        <button
          onClick={onOpenFavorites}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-sm text-white font-medium transition"
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
          Merkliste
        </button>
      </div>
    </div>
  );
}
