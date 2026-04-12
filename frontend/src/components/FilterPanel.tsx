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

  // Input and select shared styles
  const inputClass =
    'text-white placeholder:text-white/30 text-sm focus:outline-none focus:ring-2 focus:ring-aurora-indigo/40 transition';
  const inputStyle = {
    background: 'rgba(255, 255, 255, 0.05)',
    border: '1px solid rgba(255, 255, 255, 0.1)',
  };

  return (
    <div
      className="sticky top-[6.25rem] z-20 rounded-none sm:rounded-card px-4 py-3 mb-4 sm:mb-6 shadow-aurora-card"
      style={{
        background: 'rgba(15, 15, 35, 0.6)',
        backdropFilter: 'blur(20px)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
      }}
    >
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        {/* Search — full width on mobile, grows to fill on sm+ */}
        <div className="relative flex-1">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
            style={{ color: 'rgba(248, 250, 252, 0.35)' }}
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
            className={`w-full pl-10 pr-4 py-2.5 rounded-xl ${inputClass}`}
            style={inputStyle}
          />
        </div>

        {/* Distance + Sort — side by side on mobile, beside search on sm+ */}
        <div className="flex gap-3">
          {/* Max distance */}
          <div className="relative flex-1 sm:w-40 sm:flex-none">
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
              className={`w-full pr-8 pl-3 py-2.5 rounded-xl ${inputClass} disabled:opacity-40 disabled:cursor-not-allowed`}
              style={inputStyle}
            />
            <span
              className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium pointer-events-none"
              style={{ color: 'rgba(248, 250, 252, 0.35)' }}
            >
              km
            </span>
          </div>

          {/* Sort */}
          <div className="flex-1 sm:w-52 sm:flex-none">
            <select
              id="sort"
              value={`${filter.sort}_${filter.sort_dir}`}
              onChange={(e) => {
                const [field, dir] = e.target.value.split('_') as [ListingsFilter['sort'], 'asc' | 'desc'];
                if (field === 'distance' && !hasValidPlz) return;
                onChange({ ...filter, sort: field, sort_dir: dir, page: 1 });
              }}
              className={`w-full px-3 py-2.5 rounded-xl ${inputClass} appearance-none cursor-pointer`}
              style={inputStyle}
            >
              <option value="date_desc" style={{ background: '#0f0f23' }}>Datum ↓</option>
              <option value="date_asc" style={{ background: '#0f0f23' }}>Datum ↑</option>
              <option value="price_asc" style={{ background: '#0f0f23' }}>Preis ↑</option>
              <option value="price_desc" style={{ background: '#0f0f23' }}>Preis ↓</option>
              <option value="distance_asc" disabled={!hasValidPlz} style={{ background: '#0f0f23' }}>
                {!hasValidPlz ? 'Entfernung (PLZ erforderlich)' : 'Entfernung ↑'}
              </option>
              <option value="distance_desc" disabled={!hasValidPlz} style={{ background: '#0f0f23' }}>
                {!hasValidPlz ? 'Entfernung ↓ (PLZ erforderlich)' : 'Entfernung ↓'}
              </option>
            </select>
          </div>
        </div>
      </div>
    </div>
  );
}
