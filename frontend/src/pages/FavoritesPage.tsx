import { useEffect, useState, useCallback } from 'react';
import React from 'react';
import { useNavigate } from 'react-router-dom';
import { getFavorites } from '../api/client';
import { useSavedSearches } from '../hooks/useSavedSearches';
import type { ListingSummary, SavedSearch } from '../types/api';
import { writeFiltersToParams } from '../hooks/useListings';
import { filterFromSavedSearch } from '../lib/savedSearchCriteria';
import FavoriteCard from '../components/FavoriteCard';
import { useConfirm } from '../components/ConfirmDialog';

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------



function TrashIcon() {
  return (
    <svg
      className="w-4 h-4"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
      <path d="M10 11v6M14 11v6" />
      <path d="M9 6V4h6v2" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// SavedSearchCard — same as in FavoritesModal, kept local to avoid coupling
// ---------------------------------------------------------------------------

interface SavedSearchCardProps {
  search: SavedSearch;
  onActivate: () => void;
  onToggle: () => void;
  onRemove: () => void;
}

function SavedSearchCard({ search, onActivate, onToggle, onRemove }: SavedSearchCardProps) {
  const confirm = useConfirm();
  const displayName = search.name ?? search.search ?? 'Alle Anzeigen';
  const hasDistance = search.max_distance != null;

  const sortLabel: Record<string, string> = { date: 'Datum', price: 'Preis', distance: 'Entfernung' };
  const sortDir = search.sort_dir === 'asc' ? '↑' : '↓';

  const filterParts: string[] = [];
  if (search.plz) filterParts.push(`PLZ ${search.plz}`);
  if (hasDistance) filterParts.push(`bis ${search.max_distance} km`);
  if (search.sort) filterParts.push(`${sortLabel[search.sort] ?? search.sort} ${sortDir}`);
  if (search.model_type) filterParts.push(search.model_type);
  if (search.model_subtype) filterParts.push(search.model_subtype);
  if (search.price_min != null || search.price_max != null) {
    const pricePart = search.price_min != null && search.price_max != null
      ? `${search.price_min}–${search.price_max} €`
      : search.price_min != null
      ? `ab ${search.price_min} €`
      : `bis ${search.price_max} €`;
    filterParts.push(pricePart);
  }
  if (search.drive_type) filterParts.push(search.drive_type);
  if (search.completeness) filterParts.push(search.completeness);
  if (search.shipping_available) filterParts.push('Versand');
  if (search.only_sold) filterParts.push('Verkauft');
  if (search.show_outdated) filterParts.push('inkl. veraltet');
  const filterSummary = filterParts.join(', ');

  return (
    <div
      style={{
        background: 'rgba(255,255,255,0.04)',
        border: `1px solid ${search.is_active ? 'rgba(99,102,241,0.3)' : 'rgba(255,255,255,0.06)'}`,
        borderRadius: 12,
        padding: '12px 14px',
        opacity: search.is_active ? 1 : 0.5,
        cursor: 'pointer',
        transition: 'opacity 0.15s, border-color 0.15s',
      }}
      onClick={onActivate}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onActivate();
        }
      }}
      aria-label={`Gespeicherte Suche aktivieren: ${displayName}`}
    >
      <div className="flex items-start justify-between gap-2">
        {/* Left: name + filter summary */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-sm font-semibold truncate"
              style={{ color: '#F8FAFC' }}
            >
              {displayName}
            </span>
            {search.match_count > 0 && (
              <span
                className="inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-bold"
                style={{
                  background: 'rgba(236,72,153,0.15)',
                  border: '1px solid rgba(236,72,153,0.4)',
                  color: '#EC4899',
                  flexShrink: 0,
                }}
              >
                {search.match_count}
              </span>
            )}
          </div>
          {filterSummary && (
            <p
              className="text-xs mt-0.5 truncate"
              style={{ color: 'rgba(248,250,252,0.45)' }}
            >
              {filterSummary}
            </p>
          )}
        </div>

        {/* Right: toggle + delete */}
        <div
          className="flex items-center gap-2 flex-shrink-0"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Toggle switch */}
          <button
            type="button"
            role="switch"
            aria-checked={search.is_active}
            aria-label={search.is_active ? 'Suche deaktivieren' : 'Suche aktivieren'}
            onClick={onToggle}
            style={{
              width: 36,
              height: 20,
              borderRadius: 10,
              background: search.is_active ? '#6366F1' : 'rgba(255,255,255,0.12)',
              border: `1px solid ${search.is_active ? '#6366F1' : 'rgba(255,255,255,0.15)'}`,
              position: 'relative',
              transition: 'background 0.2s, border-color 0.2s',
              cursor: 'pointer',
              flexShrink: 0,
            }}
          >
            <span
              style={{
                position: 'absolute',
                top: 2,
                left: search.is_active ? 18 : 2,
                width: 14,
                height: 14,
                borderRadius: '50%',
                background: '#F8FAFC',
                transition: 'left 0.2s',
                display: 'block',
              }}
            />
          </button>

          {/* Delete button */}
          <button
            type="button"
            aria-label="Gespeicherte Suche löschen"
            onClick={async () => {
              const ok = await confirm({
                title: 'Gespeicherte Suche löschen?',
                message: `„${displayName}" wird dauerhaft entfernt.`,
                confirmLabel: 'Löschen',
                destructive: true,
              });
              if (ok) onRemove();
            }}
            className="p-1 rounded transition-colors"
            style={{ color: 'rgba(248,250,252,0.3)' }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = '#EC4899';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.3)';
            }}
          >
            <TrashIcon />
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab style helper — identical to FavoritesModal
// ---------------------------------------------------------------------------

function tabStyle(active: boolean): React.CSSProperties {
  return {
    padding: '14px 0',
    marginRight: 24,
    fontSize: 14,
    fontWeight: active ? 600 : 400,
    color: active ? '#F8FAFC' : 'rgba(248,250,252,0.4)',
    borderBottom: active ? '2px solid #6366F1' : '2px solid transparent',
    background: 'none',
    cursor: 'pointer',
    transition: 'color 0.15s, border-color 0.15s',
  };
}

// ---------------------------------------------------------------------------
// FavoritesPage
// ---------------------------------------------------------------------------

export function FavoritesPage() {
  const navigate = useNavigate();

  const { searches, totalUnread, load: loadSearches, remove: removeSearch, toggleActive, markViewed } =
    useSavedSearches();

  const [favorites, setFavorites] = useState<ListingSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<'merkliste' | 'suchen'>('merkliste');

  const loadFavorites = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setFavorites(await getFavorites());
    } catch {
      setLoadError('Merkliste konnte nicht geladen werden.');
    } finally {
      setLoading(false);
    }
  }, []);

  // Load the appropriate data when the tab changes (page is always mounted)
  useEffect(() => {
    if (tab === 'merkliste') {
      loadFavorites();
    } else {
      loadSearches();
    }
    // loadSearches is a stable reference from useSavedSearches
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  // Mark searches as viewed when the user leaves this page — not on enter,
  // so the unread badge stays visible for the duration of their visit.
  useEffect(() => {
    return () => { markViewed(); };
    // markViewed is a stable reference
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleRemoveFavorite(id: number) {
    setFavorites((prev) => prev.filter((f) => f.id !== id));
  }

  function handleCleanup() {
    setFavorites((prev) => prev.filter((f) => !f.is_sold));
  }

  function handleActivateSearch(_id: number, saved: SavedSearch) {
    // Saved searches do not override the currently chosen category — preserve it.
    const currentCategory = localStorage.getItem('rcn_category') ?? 'all';
    const f = filterFromSavedSearch(saved, currentCategory);
    const qs = writeFiltersToParams(f).toString();
    navigate(qs ? `/?${qs}` : '/');
  }

  const soldCount = favorites.filter((f) => f.is_sold).length;

  return (
    <div className="flex flex-col" style={{ color: '#F8FAFC' }}>
      {/* Tab bar */}
      <div
        className="px-4 flex-shrink-0 sticky top-0 z-10"
        style={{
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          background: 'rgba(15, 15, 35, 0.85)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
        }}
      >
        <div className="flex" role="tablist">
          <button
            role="tab"
            aria-selected={tab === 'merkliste'}
            style={tabStyle(tab === 'merkliste')}
            onClick={() => setTab('merkliste')}
          >
            Merkliste
            {favorites.length > 0 && (
              <span
                className="ml-1.5 text-xs"
                style={{ color: 'rgba(248,250,252,0.35)' }}
              >
                ({favorites.length})
              </span>
            )}
          </button>
          <button
            role="tab"
            aria-selected={tab === 'suchen'}
            style={tabStyle(tab === 'suchen')}
            onClick={() => setTab('suchen')}
          >
            Suchen
            {searches.length > 0 && (
              <span
                className="ml-1.5 text-xs"
                style={{ color: 'rgba(248,250,252,0.35)' }}
              >
                ({searches.length})
              </span>
            )}
            {totalUnread > 0 && (
              <span
                className="ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-bold"
                style={{
                  background: 'rgba(236,72,153,0.15)',
                  border: '1px solid rgba(236,72,153,0.4)',
                  color: '#EC4899',
                }}
              >
                {totalUnread > 99 ? '99+' : totalUnread}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-4 py-4 pb-32">
        {tab === 'merkliste' && (
          <>
            {loading && (
              <div className="flex justify-center py-8">
                <div
                  className="animate-spin h-6 w-6 border-2 rounded-full"
                  style={{ borderColor: '#A78BFA', borderTopColor: 'transparent' }}
                />
              </div>
            )}
            {!loading && loadError && (
              <p className="text-center py-8" style={{ color: '#EC4899' }}>{loadError}</p>
            )}
            {!loading && !loadError && favorites.length === 0 && (
              <p className="text-center py-8" style={{ color: 'rgba(248,250,252,0.35)' }}>
                Keine Favoriten gespeichert
              </p>
            )}
            {!loading &&
              favorites.map((listing, i) => (
                <React.Fragment key={listing.id}>
                  {i > 0 && <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }} />}
                  <FavoriteCard listing={listing} onRemove={handleRemoveFavorite} />
                </React.Fragment>
              ))}
          </>
        )}

        {tab === 'suchen' && (
          <>
            {searches.length === 0 ? (
              <p className="text-center py-8" style={{ color: 'rgba(248,250,252,0.35)' }}>
                Noch keine Suchen gespeichert.
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {searches.map((search) => (
                  <SavedSearchCard
                    key={search.id}
                    search={search}
                    onActivate={() => handleActivateSearch(search.id, search)}
                    onToggle={() => toggleActive(search.id)}
                    onRemove={() => removeSearch(search.id)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Sticky "Aufräumen" footer — only in merkliste tab when sold items exist */}
      {tab === 'merkliste' && soldCount > 0 && (
        <div
          className="sticky bottom-0 px-6 py-3 flex items-center gap-3"
          style={{
            borderTop: '1px solid rgba(255,255,255,0.08)',
            background: 'rgba(15,15,35,0.88)',
            backdropFilter: 'blur(12px)',
          }}
        >
          <button
            onClick={handleCleanup}
            className="flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-semibold transition-all duration-200"
            style={{
              background: 'rgba(45,212,191,0.1)',
              border: '1px solid rgba(45,212,191,0.3)',
              color: '#2DD4BF',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(45,212,191,0.2)';
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(45,212,191,0.5)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(45,212,191,0.1)';
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(45,212,191,0.3)';
            }}
          >
            Aufräumen
          </button>
          <span className="text-xs" style={{ color: 'rgba(248,250,252,0.35)' }}>
            Nicht mehr verfügbare Anzeigen entfernen
          </span>
        </div>
      )}
    </div>
  );
}
