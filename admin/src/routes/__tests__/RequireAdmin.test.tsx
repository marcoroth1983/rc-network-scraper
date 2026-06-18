import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RequireAdmin } from '../RequireAdmin';

vi.mock('../../hooks/useAuth');

import { useAuth } from '../../hooks/useAuth';
import type { Mock } from 'vitest';
const mockUseAuth = useAuth as Mock;

describe('RequireAdmin', () => {
  it('shows loader while auth is loading', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: true, logout: vi.fn(), reloadUser: vi.fn() });
    render(<RequireAdmin><div>Protected</div></RequireAdmin>);
    expect(screen.getByText('Lade…')).toBeInTheDocument();
    expect(screen.queryByText('Protected')).not.toBeInTheDocument();
  });

  it('renders children for an admin user', () => {
    mockUseAuth.mockReturnValue({
      user: { id: 1, email: 'admin@test.com', name: 'Admin', role: 'admin' },
      loading: false,
      logout: vi.fn(),
      reloadUser: vi.fn(),
    });
    render(<RequireAdmin><div>Protected</div></RequireAdmin>);
    expect(screen.getByText('Protected')).toBeInTheDocument();
  });

  it('renders "Kein Zugriff" for a member user', () => {
    mockUseAuth.mockReturnValue({
      user: { id: 2, email: 'member@test.com', name: 'Member', role: 'member' },
      loading: false,
      logout: vi.fn(),
      reloadUser: vi.fn(),
    });
    render(<RequireAdmin><div>Protected</div></RequireAdmin>);
    expect(screen.getByText('Kein Zugriff')).toBeInTheDocument();
    expect(screen.queryByText('Protected')).not.toBeInTheDocument();
  });
});
