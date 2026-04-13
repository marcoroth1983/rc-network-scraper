import { useState, useEffect } from 'react';
import type { ListingsFilter } from '../hooks/useListings';

interface Props {
  filter: ListingsFilter;
  onChange: (next: ListingsFilter) => void;
  activeCategoryLabel: string;
  onOpenCategoryModal: () => void;
}

export default function FilterPanel({ filter, onChange, activeCategoryLabel, onOpenCategoryModal }: Props) {
  const [searchInput, setSearchInput] = useState(filter.search);
  const [distanceInput, setDistanceInput] = useState(filter.max_distance);
  const [priceMinInput, setPriceMinInput] = useState(filter.price_min);
  const [priceMaxInput, setPriceMaxInput] = useState(filter.price_max);

  const [filterOpen, setFilterOpen] = useState(false);

  // Keep local inputs in sync when filter changes externally (e.g. PLZ clear resets max_distance)
  useEffect(() => { setSearchInput(filter.search); }, [filter.search]);
  useEffect(() => { setDistanceInput(filter.max_distance); }, [filter.max_distance]);
  useEffect(() => { setPriceMinInput(filter.price_min); }, [filter.price_min]);
  useEffect(() => { setPriceMaxInput(filter.price_max); }, [filter.price_max]);

  // PLZ is managed by PlzBar; here we only read it to enable/disable distance-dependent controls
  const hasValidPlz = !!filter.plz;

  // Show badge on filter button when any secondary filter is active
  const hasSecondaryFilters =
    filter.category !== 'all' || !!filter.max_distance || filter.sort !== 'date' || filter.sort_dir !== 'desc' || !!filter.price_min || !!filter.price_max;

  // Input and select shared styles
  const inputClass =
    'text-white placeholder:text-white/30 text-sm focus:outline-none focus:ring-2 focus:ring-aurora-indigo/40 transition';
  const inputStyle = {
    background: 'rgba(255, 255, 255, 0.05)',
    border: '1px solid rgba(255, 255, 255, 0.1)',
  };

  return (
    <div
      className="sticky top-0 z-20 rounded-none px-4 py-3 mb-4 shadow-aurora-card sm:hidden -mx-3"
      style={{
        background: 'rgba(15, 15, 35, 0.6)',
        backdropFilter: 'blur(20px)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
      }}
    >
      {/* Row 1: Search + filter toggle (mobile) | Search + distance + sort (desktop) */}
      <div className="flex items-center gap-3">
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

        {/* Filter toggle button — mobile only */}
        <button
          type="button"
          className="relative sm:hidden flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-xl transition"
          style={{
            background: filterOpen
              ? 'rgba(167, 139, 250, 0.15)'
              : 'rgba(255, 255, 255, 0.05)',
            border: filterOpen
              ? '1px solid rgba(167, 139, 250, 0.4)'
              : '1px solid rgba(255, 255, 255, 0.1)',
            color: filterOpen ? '#C4B5FD' : 'rgba(248, 250, 252, 0.5)',
          }}
          onClick={() => setFilterOpen((o) => !o)}
          aria-label="Filter"
          aria-expanded={filterOpen}
        >
          {/* Sliders / tune icon */}
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <line x1="4" y1="6" x2="20" y2="6" />
            <line x1="8" y1="12" x2="20" y2="12" />
            <line x1="10" y1="18" x2="20" y2="18" />
            <circle cx="4" cy="6" r="1.5" fill="currentColor" stroke="none" />
            <circle cx="8" cy="12" r="1.5" fill="currentColor" stroke="none" />
            <circle cx="10" cy="18" r="1.5" fill="currentColor" stroke="none" />
          </svg>
          {/* Active indicator dot */}
          {hasSecondaryFilters && (
            <span
              className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full"
              style={{ background: '#A78BFA' }}
              aria-hidden="true"
            />
          )}
        </button>

        {/* Distance — desktop only */}
        <div className="hidden sm:block sm:w-40">
          <div className="relative">
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
        </div>

        {/* Sort — desktop only */}
        <div className="hidden sm:block sm:w-52">
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

      {/* Row 2: Expandable filter panel — mobile only */}
      {filterOpen && (
        <div className="sm:hidden mt-3 flex flex-col gap-3">
          {/* Category */}
          <button
            type="button"
            onClick={onOpenCategoryModal}
            className="w-full flex items-center justify-between gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition"
            style={{
              background: 'rgba(167, 139, 250, 0.07)',
              border: '1px solid rgba(167, 139, 250, 0.2)',
              color: '#C4B5FD',
            }}
            aria-label={`Kategorie: ${activeCategoryLabel} — wechseln`}
          >
            <div className="flex items-center gap-2">
              <svg
                className="w-3.5 h-3.5 flex-shrink-0"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                aria-hidden="true"
              >
                <rect x="3" y="3" width="7" height="7" rx="1" />
                <rect x="14" y="3" width="7" height="7" rx="1" />
                <rect x="3" y="14" width="7" height="7" rx="1" />
                <rect x="14" y="14" width="7" height="7" rx="1" />
              </svg>
              <span>{activeCategoryLabel}</span>
            </div>
            <svg
              className="w-3.5 h-3.5 opacity-50"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.5}
              aria-hidden="true"
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>

          {/* Distance + Sort */}
          <div className="flex gap-3">
            <div className="relative flex-1">
              <input
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
            <div className="flex-1">
              <select
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
                  {!hasValidPlz ? 'Entfernung (PLZ erf.)' : 'Entfernung ↑'}
                </option>
                <option value="distance_desc" disabled={!hasValidPlz} style={{ background: '#0f0f23' }}>
                  {!hasValidPlz ? 'Entfernung ↓ (PLZ erf.)' : 'Entfernung ↓'}
                </option>
              </select>
            </div>
          </div>

          {/* Price range */}
          <div className="flex gap-3">
            <div className="relative flex-1">
              <input
                type="number"
                min={0}
                placeholder="Min €"
                aria-label="Mindestpreis"
                value={priceMinInput}
                onChange={(e) => setPriceMinInput(e.target.value)}
                onBlur={() => onChange({ ...filter, price_min: priceMinInput, page: 1 })}
                onKeyDown={(e) => e.key === 'Enter' && onChange({ ...filter, price_min: priceMinInput, page: 1 })}
                className={`w-full pl-3 pr-6 py-2.5 rounded-xl ${inputClass}`}
                style={inputStyle}
              />
              <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs font-medium pointer-events-none" style={{ color: 'rgba(248,250,252,0.35)' }}>€</span>
            </div>
            <div className="relative flex-1">
              <input
                type="number"
                min={0}
                placeholder="Max €"
                aria-label="Höchstpreis"
                value={priceMaxInput}
                onChange={(e) => setPriceMaxInput(e.target.value)}
                onBlur={() => onChange({ ...filter, price_max: priceMaxInput, page: 1 })}
                onKeyDown={(e) => e.key === 'Enter' && onChange({ ...filter, price_max: priceMaxInput, page: 1 })}
                className={`w-full pl-3 pr-6 py-2.5 rounded-xl ${inputClass}`}
                style={inputStyle}
              />
              <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs font-medium pointer-events-none" style={{ color: 'rgba(248,250,252,0.35)' }}>€</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
