import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TelegramPanel } from '../TelegramPanel';
import * as client from '../../api/client';

// ConfirmDialog requires a Provider; mock useConfirm so tests don't need it
vi.mock('../ConfirmDialog', () => ({
  useConfirm: () => mockConfirm,
}));

vi.mock('../../api/client');
vi.mock('../../utils/format', () => ({
  formatRelativeTime: (iso: string) => `vor X Zeit (${iso})`,
}));

// Shared confirm mock — replaced per test
let mockConfirm: (opts: unknown) => Promise<boolean>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

import type { AuthUser } from '../../hooks/useAuth';
import type { NotificationPrefs } from '../../types/api';

function makeUser(overrides: Partial<AuthUser> = {}): AuthUser {
  return {
    id: 1,
    email: 'test@example.com',
    name: null,
    role: 'member',
    telegram_chat_id: null,
    telegram_linked_at: null,
    ...overrides,
  };
}

const defaultPrefs: NotificationPrefs = {
  new_search_results: true,
  fav_sold: true,
  fav_price: false,
  fav_deleted: false,
  fav_indicator: true,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('TelegramPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: confirm resolves false (cancel) unless overridden
    mockConfirm = vi.fn().mockResolvedValue(false);
  });

  // 1. Renders "Nicht verbunden" + link button when telegram_chat_id is null
  it('renders "Nicht verbunden" and link button when not linked', () => {
    const user = makeUser({ telegram_chat_id: null });

    render(<TelegramPanel user={user} onUserReload={vi.fn()} />);

    expect(screen.getByText('Nicht verbunden')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /mit telegram verbinden/i })).toBeInTheDocument();
  });

  // 2. Clicking link button calls linkTelegram, tries tg:// native scheme first,
  //    then falls back to the https://t.me/ deeplink after 800ms if the page
  //    is still visible (meaning the Telegram app did not catch the tg:// URL).
  it('calls linkTelegram, tries tg:// first, falls back to https after 800ms', async () => {
    const user = makeUser({ telegram_chat_id: null });
    const deeplink = 'https://t.me/testbot?start=abc123';
    vi.mocked(client.linkTelegram).mockResolvedValue({
      deeplink,
      expires_at: '2026-04-17T12:00:00Z',
    });

    // Capture every assignment to window.location.href without actually
    // navigating (JSDOM would throw on cross-origin navigation).
    const navigations: string[] = [];
    const descriptor = Object.getOwnPropertyDescriptor(window, 'location')!;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: new Proxy(window.location, {
        set(target, prop, value) {
          if (prop === 'href') {
            navigations.push(String(value));
            return true;
          }
          return Reflect.set(target, prop, value);
        },
      }),
    });

    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<TelegramPanel user={user} onUserReload={vi.fn()} />);
      await userEvent.click(screen.getByRole('button', { name: /mit telegram verbinden/i }));

      // Wait for the first navigation (tg://)
      await waitFor(() => {
        expect(client.linkTelegram).toHaveBeenCalledOnce();
        expect(navigations.some((u) => u.startsWith('tg://resolve?domain=testbot&start=abc123'))).toBe(true);
      });

      // Advance timers past the 800ms fallback window
      vi.advanceTimersByTime(900);
      expect(navigations).toContain(deeplink);
    } finally {
      vi.useRealTimers();
      Object.defineProperty(window, 'location', descriptor);
    }
  });

  // 3. Renders toggles and "Verbunden"-status when telegram_chat_id is set
  it('renders connected status and toggles when linked', async () => {
    const linkedAt = '2026-04-10T10:00:00Z';
    const user = makeUser({ telegram_chat_id: 12345, telegram_linked_at: linkedAt });
    vi.mocked(client.getNotificationPrefs).mockResolvedValue(defaultPrefs);

    render(<TelegramPanel user={user} onUserReload={vi.fn()} />);

    // Status text contains the checkmark and "Verbunden"
    await waitFor(() => {
      expect(screen.getByText(/Verbunden seit/)).toBeInTheDocument();
    });

    // All 5 toggle labels visible
    expect(screen.getByText('Neue Suchtreffer')).toBeInTheDocument();
    expect(screen.getByText('Verkauft')).toBeInTheDocument();
    expect(screen.getByText('Preis')).toBeInTheDocument();
    expect(screen.getByText('Gelöscht')).toBeInTheDocument();
    expect(screen.getByText('Preisbewertung')).toBeInTheDocument();

    // Trennen button present
    expect(screen.getByRole('button', { name: /telegram-verbindung trennen/i })).toBeInTheDocument();
  });

  // 4. Clicking a toggle calls updateNotificationPrefs with the flipped value
  it('calls updateNotificationPrefs with flipped value when toggle is clicked', async () => {
    const user = makeUser({ telegram_chat_id: 12345, telegram_linked_at: '2026-04-10T10:00:00Z' });
    vi.mocked(client.getNotificationPrefs).mockResolvedValue(defaultPrefs);
    // fav_sold starts true → clicking it sends { fav_sold: false }
    vi.mocked(client.updateNotificationPrefs).mockResolvedValue({ ...defaultPrefs, fav_sold: false });

    render(<TelegramPanel user={user} onUserReload={vi.fn()} />);

    // Wait for prefs to load
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Verkauft' })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole('switch', { name: 'Verkauft' }));

    await waitFor(() => {
      expect(client.updateNotificationPrefs).toHaveBeenCalledWith({ fav_sold: false });
    });
  });

  // 5. Failed updateNotificationPrefs reverts the toggle UI
  it('reverts toggle to original value when updateNotificationPrefs fails', async () => {
    const user = makeUser({ telegram_chat_id: 12345, telegram_linked_at: '2026-04-10T10:00:00Z' });
    // fav_sold starts true
    vi.mocked(client.getNotificationPrefs).mockResolvedValue(defaultPrefs);
    vi.mocked(client.updateNotificationPrefs).mockRejectedValue(new Error('Server error'));

    render(<TelegramPanel user={user} onUserReload={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Verkauft' })).toBeInTheDocument();
    });

    const toggle = screen.getByRole('switch', { name: 'Verkauft' });
    // Initially checked (fav_sold: true)
    expect(toggle).toHaveAttribute('aria-checked', 'true');

    await userEvent.click(toggle);

    // After failed PUT, aria-checked reverts to true
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Verkauft' })).toHaveAttribute('aria-checked', 'true');
    });
  });

  // 6. visibilitychange fires while unlinked → onUserReload is called
  it('calls onUserReload when visibilitychange fires and user is not linked', () => {
    const user = makeUser({ telegram_chat_id: null });
    const onUserReload = vi.fn();

    render(<TelegramPanel user={user} onUserReload={onUserReload} />);

    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));

    expect(onUserReload).toHaveBeenCalledOnce();
  });

  // 7. visibilitychange fires while already linked → onUserReload is NOT called
  it('does not call onUserReload on visibilitychange when user is already linked', () => {
    const user = makeUser({ telegram_chat_id: 12345, telegram_linked_at: '2026-04-10T10:00:00Z' });
    vi.mocked(client.getNotificationPrefs).mockResolvedValue(defaultPrefs);
    const onUserReload = vi.fn();

    render(<TelegramPanel user={user} onUserReload={onUserReload} />);

    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));

    expect(onUserReload).not.toHaveBeenCalled();
  });

  // 8. visibilitychange fires while hidden → onUserReload is NOT called (guards if (!document.hidden))
  it('does not call onUserReload when visibilitychange fires but document is hidden', () => {
    const user = makeUser({ telegram_chat_id: null });
    const onUserReload = vi.fn();

    render(<TelegramPanel user={user} onUserReload={onUserReload} />);

    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));

    expect(onUserReload).not.toHaveBeenCalled();
  });

  // 9. Transitioning from unlinked to linked tears down the listener — no reload after rerender
  it('does not call onUserReload after rerender with linked user', () => {
    const unlinkedUser = makeUser({ telegram_chat_id: null });
    const linkedUser = makeUser({ telegram_chat_id: 12345, telegram_linked_at: '2026-04-10T10:00:00Z' });
    vi.mocked(client.getNotificationPrefs).mockResolvedValue(defaultPrefs);
    const onUserReload = vi.fn();

    const { rerender } = render(<TelegramPanel user={unlinkedUser} onUserReload={onUserReload} />);

    // Re-render with a linked user (simulates Telegram link completing in another tab)
    rerender(<TelegramPanel user={linkedUser} onUserReload={onUserReload} />);

    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));

    expect(onUserReload).not.toHaveBeenCalled();
  });

  // 10. Unlink button opens confirm dialog, then calls unlinkTelegram + onUserReload on confirm
  it('calls unlinkTelegram and onUserReload after confirm dialog is accepted', async () => {
    const user = makeUser({ telegram_chat_id: 12345, telegram_linked_at: '2026-04-10T10:00:00Z' });
    vi.mocked(client.getNotificationPrefs).mockResolvedValue(defaultPrefs);
    vi.mocked(client.unlinkTelegram).mockResolvedValue({ ok: true });
    const onUserReload = vi.fn();
    // Override mockConfirm to resolve true (confirmed)
    mockConfirm = vi.fn().mockResolvedValue(true);

    render(<TelegramPanel user={user} onUserReload={onUserReload} />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /telegram-verbindung trennen/i })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole('button', { name: /telegram-verbindung trennen/i }));

    await waitFor(() => {
      expect(mockConfirm).toHaveBeenCalledOnce();
      expect(client.unlinkTelegram).toHaveBeenCalledOnce();
      expect(onUserReload).toHaveBeenCalledOnce();
    });
  });
});
