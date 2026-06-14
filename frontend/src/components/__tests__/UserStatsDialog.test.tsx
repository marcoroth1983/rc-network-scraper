import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const getUserStats = vi.fn();
vi.mock('../../api/client', () => ({
  getUserStats: (...a: unknown[]) => getUserStats(...a),
}));

import { UserStatsDialog } from '../UserStatsDialog';

const stats = {
  user_id: 5, saved_searches: 3, favorites: 7, push_devices: 2,
  logins_total: 19, logins_30d: 4, created_at: '2026-02-01T00:00:00Z', last_seen_at: null,
};

describe('UserStatsDialog', () => {
  beforeEach(() => { getUserStats.mockResolvedValue(stats); });

  it('loads and shows the per-user activity counts', async () => {
    render(<UserStatsDialog userId={5} email="x@example.com" onClose={() => {}} />);
    expect(await screen.findByText('Gespeicherte Suchen')).toBeInTheDocument();
    expect(screen.getByText('19')).toBeInTheDocument();      // logins_total
  });

  it('calls onClose when the close button is clicked', async () => {
    const onClose = vi.fn();
    render(<UserStatsDialog userId={5} email="x@example.com" onClose={onClose} />);
    await screen.findByText('Gespeicherte Suchen');
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
