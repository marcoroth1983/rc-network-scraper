import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../useWebPushSubscription', () => ({ useWebPushSubscription: vi.fn() }));
vi.mock('../../lib/pwa-detect', () => ({ isIos: vi.fn(() => false), isStandalone: vi.fn(() => true) }));

import { FirstStartPushPrompt } from '../FirstStartPushPrompt';
import { useWebPushSubscription } from '../useWebPushSubscription';

const mockHook = useWebPushSubscription as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  mockHook.mockReset();
});

describe('FirstStartPushPrompt', () => {
  it('hides when localStorage flag is set', () => {
    localStorage.setItem('rcn_notif_asked', 'true');
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe: vi.fn() });
    const { container } = render(<FirstStartPushPrompt />);
    expect(container.firstChild).toBeNull();
  });

  it('hides when state is not default', () => {
    mockHook.mockReturnValue({ state: { status: 'granted-subscribed', endpoint: 'x' }, subscribe: vi.fn() });
    const { container } = render(<FirstStartPushPrompt />);
    expect(container.firstChild).toBeNull();
  });

  it('shows banner when state is default and no flag set', () => {
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe: vi.fn() });
    render(<FirstStartPushPrompt />);
    expect(screen.getByText(/Benachrichtigungen aktivieren/)).toBeInTheDocument();
  });

  it('dismiss sets flag and hides banner', () => {
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe: vi.fn() });
    const { container } = render(<FirstStartPushPrompt />);
    fireEvent.click(screen.getByText('Später'));
    expect(localStorage.getItem('rcn_notif_asked')).toBe('true');
    expect(container.firstChild).toBeNull();
  });

  it('enable calls subscribe then sets flag', async () => {
    const subscribe = vi.fn().mockResolvedValue(undefined);
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe });
    render(<FirstStartPushPrompt />);
    fireEvent.click(screen.getByText('Aktivieren'));
    await waitFor(() => expect(subscribe).toHaveBeenCalledOnce());
    await waitFor(() => expect(localStorage.getItem('rcn_notif_asked')).toBe('true'));
  });

  it('hidden on iOS Safari without standalone', async () => {
    const pwa = await import('../../lib/pwa-detect');
    (pwa.isIos as unknown as ReturnType<typeof vi.fn>).mockReturnValue(true);
    (pwa.isStandalone as unknown as ReturnType<typeof vi.fn>).mockReturnValue(false);
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe: vi.fn() });
    const { container } = render(<FirstStartPushPrompt />);
    expect(container.firstChild).toBeNull();
  });

  it('shows error when subscribe rejects', async () => {
    const subscribe = vi.fn().mockRejectedValue(new Error('boom'));
    mockHook.mockReturnValue({ state: { status: 'default' }, subscribe });
    render(<FirstStartPushPrompt />);
    fireEvent.click(screen.getByText('Aktivieren'));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/boom/));
  });
});
