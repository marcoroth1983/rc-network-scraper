import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import type { ListingsFilter } from '../hooks/useListings';

const PLZ_CITY_STORAGE_KEY = 'rcn_ref_plz_city';

interface Props {
  filter: ListingsFilter;
  onChange: (next: ListingsFilter) => void;
  activeCategoryLabel: string;
  onOpenCategoryModal: () => void;
}

const sectionLabel = 'text-[10px] font-semibold uppercase tracking-widest mb-2';
const sectionLabelColor = { color: 'rgba(248,250,252,0.3)' };

export default function FilterPanel({ filter, onChange, activeCategoryLabel, onOpenCategoryModal }: Props) {
  const navigate = useNavigate();
  const [plzCity] = useState<string | null>(() => localStorage.getItem(PLZ_CITY_STORAGE_KEY));
  const [searchInput, setSearchInput] = useState(filter.search);
  const [distanceInput, setDistanceInput] = useState(filter.max_distance);
  const [priceMinInput, setPriceMinInput] = useState(filter.price_min);
  const [priceMaxInput, setPriceMaxInput] = useState(filter.price_max);
  const [filterOpen, setFilterOpen] = useState(false);
  const swipeStartY = useRef<number | null>(null);

  useEffect(() => { setSearchInput(filter.search); }, [filter.search]);
  useEffect(() => { setDistanceInput(filter.max_distance); }, [filter.max_distance]);
  useEffect(() => { setPriceMinInput(filter.price_min); }, [filter.price_min]);
  useEffect(() => { setPriceMaxInput(filter.price_max); }, [filter.price_max]);

  // Lock body scroll when modal is open
  useEffect(() => {
    if (filterOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [filterOpen]);

  const hasValidPlz = !!filter.plz;
  const hasSecondaryFilters =
    filter.category !== 'all' || !!filter.max_distance || filter.sort !== 'date' ||
    filter.sort_dir !== 'desc' || !!filter.price_min || !!filter.price_max;

  const inputClass =
    'placeholder:text-white/30 text-sm focus:outline-none focus:ring-2 focus:ring-aurora-indigo/40 transition';
  const inputStyle = {
    background: 'rgba(255, 255, 255, 0.05)',
    border: '1px solid rgba(255, 255, 255, 0.1)',
    color: 'rgba(248, 250, 252, 0.85)',
  };

  const modal = createPortal(
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-40 sm:hidden transition-opacity duration-300 ${
          filterOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(3px)' }}
        onClick={() => setFilterOpen(false)}
        aria-hidden="true"
      />

      {/* Bottom sheet */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Filteroptionen"
        className={`fixed bottom-0 left-0 right-0 z-50 sm:hidden rounded-t-2xl transition-transform duration-300 ease-out ${
          filterOpen ? 'translate-y-0' : 'translate-y-full'
        }`}
        onTouchStart={(e) => { swipeStartY.current = e.touches[0].clientY; }}
        onTouchEnd={(e) => {
          if (swipeStartY.current === null) return;
          const delta = e.changedTouches[0].clientY - swipeStartY.current;
          swipeStartY.current = null;
          if (delta > 60) setFilterOpen(false);
        }}
        style={{
          background: 'rgba(12, 12, 28, 0.98)',
          backdropFilter: 'blur(24px)',
          WebkitBackdropFilter: 'blur(24px)',
          border: '1px solid rgba(255,255,255,0.09)',
          borderBottom: 'none',
          boxShadow: '0 -8px 40px rgba(0,0,0,0.5)',
          paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 1.5rem)',
        }}
      >
        {/* Drag handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 rounded-full" style={{ background: 'rgba(255,255,255,0.18)' }} aria-hidden="true" />
        </div>

        {/* Header */}
        <div className="px-5 py-3">
          <span className="text-sm font-semibold" style={{ color: '#F8FAFC' }}>Filter</span>
        </div>

        {/* Divider */}
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.07)' }} />

        {/* Content */}
        <div className="px-5 pt-5 flex flex-col gap-5">

          {/* Kategorie */}
          <div>
            <p className={sectionLabel} style={sectionLabelColor}>Kategorie</p>
            <button
              type="button"
              onClick={() => { setFilterOpen(false); onOpenCategoryModal(); }}
              className="w-full flex items-center justify-between gap-2 px-4 py-3 rounded-xl text-sm font-medium transition-colors"
              style={{
                background: 'rgba(167,139,250,0.07)',
                border: '1px solid rgba(167,139,250,0.2)',
                color: '#C4B5FD',
              }}
              aria-label={`Kategorie: ${activeCategoryLabel} — wechseln`}
            >
              <div className="flex items-center gap-2">
                <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <rect x="3" y="3" width="7" height="7" rx="1" />
                  <rect x="14" y="3" width="7" height="7" rx="1" />
                  <rect x="3" y="14" width="7" height="7" rx="1" />
                  <rect x="14" y="14" width="7" height="7" rx="1" />
                </svg>
                <span>{activeCategoryLabel}</span>
              </div>
              <svg className="w-3.5 h-3.5 opacity-40 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
          </div>

          {/* Sortierung */}
          <div>
            <p className={sectionLabel} style={sectionLabelColor}>Sortierung</p>
            <select
              value={`${filter.sort}_${filter.sort_dir}`}
              onChange={(e) => {
                const [field, dir] = e.target.value.split('_') as [ListingsFilter['sort'], 'asc' | 'desc'];
                if (field === 'distance' && !hasValidPlz) return;
                onChange({ ...filter, sort: field, sort_dir: dir, page: 1 });
              }}
              className={`w-full px-4 py-3 rounded-xl ${inputClass} appearance-none cursor-pointer`}
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

          {/* Entfernung */}
          <div>
            <p className={sectionLabel} style={sectionLabelColor}>Entfernung</p>
            <div className="relative">
              <input
                type="number"
                min={1}
                placeholder={hasValidPlz ? 'Max. km' : 'PLZ erforderlich'}
                aria-label="Max. Entfernung in km"
                disabled={!hasValidPlz}
                value={distanceInput}
                onChange={(e) => setDistanceInput(e.target.value)}
                onBlur={() => onChange({ ...filter, max_distance: distanceInput, page: 1 })}
                onKeyDown={(e) => e.key === 'Enter' && onChange({ ...filter, max_distance: distanceInput, page: 1 })}
                className={`w-full pl-4 pr-12 py-3 rounded-xl ${inputClass} disabled:opacity-35 disabled:cursor-not-allowed`}
                style={inputStyle}
              />
              <span className="absolute right-4 top-1/2 -translate-y-1/2 text-xs font-medium pointer-events-none" style={{ color: 'rgba(248,250,252,0.3)' }}>
                km
              </span>
            </div>
          </div>

          {/* Preis */}
          <div>
            <p className={sectionLabel} style={sectionLabelColor}>Preis</p>
            <div className="flex gap-3">
              <div className="relative flex-1">
                <input
                  type="number"
                  min={0}
                  placeholder="Min"
                  aria-label="Mindestpreis"
                  value={priceMinInput}
                  onChange={(e) => setPriceMinInput(e.target.value)}
                  onBlur={() => onChange({ ...filter, price_min: priceMinInput, page: 1 })}
                  onKeyDown={(e) => e.key === 'Enter' && onChange({ ...filter, price_min: priceMinInput, page: 1 })}
                  className={`w-full pl-4 pr-8 py-3 rounded-xl ${inputClass}`}
                  style={inputStyle}
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium pointer-events-none" style={{ color: 'rgba(248,250,252,0.3)' }}>€</span>
              </div>
              <div className="relative flex-1">
                <input
                  type="number"
                  min={0}
                  placeholder="Max"
                  aria-label="Höchstpreis"
                  value={priceMaxInput}
                  onChange={(e) => setPriceMaxInput(e.target.value)}
                  onBlur={() => onChange({ ...filter, price_max: priceMaxInput, page: 1 })}
                  onKeyDown={(e) => e.key === 'Enter' && onChange({ ...filter, price_max: priceMaxInput, page: 1 })}
                  className={`w-full pl-4 pr-8 py-3 rounded-xl ${inputClass}`}
                  style={inputStyle}
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium pointer-events-none" style={{ color: 'rgba(248,250,252,0.3)' }}>€</span>
              </div>
            </div>
          </div>

        </div>
      </div>
    </>,
    document.body,
  );

  return (
    <>
      {/* Sticky search bar — mobile only */}
      <div
        className="sticky top-0 z-20 rounded-none px-4 py-3 mb-4 shadow-aurora-card sm:hidden -mx-3"
        style={{
          background: 'rgba(15, 15, 35, 0.6)',
          backdropFilter: 'blur(20px)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
        }}
      >
        <div className="flex items-center gap-3">
          {/* Search input */}
          <div className="relative flex-1">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5"
              style={{ color: 'rgba(248, 250, 252, 0.35)' }}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
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
              className={`w-full pl-10 py-2.5 rounded-xl ${inputClass}`}
              style={{ ...inputStyle, paddingRight: '2.25rem' }}
            />
            {/* PLZ status indicator — right side of search input */}
            <button
              type="button"
              onClick={() => navigate('/profile')}
              aria-label={plzCity ? `Standort: ${plzCity}` : 'Kein Standort gesetzt — zum Profil'}
              className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center transition-opacity duration-150 hover:opacity-80 cursor-pointer"
            >
              {plzCity ? (
                <svg
                  className="w-5 h-5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                  aria-hidden="true"
                  style={{ color: '#2DD4BF' }}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 2C8.686 2 6 4.686 6 8c0 4.5 6 12 6 12s6-7.5 6-12c0-3.314-2.686-6-6-6z" />
                  <circle cx="12" cy="8" r="2" fill="currentColor" stroke="none" />
                </svg>
              ) : (
                <span
                  className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
                  style={{
                    background: 'rgba(236,72,153,0.15)',
                    border: '1px solid rgba(236,72,153,0.4)',
                    color: '#EC4899',
                  }}
                  aria-hidden="true"
                >
                  !
                </span>
              )}
            </button>
          </div>

          {/* Filter toggle button */}
          <button
            type="button"
            className="relative flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-xl transition"
            style={{
              background: filterOpen ? 'rgba(167,139,250,0.15)' : 'rgba(255,255,255,0.05)',
              border: filterOpen ? '1px solid rgba(167,139,250,0.4)' : '1px solid rgba(255,255,255,0.1)',
              color: filterOpen ? '#C4B5FD' : 'rgba(248,250,252,0.5)',
            }}
            onClick={() => setFilterOpen((o) => !o)}
            aria-label="Filteroptionen öffnen"
            aria-expanded={filterOpen}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <line x1="4" y1="6" x2="20" y2="6" />
              <line x1="8" y1="12" x2="20" y2="12" />
              <line x1="10" y1="18" x2="20" y2="18" />
              <circle cx="4" cy="6" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="8" cy="12" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="10" cy="18" r="1.5" fill="currentColor" stroke="none" />
            </svg>
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
                onKeyDown={(e) => e.key === 'Enter' && onChange({ ...filter, max_distance: distanceInput, page: 1 })}
                className={`w-full pr-8 pl-3 py-2.5 rounded-xl ${inputClass} disabled:opacity-40 disabled:cursor-not-allowed`}
                style={inputStyle}
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium pointer-events-none" style={{ color: 'rgba(248,250,252,0.35)' }}>km</span>
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
      </div>

      {/* Bottom sheet modal — portaled to document.body */}
      {modal}
    </>
  );
}
