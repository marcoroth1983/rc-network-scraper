import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AdminPage } from '../AdminPage';
import type { AuthUser } from '../../hooks/useAuth';

vi.mock('../../api/client', () => ({
  getLLMModels: vi.fn().mockResolvedValue([]),
  refreshLLMModels: vi.fn().mockResolvedValue([]),
  getUsers: vi.fn().mockResolvedValue([]),
  setUserApproval: vi.fn(),
  // PLAN-033: AdminPage now hosts MetricsPanel (user list moved to /admin/users)
  getMetricsSummary: vi.fn().mockResolvedValue({
    users_total: 0, users_approved: 0, users_pending: 0,
    users_active_7d: 0, users_active_30d: 0,
    listings_total: 0, favorites_total: 0, saved_searches_total: 0,
  }),
  getMetricsTimeseries: vi.fn().mockResolvedValue({
    days: 30, listings_new: [], listings_closed: [], users_new: [], logins: [], notifications: [],
  }),
}));
vi.mock('../../components/ConfirmDialog', () => ({
  useConfirm: () => vi.fn(),
  ConfirmProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('../../hooks/usePullToRefresh', () => ({
  usePullToRefresh: () => ({ containerRef: { current: null }, pullDistance: 0, refreshing: false }),
}));

const adminUser: AuthUser = { id: 1, email: 'admin@example.com', name: 'A', role: 'admin' };
const memberUser: AuthUser = { id: 2, email: 'member@example.com', name: 'M', role: 'member' };

describe('AdminPage', () => {
  it('renders the dashboard panels + user-management link for an admin user', async () => {
    render(<MemoryRouter><AdminPage user={adminUser} /></MemoryRouter>);
    // Metrics panel heading (user list moved to /admin/users in PLAN-033)
    expect(await screen.findByText('Nutzungs-Metriken')).toBeInTheDocument();
    // Link card to the dedicated account-management page
    expect(screen.getByRole('link', { name: /Benutzer-Verwaltung/ })).toHaveAttribute('href', '/admin/users');
  });

  it('redirects a non-admin user to home', () => {
    render(
      <MemoryRouter initialEntries={['/admin']}>
        <Routes>
          <Route path="/admin" element={<AdminPage user={memberUser} />} />
          <Route path="/" element={<div>HOME</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('HOME')).toBeInTheDocument();
  });
});
