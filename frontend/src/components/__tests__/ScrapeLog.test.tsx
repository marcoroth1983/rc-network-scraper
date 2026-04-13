import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import ScrapeLog from '../ScrapeLog';
import * as client from '../../api/client';

describe('ScrapeLog', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders clock icon button', () => {
    vi.spyOn(client, 'getScrapeLog').mockResolvedValue([]);
    render(<ScrapeLog />);
    expect(screen.getByRole('button', { name: /verlauf/i })).toBeInTheDocument();
  });

  it('shows "Noch keine Läufe" when log is empty', async () => {
    vi.spyOn(client, 'getScrapeLog').mockResolvedValue([]);
    render(<ScrapeLog />);
    await userEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      expect(screen.getByText(/noch keine läufe/i)).toBeInTheDocument();
    });
  });

  it('renders update entry correctly', async () => {
    vi.spyOn(client, 'getScrapeLog').mockResolvedValue([
      {
        job_type: 'update',
        finished_at: new Date('2026-04-08T14:30:00Z').toISOString(),
        summary: { pages_crawled: 2, new: 4, updated: 0, rechecked: 0, sold_found: 0, cleaned_sold: 0, deleted_stale: 0 },
        error: null,
      },
    ]);
    render(<ScrapeLog />);
    await userEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      expect(screen.getByText('update')).toBeInTheDocument();
      expect(screen.getByText('4 neu')).toBeInTheDocument();
    });
  });

  it('renders error entry with red styling', async () => {
    vi.spyOn(client, 'getScrapeLog').mockResolvedValue([
      {
        job_type: 'update',
        finished_at: new Date('2026-04-08T16:00:00Z').toISOString(),
        summary: null,
        error: 'connection timeout',
      },
    ]);
    render(<ScrapeLog />);
    await userEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      expect(screen.getByText('Fehler')).toBeInTheDocument();
      // Aurora Dark uses inline pink color instead of Tailwind text-red-500
      expect(screen.getByText('Fehler').style.color).toBe('rgb(236, 72, 153)');
    });
  });

  it('renders regular entry correctly', async () => {
    vi.spyOn(client, 'getScrapeLog').mockResolvedValue([
      {
        job_type: 'regular',
        finished_at: new Date('2026-04-08T15:00:00Z').toISOString(),
        summary: { pages_crawled: 0, new: 0, updated: 0, rechecked: 10, sold_found: 2, cleaned_sold: 1, deleted_stale: 0 },
        error: null,
      },
    ]);
    render(<ScrapeLog />);
    await userEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      expect(screen.getByText('regular')).toBeInTheDocument();
      expect(screen.getByText(/10 geprüft/)).toBeInTheDocument();
      expect(screen.getByText(/2 verkauft/)).toBeInTheDocument();
      expect(screen.getByText(/1 gelöscht/)).toBeInTheDocument();
    });
  });
});
