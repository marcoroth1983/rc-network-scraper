import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

vi.mock('../../api/client', () => ({
  getMetricsSummary: vi.fn(),
  getMetricsTimeseries: vi.fn(),
}));

// Mock Recharts ResponsiveContainer to avoid zero-width JSDOM issue
vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 500, height: 220 }}>{children}</div>
    ),
  };
});

import { MetricsPage } from '../MetricsPage';
import { getMetricsSummary, getMetricsTimeseries } from '../../api/client';

const mockSummary = {
  users_total: 42,
  users_approved: 38,
  users_pending: 4,
  users_active_7d: 12,
  users_active_30d: 25,
  listings_total: 100,
  favorites_total: 55,
  saved_searches_total: 20,
};

const mockPoint = { day: '2024-01-15', value: 5 };

const mockTimeseries = {
  days: 30,
  listings_new: [mockPoint],
  listings_closed: [mockPoint],
  users_new: [mockPoint],
  logins: [mockPoint],
  notifications: [mockPoint],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('MetricsPage', () => {
  it('renders KPI values from the summary response', async () => {
    vi.mocked(getMetricsSummary).mockResolvedValue(mockSummary);
    vi.mocked(getMetricsTimeseries).mockResolvedValue(mockTimeseries);

    render(
      <MemoryRouter>
        <MetricsPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('42')).toBeInTheDocument());
    expect(screen.getByText('38')).toBeInTheDocument();
    expect(screen.getByText('4 wartend')).toBeInTheDocument();
  });

  it('renders the configured trend charts', async () => {
    vi.mocked(getMetricsSummary).mockResolvedValue(mockSummary);
    vi.mocked(getMetricsTimeseries).mockResolvedValue(mockTimeseries);

    render(
      <MemoryRouter>
        <MetricsPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('42')).toBeInTheDocument());

    expect(screen.getByText('Neue Annoncen / Tag')).toBeInTheDocument();
    expect(screen.getByText('Verkauft / Tag')).toBeInTheDocument();
    expect(screen.getByText('Neue Nutzer / Tag')).toBeInTheDocument();
    expect(screen.getByText('Logins / Tag')).toBeInTheDocument();
    expect(screen.getByText('Benachrichtigungen / Tag')).toBeInTheDocument();
  });

  it('switches the time range and refetches', async () => {
    vi.mocked(getMetricsSummary).mockResolvedValue(mockSummary);
    vi.mocked(getMetricsTimeseries).mockResolvedValue(mockTimeseries);

    render(
      <MemoryRouter>
        <MetricsPage />
      </MemoryRouter>,
    );

    // Wait for initial 30-day load
    await waitFor(() => expect(getMetricsTimeseries).toHaveBeenCalledWith(30));

    fireEvent.click(screen.getByText('7 Tage'));

    await waitFor(() => expect(getMetricsTimeseries).toHaveBeenCalledWith(7));
  });

  it('shows an error message when the metrics request fails', async () => {
    vi.mocked(getMetricsSummary).mockRejectedValue(new Error('Server Error'));
    vi.mocked(getMetricsTimeseries).mockResolvedValue(mockTimeseries);

    render(
      <MemoryRouter>
        <MetricsPage />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Fehler: Server Error'),
    );
  });
});
