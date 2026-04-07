import { render, screen, fireEvent, act } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import ScrapeButton from '../ScrapeButton';
import * as client from '../../api/client';

vi.mock('../../api/client');

const idle = { status: 'idle' as const, started_at: null, finished_at: null, phase: null, progress: null, summary: null, error: null };
const running = { ...idle, status: 'running' as const, phase: 'phase1' as const, progress: 'Seite 1 scannen…' };
const done = {
  ...idle, status: 'done' as const,
  summary: { pages_crawled: 2, new: 5, updated: 1, rechecked: 10, sold_found: 0, deleted_sold: 0, deleted_stale: 0 },
};
/**
 * Drain React's async state-update queue under fake timers.
 * Each `await Promise.resolve()` tick flushes one level of promise continuations.
 * 20 ticks covers multiple chained `await` calls in handleClick without triggering
 * setInterval (which is controlled separately with advanceTimersByTimeAsync).
 */
async function flushMicrotasks() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

describe('ScrapeButton', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows "Scrape starten" initially', () => {
    render(<ScrapeButton />);
    expect(screen.getByText('Scrape starten')).toBeTruthy();
  });

  it('polls and shows done summary after job completes', async () => {
    vi.mocked(client.startScrape).mockResolvedValue({ status: 'started' });
    vi.mocked(client.getScrapeStatus)
      .mockResolvedValueOnce(running)
      .mockResolvedValueOnce(done);

    const onDone = vi.fn();
    render(<ScrapeButton onDone={onDone} />);

    // Click triggers startScrape() + immediate getScrapeStatus() call
    await act(async () => {
      fireEvent.click(screen.getByText('Scrape starten'));
      await flushMicrotasks();
    });

    // Advance past first poll interval (3s) — fires second getScrapeStatus() call
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });

    expect(screen.queryByText(/5 neu/)).toBeTruthy();
    expect(onDone).toHaveBeenCalled();
  });

  it('shows error when startScrape fails', async () => {
    vi.mocked(client.startScrape).mockRejectedValue(new Error('Netzwerkfehler'));

    render(<ScrapeButton />);
    await act(async () => {
      fireEvent.click(screen.getByText('Scrape starten'));
      await flushMicrotasks();
    });

    expect(screen.queryByText(/Netzwerkfehler/)).toBeTruthy();
  });

  it('disables button while running', async () => {
    vi.mocked(client.startScrape).mockResolvedValue({ status: 'started' });
    vi.mocked(client.getScrapeStatus).mockResolvedValue(running);

    render(<ScrapeButton />);
    await act(async () => {
      fireEvent.click(screen.getByText('Scrape starten'));
      await flushMicrotasks();
    });

    const btn = screen.getByRole('button');
    expect(btn).toHaveProperty('disabled', true);
  });

  it('attaches to existing job when server returns already_running', async () => {
    vi.mocked(client.startScrape).mockResolvedValue({ status: 'already_running' });
    vi.mocked(client.getScrapeStatus).mockResolvedValue(running);

    render(<ScrapeButton />);
    await act(async () => {
      fireEvent.click(screen.getByText('Scrape starten'));
      await flushMicrotasks();
    });

    // Must start polling and disable the button
    const btn = screen.getByRole('button');
    expect(btn).toHaveProperty('disabled', true);
  });

  it('clears polling interval on unmount', async () => {
    vi.mocked(client.startScrape).mockResolvedValue({ status: 'started' });
    // Never resolves to done — keeps polling
    vi.mocked(client.getScrapeStatus).mockResolvedValue(running);

    const { unmount } = render(<ScrapeButton />);
    await act(async () => {
      fireEvent.click(screen.getByText('Scrape starten'));
      await flushMicrotasks();
    });

    // Interval must be active at this point
    expect(vi.getTimerCount()).toBeGreaterThan(0);

    unmount();

    // After unmount, all intervals must be cleared
    expect(vi.getTimerCount()).toBe(0);
  });
});
