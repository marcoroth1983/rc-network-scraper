import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// Must be mocked before importing any component that uses react-router-dom
type AriaCurrent = React.AnchorHTMLAttributes<HTMLAnchorElement>['aria-current'];

vi.mock('react-router-dom', () => ({
  useLocation: vi.fn(),
  Link: ({ to, children, className, onClick, 'aria-current': ariaCurrent }: {
    to: string;
    children: React.ReactNode;
    className?: string;
    onClick?: () => void;
    'aria-current'?: AriaCurrent;
  }) => (
    <a href={to} className={className} onClick={onClick} aria-current={ariaCurrent}>
      {children}
    </a>
  ),
}));

vi.mock('../../hooks/useAuth', () => ({
  useAuth: vi.fn(),
}));

import { useLocation } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';
import { Sidebar } from '../Sidebar';

const mockUseLocation = useLocation as ReturnType<typeof vi.fn>;
const mockUseAuth = useAuth as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockUseAuth.mockReturnValue({
    user: { id: 1, name: 'Test User', email: 'test@example.com', role: 'admin' },
    loading: false,
    logout: vi.fn(),
    reloadUser: vi.fn(),
  });
});

describe('Sidebar', () => {
  it('marks the active nav item based on the current route', () => {
    mockUseLocation.mockReturnValue({ pathname: '/metrics' });

    render(<Sidebar isOpen={false} onClose={vi.fn()} />);

    // Find the Metriken link — it should have the active class
    const metrikenLink = screen.getByRole('link', { name: /metriken/i });
    expect(metrikenLink).toHaveAttribute('aria-current', 'page');
    expect(metrikenLink.className).toContain('bg-surface-active');

    // Übersicht link should NOT be active
    const uebersichtLink = screen.getByRole('link', { name: /übersicht/i });
    expect(uebersichtLink).not.toHaveAttribute('aria-current', 'page');
  });

  it('renders the user email in the profile card', () => {
    mockUseLocation.mockReturnValue({ pathname: '/' });

    mockUseAuth.mockReturnValue({
      user: { id: 1, name: 'Test User', email: 'test@example.com', role: 'admin' },
      loading: false,
      logout: vi.fn(),
      reloadUser: vi.fn(),
    });

    render(<Sidebar isOpen={false} onClose={vi.fn()} />);

    expect(screen.getByText('test@example.com')).toBeInTheDocument();
  });
});
