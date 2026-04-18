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
  price_indicator?: string;
  model_type?: string;
  model_subtype?: string;
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
    price_indicator: params.get('price_indicator') ?? undefined,
    model_type: params.get('model_type') ?? undefined,
    model_subtype: params.get('model_subtype') ?? undefined,
  };
}

export function writeFiltersToParams(
  filter: ListingsFilter,
  setParams: (p: URLSearchParams) => void,
) {
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
  if (filter.price_indicator) p.set('price_indicator', filter.price_indicator);
  if (filter.model_type) p.set('model_type', filter.model_type);
  if (filter.model_subtype) p.set('model_subtype', filter.model_subtype);
  if (filter.page > 1) p.set('page', String(filter.page));
  setParams(p);
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
    writeFiltersToParams(next, setSearchParams);
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
      price_indicator: filter.price_indicator,
      model_type: filter.model_type,
      model_subtype: filter.model_subtype,
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
    filter.price_indicator,
    filter.model_type,
    filter.model_subtype,
  ]);

  return { data, loading, error, filter, setFilter };
}
