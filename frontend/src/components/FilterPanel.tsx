import { useState, useEffect } from 'react';
import type { ListingsFilter } from '../hooks/useListings';

interface Props {
  filter: ListingsFilter;
  onChange: (next: ListingsFilter) => void;
}

export default function FilterPanel({ filter, onChange }: Props) {
  const [searchInput, setSearchInput] = useState(filter.search);
  const [distanceInput, setDistanceInput] = useState(filter.max_distance);

  // Keep local inputs in sync when filter changes externally (e.g. PLZ clear resets max_distance)
  useEffect(() => { setSearchInput(filter.search); }, [filter.search]);
  useEffect(() => { setDistanceInput(filter.max_distance); }, [filter.max_distance]);

  // PLZ is managed by PlzBar; here we only read it to enable/disable distance-dependent controls
  const hasValidPlz = !!filter.plz;

  return (
    <div className="bg-white rounded-card shadow-card px-4 py-3 mb-6">
      <div className="flex gap-3 items-center">
        {/* Search — grows to fill available space */}
        <div className="relative flex-1">
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
            onKeyDown={(e) =>
              e.key === 'Enter' && onChange({ ...filter, search: searchInput, page: 1 })
            }
            className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand bg-gray-50 transition"
          />
        </div>

        {/* Max distance */}
        <div className="relative w-40 shrink-0">
          <input
            id="max_distance"
            type="number"
            min={1}
            placeholder="Entfernung"
            aria-label="Max. Entfernung"
            disabled={!hasValidPlz}
            value={distanceInput}
            onChange={(e) => setDistanceInput(e.target.value)}
            onBlur={() => onChange({ ...filter, max_distance: distanceInput, page: 1 })}
            onKeyDown={(e) =>
              e.key === 'Enter' && onChange({ ...filter, max_distance: distanceInput, page: 1 })
            }
            className="w-full pr-8 pl-3 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand transition disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium text-gray-400 pointer-events-none">
            km
          </span>
        </div>

        {/* Sort */}
        <div className="w-52 shrink-0">
          <select
            id="sort"
            value={`${filter.sort}_${filter.sort_dir}`}
            onChange={(e) => {
              const [field, dir] = e.target.value.split('_') as [ListingsFilter['sort'], 'asc' | 'desc'];
              if (field === 'distance' && !hasValidPlz) return;
              onChange({ ...filter, sort: field, sort_dir: dir, page: 1 });
            }}
            className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand bg-gray-50 transition appearance-none cursor-pointer"
          >
            <option value="date_desc">Datum ↓</option>
            <option value="date_asc">Datum ↑</option>
            <option value="price_asc">Preis ↑</option>
            <option value="price_desc">Preis ↓</option>
            <option value="distance_asc" disabled={!hasValidPlz}>
              {!hasValidPlz ? 'Entfernung (PLZ erforderlich)' : 'Entfernung ↑'}
            </option>
            <option value="distance_desc" disabled={!hasValidPlz}>
              {!hasValidPlz ? 'Entfernung ↓ (PLZ erforderlich)' : 'Entfernung ↓'}
            </option>
          </select>
        </div>
      </div>
    </div>
  );
}
