import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams, useLocation } from 'react-router-dom';
import { getListings } from '../api/client';
import type { ListingSummary } from '../types/api';
import { getBackground } from '../lib/modalLocation';
import {
  readFiltersFromParams,
  writeFiltersToParams,
  extractFilterDimensions,
  filterDimensionsEqual,
  type ListingsFilter,
  type FilterDimensions,
} from './useListings';

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
  const [, setSearchParams] = useSearchParams();
  const location = useLocation();

  // CRITICAL: When the detail modal is open, the URL is `/listings/:id` with
  // NO query string — useSearchParams() would see an empty filter and reset
  // our accumulated items. We must read filters from the BACKGROUND location
  // (the listings URL captured when the modal opened) so the hook stays stable
  // for the entire modal lifetime.
  const background = getBackground(location);
  const effectiveSearch = background != null ? background.search : location.search;
  const effectiveParams = new URLSearchParams(effectiveSearch.startsWith('?') ? effectiveSearch.slice(1) : effectiveSearch);

  // Read filter from URL but ignore the `page` param — page is internal state.
  // Category is read from localStorage inside readFiltersFromParams.
  const urlFilter = readFiltersFromParams(effectiveParams);

  const [items, setItems] = useState<ListingSummary[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  // Stable reference to the current filter dimensions used for change detection.
  // Using FilterDimensions (page stripped) keeps this in sync with ListingsFilter
  // automatically — no manual parallel lists needed.
  const filterRef = useRef<FilterDimensions>(extractFilterDimensions(urlFilter));

  // Detect filter dimension changes (anything except page).
  // filterDimensionsEqual covers all keys via Object.keys — new fields are
  // automatically included without touching this hook.
  const urlDims = extractFilterDimensions(urlFilter);
  const filterChanged = !filterDimensionsEqual(filterRef.current, urlDims);

  if (filterChanged) {
    filterRef.current = urlDims;
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
  // We serialise to a string so the useEffect dep comparison is O(1) and stable.
  const dims = filterRef.current;
  const dimsKey = JSON.stringify(dims);

  useEffect(() => {
    // Fetch gate: no localStorage value means first visit — wait for modal selection.
    // readFiltersFromParams falls back to "all" when localStorage is null, but we
    // distinguish "explicitly set to all" from "not yet chosen" here.
    if (localStorage.getItem('rcn_category') === null) {
      return;
    }

    // Guard: distance-related params require PLZ (backend returns 400 otherwise)
    if ((dims.sort === 'distance' || dims.max_distance) && !dims.plz) {
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
      search: dims.search || null,
      sort: dims.sort,
      sort_dir: dims.sort_dir,
      plz: dims.plz || null,
      max_distance: dims.max_distance ? parseInt(dims.max_distance, 10) : null,
      category: dims.category !== 'all' ? dims.category : undefined,
      price_min: dims.price_min ? parseFloat(dims.price_min) : null,
      price_max: dims.price_max ? parseFloat(dims.price_max) : null,
      drive_type: dims.drive_type,
      completeness: dims.completeness,
      shipping_available: dims.shipping_available,
      model_type: dims.model_type,
      model_subtype: dims.model_subtype,
      show_outdated: dims.show_outdated,
      only_sold: dims.only_sold,
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
    // `dimsKey` is the serialised snapshot of all filter dimensions — one stable
    // dep instead of a manually enumerated list of fields.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, dimsKey]);

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
  const filter: ListingsFilter = { ...urlFilter, page: 1 };

  return { items, total, loading, loadingMore, hasMore, error, filter, setFilter, setCategory, loadMore };
}
