import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { LLMAdminPanel } from '../LLMAdminPanel';
import * as client from '../../api/client';

vi.mock('../../api/client');

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const NOW = new Date('2026-04-15T12:00:00Z').getTime();

/** Build a minimal LLMModelRow with sensible defaults. */
function makeRow(overrides: Partial<import('../../types/api').LLMModelRow> = {}): import('../../types/api').LLMModelRow {
  return {
    model_id: 'test/model:free',
    position: 0,
    is_active: true,
    active_now: true,
    context_length: 131072,
    created_upstream: '2025-09-01T00:00:00Z',
    added_at: '2026-04-01T00:00:00Z',
    last_refresh_at: new Date(NOW - 3 * 60 * 1000).toISOString(),  // 3 min ago
    consecutive_failures: 0,
    disabled_until: null,
    last_error: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LLMAdminPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // a. Renders table with model rows on successful fetch
  it('renders table with model rows on successful fetch', async () => {
    // 262144 / 1000 = 262.144 → Math.round → 262 → "262k"
    const row = makeRow({ model_id: 'qwen/qwen3:free', context_length: 262144 });
    vi.mocked(client.getLLMModels).mockResolvedValue([row]);

    render(<LLMAdminPanel />);

    await waitFor(() => {
      expect(screen.getByText('qwen/qwen3:free')).toBeInTheDocument();
    });
    expect(screen.getByText('262k')).toBeInTheDocument();
  });

  // b. Shows loading state while fetch pending
  it('shows loading state while fetch is pending', () => {
    // Never-resolving promise keeps the component in loading state
    vi.mocked(client.getLLMModels).mockReturnValue(new Promise(() => {}));

    render(<LLMAdminPanel />);

    expect(screen.getByText('Lade Modelle…')).toBeInTheDocument();
  });

  // c. Shows error state when fetch rejects
  it('shows error state when fetch rejects', async () => {
    vi.mocked(client.getLLMModels).mockRejectedValue(new Error('HTTP 403'));

    render(<LLMAdminPanel />);

    await waitFor(() => {
      expect(screen.getByText(/HTTP 403/)).toBeInTheDocument();
    });
  });

  // d. Clicking refresh button triggers refreshLLMModels and updates rows
  it('calls refreshLLMModels and updates table when refresh button is clicked', async () => {
    const initialRow = makeRow({ model_id: 'model-a:free' });
    const updatedRow = makeRow({ model_id: 'model-b:free' });
    vi.mocked(client.getLLMModels).mockResolvedValue([initialRow]);
    vi.mocked(client.refreshLLMModels).mockResolvedValue([updatedRow]);

    render(<LLMAdminPanel />);

    // Wait for initial load
    await waitFor(() => expect(screen.getByText('model-a:free')).toBeInTheDocument());

    // Click refresh
    await userEvent.click(screen.getByRole('button', { name: /aktualisieren/i }));

    await waitFor(() => {
      expect(client.refreshLLMModels).toHaveBeenCalledOnce();
      expect(screen.getByText('model-b:free')).toBeInTheDocument();
    });
    expect(screen.queryByText('model-a:free')).not.toBeInTheDocument();
  });

  // e. Disabled-model row shows "Pausiert bis …" badge and countdown
  it('shows Pausiert badge and countdown for a currently-disabled model', async () => {
    // Pin Date.now() so formatCountdown and isCurrentlyDisabled are deterministic.
    // Use fake timers but DO NOT run them — the 30s interval ticker must not fire
    // during the test or it causes un-wrapped act() warnings.
    vi.useFakeTimers({ now: NOW, shouldAdvanceTime: false });

    const disabledUntil = new Date(NOW + 45 * 60 * 1000).toISOString();  // 45 min from now
    const row = makeRow({
      model_id: 'slow/model:free',
      active_now: false,
      disabled_until: disabledUntil,
      consecutive_failures: 3,
      last_error: 'RateLimitError: 429',
    });
    vi.mocked(client.getLLMModels).mockResolvedValue([row]);

    // Wrap render + async resolution in act() so React can flush state updates
    await act(async () => {
      render(<LLMAdminPanel />);
      // Flush promise microtasks so useEffect fetch resolves
      await Promise.resolve();
      await Promise.resolve();
    });

    // Badge containing "Pausiert" should be present
    expect(screen.getByText(/Pausiert bis/)).toBeInTheDocument();

    // Countdown cell should show "noch 45 Min"
    expect(screen.getByText(/noch 45 Min/)).toBeInTheDocument();
  });

  // f. Active model row shows "Aktiv" badge
  it('shows Aktiv badge for an active model', async () => {
    const row = makeRow({ active_now: true, disabled_until: null });
    vi.mocked(client.getLLMModels).mockResolvedValue([row]);

    render(<LLMAdminPanel />);

    await waitFor(() => {
      // Both the column header <th> and the badge span contain "Aktiv".
      // Verify the badge span is present via getAllByText (at least 2 matches expected).
      const matches = screen.getAllByText('Aktiv');
      // One is the <th> header, one is the badge <span>
      expect(matches.length).toBeGreaterThanOrEqual(2);
      // The badge span has inline teal color
      const badge = matches.find(
        (el) => el.tagName === 'SPAN' && el.style.color.includes('45, 212, 191'),
      );
      expect(badge).toBeDefined();
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });
});
