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
  setCategory: (key: string) => void;
  loadMore: () => void;
}

export function useInfiniteListings(): UseInfiniteListingsResult {
  const [searchParams, setSearchParams] = useSearchParams();

  // Read filter from URL but ignore the `page` param — page is internal state.
  // Category is read from localStorage inside readFiltersFromParams.
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
    category: urlFilter.category,
    price_min: urlFilter.price_min,
    price_max: urlFilter.price_max,
  });

  // Detect filter dimension changes (anything except page).
  // When they change, reset accumulated state and go back to page 1.
  const prevFilter = filterRef.current;
  const filterChanged =
    prevFilter.search !== urlFilter.search ||
    prevFilter.plz !== urlFilter.plz ||
    prevFilter.sort !== urlFilter.sort ||
    prevFilter.sort_dir !== urlFilter.sort_dir ||
    prevFilter.max_distance !== urlFilter.max_distance ||
    prevFilter.category !== urlFilter.category ||
    prevFilter.price_min !== urlFilter.price_min ||
    prevFilter.price_max !== urlFilter.price_max;

  if (filterChanged) {
    filterRef.current = {
      search: urlFilter.search,
      plz: urlFilter.plz,
      sort: urlFilter.sort,
      sort_dir: urlFilter.sort_dir,
      max_distance: urlFilter.max_distance,
      category: urlFilter.category,
      price_min: urlFilter.price_min,
      price_max: urlFilter.price_max,
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
  const { search, plz, sort, sort_dir, max_distance, category, price_min, price_max } = filterRef.current;

  useEffect(() => {
    // Fetch gate: no localStorage value means first visit — wait for modal selection.
    // readFiltersFromParams falls back to "all" when localStorage is null, but we
    // distinguish "explicitly set to all" from "not yet chosen" here.
    if (localStorage.getItem('rcn_category') === null) {
      return;
    }

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
      category: category !== 'all' ? category : undefined,
      price_min: price_min ? parseFloat(price_min) : null,
      price_max: price_max ? parseFloat(price_max) : null,
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
  }, [page, search, plz, sort, sort_dir, max_distance, category, price_min, price_max]);

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

  // setCategory: write to localStorage, reset accumulated state, and nudge the URL
  // so React re-reads filters (which picks up the new localStorage value).
  const setCategory = useCallback(
    (key: string) => {
      localStorage.setItem('rcn_category', key);
      setItems([]);
      setTotal(null);
      setHasMore(true);
      setPage(1);
      // Nudge search params so readFiltersFromParams re-runs and picks up new localStorage value
      setSearchParams((prev) => new URLSearchParams(prev));
    },
    [setSearchParams],
  );

  // Also respond to category changes dispatched from App (when header modal is used)
  useEffect(() => {
    const handler = () => {
      setItems([]);
      setTotal(null);
      setHasMore(true);
      setPage(1);
      setSearchParams((prev) => new URLSearchParams(prev));
    };
    window.addEventListener('rcn_category_changed', handler);
    return () => window.removeEventListener('rcn_category_changed', handler);
  // setSearchParams is stable; no other deps needed
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    category: urlFilter.category,
    price_min: urlFilter.price_min,
    price_max: urlFilter.price_max,
  };

  return { items, total, loading, loadingMore, hasMore, error, filter, setFilter, setCategory, loadMore };
}
