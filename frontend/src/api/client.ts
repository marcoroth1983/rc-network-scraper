import type {
  Category,
  ComparablesResponse,
  ListingsQueryParams,
  ListingDetail,
  ListingSummary,
  LLMModelRow,
  NotificationPrefs,
  PaginatedResponse,
  PlzResponse,
  SavedSearch,
  SearchCriteria,
  ScrapeLogEntry,
  ScrapeStatus,
  TelegramLinkResponse,
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

export async function getCategories(): Promise<Category[]> {
  const res = await fetch('/api/categories');
  return handleResponse<Category[]>(res);
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
  if (params.price_min != null) qs.set('price_min', String(params.price_min));
  if (params.price_max != null) qs.set('price_max', String(params.price_max));
  // Omit the category param entirely when it is "all" or absent — backend treats absence as "all"
  if (params.category && params.category !== 'all') qs.set('category', params.category);
  if (params.drive_type) qs.set('drive_type', params.drive_type);
  if (params.completeness) qs.set('completeness', params.completeness);
  if (params.shipping_available != null) qs.set('shipping_available', String(params.shipping_available));
  if (params.model_type) qs.set('model_type', params.model_type);
  if (params.model_subtype) qs.set('model_subtype', params.model_subtype);
  if (params.source) qs.set('source', params.source);
  if (params.show_outdated) qs.set('show_outdated', 'true');
  if (params.only_sold) qs.set('only_sold', 'true');

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

export async function getListingsByAuthor(author: string, excludeId: number): Promise<ListingSummary[]> {
  const qs = new URLSearchParams({ author, exclude_id: String(excludeId) });
  const res = await fetch(`/api/listings/by-author?${qs.toString()}`);
  return handleResponse<ListingSummary[]>(res);
}

export async function getFavorites(): Promise<ListingSummary[]> {
  const plz = localStorage.getItem('rcn_ref_plz');
  const url = plz ? `/api/favorites?plz=${encodeURIComponent(plz)}` : '/api/favorites';
  const res = await fetch(url);
  return handleResponse<ListingSummary[]>(res);
}

export async function getSavedSearches(): Promise<SavedSearch[]> {
  const res = await fetch('/api/searches');
  return handleResponse<SavedSearch[]>(res);
}

export async function createSavedSearch(criteria: SearchCriteria): Promise<SavedSearch> {
  const res = await fetch('/api/searches', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(criteria),
  });
  return handleResponse<SavedSearch>(res);
}

export async function updateSavedSearch(id: number, criteria: SearchCriteria): Promise<SavedSearch> {
  const res = await fetch(`/api/searches/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(criteria),
  });
  return handleResponse<SavedSearch>(res);
}

export async function deleteSavedSearch(id: number): Promise<{ ok: boolean }> {
  const res = await fetch(`/api/searches/${id}`, { method: 'DELETE' });
  return handleResponse<{ ok: boolean }>(res);
}

export async function toggleSavedSearch(id: number, isActive: boolean): Promise<{ id: number; is_active: boolean }> {
  const res = await fetch(`/api/searches/${id}?is_active=${isActive}`, { method: 'PATCH' });
  return handleResponse<{ id: number; is_active: boolean }>(res);
}

export async function markSearchesViewed(): Promise<{ ok: boolean }> {
  const res = await fetch('/api/searches/mark-viewed', { method: 'POST' });
  return handleResponse<{ ok: boolean }>(res);
}

export async function getLLMModels(): Promise<LLMModelRow[]> {
  const res = await fetch('/api/admin/llm-models');
  return handleResponse<LLMModelRow[]>(res);
}

export async function refreshLLMModels(): Promise<LLMModelRow[]> {
  const res = await fetch('/api/admin/llm-models/refresh', { method: 'POST' });
  return handleResponse<LLMModelRow[]>(res);
}

export async function getComparables(id: number): Promise<ComparablesResponse> {
  const res = await fetch(`/api/listings/${id}/comparables`);
  return handleResponse<ComparablesResponse>(res);
}

export async function linkTelegram(): Promise<TelegramLinkResponse> {
  const res = await fetch('/api/telegram/link', { method: 'POST' });
  return handleResponse<TelegramLinkResponse>(res);
}

export async function unlinkTelegram(): Promise<{ ok: true }> {
  const res = await fetch('/api/telegram/unlink', { method: 'POST' });
  return handleResponse<{ ok: true }>(res);
}

export async function getNotificationPrefs(): Promise<NotificationPrefs> {
  const res = await fetch('/api/telegram/prefs');
  return handleResponse<NotificationPrefs>(res);
}

export async function updateNotificationPrefs(partial: Partial<NotificationPrefs>): Promise<NotificationPrefs> {
  const res = await fetch('/api/telegram/prefs', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(partial),
  });
  return handleResponse<NotificationPrefs>(res);
}
