import { useEffect, useState, useCallback } from 'react';
import React from 'react';
import { getFavorites } from '../api/client';
import type { Category, ListingSummary, SavedSearch, SearchCriteria } from '../types/api';
import FavoriteCard from './FavoriteCard';
import { useConfirm } from './ConfirmDialog';

interface Props {
  open: boolean;
  onClose: () => void;
  // Saved search props
  searches: SavedSearch[];
  onLoadSearches: () => Promise<void>;
  onRemoveSearch: (id: number) => Promise<void>;
  onToggleSearchActive: (id: number) => Promise<void>;
  onMarkViewed: () => Promise<void>;
  onActivateSearch: (id: number, criteria: SearchCriteria) => void;
  categories: Category[];
}

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

interface SavedSearchCardProps {
  search: SavedSearch;
  categoryLabel: string | null;
  onActivate: () => void;
  onToggle: () => void;
  onRemove: () => void;
}

function SavedSearchCard({ search, categoryLabel, onActivate, onToggle, onRemove }: SavedSearchCardProps) {
  const confirm = useConfirm();
  const displayName = search.name ?? search.search ?? 'Alle Anzeigen';
  const hasDistance = search.max_distance != null;

  const sortLabel: Record<string, string> = { date: 'Datum', price: 'Preis', distance: 'Entfernung' };
  const sortDir = search.sort_dir === 'asc' ? '↑' : '↓';

  const filterParts: string[] = [];
  if (search.plz) filterParts.push(`PLZ ${search.plz}`);
  if (hasDistance) filterParts.push(`bis ${search.max_distance} km`);
  if (search.sort) filterParts.push(`${sortLabel[search.sort] ?? search.sort} ${sortDir}`);
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
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onActivate(); } }}
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
            {/* Category badge */}
            {categoryLabel && (
              <span
                className="inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-medium"
                style={{
                  background: 'rgba(167,139,250,0.12)',
                  border: '1px solid rgba(167,139,250,0.3)',
                  color: '#C4B5FD',
                  flexShrink: 0,
                }}
              >
                {categoryLabel}
              </span>
            )}
            {/* Match count badge */}
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
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = '#EC4899'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.3)'; }}
          >
            <TrashIcon />
          </button>
        </div>
      </div>
    </div>
  );
}

export default function FavoritesModal({
  open,
  onClose,
  searches,
  onLoadSearches,
  onRemoveSearch,
  onToggleSearchActive,
  onMarkViewed,
  onActivateSearch,
  categories,
}: Props) {
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

  // Load appropriate data whenever modal opens or tab changes
  useEffect(() => {
    if (!open) return;
    if (tab === 'merkliste') {
      loadFavorites();
    } else {
      onLoadSearches();
    }
  // onLoadSearches is a stable reference from useSavedSearches
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tab]);

  // Mark searches as viewed when the modal closes — not on open,
  // so the unread badges stay visible for the duration of the visit.
  useEffect(() => {
    if (!open) return;
    return () => { onMarkViewed(); };
  // onMarkViewed is a stable reference
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Lock body scroll while modal is open
  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  function handleRemoveFavorite(id: number) {
    setFavorites((prev) => prev.filter((f) => f.id !== id));
  }

  // "Aufräumen" removes sold items from the local list view only.
  // Sold favorites will reappear on next modal open (re-fetched from API).
  // To permanently remove, use the individual "Von Merkliste entfernen" button.
  function handleCleanup() {
    setFavorites((prev) => prev.filter((f) => !f.is_sold));
  }

  if (!open) return null;

  const soldCount = favorites.filter((f) => f.is_sold).length;

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: '8px 0',
    marginRight: 24,
    fontSize: 14,
    fontWeight: active ? 600 : 400,
    color: active ? '#F8FAFC' : 'rgba(248,250,252,0.4)',
    borderBottom: active ? '2px solid #6366F1' : '2px solid transparent',
    background: 'none',
    cursor: 'pointer',
    transition: 'color 0.15s, border-color 0.15s',
  });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Meine Merkliste"
      className="fixed inset-0 z-50 flex items-stretch sm:items-start justify-center overflow-hidden sm:overflow-y-auto py-0 sm:py-8 px-0 sm:px-4"
      style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="relative w-full sm:max-w-2xl rounded-none sm:rounded-2xl shadow-2xl flex flex-col max-h-[100dvh] sm:max-h-[90vh]"
        style={{
          background: 'rgba(15, 15, 35, 0.85)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          backdropFilter: 'blur(20px) saturate(1.2)',
        }}
      >
        {/* Header */}
        <div
          className="px-6 pt-4 pb-0"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}
        >
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-bold" style={{ color: '#F8FAFC' }}>
              Meine Listen
            </h2>
            <button
              onClick={onClose}
              className="transition-colors p-1 rounded-lg"
              style={{ color: 'rgba(248,250,252,0.5)' }}
              aria-label="Schließen"
              onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = '#F8FAFC'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.5)'; }}
            >
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
          {/* Tab bar */}
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
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="px-4 py-4 min-h-0 flex-1 overflow-y-auto">
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
              {!loading && favorites.map((listing, i) => (
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
                searches.map((search) => (
                  <SavedSearchCard
                    key={search.id}
                    search={search}
                    categoryLabel={
                      search.category
                        ? (categories.find((c) => c.key === search.category)?.label ?? search.category)
                        : null
                    }
                    onActivate={() => {
                      onActivateSearch(search.id, {
                        search: search.search,
                        plz: search.plz,
                        max_distance: search.max_distance,
                        sort: search.sort as 'date' | 'price' | 'distance',
                        sort_dir: search.sort_dir as 'asc' | 'desc',
                      });
                    }}
                    onToggle={() => onToggleSearchActive(search.id)}
                    onRemove={() => onRemoveSearch(search.id)}
                  />
                ))
              )}
            </>
          )}
        </div>

        {/* Footer — shown only in merkliste tab when there are sold items */}
        {tab === 'merkliste' && soldCount > 0 && (
          <div
            className="px-6 py-3 flex items-center gap-3"
            style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}
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
    </div>
  );
}
