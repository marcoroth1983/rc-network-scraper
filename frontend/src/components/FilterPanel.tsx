import { useState, useEffect } from 'react';
import { resolvePlz } from '../api/client';
import { ApiError } from '../types/api';
import type { ListingsFilter } from '../hooks/useListings';

const PLZ_STORAGE_KEY = 'rcn_ref_plz';

interface Props {
  filter: ListingsFilter;
  onChange: (next: ListingsFilter) => void;
}

export default function FilterPanel({ filter, onChange }: Props) {
  const [searchInput, setSearchInput] = useState(filter.search);
  const [distanceInput, setDistanceInput] = useState(filter.max_distance);
  const [plzInput, setPlzInput] = useState(filter.plz);
  const [plzCity, setPlzCity] = useState<string | null>(null);
  const [plzError, setPlzError] = useState<string | null>(null);
  const [plzValidating, setPlzValidating] = useState(false);

  // On mount: restore PLZ from localStorage if URL has none.
  // Calls onChange (not silent) so PLZ propagates to URL and API.
  useEffect(() => {
    if (!filter.plz) {
      const saved = localStorage.getItem(PLZ_STORAGE_KEY);
      if (saved) {
        setPlzInput(saved);
        validateAndApplyPlz(saved); // silent=false → calls onChange → updates URL
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function validateAndApplyPlz(value: string, silent = false) {
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
      if (!silent) {
        onChange({ ...filter, plz: value, page: 1 });
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setPlzError('PLZ nicht gefunden');
      } else {
        setPlzError('Fehler bei der PLZ-Validierung');
      }
    } finally {
      setPlzValidating(false);
    }
  }

  function handlePlzBlur() {
    validateAndApplyPlz(plzInput);
  }

  function handlePlzClear() {
    setPlzInput('');
    setPlzCity(null);
    setPlzError(null);
    localStorage.removeItem(PLZ_STORAGE_KEY);
    onChange({
      ...filter,
      plz: '',
      sort: filter.sort === 'distance' ? 'date' : filter.sort,
      max_distance: '',
      page: 1,
    });
  }

  // hasValidPlz is based on URL filter state (not local plzInput)
  const hasValidPlz = !!filter.plz && !plzError;

  return (
    <div className="bg-white rounded-card shadow-card p-5 mb-6 flex flex-col gap-4">
      {/* Search */}
      <div>
        <label
          htmlFor="search"
          className="block text-xs font-semibold text-gray-500 uppercase tracking-widest mb-1.5"
        >
          Suche
        </label>
        <div className="relative">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <input
            id="search"
            type="text"
            placeholder="Suche nach Titel oder Beschreibung…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onBlur={() => onChange({ ...filter, search: searchInput, page: 1 })}
            onKeyDown={(e) => e.key === 'Enter' && onChange({ ...filter, search: searchInput, page: 1 })}
            className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand bg-gray-50 transition"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {/* PLZ */}
        <div>
          <label
            htmlFor="plz"
            className="block text-xs font-semibold text-gray-500 uppercase tracking-widest mb-1.5"
          >
            Meine PLZ
          </label>
          <div className="relative">
            <input
              id="plz"
              type="text"
              placeholder="PLZ (z.B. 49356)"
              value={plzInput}
              onChange={(e) => setPlzInput(e.target.value)}
              onBlur={handlePlzBlur}
              maxLength={5}
              className={`w-full px-3 py-2.5 rounded-xl border text-sm font-mono focus:outline-none transition ${
                plzCity
                  ? 'border-green-400 bg-green-50 focus:ring-2 focus:ring-green-300'
                  : plzError
                  ? 'border-red-400 bg-gray-50 focus:ring-2 focus:ring-brand/30 focus:border-brand'
                  : 'border-gray-200 bg-gray-50 focus:ring-2 focus:ring-brand/30 focus:border-brand'
              }`}
            />
            {plzValidating && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">
                …
              </span>
            )}
            {plzInput && !plzValidating && (
              <button
                type="button"
                onClick={handlePlzClear}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-sm leading-none"
                aria-label="PLZ löschen"
              >
                ✕
              </button>
            )}
          </div>
          {plzCity && (
            <p className="mt-1 text-xs text-green-600 font-medium">{plzCity}</p>
          )}
          {plzError && (
            <p className="mt-1 text-xs text-red-500">{plzError}</p>
          )}
        </div>

        {/* Max distance */}
        <div>
          <label
            htmlFor="max_distance"
            className="block text-xs font-semibold text-gray-500 uppercase tracking-widest mb-1.5"
          >
            Max. Entfernung
          </label>
          <div className="relative">
            <input
              id="max_distance"
              type="number"
              min={1}
              placeholder="km"
              disabled={!hasValidPlz}
              value={distanceInput}
              onChange={(e) => setDistanceInput(e.target.value)}
              onBlur={() => onChange({ ...filter, max_distance: distanceInput, page: 1 })}
              onKeyDown={(e) => e.key === 'Enter' && onChange({ ...filter, max_distance: distanceInput, page: 1 })}
              className="w-full pr-12 pl-3 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand transition disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium text-gray-400 pointer-events-none">
              km
            </span>
          </div>
        </div>

        {/* Sort */}
        <div>
          <label
            htmlFor="sort"
            className="block text-xs font-semibold text-gray-500 uppercase tracking-widest mb-1.5"
          >
            Sortierung
          </label>
          <select
            id="sort"
            value={filter.sort}
            onChange={(e) => {
              const val = e.target.value as ListingsFilter['sort'];
              if (val === 'distance' && !hasValidPlz) return;
              onChange({ ...filter, sort: val, page: 1 });
            }}
            className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand bg-gray-50 transition appearance-none cursor-pointer"
          >
            <option value="date">Datum ↓</option>
            <option value="price">Preis ↑</option>
            <option value="distance" disabled={!hasValidPlz}>
              Entfernung{!hasValidPlz ? ' (PLZ erforderlich)' : ' ↑'}
            </option>
          </select>
        </div>
      </div>
    </div>
  );
}
