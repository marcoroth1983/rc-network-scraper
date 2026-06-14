import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const getMetricsSummary = vi.fn();
const getMetricsTimeseries = vi.fn();
vi.mock('../../api/client', () => ({
  getMetricsSummary: (...a: unknown[]) => getMetricsSummary(...a),
  getMetricsTimeseries: (...a: unknown[]) => getMetricsTimeseries(...a),
}));

import { MetricsPanel } from '../MetricsPanel';

const summary = {
  users_total: 4, users_approved: 3, users_pending: 1,
  users_active_7d: 2, users_active_30d: 3,
  listings_total: 120, favorites_total: 8, saved_searches_total: 5,
};
const emptySeries = (days: number) => Array.from({ length: days }, (_, i) => ({ day: `2026-06-${String(i + 1).padStart(2, '0')}`, value: 0 }));
const ts = { days: 30, listings_new: emptySeries(30), listings_closed: emptySeries(30), users_new: emptySeries(30), logins: emptySeries(30), notifications: emptySeries(30) };

describe('MetricsPanel', () => {
  beforeEach(() => {
    getMetricsSummary.mockResolvedValue(summary);
    getMetricsTimeseries.mockResolvedValue(ts);
  });

  it('renders KPI tiles from the summary', async () => {
    render(<MetricsPanel />);
    expect(await screen.findByText('Nutzer gesamt')).toBeInTheDocument();
    expect(screen.getByText('1 wartend')).toBeInTheDocument();
  });

  it('refetches the timeseries when the range changes', async () => {
    render(<MetricsPanel />);
    await screen.findByText('Nutzer gesamt');
    fireEvent.click(screen.getByRole('button', { name: '7 Tage' }));
    await waitFor(() => expect(getMetricsTimeseries).toHaveBeenCalledWith(7));
  });
});
