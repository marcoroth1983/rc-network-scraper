import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import type { UserRow } from '../../types/api';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../../api/client', () => ({
  getUsers: vi.fn(),
  setUserApproval: vi.fn(),
  deleteUser: vi.fn(),
  getUserStats: vi.fn(),
}));

vi.mock('../../hooks/useAuth', () => ({
  useAuth: vi.fn(() => ({
    user: { id: 1, email: 'admin@test.com', name: 'Admin', role: 'admin' as const },
    loading: false,
  })),
}));

import { UsersPage } from '../UsersPage';
import { getUsers, setUserApproval, deleteUser } from '../../api/client';

const makeUser = (overrides: Partial<UserRow> = {}): UserRow => ({
  id: 99,
  email: 'user@test.com',
  name: null,
  is_approved: false,
  role: 'member',
  created_at: new Date().toISOString(),
  last_seen_at: null,
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('UsersPage', () => {
  it('renders a row per user with email and approval switch', async () => {
    vi.mocked(getUsers).mockResolvedValue([
      makeUser({ id: 1, email: 'admin@test.com', is_approved: true }),
      makeUser({ id: 2, email: 'other@test.com', is_approved: false }),
    ]);

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('admin@test.com')).toBeInTheDocument());
    expect(screen.getByText('other@test.com')).toBeInTheDocument();
  });

  it('toggles approval optimistically and persists via setUserApproval', async () => {
    const user2 = makeUser({ id: 2, email: 'other@test.com', is_approved: false });
    vi.mocked(getUsers).mockResolvedValue([user2]);
    vi.mocked(setUserApproval).mockResolvedValue({ ...user2, is_approved: true });

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('other@test.com')).toBeInTheDocument());

    // is_approved = false → true: no confirmation dialog, proceed immediately
    const switchEl = screen.getByRole('switch', { name: /Freischaltung für other@test.com/i });

    // Delay resolution to observe the optimistic flip before the API resolves
    let resolveApproval!: (value: UserRow) => void;
    vi.mocked(setUserApproval).mockImplementation(
      () => new Promise<UserRow>((res) => { resolveApproval = res; }),
    );

    fireEvent.click(switchEl);

    // Optimistic update: switch should be checked before API resolves
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: /Freischaltung für other@test.com/i }))
        .toHaveAttribute('aria-checked', 'true'),
    );

    // Resolve the API call
    await act(async () => {
      resolveApproval({ ...user2, is_approved: true });
    });

    expect(setUserApproval).toHaveBeenCalledWith(2, true);
  });

  it('rolls back the toggle when setUserApproval rejects', async () => {
    const user2 = makeUser({ id: 2, email: 'other@test.com', is_approved: true });
    vi.mocked(getUsers).mockResolvedValue([user2]);
    vi.mocked(setUserApproval).mockRejectedValue(new Error('Server error'));

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('other@test.com')).toBeInTheDocument());

    // is_approved = true → false: triggers AlertDialog
    const switchEl = screen.getByRole('switch', { name: /Freischaltung für other@test.com/i });
    fireEvent.click(switchEl);

    // Confirm the dialog
    const confirmBtn = await screen.findByRole('button', { name: 'Entziehen' });
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(setUserApproval).toHaveBeenCalled());

    // Switch should be rolled back to checked
    await waitFor(() => {
      const sw = screen.getByRole('switch', { name: /Freischaltung für other@test.com/i });
      expect(sw).toHaveAttribute('aria-checked', 'true');
    });

    // Error alert should be visible
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('confirms before deleting and calls deleteUser', async () => {
    const user2 = makeUser({ id: 2, email: 'other@test.com', is_approved: false });
    vi.mocked(getUsers).mockResolvedValue([user2]);
    vi.mocked(deleteUser).mockResolvedValue(undefined);

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('other@test.com')).toBeInTheDocument());

    const deleteBtn = screen.getByRole('button', { name: /Konto other@test.com löschen/i });
    fireEvent.click(deleteBtn);

    const confirmBtn = await screen.findByRole('button', { name: 'Endgültig löschen' });
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(deleteUser).toHaveBeenCalledWith(2));
  });

  it('disables approval and delete controls for the current user row', async () => {
    // id: 1 matches useAuth mock
    const selfUser = makeUser({ id: 1, email: 'admin@test.com', is_approved: true });
    vi.mocked(getUsers).mockResolvedValue([selfUser]);

    render(
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('admin@test.com')).toBeInTheDocument());

    const switchEl = screen.getByRole('switch', { name: /Freischaltung für admin@test.com/i });
    expect(switchEl).toBeDisabled();

    const deleteBtn = screen.getByRole('button', { name: /Konto admin@test.com löschen/i });
    expect(deleteBtn).toBeDisabled();
  });
});
