import { useState, useEffect, useRef } from 'react';
import ListingCard from '../components/ListingCard';
import FilterPanel from '../components/FilterPanel';
import CategoryModal from '../components/CategoryModal';
import { useInfiniteListings } from '../hooks/useInfiniteListings';
import type { Category, SavedSearch, SearchCriteria } from '../types/api';

interface Props {
  activeSavedSearchId: number | null;
  activeSavedSearchCriteria?: SavedSearch;
  onSaveSearch: (criteria: SearchCriteria) => Promise<void>;
  onUpdateSearch: (id: number, criteria: SearchCriteria) => Promise<void>;
  onClearActiveSavedSearch: () => void;
  categories: Category[];
  onOpenCategoryModal: () => void;
}

function Spinner() {
  return (
    <div className="flex justify-center py-12">
      <div
        className="animate-spin h-8 w-8 border-4 rounded-full"
        style={{ borderColor: '#A78BFA', borderTopColor: 'transparent' }}
      />
    </div>
  );
}

function BookmarkIcon() {
  return (
    <svg
      className="w-4 h-4"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg
      className="w-4 h-4"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
    </svg>
  );
}

// Returns true if the current filter differs from the saved search criteria
function criteriaChanged(
  filter: { search: string; plz: string; sort: string; sort_dir: string; max_distance: string },
  saved: SavedSearch,
): boolean {
  const savedSearch = saved.search ?? '';
  const savedPlz = saved.plz ?? '';
  const savedMaxDistance = saved.max_distance != null ? String(saved.max_distance) : '';
  return (
    filter.search !== savedSearch ||
    filter.plz !== savedPlz ||
    filter.sort !== saved.sort ||
    filter.sort_dir !== saved.sort_dir ||
    filter.max_distance !== savedMaxDistance
  );
}

export default function ListingsPage({
  activeSavedSearchId,
  activeSavedSearchCriteria,
  onSaveSearch,
  onUpdateSearch,
  onClearActiveSavedSearch,
  categories,
  onOpenCategoryModal,
}: Props) {
  const { items, total, loading, loadingMore, hasMore, error, filter, setFilter, setCategory, loadMore } =
    useInfiniteListings();
  const [fabFeedback, setFabFeedback] = useState<'saved' | 'updated' | null>(null);

  // First-visit modal: show when no category has been chosen yet
  const [firstVisitModalOpen, setFirstVisitModalOpen] = useState(
    () => localStorage.getItem('rcn_category') === null,
  );

  function handleFirstVisitSelect(key: string) {
    setCategory(key);
    setFirstVisitModalOpen(false);
  }
  const feedbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sentinel ref for IntersectionObserver-based infinite scroll trigger
  const sentinelRef = useRef<HTMLDivElement>(null);

  // When all filter fields are cleared, clear the active saved search ID
  useEffect(() => {
    if (!filter.search && !filter.plz && !filter.max_distance && activeSavedSearchId != null) {
      onClearActiveSavedSearch();
    }
  }, [filter.search, filter.plz, filter.max_distance, activeSavedSearchId, onClearActiveSavedSearch]);

  // Stable loadMore ref so the observer effect doesn't re-run on every render
  const loadMoreRef = useRef(loadMore);
  loadMoreRef.current = loadMore;

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadMoreRef.current();
      },
      { rootMargin: '200px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Determine FAB mode
  const hasActiveFilters = Boolean(filter.search || filter.plz || filter.max_distance);
  const isExistingSearch = activeSavedSearchId != null;
  const hasCriteriaChanged =
    isExistingSearch && activeSavedSearchCriteria != null
      ? criteriaChanged(filter, activeSavedSearchCriteria)
      : false;

  // Mode 1: new search — filters active, no saved search selected
  const showSaveNew = hasActiveFilters && !isExistingSearch;
  // Mode 2: update existing — active saved search selected and filters differ
  const showUpdate = isExistingSearch && hasCriteriaChanged;

  function showFeedback(type: 'saved' | 'updated') {
    setFabFeedback(type);
    if (feedbackTimerRef.current) clearTimeout(feedbackTimerRef.current);
    feedbackTimerRef.current = setTimeout(() => setFabFeedback(null), 2000);
  }

  async function handleSave() {
    await onSaveSearch({
      search: filter.search || null,
      plz: filter.plz || null,
      max_distance: filter.max_distance ? parseInt(filter.max_distance, 10) : null,
      sort: filter.sort,
      sort_dir: filter.sort_dir,
      // Pass undefined (not "all") when no specific category — backend stores NULL for "all"
      category: filter.category !== 'all' ? filter.category : undefined,
    });
    showFeedback('saved');
  }

  async function handleUpdate() {
    if (activeSavedSearchId == null) return;
    await onUpdateSearch(activeSavedSearchId, {
      search: filter.search || null,
      plz: filter.plz || null,
      max_distance: filter.max_distance ? parseInt(filter.max_distance, 10) : null,
      sort: filter.sort,
      sort_dir: filter.sort_dir,
      category: filter.category !== 'all' ? filter.category : undefined,
    });
    showFeedback('updated');
  }

  const showFab = showSaveNew || showUpdate;

  const activeCategoryLabel = (() => {
    if (filter.category === 'all') return 'Alle Kategorien';
    return categories.find((c) => c.key === filter.category)?.label ?? 'Alle Kategorien';
  })();

  return (
    <div>
      {/* First-visit category modal — not closeable until a choice is made */}
      <CategoryModal
        open={firstVisitModalOpen}
        categories={categories}
        closeable={false}
        onSelect={handleFirstVisitSelect}
        onClose={() => {/* blocked on first visit */}}
      />

      <FilterPanel
        filter={filter}
        onChange={setFilter}
        activeCategoryLabel={activeCategoryLabel}
        onOpenCategoryModal={onOpenCategoryModal}
      />

      {/* Full-page spinner: only on the very first load before any items exist */}
      {loading && items.length === 0 && <Spinner />}

      {!loading && error && (
        <div
          className="rounded-xl p-4"
          style={{
            background: 'rgba(236,72,153,0.08)',
            border: '1px solid rgba(236,72,153,0.3)',
            color: '#EC4899',
          }}
        >
          Fehler beim Laden: {error}
        </div>
      )}

      {!error && (total !== null || items.length > 0) && (
        <>
          <p className="text-sm mb-4" style={{ color: 'rgba(248,250,252,0.65)' }}>
            <span className="font-semibold" style={{ color: '#F8FAFC' }}>{total}</span>{' '}
            Anzeigen gefunden
          </p>

          {items.length === 0 && !loading ? (
            <div className="text-center py-16">
              <svg
                className="w-12 h-12 mx-auto mb-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1}
                style={{ color: 'rgba(248,250,252,0.15)' }}
              >
                <rect x="3" y="3" width="18" height="18" rx="3" />
                <path strokeLinecap="round" d="M9 9h6M9 12h6M9 15h4" />
              </svg>
              <p style={{ color: 'rgba(248,250,252,0.35)' }}>Keine Anzeigen gefunden.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {items.map((listing) => (
                <ListingCard key={listing.id} listing={listing} />
              ))}
            </div>
          )}

          {/* Small spinner shown while fetching subsequent pages */}
          {loadingMore && (
            <div className="flex justify-center py-6">
              <div
                className="animate-spin h-5 w-5 border-2 rounded-full"
                style={{ borderColor: '#A78BFA', borderTopColor: 'transparent' }}
              />
            </div>
          )}

          {/* End-of-list indicator */}
          {!hasMore && items.length > 0 && (
            <p className="text-center text-sm py-6" style={{ color: 'rgba(248,250,252,0.35)' }}>
              Alle {total} Anzeigen geladen
            </p>
          )}
        </>
      )}

      {/* Sentinel: always mounted so the IntersectionObserver is set up on initial render */}
      <div ref={sentinelRef} className="h-1" />

      {/* FAB — Suche speichern / aktualisieren */}
      {showFab && (
        <button
          type="button"
          onClick={showUpdate ? handleUpdate : handleSave}
          aria-label={showUpdate ? 'Suche aktualisieren' : 'Suche speichern'}
          className="fixed bottom-20 sm:bottom-6 right-6 z-30 flex items-center gap-2 rounded-full px-4 py-3 font-semibold text-sm shadow-lg transition-all duration-200"
          style={{
            background: fabFeedback
              ? 'rgba(45,212,191,0.25)'
              : 'rgba(99,102,241,0.85)',
            border: fabFeedback
              ? '1px solid rgba(45,212,191,0.5)'
              : '1px solid rgba(139,92,246,0.5)',
            color: fabFeedback ? '#2DD4BF' : '#F8FAFC',
            backdropFilter: 'blur(12px)',
          }}
        >
          <span className="flex-shrink-0">
            {fabFeedback ? (
              // Checkmark on success
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            ) : showUpdate ? (
              <RefreshIcon />
            ) : (
              <BookmarkIcon />
            )}
          </span>
          <span className="hidden sm:inline">
            {fabFeedback === 'saved'
              ? 'Gespeichert!'
              : fabFeedback === 'updated'
              ? 'Aktualisiert!'
              : showUpdate
              ? 'Suche aktualisieren'
              : 'Suche speichern'}
          </span>
        </button>
      )}
    </div>
  );
}
