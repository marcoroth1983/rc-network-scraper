import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
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

  describe('unauthenticated redirect (security-critical path)', () => {
    let originalLocation: Location;

    beforeEach(() => {
      originalLocation = window.location;
      // Replace window.location with a writable mock so we can assert href assignment.
      Object.defineProperty(window, 'location', {
        configurable: true,
        writable: true,
        value: { ...originalLocation, href: '' },
      });
    });

    afterEach(() => {
      Object.defineProperty(window, 'location', {
        configurable: true,
        writable: true,
        value: originalLocation,
      });
    });

    it('redirects to /api/auth/google with encoded origin when unauthenticated', () => {
      mockUseAuth.mockReturnValue({ user: null, loading: false, logout: vi.fn(), reloadUser: vi.fn() });
      render(<RequireAdmin><div>Protected</div></RequireAdmin>);
      const expectedHref =
        '/api/auth/google?return_to=' + encodeURIComponent(window.location.origin);
      expect(window.location.href).toBe(expectedHref);
      expect(screen.queryByText('Protected')).not.toBeInTheDocument();
    });
  });
});
