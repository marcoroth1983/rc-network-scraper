import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../../notifications/useWebPushSubscription', () => ({ useWebPushSubscription: vi.fn() }));
vi.mock('../../notifications/api', () => ({
  notificationsApi: { listSubscriptions: vi.fn(), deleteSubscription: vi.fn() },
}));
vi.mock('../../api/client', () => ({
  getNotificationPrefs: vi.fn(),
  updateNotificationPrefs: vi.fn(),
}));

import { NotificationsPanel } from '../NotificationsPanel';
import { useWebPushSubscription } from '../../notifications/useWebPushSubscription';
import { notificationsApi } from '../../notifications/api';
import { getNotificationPrefs, updateNotificationPrefs } from '../../api/client';
import type { NotificationPrefs } from '../../types/api';

const mockHook = useWebPushSubscription as unknown as ReturnType<typeof vi.fn>;
beforeEach(() => mockHook.mockReset());

describe('NotificationsPanel — state display', () => {
  it('renders unsupported message when supported=false', () => {
    mockHook.mockReturnValue({ state: { status: 'unsupported' }, supported: false, subscribe: vi.fn() });
    render(<NotificationsPanel />);
    expect(screen.getByText(/unterstützt keine Web-Push/)).toBeInTheDocument();
  });

  it('renders default state with Aktivieren button', () => {
    mockHook.mockReturnValue({ state: { status: 'default' }, supported: true, subscribe: vi.fn() });
    render(<NotificationsPanel />);
    expect(screen.getByText('Aktivieren')).toBeInTheDocument();
  });

  it('renders denied state with browser hint', () => {
    mockHook.mockReturnValue({ state: { status: 'denied' }, supported: true, subscribe: vi.fn() });
    render(<NotificationsPanel />);
    expect(screen.getByText(/im Browser blockiert/)).toBeInTheDocument();
  });

  it('renders granted-no-subscription with on-device button', () => {
    mockHook.mockReturnValue({ state: { status: 'granted-no-subscription' }, supported: true, subscribe: vi.fn() });
    render(<NotificationsPanel />);
    expect(screen.getByText('Auf diesem Gerät aktivieren')).toBeInTheDocument();
  });

  it('renders granted-subscribed confirmation', () => {
    mockHook.mockReturnValue({ state: { status: 'granted-subscribed', endpoint: 'x' }, supported: true, subscribe: vi.fn() });
    render(<NotificationsPanel />);
    expect(screen.getByText(/aktiv/)).toBeInTheDocument();
  });

  it('renders error when subscribe rejects', async () => {
    const subscribe = vi.fn().mockRejectedValue(new Error('boom'));
    mockHook.mockReturnValue({ state: { status: 'default' }, supported: true, subscribe });
    render(<NotificationsPanel />);
    fireEvent.click(screen.getByText('Aktivieren'));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/boom/));
  });
});

describe('NotificationsPanel — device list + prefs toggle', () => {
  const mockList = notificationsApi.listSubscriptions as unknown as ReturnType<typeof vi.fn>;
  const mockDelete = notificationsApi.deleteSubscription as unknown as ReturnType<typeof vi.fn>;
  const mockGetPrefs = getNotificationPrefs as unknown as ReturnType<typeof vi.fn>;
  const mockUpdatePrefs = updateNotificationPrefs as unknown as ReturnType<typeof vi.fn>;

  const prefs = (web_push_enabled: boolean): NotificationPrefs => ({
    new_search_results: true,
    fav_sold: true,
    fav_price: true,
    fav_deleted: true,
    web_push_enabled,
  });

  beforeEach(() => {
    mockHook.mockReset();
    mockList.mockReset();
    mockDelete.mockReset();
    mockGetPrefs.mockReset();
    mockUpdatePrefs.mockReset();
    mockHook.mockReturnValue({ state: { status: 'granted-subscribed', endpoint: 'x' }, supported: true, subscribe: vi.fn() });
    mockGetPrefs.mockResolvedValue(prefs(true));
  });

  it('shows device list when granted-subscribed and listSubscriptions returned rows', async () => {
    mockList.mockResolvedValue([
      { id: 1, endpoint: 'e1', device_label: 'Chrome auf Windows', user_agent: null, last_used_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z' },
      { id: 2, endpoint: 'e2', device_label: null, user_agent: null, last_used_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z' },
    ]);
    render(<NotificationsPanel />);
    await waitFor(() => expect(screen.getByText('Chrome auf Windows')).toBeInTheDocument());
    expect(screen.getByText('Unbekanntes Gerät')).toBeInTheDocument();
  });

  it('clicking Entfernen calls deleteSubscription and reloads', async () => {
    mockList
      .mockResolvedValueOnce([
        { id: 7, endpoint: 'e7', device_label: 'iPhone', user_agent: null, last_used_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z' },
      ])
      .mockResolvedValueOnce([]);
    mockDelete.mockResolvedValue(undefined);
    render(<NotificationsPanel />);

    const removeBtn = await screen.findByRole('button', { name: /Gerät iPhone entfernen/ });
    fireEvent.click(removeBtn);

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith(7));
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });

  it('toggling pref calls updateNotificationPrefs with web_push_enabled', async () => {
    mockList.mockResolvedValue([]);
    mockUpdatePrefs.mockResolvedValue(prefs(false));
    render(<NotificationsPanel />);

    const toggle = await screen.findByRole('switch', { name: 'Push aktiv' });
    expect(toggle).toHaveAttribute('aria-checked', 'true');

    fireEvent.click(toggle);
    await waitFor(() => expect(mockUpdatePrefs).toHaveBeenCalledWith({ web_push_enabled: false }));
  });
});
