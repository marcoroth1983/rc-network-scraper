import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// Hoisted mocks — must precede any import that touches these modules.
vi.mock('../api', () => ({
  notificationsApi: {
    getVapidPublicKey: vi.fn().mockResolvedValue({ public_key: 'dGVzdA' }), // URL-safe b64 "test"
    createSubscription: vi.fn().mockResolvedValue(undefined),
  },
}));
vi.mock('../device-label', () => ({
  getDeviceLabel: vi.fn().mockReturnValue('Chrome auf Windows'),
}));

import { useWebPushSubscription } from '../useWebPushSubscription';
import { notificationsApi } from '../api';

type Permission = 'default' | 'denied' | 'granted';

interface StubHandles {
  mockSub: {
    endpoint: string;
    unsubscribe: ReturnType<typeof vi.fn>;
    toJSON: ReturnType<typeof vi.fn>;
  };
  mockPushManager: {
    getSubscription: ReturnType<typeof vi.fn>;
    subscribe: ReturnType<typeof vi.fn>;
  };
}

// Installs fake push APIs on window/navigator. pushSupported() is evaluated at
// render time, so stubs must be in place before renderHook() is called.
function stubPushEnvironment(permission: Permission, hasSub: boolean): StubHandles {
  const mockSub = {
    endpoint: 'https://push.example.com/stub-endpoint',
    unsubscribe: vi.fn().mockResolvedValue(true),
    toJSON: vi.fn().mockReturnValue({
      endpoint: 'https://push.example.com/stub-endpoint',
      keys: { p256dh: 'p256dh-value', auth: 'auth-value' },
    }),
  };
  const mockPushManager = {
    getSubscription: vi.fn().mockResolvedValue(hasSub ? mockSub : null),
    subscribe: vi.fn().mockResolvedValue(mockSub),
  };
  const mockRegistration = { pushManager: mockPushManager };

  Object.defineProperty(navigator, 'serviceWorker', {
    value: { ready: Promise.resolve(mockRegistration) },
    writable: true,
    configurable: true,
  });
  Object.defineProperty(window, 'Notification', {
    value: { permission, requestPermission: vi.fn().mockResolvedValue(permission) },
    writable: true,
    configurable: true,
  });
  // jsdom lacks PushManager — add a sentinel so the `'PushManager' in window` check passes.
  Object.defineProperty(window, 'PushManager', {
    value: class {},
    writable: true,
    configurable: true,
  });
  return { mockSub, mockPushManager };
}

beforeEach(() => {
  vi.mocked(notificationsApi.getVapidPublicKey).mockResolvedValue({ public_key: 'dGVzdA' });
  vi.mocked(notificationsApi.createSubscription).mockResolvedValue(undefined as never);
});
afterEach(() => {
  vi.clearAllMocks();
});

describe('useWebPushSubscription', () => {
  it('unsupported when push APIs are missing', async () => {
    Object.defineProperty(navigator, 'serviceWorker', {
      value: undefined,
      writable: true,
      configurable: true,
    });
    // Setting to undefined is not enough — `'X' in window` stays true. Delete them.
    delete (window as unknown as Record<string, unknown>)['Notification'];
    delete (window as unknown as Record<string, unknown>)['PushManager'];

    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('unsupported'));
    expect(result.current.supported).toBe(false);
  });

  it('default when permission is default', async () => {
    stubPushEnvironment('default', false);
    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('default'));
  });

  it('denied when permission is denied', async () => {
    stubPushEnvironment('denied', false);
    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('denied'));
  });

  it('granted-no-subscription when granted but getSubscription() → null', async () => {
    stubPushEnvironment('granted', false);
    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('granted-no-subscription'));
  });

  it('granted-subscribed when getSubscription() → { endpoint }', async () => {
    const { mockSub } = stubPushEnvironment('granted', true);
    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('granted-subscribed'));
    expect((result.current.state as { status: string; endpoint: string }).endpoint)
      .toBe(mockSub.endpoint);
  });

  it('subscribe requests permission, calls pushManager.subscribe, posts snake_case payload to API', async () => {
    const { mockPushManager } = stubPushEnvironment('default', false);
    vi.mocked(window.Notification.requestPermission).mockResolvedValue('granted');

    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('default'));

    await act(async () => {
      await result.current.subscribe();
    });

    expect(window.Notification.requestPermission).toHaveBeenCalledOnce();
    expect(mockPushManager.subscribe).toHaveBeenCalledWith({
      userVisibleOnly: true,
      applicationServerKey: expect.anything(),
    });
    expect(notificationsApi.createSubscription).toHaveBeenCalledWith({
      endpoint: 'https://push.example.com/stub-endpoint',
      keys: { p256dh: 'p256dh-value', auth: 'auth-value' },
      user_agent: navigator.userAgent,
      device_label: 'Chrome auf Windows',
    });
  });

  it('subscribe throws when public_key is empty', async () => {
    stubPushEnvironment('default', false);
    vi.mocked(notificationsApi.getVapidPublicKey).mockResolvedValue({ public_key: '' });

    const { result } = renderHook(() => useWebPushSubscription());
    await waitFor(() => expect(result.current.state.status).toBe('default'));

    await expect(
      act(async () => {
        await result.current.subscribe();
      }),
    ).rejects.toThrow(/VAPID-Schlüssel nicht verfügbar/);
    expect(notificationsApi.createSubscription).not.toHaveBeenCalled();
  });
});
