import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { notificationsApi } from '../api';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const ok = (json: unknown, status = 200) => ({ ok: status < 400, status, json: () => Promise.resolve(json) });

describe('notificationsApi', () => {
  it('getVapidPublicKey GETs /api/notifications/vapid-public-key', async () => {
    fetchMock.mockResolvedValue(ok({ public_key: 'pub' }));
    await notificationsApi.getVapidPublicKey();
    expect(fetchMock).toHaveBeenCalledWith('/api/notifications/vapid-public-key');
  });

  it('createSubscription POSTs JSON body', async () => {
    fetchMock.mockResolvedValue(ok({ id: 1, endpoint: 'x' }, 201));
    await notificationsApi.createSubscription({ endpoint: 'x', keys: { p256dh: 'p', auth: 'a' } });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/notifications/subscriptions',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('deleteSubscription DELETEs the id path and returns void on 204', async () => {
    fetchMock.mockResolvedValue(ok(undefined, 204));
    await expect(notificationsApi.deleteSubscription(42)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/notifications/subscriptions/42',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('throws ApiError on 4xx', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: 'gone' }) });
    await expect(notificationsApi.deleteSubscription(99)).rejects.toMatchObject({ status: 404 });
  });
});
