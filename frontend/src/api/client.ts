import type {
  ListingsQueryParams,
  ListingDetail,
  ListingSummary,
  PaginatedResponse,
  PlzResponse,
  ScrapeLogEntry,
  ScrapeStatus,
} from '../types/api';
import { ApiError } from '../types/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // ignore JSON parse errors
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export async function getListings(params: ListingsQueryParams): Promise<PaginatedResponse> {
  const qs = new URLSearchParams();
  if (params.page != null) qs.set('page', String(params.page));
  if (params.per_page != null) qs.set('per_page', String(params.per_page));
  if (params.search) qs.set('search', params.search);
  if (params.sort) qs.set('sort', params.sort);
  if (params.sort_dir) qs.set('sort_dir', params.sort_dir);
  if (params.plz) qs.set('plz', params.plz);
  if (params.max_distance != null) qs.set('max_distance', String(params.max_distance));

  const res = await fetch(`/api/listings?${qs.toString()}`);
  return handleResponse<PaginatedResponse>(res);
}

export async function getListing(id: number): Promise<ListingDetail> {
  const res = await fetch(`/api/listings/${id}`);
  return handleResponse<ListingDetail>(res);
}

export async function resolvePlz(plz: string): Promise<PlzResponse> {
  const res = await fetch(`/api/geo/plz/${encodeURIComponent(plz)}`);
  return handleResponse<PlzResponse>(res);
}

export async function startScrape(): Promise<{ status: 'started' | 'already_running' }> {
  const res = await fetch('/api/scrape', { method: 'POST' });
  return handleResponse<{ status: 'started' | 'already_running' }>(res);
}

export async function getScrapeStatus(): Promise<ScrapeStatus> {
  const res = await fetch('/api/scrape/status');
  return handleResponse<ScrapeStatus>(res);
}

export async function getScrapeLog(): Promise<ScrapeLogEntry[]> {
  const res = await fetch('/api/scrape/log');
  return handleResponse<ScrapeLogEntry[]>(res);
}

export async function toggleSold(id: number, isSold: boolean): Promise<void> {
  const res = await fetch(`/api/listings/${id}/sold?is_sold=${isSold}`, { method: 'PATCH' });
  return handleResponse<void>(res);
}

export async function toggleFavorite(id: number, isFavorite: boolean): Promise<void> {
  const res = await fetch(`/api/listings/${id}/favorite?is_favorite=${isFavorite}`, {
    method: 'PATCH',
  });
  return handleResponse<void>(res);
}

export async function getFavorites(): Promise<ListingSummary[]> {
  const res = await fetch('/api/favorites');
  return handleResponse<ListingSummary[]>(res);
}
