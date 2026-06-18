import type {
  LLMModelRow,
  MetricsSummary,
  MetricsTimeseries,
  UserRow,
  UserStats,
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

export async function getLLMModels(): Promise<LLMModelRow[]> {
  const res = await fetch('/api/admin/llm-models');
  return handleResponse<LLMModelRow[]>(res);
}

export async function refreshLLMModels(): Promise<LLMModelRow[]> {
  const res = await fetch('/api/admin/llm-models/refresh', { method: 'POST' });
  return handleResponse<LLMModelRow[]>(res);
}

export async function getUsers(): Promise<UserRow[]> {
  const res = await fetch('/api/admin/users');
  return handleResponse<UserRow[]>(res);
}

export async function setUserApproval(userId: number, isApproved: boolean): Promise<UserRow> {
  const res = await fetch(`/api/admin/users/${userId}/approval`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_approved: isApproved }),
  });
  return handleResponse<UserRow>(res);
}

export async function deleteUser(userId: number): Promise<void> {
  const res = await fetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
  if (!res.ok) {
    throw new ApiError(res.status, `HTTP ${res.status}`);
  }
}

export async function getUserStats(userId: number): Promise<UserStats> {
  const res = await fetch(`/api/admin/users/${userId}/stats`);
  return handleResponse<UserStats>(res);
}

export async function getMetricsSummary(): Promise<MetricsSummary> {
  const res = await fetch('/api/admin/metrics/summary');
  return handleResponse<MetricsSummary>(res);
}

export async function getMetricsTimeseries(days: number): Promise<MetricsTimeseries> {
  const res = await fetch(`/api/admin/metrics/timeseries?days=${days}`);
  return handleResponse<MetricsTimeseries>(res);
}
