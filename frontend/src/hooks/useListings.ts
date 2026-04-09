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
}

export function readFiltersFromParams(params: URLSearchParams): ListingsFilter {
  const sortRaw = params.get('sort') ?? 'date';
  const sort: ListingsFilter['sort'] =
    sortRaw === 'price' || sortRaw === 'distance' ? sortRaw : 'date';
  const sortDirRaw = params.get('sort_dir');
  const sort_dir: 'asc' | 'desc' = sortDirRaw === 'asc' ? 'asc' : 'desc';
  return {
    search: params.get('search') ?? '',
    plz: params.get('plz') ?? '',
    sort,
    sort_dir,
    max_distance: params.get('max_distance') ?? '',
    page: parseInt(params.get('page') ?? '1', 10) || 1,
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
  ]);

  return { data, loading, error, filter, setFilter };
}
