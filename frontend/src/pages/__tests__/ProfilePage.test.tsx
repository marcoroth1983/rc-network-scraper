import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ProfilePage } from '../ProfilePage';
import type { AuthUser } from '../../hooks/useAuth';

vi.mock('../../api/client', () => ({
  resolvePlz: vi.fn().mockResolvedValue({ plz: '12345', city: 'Berlin', lat: 52.5, lon: 13.4 }),
}));
vi.mock('../../components/NotificationsPanel', () => ({
  NotificationsPanel: () => <div>NotificationsPanel</div>,
}));

const noop = () => {};
const adminUser: AuthUser = { id: 1, email: 'admin@example.com', name: 'A', role: 'admin' };
const memberUser: AuthUser = { id: 2, email: 'member@example.com', name: 'M', role: 'member' };

function renderProfile(user: AuthUser) {
  return render(
    <MemoryRouter>
      <ProfilePage user={user} onLogout={noop} onUserReload={noop} />
    </MemoryRouter>,
  );
}

describe('ProfilePage', () => {
  // PLAN-034: the admin area moved to a standalone console (admin.rcn-scout.d2x-labs.de);
  // the PWA no longer links to /admin for anyone, including admins.
  it('no longer shows an Admin-Bereich button for an admin', () => {
    renderProfile(adminUser);
    expect(screen.queryByRole('button', { name: 'Admin-Bereich' })).not.toBeInTheDocument();
  });

  it('shows no Admin-Bereich button for a non-admin either', () => {
    renderProfile(memberUser);
    expect(screen.queryByRole('button', { name: 'Admin-Bereich' })).not.toBeInTheDocument();
  });

  it('no longer renders the admin panels inline', () => {
    renderProfile(adminUser);
    expect(screen.queryByText('Benutzer-Freischaltung')).not.toBeInTheDocument();
  });
});
