export interface ListingSummary {
  id: number;
  external_id: string;
  url: string;
  title: string;
  price: string | null;
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
}

export interface ListingDetail {
  id: number;
  external_id: string;
  url: string;
  title: string;
  price: string | null;
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
  is_sold: boolean;
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
  listings_found: number;
  new: number;
  updated: number;
  skipped: number;
}

export interface ListingsQueryParams {
  page?: number;
  per_page?: number;
  search?: string | null;
  sort?: 'date' | 'price' | 'distance';
  plz?: string | null;
  max_distance?: number | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}
