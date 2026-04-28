import { useState, useEffect, useRef } from 'react';
import { useSearchParams, useLocation, useNavigate } from 'react-router-dom';
import { resolvePlz } from '../api/client';
import { ApiError } from '../types/api';
import { getBackground } from '../lib/modalLocation';
import { readFiltersFromParams, writeFiltersToParams } from '../hooks/useListings';
import type { ListingsFilter } from '../hooks/useListings';
import { MODEL_SUBTYPES, MODEL_TYPE_LABELS, availableModelTypes } from '../constants/vocabulary';
import type { ModelType } from '../constants/vocabulary';

const PLZ_STORAGE_KEY = 'rcn_ref_plz';
const PLZ_CITY_STORAGE_KEY = 'rcn_ref_plz_city';
const PLZ_LAT_KEY = 'rcn_ref_lat';
const PLZ_LON_KEY = 'rcn_ref_lon';

interface Props {
  suppressPlzRestore: boolean;
  activeCategoryLabel: string;
  onOpenCategoryModal: () => void;
  onLogout: () => void;
  userEmail: string;
}

export default function PlzBar({
  suppressPlzRestore,
  activeCategoryLabel,
  onOpenCategoryModal,
  onLogout,
  userEmail,
}: Props) {
  const [, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();

  // Read filters from the background location while the detail modal is open,
  // otherwise the URL is `/listings/:id` (no query string) and every buffered
  // input (search, PLZ, distance, price) would flash to empty and potentially
  // overwrite real filter state on the next onBlur. See useInfiniteListings
  // for the same rationale on the fetch side.
  const background = getBackground(location);
  const effectiveSearch = background != null ? background.search : location.search;
  const effectiveParams = new URLSearchParams(
    effectiveSearch.startsWith('?') ? effectiveSearch.slice(1) : effectiveSearch,
  );
  const filter = readFiltersFromParams(effectiveParams);

  // PLZ state
  const [plzInput, setPlzInput] = useState(() => localStorage.getItem(PLZ_STORAGE_KEY) ?? '');
  const [plzCity, setPlzCity] = useState<string | null>(() => localStorage.getItem(PLZ_CITY_STORAGE_KEY));
  const [plzError, setPlzError] = useState<string | null>(null);
  const [plzValidating, setPlzValidating] = useState(false);

  // Buffered inputs
  const [searchInput, setSearchInput] = useState(filter.search);
  const [distanceInput, setDistanceInput] = useState(filter.max_distance);
  const [priceMinInput, setPriceMinInput] = useState(filter.price_min);
  const [priceMaxInput, setPriceMaxInput] = useState(filter.price_max);

  // Popover/dropdown open state
  const [filterOpen, setFilterOpen] = useState(false);
  const [personOpen, setPersonOpen] = useState(false);

  // Click-outside refs
  const filterRef = useRef<HTMLDivElement>(null);
  const personRef = useRef<HTMLDivElement>(null);

  // Sync buffered inputs when URL params change externally
  useEffect(() => { setSearchInput(filter.search); }, [filter.search]);
  useEffect(() => { setDistanceInput(filter.max_distance); }, [filter.max_distance]);
  useEffect(() => { setPriceMinInput(filter.price_min); }, [filter.price_min]);
  useEffect(() => { setPriceMaxInput(filter.price_max); }, [filter.price_max]);

  // Restore PLZ from localStorage when missing from URL.
  // Skip entirely while a detail modal is open (pathname = /listings/:id):
  // setSearchParams() would mutate the DETAIL URL's query and drop the
  // history state that carries `background`. Losing `background` makes
  // DirectHitDetailRedirect re-synthesize a state, which wipes the query
  // again — an infinite loop (see the 454-request network screenshot).
  useEffect(() => {
    if (suppressPlzRestore) return;
    if (location.pathname !== '/') return;
    if (!filter.plz) {
      const saved = localStorage.getItem(PLZ_STORAGE_KEY);
      const savedCity = localStorage.getItem(PLZ_CITY_STORAGE_KEY);
      if (saved && savedCity) {
        setPlzInput(saved);
        setPlzCity(savedCity);
        setSearchParams(writeFiltersToParams({ ...filter, plz: saved, page: 1 }));
        if (!localStorage.getItem(PLZ_LAT_KEY)) {
          resolvePlz(saved)
            .then((result) => {
              localStorage.setItem(PLZ_LAT_KEY, String(result.lat));
              localStorage.setItem(PLZ_LON_KEY, String(result.lon));
            })
            .catch(() => {});
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter.plz, suppressPlzRestore, location.pathname]);

  // Close filter popover on outside click
  useEffect(() => {
    if (!filterOpen) return;
    function handleClick(e: MouseEvent) {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) {
        setFilterOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [filterOpen]);

  // Close person dropdown on outside click
  useEffect(() => {
    if (!personOpen) return;
    function handleClick(e: MouseEvent) {
      if (personRef.current && !personRef.current.contains(e.target as Node)) {
        setPersonOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [personOpen]);

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
      setSearchParams(writeFiltersToParams({ ...filter, plz: value, page: 1 }));
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
    setSearchParams(writeFiltersToParams(
      {
        ...filter,
        plz: '',
        sort: filter.sort === 'distance' ? 'date' : filter.sort,
        max_distance: '',
        page: 1,
      },
    ));
  }

  const hasValidPlz = !!filter.plz;
  const hasActiveFilterBadge = filter.category !== 'all' || !!filter.max_distance ||
    !!filter.price_min || !!filter.price_max ||
    filter.shipping_available === true ||
    !!filter.model_type || !!filter.model_subtype ||
    filter.show_outdated === true || filter.only_sold === true;
  const emailInitial = userEmail.charAt(0).toUpperCase();

  const inputClass =
    'text-white placeholder:text-white/30 text-sm focus:outline-none focus:ring-2 focus:ring-aurora-indigo/40 transition';
  const inputStyle = {
    background: 'rgba(255, 255, 255, 0.05)',
    border: '1px solid rgba(255, 255, 255, 0.1)',
  };

  // Shared panel style — premium dark glass
  const panelStyle = {
    background: 'rgba(12, 12, 28, 0.98)',
    backdropFilter: 'blur(24px)',
    WebkitBackdropFilter: 'blur(24px)',
    border: '1px solid rgba(255, 255, 255, 0.09)',
    boxShadow: '0 16px 48px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.04)',
  };

  // Section label style
  const sectionLabel = 'text-[10px] font-semibold uppercase tracking-widest mb-2.5';
  const sectionLabelColor = { color: 'rgba(248,250,252,0.3)' };

  const divider = <div style={{ borderTop: '1px solid rgba(255,255,255,0.07)' }} />;

  function IconButton({
    onClick,
    active,
    badge,
    ariaLabel,
    children,
  }: {
    onClick: () => void;
    active: boolean;
    badge?: React.ReactNode;
    ariaLabel: string;
    children: React.ReactNode;
  }) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-label={ariaLabel}
        aria-expanded={active}
        className="relative flex-shrink-0 w-9 h-9 flex items-center justify-center rounded-xl transition-all duration-150 cursor-pointer"
        style={
          active
            ? { background: 'rgba(167,139,250,0.18)', border: '1px solid rgba(167,139,250,0.45)', color: '#C4B5FD' }
            : { background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(248,250,252,0.5)' }
        }
      >
        {children}
        {badge}
      </button>
    );
  }

  return (
    <div
      className="hidden sm:block sticky top-14 z-30"
      style={{
        background: 'rgba(15, 15, 35, 0.7)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      <div className="max-w-6xl mx-auto px-4 h-12 flex items-center gap-3">

        {/* Search */}
        <div className="relative flex-1">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
            style={{ color: 'rgba(248,250,252,0.35)' }}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <input
            type="text"
            placeholder="Suche nach Titel oder Beschreibung…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onBlur={() => setSearchParams(writeFiltersToParams({ ...filter, search: searchInput, page: 1 }))}
            onKeyDown={(e) => e.key === 'Enter' && setSearchParams(writeFiltersToParams({ ...filter, search: searchInput, page: 1 }))}
            className={`w-full pl-10 py-2 rounded-xl ${inputClass}`}
            style={{ ...inputStyle, paddingRight: hasValidPlz ? '4.5rem' : '2.25rem' }}
          />
          {/* PLZ status indicator — right side of search input */}
          <button
            type="button"
            onClick={() => { setFilterOpen(false); setPersonOpen((o) => !o); }}
            aria-label={hasValidPlz ? `Standort: ${filter.plz}` : 'Kein Standort gesetzt — klicken zum Eingeben'}
            className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center transition-opacity duration-150 hover:opacity-80 cursor-pointer"
          >
            {hasValidPlz ? (
              <span
                className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold tabular-nums"
                style={{
                  background: 'rgba(45,212,191,0.12)',
                  border: '1px solid rgba(45,212,191,0.3)',
                  color: '#2DD4BF',
                }}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{ background: '#2DD4BF' }}
                  aria-hidden="true"
                />
                {filter.plz}
              </span>
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

        {/* Sort */}
        <select
          value={`${filter.sort}_${filter.sort_dir}`}
          onChange={(e) => {
            const [field, dir] = e.target.value.split('_') as [ListingsFilter['sort'], 'asc' | 'desc'];
            if (field === 'distance' && !hasValidPlz) return;
            setSearchParams(writeFiltersToParams({ ...filter, sort: field, sort_dir: dir, page: 1 }));
          }}
          className={`w-36 px-3 py-2 rounded-xl ${inputClass} appearance-none cursor-pointer`}
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

        {/* ── Filter button + popover ── */}
        <div className="relative" ref={filterRef}>
          <IconButton
            onClick={() => { setPersonOpen(false); setFilterOpen((o) => !o); }}
            active={filterOpen}
            ariaLabel="Filter"
            badge={
              hasActiveFilterBadge && !filterOpen ? (
                <span
                  className="absolute top-1 right-1 w-2 h-2 rounded-full"
                  style={{ background: '#A78BFA' }}
                  aria-hidden="true"
                />
              ) : undefined
            }
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <line x1="4" y1="6" x2="20" y2="6" />
              <line x1="8" y1="12" x2="20" y2="12" />
              <line x1="10" y1="18" x2="20" y2="18" />
              <circle cx="4" cy="6" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="8" cy="12" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="10" cy="18" r="1.5" fill="currentColor" stroke="none" />
            </svg>
          </IconButton>

          {filterOpen && (
            <div
              className="absolute top-full right-0 mt-2.5 w-72 rounded-2xl z-50 overflow-hidden"
              style={panelStyle}
            >
              {/* Kategorie */}
              <div className="px-4 pt-4 pb-3">
                <p className={sectionLabel} style={sectionLabelColor}>Kategorie</p>
                <button
                  type="button"
                  onClick={() => { setFilterOpen(false); onOpenCategoryModal(); }}
                  className="w-full flex items-center justify-between gap-2 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors duration-150 cursor-pointer"
                  style={{ background: 'rgba(167,139,250,0.07)', border: '1px solid rgba(167,139,250,0.2)', color: '#C4B5FD' }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(167,139,250,0.14)'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(167,139,250,0.07)'; }}
                  aria-label={`Kategorie: ${activeCategoryLabel} — wechseln`}
                >
                  <div className="flex items-center gap-2">
                    <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                      <rect x="3" y="3" width="7" height="7" rx="1" />
                      <rect x="14" y="3" width="7" height="7" rx="1" />
                      <rect x="3" y="14" width="7" height="7" rx="1" />
                      <rect x="14" y="14" width="7" height="7" rx="1" />
                    </svg>
                    <span className="truncate">{activeCategoryLabel}</span>
                  </div>
                  <svg className="w-3 h-3 opacity-40 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>
              </div>

              {divider}

              {/* Entfernung */}
              <div className="px-4 pt-3 pb-4">
                <p className={sectionLabel} style={sectionLabelColor}>Entfernung</p>
                <div className="relative">
                  <input
                    type="number"
                    min={1}
                    placeholder={hasValidPlz ? 'Max. km eingeben' : 'PLZ erforderlich'}
                    aria-label="Max. Entfernung in km"
                    disabled={!hasValidPlz}
                    value={distanceInput}
                    onChange={(e) => setDistanceInput(e.target.value)}
                    onBlur={() => setSearchParams(writeFiltersToParams({ ...filter, max_distance: distanceInput, page: 1 }))}
                    onKeyDown={(e) => e.key === 'Enter' && setSearchParams(writeFiltersToParams({ ...filter, max_distance: distanceInput, page: 1 }))}
                    className={`w-full pr-10 pl-3 py-2.5 rounded-xl ${inputClass} disabled:opacity-35 disabled:cursor-not-allowed`}
                    style={inputStyle}
                  />
                  <span
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium pointer-events-none"
                    style={{ color: 'rgba(248,250,252,0.3)' }}
                  >
                    km
                  </span>
                </div>
              </div>

              {divider}

              {/* Preis */}
              <div className="px-4 pt-3 pb-4">
                <p className={sectionLabel} style={sectionLabelColor}>Preis</p>
                <div className="flex gap-2">
                  {/* Min */}
                  <div className="relative flex-1">
                    <input
                      type="number"
                      min={0}
                      placeholder="Min"
                      aria-label="Mindestpreis"
                      value={priceMinInput}
                      onChange={(e) => setPriceMinInput(e.target.value)}
                      onBlur={() => setSearchParams(writeFiltersToParams({ ...filter, price_min: priceMinInput, page: 1 }))}
                      onKeyDown={(e) => e.key === 'Enter' && setSearchParams(writeFiltersToParams({ ...filter, price_min: priceMinInput, page: 1 }))}
                      className={`w-full pl-3 pr-7 py-2.5 rounded-xl ${inputClass}`}
                      style={inputStyle}
                    />
                    <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs font-medium pointer-events-none" style={{ color: 'rgba(248,250,252,0.3)' }}>€</span>
                  </div>
                  {/* Max */}
                  <div className="relative flex-1">
                    <input
                      type="number"
                      min={0}
                      placeholder="Max"
                      aria-label="Höchstpreis"
                      value={priceMaxInput}
                      onChange={(e) => setPriceMaxInput(e.target.value)}
                      onBlur={() => setSearchParams(writeFiltersToParams({ ...filter, price_max: priceMaxInput, page: 1 }))}
                      onKeyDown={(e) => e.key === 'Enter' && setSearchParams(writeFiltersToParams({ ...filter, price_max: priceMaxInput, page: 1 }))}
                      className={`w-full pl-3 pr-7 py-2.5 rounded-xl ${inputClass}`}
                      style={inputStyle}
                    />
                    <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs font-medium pointer-events-none" style={{ color: 'rgba(248,250,252,0.3)' }}>€</span>
                  </div>
                </div>
              </div>

              {divider}

              {/* Versand */}
              <div className="px-4 pt-3 pb-3">
                <p className={sectionLabel} style={sectionLabelColor}>Versand</p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={`px-3 py-1.5 rounded-full text-sm transition ${
                      filter.shipping_available === true
                        ? 'bg-aurora-indigo text-white'
                        : 'bg-white/10 text-white/70 hover:bg-white/20'
                    }`}
                    onClick={() => setSearchParams(writeFiltersToParams({
                      ...filter,
                      shipping_available: filter.shipping_available === true ? undefined : true,
                      page: 1,
                    }))}
                  >
                    Versand möglich
                  </button>
                </div>
              </div>

              {/* Modelltyp + Subtyp — only shown when category implies model types */}
              {availableModelTypes(filter.category).length > 0 && (
                <>
                  {divider}
                  <div className="px-4 pt-3 pb-3">
                    <p className={sectionLabel} style={sectionLabelColor}>Modelltyp</p>
                    <select
                      value={filter.model_type ?? ''}
                      onChange={(e) => {
                        const val = e.target.value;
                        setSearchParams(writeFiltersToParams({
                          ...filter,
                          model_type: val || undefined,
                          model_subtype: undefined,
                          page: 1,
                        }));
                      }}
                      className={`w-full px-3 py-2 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-aurora-indigo/40 transition appearance-none cursor-pointer`}
                      style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(248,250,252,0.85)' }}
                      aria-label="Modelltyp"
                    >
                      <option value="" style={{ background: '#0f0f23' }}>Alle Typen</option>
                      {availableModelTypes(filter.category).map((t) => (
                        <option key={t} value={t} style={{ background: '#0f0f23' }}>
                          {MODEL_TYPE_LABELS[t]}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="px-4 pt-0 pb-4">
                    <p className={sectionLabel} style={sectionLabelColor}>Subtyp</p>
                    <select
                      value={filter.model_subtype ?? ''}
                      onChange={(e) => setSearchParams(writeFiltersToParams({ ...filter, model_subtype: e.target.value || undefined, page: 1 }))}
                      disabled={!filter.model_type}
                      className={`w-full px-3 py-2 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-aurora-indigo/40 transition appearance-none cursor-pointer disabled:opacity-35 disabled:cursor-not-allowed`}
                      style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(248,250,252,0.85)' }}
                      aria-label="Subtyp"
                    >
                      <option value="" style={{ background: '#0f0f23' }}>Alle Subtypen</option>
                      {filter.model_type &&
                        MODEL_SUBTYPES[filter.model_type as ModelType]?.map((s) => (
                          <option key={s} value={s} style={{ background: '#0f0f23' }}>
                            {s}
                          </option>
                        ))}
                    </select>
                  </div>
                </>
              )}

              {divider}

              {/* Ansicht */}
              <div className="px-4 pt-3 pb-4">
                <p className={sectionLabel} style={sectionLabelColor}>Ansicht</p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={`px-3 py-1.5 rounded-full text-sm transition ${
                      filter.only_sold === true
                        ? 'bg-aurora-indigo text-white'
                        : 'bg-white/10 text-white/70 hover:bg-white/20'
                    }`}
                    onClick={() => setSearchParams(writeFiltersToParams({
                      ...filter,
                      only_sold: filter.only_sold === true ? undefined : true,
                      show_outdated: undefined,
                      page: 1,
                    }))}
                  >
                    Nur Verkaufte
                  </button>
                  <button
                    type="button"
                    className={`px-3 py-1.5 rounded-full text-sm transition ${
                      filter.show_outdated === true
                        ? 'bg-aurora-indigo text-white'
                        : 'bg-white/10 text-white/70 hover:bg-white/20'
                    }`}
                    disabled={filter.only_sold === true}
                    onClick={() => setSearchParams(writeFiltersToParams({
                      ...filter,
                      show_outdated: filter.show_outdated === true ? undefined : true,
                      page: 1,
                    }))}
                  >
                    Ältere anzeigen
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── Person button + dropdown ── */}
        <div className="relative" ref={personRef}>
          <IconButton
            onClick={() => { setFilterOpen(false); setPersonOpen((o) => !o); }}
            active={personOpen}
            ariaLabel="Profil & Einstellungen"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" strokeLinecap="round" />
            </svg>
          </IconButton>

          {personOpen && (
            <div
              className="absolute top-full right-0 mt-2.5 w-72 rounded-2xl z-50 overflow-hidden"
              style={panelStyle}
            >
              {/* Email header */}
              <div className="px-4 py-4 flex items-center gap-3">
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 text-sm font-bold"
                  style={{ background: 'linear-gradient(135deg, #6366F1 0%, #A78BFA 100%)', color: '#fff' }}
                  aria-hidden="true"
                >
                  {emailInitial}
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-medium mb-0.5" style={{ color: 'rgba(248,250,252,0.35)' }}>Angemeldet als</p>
                  <p className="text-sm font-medium truncate" style={{ color: '#EDEDEF' }}>{userEmail}</p>
                </div>
              </div>

              {divider}

              {/* Standort / PLZ */}
              <div className="px-4 py-4">
                <p className={sectionLabel} style={sectionLabelColor}>Standort</p>
                <div className="relative">
                  <input
                    type="text"
                    aria-label="Meine PLZ"
                    placeholder="PLZ eingeben…"
                    value={plzInput}
                    onChange={(e) => setPlzInput(e.target.value)}
                    onBlur={() => validateAndApplyPlz(plzInput)}
                    onKeyDown={(e) => e.key === 'Enter' && validateAndApplyPlz(plzInput)}
                    maxLength={5}
                    className={`w-full px-3 py-2.5 pr-8 rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-aurora-indigo/50 transition text-white placeholder:text-white/30 ${
                      plzCity ? 'border-2 border-aurora-teal/60' : plzError ? 'border-2 border-aurora-pink/60' : ''
                    }`}
                    style={{
                      background: 'rgba(255,255,255,0.05)',
                      ...(plzCity || plzError ? {} : { border: '1px solid rgba(255,255,255,0.1)' }),
                    }}
                  />
                  {plzValidating && (
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs pointer-events-none" style={{ color: 'rgba(248,250,252,0.35)' }}>…</span>
                  )}
                  {plzInput && !plzValidating && (
                    <button
                      type="button"
                      onClick={handlePlzClear}
                      className="absolute right-0 top-1/2 -translate-y-1/2 p-2.5 text-xs leading-none transition-opacity hover:opacity-80 cursor-pointer"
                      style={{ color: 'rgba(248,250,252,0.35)' }}
                      aria-label="PLZ löschen"
                    >
                      ✕
                    </button>
                  )}
                </div>
                {plzCity && (
                  <div className="mt-2 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: '#2DD4BF' }} aria-hidden="true" />
                    <p className="text-xs font-medium" style={{ color: 'rgba(45,212,191,0.85)' }}>{plzCity}</p>
                  </div>
                )}
                {plzError && (
                  <p className="mt-2 text-xs font-medium" style={{ color: '#EC4899' }}>{plzError}</p>
                )}
              </div>

              {divider}

              {/* Weitere Einstellungen (Telegram, Admin-Panel, ...) */}
              <button
                type="button"
                onClick={() => { setPersonOpen(false); navigate('/profile'); }}
                className="w-full flex items-center gap-3 px-4 py-3.5 text-sm transition-colors duration-150 cursor-pointer"
                style={{ color: 'rgba(248,250,252,0.5)' }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.04)';
                  (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.75)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                  (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.5)';
                }}
              >
                <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
                </svg>
                <span>Einstellungen</span>
              </button>

              {divider}

              {/* Abmelden */}
              <button
                type="button"
                onClick={() => { setPersonOpen(false); onLogout(); }}
                className="w-full flex items-center gap-3 px-4 py-3.5 text-sm transition-colors duration-150 cursor-pointer"
                style={{ color: 'rgba(248,250,252,0.4)' }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.04)';
                  (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.65)';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                  (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.4)';
                }}
              >
                <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
                  <polyline points="16 17 21 12 16 7" />
                  <line x1="21" y1="12" x2="9" y2="12" />
                </svg>
                <span>Abmelden</span>
              </button>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
