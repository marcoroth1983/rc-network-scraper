export interface Category {
  key: string;
  label: string;
  count: number;
}

export interface ListingSummary {
  id: number;
  external_id: string;
  url: string;
  title: string;
  price: string | null;
  price_numeric: number | null;
  condition: string | null;
  plz: string | null;
  city: string | null;
  latitude: number | null;
  longitude: number | null;
  author: string;
  posted_at: string | null;   // ISO 8601 string
  scraped_at: string;          // ISO 8601 string
  distance_km: number | null;
  images: string[];
  is_sold: boolean;
  is_favorite: boolean;
  category: string;
  // LLM-extracted product fields
  manufacturer: string | null;
  model_name: string | null;
  model_type: string | null;
  model_subtype: string | null;
  // LLM-extracted analysis fields
  drive_type: string | null;
  completeness: string | null;
  shipping_available: boolean | null;
  price_indicator: 'deal' | 'fair' | 'expensive' | null;
  price_indicator_median: number | null;
  price_indicator_count: number | null;
}

export interface ListingDetail {
  id: number;
  external_id: string;
  url: string;
  title: string;
  price: string | null;
  price_numeric: number | null;
  condition: string | null;
  shipping: string | null;
  description: string;
  images: string[];
  author: string;
  posted_at: string | null;
  posted_at_raw: string | null;
  plz: string | null;
  city: string | null;
  latitude: number | null;
  longitude: number | null;
  scraped_at: string;
  tags: string[];
  is_sold: boolean;
  is_favorite: boolean;
  category: string;
  // LLM-extracted product fields
  manufacturer: string | null;
  model_name: string | null;
  model_type: string | null;
  model_subtype: string | null;
  drive_type: string | null;
  completeness: string | null;
  attributes: Record<string, string>;
  price_indicator: 'deal' | 'fair' | 'expensive' | null;
  price_indicator_median: number | null;
  price_indicator_count: number | null;
}

export interface PaginatedResponse {
  total: number;
  page: number;
  per_page: number;
  items: ListingSummary[];
}

export interface PlzResponse {
  plz: string;
  city: string;
  lat: number;
  lon: number;
}

export interface ScrapeSummary {
  pages_crawled: number;
  new: number;
  updated: number;
  rechecked: number;
  sold_found: number;
  cleaned_sold: number;
  deleted_stale: number;
}

export type ScrapeJobStatus = 'idle' | 'running' | 'done' | 'error';
export type ScrapePhase = 'phase1' | 'phase2' | 'phase3' | null;

export interface ScrapeStatus {
  status: ScrapeJobStatus;
  job_type: 'update' | 'regular' | null;
  started_at: string | null;
  finished_at: string | null;
  phase: ScrapePhase;
  progress: string | null;
  summary: ScrapeSummary | null;
  error: string | null;
}

export interface ScrapeLogEntry {
  job_type: 'update' | 'regular';
  finished_at: string;  // ISO 8601
  summary: ScrapeSummary | null;
  error: string | null;
}

export interface ListingsQueryParams {
  page?: number;
  per_page?: number;
  search?: string | null;
  sort?: 'date' | 'price' | 'distance';
  sort_dir?: 'asc' | 'desc';
  plz?: string | null;
  max_distance?: number | null;
  category?: string | null;
  price_min?: number | null;
  price_max?: number | null;
  drive_type?: string;
  completeness?: string;
  shipping_available?: boolean;
  price_indicator?: string;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

export interface SearchCriteria {
  search?: string | null;
  plz?: string | null;
  max_distance?: number | null;
  sort?: 'date' | 'price' | 'distance';
  sort_dir?: 'asc' | 'desc';
  category?: string;  // undefined = all categories; never send "all" to the backend
}

export interface SavedSearch {
  id: number;
  user_id: number;
  name: string | null;
  search: string | null;
  plz: string | null;
  max_distance: number | null;
  sort: string;
  sort_dir: string;
  is_active: boolean;
  last_checked_at: string | null;  // ISO 8601
  last_viewed_at: string | null;   // ISO 8601
  created_at: string;              // ISO 8601
  match_count: number;
  category?: string | null;  // null = all categories
}

export interface LLMModelRow {
  model_id: string;
  position: number;
  is_active: boolean;        // permanent admin flag, always true in this iteration
  active_now: boolean;       // is_active AND (disabled_until null or in past)
  context_length: number | null;
  created_upstream: string | null;  // ISO timestamp (openrouter's created)
  added_at: string;                 // ISO timestamp
  last_refresh_at: string;          // ISO timestamp
  last_error: string | null;
  consecutive_failures: number;
  disabled_until: string | null;    // ISO timestamp; countdown if future
}

export interface ComparableListing {
  id: number;
  title: string;
  url: string;
  price: string | null;
  price_numeric: number | null;
  condition: string | null;
  city: string | null;
  posted_at: string | null;
  is_favorite: boolean;
  similarity_score: number;
}

export type MatchQuality = "homogeneous" | "heterogeneous" | "insufficient";

export interface ComparablesResponse {
  match_quality: MatchQuality;
  median: number | null;
  count: number;
  listings: ComparableListing[];
}

export interface NotificationPrefs {
  new_search_results: boolean;
  fav_sold: boolean;
  fav_price: boolean;
  fav_deleted: boolean;
  fav_indicator: boolean;
}

export interface TelegramLinkResponse {
  deeplink: string;
  expires_at: string;  // ISO 8601
}
