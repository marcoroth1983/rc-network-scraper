import type {
  CreatePushSubscriptionDto,
  PushSubscriptionDto,
  VapidKeyDto,
} from '../types/api';
import { ApiError } from '../types/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as unknown as T;
  return res.json() as Promise<T>;
}

export const notificationsApi = {
  getVapidPublicKey: async (): Promise<VapidKeyDto> => {
    const res = await fetch('/api/notifications/vapid-public-key');
    return handleResponse<VapidKeyDto>(res);
  },
  listSubscriptions: async (): Promise<PushSubscriptionDto[]> => {
    const res = await fetch('/api/notifications/subscriptions');
    return handleResponse<PushSubscriptionDto[]>(res);
  },
  createSubscription: async (dto: CreatePushSubscriptionDto): Promise<PushSubscriptionDto> => {
    const res = await fetch('/api/notifications/subscriptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dto),
    });
    return handleResponse<PushSubscriptionDto>(res);
  },
  deleteSubscription: async (id: number): Promise<void> => {
    const res = await fetch(`/api/notifications/subscriptions/${id}`, { method: 'DELETE' });
    return handleResponse<void>(res);
  },
};
