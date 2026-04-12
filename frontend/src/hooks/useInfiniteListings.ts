import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getListings } from '../api/client';
import type { ListingSummary } from '../types/api';
import { readFiltersFromParams, writeFiltersToParams, type ListingsFilter } from './useListings';

export interface UseInfiniteListingsResult {
  items: ListingSummary[];
  total: number | null;
  loading: boolean;       // true only on first page load (full-page spinner)
  loadingMore: boolean;   // true when fetching subsequent pages (small spinner)
  hasMore: boolean;
  error: string | null;
  filter: ListingsFilter;
  setFilter: (next: Omit<ListingsFilter, 'page'>) => void;
  loadMore: () => void;
}

export function useInfiniteListings(): UseInfiniteListingsResult {
  const [searchParams, setSearchParams] = useSearchParams();

  // Read filter from URL but ignore the `page` param — page is internal state.
  const urlFilter = readFiltersFromParams(searchParams);

  const [items, setItems] = useState<ListingSummary[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  // Stable references to the "current filter dimensions" used for change detection.
  // We track these as refs so the fetch effect's deps stay clean.
  const filterRef = useRef({
    search: urlFilter.search,
    plz: urlFilter.plz,
    sort: urlFilter.sort,
    sort_dir: urlFilter.sort_dir,
    max_distance: urlFilter.max_distance,
  });

  // Detect filter dimension changes (anything except page).
  // When they change, reset accumulated state and go back to page 1.
  const prevFilter = filterRef.current;
  const filterChanged =
    prevFilter.search !== urlFilter.search ||
    prevFilter.plz !== urlFilter.plz ||
    prevFilter.sort !== urlFilter.sort ||
    prevFilter.sort_dir !== urlFilter.sort_dir ||
    prevFilter.max_distance !== urlFilter.max_distance;

  if (filterChanged) {
    filterRef.current = {
      search: urlFilter.search,
      plz: urlFilter.plz,
      sort: urlFilter.sort,
      sort_dir: urlFilter.sort_dir,
      max_distance: urlFilter.max_distance,
    };
    // Reset synchronously during render — safe because we haven't committed yet
    // and this is logically equivalent to getDerivedStateFromProps.
    if (items.length > 0 || total !== null || page !== 1 || !hasMore) {
      setItems([]);
      setTotal(null);
      setHasMore(true);
      setPage(1);
    }
  }

  // Stable snapshot of filter dimensions for the fetch effect.
  const { search, plz, sort, sort_dir, max_distance } = filterRef.current;

  useEffect(() => {
    // Guard: distance-related params require PLZ (backend returns 400 otherwise)
    if ((sort === 'distance' || max_distance) && !plz) {
      return;
    }

    let cancelled = false;

    if (page === 1) {
      setLoading(true);
      setLoadingMore(false);
    } else {
      setLoadingMore(true);
    }
    setError(null);

    getListings({
      page,
      per_page: 20,
      search: search || null,
      sort,
      sort_dir,
      plz: plz || null,
      max_distance: max_distance ? parseInt(max_distance, 10) : null,
    })
      .then((res) => {
        if (cancelled) return;
        setItems((prev) => (page === 1 ? res.items : [...prev, ...res.items]));
        setTotal(res.total);
        // hasMore: compare accumulated count after this page
        const nextCount = page === 1 ? res.items.length : items.length + res.items.length;
        setHasMore(nextCount < res.total);
        setLoading(false);
        setLoadingMore(false);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message);
        setLoading(false);
        setLoadingMore(false);
      });

    return () => {
      cancelled = true;
    };
    // `items.length` is intentionally included so hasMore calculation is correct.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search, plz, sort, sort_dir, max_distance]);

  const loadMore = useCallback(() => {
    if (!loading && !loadingMore && hasMore) {
      setPage((p) => p + 1);
    }
  }, [loading, loadingMore, hasMore]);

  const setFilter = useCallback(
    (next: Omit<ListingsFilter, 'page'>) => {
      // Always write page: 1 so the page param never appears in the URL.
      writeFiltersToParams({ ...next, page: 1 }, setSearchParams);
    },
    [setSearchParams],
  );

  // Expose the filter with the internal page for consumers that read filter.page
  // (e.g. criteriaChanged helper). Page in the returned filter reflects the
  // URL's page param, which we intentionally keep absent — so it will be 1.
  const filter: ListingsFilter = {
    search: urlFilter.search,
    plz: urlFilter.plz,
    sort: urlFilter.sort,
    sort_dir: urlFilter.sort_dir,
    max_distance: urlFilter.max_distance,
    page: 1,
  };

  return { items, total, loading, loadingMore, hasMore, error, filter, setFilter, loadMore };
}
