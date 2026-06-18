export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

export type AuthUser = {
  id: number;
  email: string;
  name: string | null;
  role: 'member' | 'admin';
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

export interface UserRow {
  id: number;
  email: string;
  name: string | null;
  is_approved: boolean;
  role: string;
  created_at: string;        // ISO timestamp
  last_seen_at: string | null; // ISO timestamp
}

export interface MetricsSummary {
  users_total: number;
  users_approved: number;
  users_pending: number;
  users_active_7d: number;
  users_active_30d: number;
  listings_total: number;
  favorites_total: number;
  saved_searches_total: number;
}

export interface TimeseriesPoint {
  day: string;   // YYYY-MM-DD
  value: number;
}

export interface MetricsTimeseries {
  days: number;
  listings_new: TimeseriesPoint[];
  listings_closed: TimeseriesPoint[];
  users_new: TimeseriesPoint[];
  logins: TimeseriesPoint[];
  notifications: TimeseriesPoint[];
}

export interface UserStats {
  user_id: number;
  saved_searches: number;
  favorites: number;
  push_devices: number;
  logins_total: number;
  logins_30d: number;
  created_at: string;
  last_seen_at: string | null;
}
