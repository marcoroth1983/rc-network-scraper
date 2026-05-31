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
  it('renders admin panels for an admin user', async () => {
    render(<MemoryRouter><AdminPage user={adminUser} /></MemoryRouter>);
    expect(await screen.findByText('Benutzer-Freischaltung')).toBeInTheDocument();
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
