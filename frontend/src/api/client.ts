import type {
  ListingsQueryParams,
  ListingDetail,
  PaginatedResponse,
  PlzResponse,
  ScrapeSummary,
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

export async function triggerScrape(maxPages = 10): Promise<ScrapeSummary> {
  const res = await fetch(`/api/scrape?max_pages=${maxPages}`, { method: 'POST' });
  return handleResponse<ScrapeSummary>(res);
}

export async function toggleSold(id: number, isSold: boolean): Promise<void> {
  const res = await fetch(`/api/listings/${id}/sold?is_sold=${isSold}`, { method: 'PATCH' });
  return handleResponse<void>(res);
}
