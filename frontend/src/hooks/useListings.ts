import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getListings } from '../api/client';
import type { PaginatedResponse } from '../types/api';

export interface ListingsFilter {
  search: string;
  plz: string;
  sort: 'date' | 'price' | 'distance';
  sort_dir: 'asc' | 'desc';
  max_distance: string; // stored as string in URL; convert to int before API call
  page: number;
  category: string;     // "all" or a category key; stored in localStorage, not URL
  price_min: string;
  price_max: string;
  drive_type?: string;
  completeness?: string;
  shipping_available?: boolean;
  model_type?: string;
  model_subtype?: string;
  show_outdated?: boolean;
  only_sold?: boolean;
}

// All filter fields except the pagination cursor.
// This type drives change-detection and ref storage in useInfiniteListings —
// adding a field to ListingsFilter automatically includes it here.
export type FilterDimensions = Omit<ListingsFilter, 'page'>;

/** Strip the `page` cursor from a full filter object. */
export function extractFilterDimensions(f: ListingsFilter): FilterDimensions {
  // Destructure page out, spread the rest — TypeScript keeps this in sync.
  const { page: _page, ...dims } = f;
  return dims;
}

/**
 * Deep-equality check over all FilterDimension keys.
 * Driven by Object.keys so it automatically covers new fields added to the type.
 */
export function filterDimensionsEqual(a: FilterDimensions, b: FilterDimensions): boolean {
  const keys = Object.keys(a) as (keyof FilterDimensions)[];
  return keys.every((k) => a[k] === b[k]);
}

export function readFiltersFromParams(params: URLSearchParams): ListingsFilter {
  const sortRaw = params.get('sort') ?? 'date';
  const sort: ListingsFilter['sort'] =
    sortRaw === 'price' || sortRaw === 'distance' ? sortRaw : 'date';
  const sortDirRaw = params.get('sort_dir');
  const sort_dir: 'asc' | 'desc' = sortDirRaw === 'asc' ? 'asc' : 'desc';
  // Category is kept in localStorage (not URL) — "all" is the sentinel for no filter
  const category = localStorage.getItem('rcn_category') ?? 'all';
  const shippingRaw = params.get('shipping_available');
  const shipping_available = shippingRaw === 'true' ? true : shippingRaw === 'false' ? false : undefined;
  const show_outdated = params.get('show_outdated') === 'true' ? true : undefined;
  const only_sold = params.get('only_sold') === 'true' ? true : undefined;
  return {
    search: params.get('search') ?? '',
    plz: params.get('plz') ?? '',
    sort,
    sort_dir,
    max_distance: params.get('max_distance') ?? '',
    page: parseInt(params.get('page') ?? '1', 10) || 1,
    category,
    price_min: params.get('price_min') ?? '',
    price_max: params.get('price_max') ?? '',
    drive_type: params.get('drive_type') ?? undefined,
    completeness: params.get('completeness') ?? undefined,
    shipping_available,
    model_type: params.get('model_type') ?? undefined,
    model_subtype: params.get('model_subtype') ?? undefined,
    show_outdated,
    only_sold,
  };
}

export function writeFiltersToParams(filter: ListingsFilter): URLSearchParams {
  const p = new URLSearchParams();
  if (filter.search) p.set('search', filter.search);
  if (filter.plz) p.set('plz', filter.plz);
  if (filter.sort !== 'date') p.set('sort', filter.sort);
  if (filter.sort_dir !== 'desc') p.set('sort_dir', filter.sort_dir);
  if (filter.max_distance) p.set('max_distance', filter.max_distance);
  if (filter.price_min) p.set('price_min', filter.price_min);
  if (filter.price_max) p.set('price_max', filter.price_max);
  if (filter.drive_type) p.set('drive_type', filter.drive_type);
  if (filter.completeness) p.set('completeness', filter.completeness);
  if (filter.shipping_available != null) p.set('shipping_available', String(filter.shipping_available));
  if (filter.model_type) p.set('model_type', filter.model_type);
  if (filter.model_subtype) p.set('model_subtype', filter.model_subtype);
  if (filter.show_outdated) p.set('show_outdated', 'true');
  if (filter.only_sold) p.set('only_sold', 'true');
  if (filter.page > 1) p.set('page', String(filter.page));
  return p;
}

interface UseListingsResult {
  data: PaginatedResponse | null;
  loading: boolean;
  error: string | null;
  filter: ListingsFilter;
  setFilter: (next: ListingsFilter) => void;
}

export function useListings(): UseListingsResult {
  const [searchParams, setSearchParams] = useSearchParams();
  const filter = readFiltersFromParams(searchParams);

  const [data, setData] = useState<PaginatedResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setFilter = useCallback((next: ListingsFilter) => {
    setSearchParams(writeFiltersToParams(next));
  }, [setSearchParams]);

  useEffect(() => {
    // Guard: don't send distance params without PLZ (backend returns 400)
    if ((filter.sort === 'distance' || filter.max_distance) && !filter.plz) {
      return;
    }

    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);

    getListings({
      page: filter.page,
      per_page: 20,
      search: filter.search || null,
      sort: filter.sort,
      sort_dir: filter.sort_dir,
      plz: filter.plz || null,
      max_distance: filter.max_distance ? parseInt(filter.max_distance, 10) : null,
      category: filter.category !== 'all' ? filter.category : undefined,
      price_min: filter.price_min ? parseFloat(filter.price_min) : null,
      price_max: filter.price_max ? parseFloat(filter.price_max) : null,
      drive_type: filter.drive_type,
      completeness: filter.completeness,
      shipping_available: filter.shipping_available,
      model_type: filter.model_type,
      model_subtype: filter.model_subtype,
      show_outdated: filter.show_outdated,
      only_sold: filter.only_sold,
    })
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    filter.page,
    filter.search,
    filter.plz,
    filter.sort,
    filter.sort_dir,
    filter.max_distance,
    filter.category,
    filter.price_min,
    filter.price_max,
    filter.drive_type,
    filter.completeness,
    filter.shipping_available,
    filter.model_type,
    filter.model_subtype,
    filter.show_outdated,
    filter.only_sold,
  ]);

  return { data, loading, error, filter, setFilter };
}
