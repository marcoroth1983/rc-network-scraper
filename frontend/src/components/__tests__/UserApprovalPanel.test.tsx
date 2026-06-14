import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { UserApprovalPanel } from '../UserApprovalPanel';

const getUsers = vi.fn();
const setUserApproval = vi.fn();
const deleteUser = vi.fn();
const confirmMock = vi.fn();

vi.mock('../../api/client', () => ({
  getUsers: (...a: unknown[]) => getUsers(...a),
  setUserApproval: (...a: unknown[]) => setUserApproval(...a),
  deleteUser: (...a: unknown[]) => deleteUser(...a),
}));
vi.mock('../ConfirmDialog', () => ({
  useConfirm: () => confirmMock,
  ConfirmProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('../UserStatsDialog', () => ({
  UserStatsDialog: () => null,
}));

let capturedOnRefresh: (() => Promise<void>) | null = null;
vi.mock('../../hooks/usePullToRefresh', () => ({
  usePullToRefresh: (onRefresh: () => Promise<void>) => {
    capturedOnRefresh = onRefresh;
    return { containerRef: { current: null }, pullDistance: 0, refreshing: false };
  },
}));

const baseRow = {
  id: 2, email: 'pending@example.com', name: null,
  is_approved: false, role: 'member',
  created_at: '2026-05-01T10:00:00Z', last_seen_at: null,
};

describe('UserApprovalPanel', () => {
  beforeEach(() => {
    getUsers.mockReset();
    setUserApproval.mockReset();
    deleteUser.mockReset();
    confirmMock.mockReset();
    capturedOnRefresh = null;
  });

  it('renders the fetched user list', async () => {
    getUsers.mockResolvedValue([baseRow]);
    render(<UserApprovalPanel currentUserId={1} />);
    expect(await screen.findByText('pending@example.com')).toBeInTheDocument();
  });

  it('approves without confirm when toggling false→true', async () => {
    getUsers.mockResolvedValue([baseRow]);
    setUserApproval.mockResolvedValue({ ...baseRow, is_approved: true });
    render(<UserApprovalPanel currentUserId={1} />);
    const toggle = await screen.findByRole('switch', { name: /pending@example.com/ });
    fireEvent.click(toggle);
    await waitFor(() => expect(setUserApproval).toHaveBeenCalledWith(2, true));
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it('asks for confirmation when revoking true→false and skips on cancel', async () => {
    getUsers.mockResolvedValue([{ ...baseRow, is_approved: true }]);
    confirmMock.mockResolvedValue(false);
    render(<UserApprovalPanel currentUserId={1} />);
    const toggle = await screen.findByRole('switch', { name: /pending@example.com/ });
    fireEvent.click(toggle);
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(setUserApproval).not.toHaveBeenCalled();
  });

  it('disables the toggle for the current user own row', async () => {
    getUsers.mockResolvedValue([{ ...baseRow, id: 1, email: 'me@example.com' }]);
    render(<UserApprovalPanel currentUserId={1} />);
    const toggle = await screen.findByRole('switch', { name: /me@example.com/ });
    expect(toggle).toBeDisabled();
  });

  it('refetches the user list when pull-to-refresh fires', async () => {
    getUsers.mockResolvedValue([baseRow]);
    render(<UserApprovalPanel currentUserId={1} />);
    await screen.findByText('pending@example.com');
    expect(getUsers).toHaveBeenCalledTimes(1);
    await act(async () => { await capturedOnRefresh?.(); });
    expect(getUsers).toHaveBeenCalledTimes(2);
  });

  it('shows "–" for last-seen when last_seen_at is null', async () => {
    getUsers.mockResolvedValue([baseRow]);
    render(<UserApprovalPanel currentUserId={1} />);
    await screen.findByText('pending@example.com');
    expect(screen.getByText(/Zuletzt gesehen:\s*–/)).toBeInTheDocument();
  });

  it('shows a formatted date for last-seen when present', async () => {
    getUsers.mockResolvedValue([{ ...baseRow, last_seen_at: '2026-05-20T08:00:00Z' }]);
    render(<UserApprovalPanel currentUserId={1} />);
    await screen.findByText('pending@example.com');
    expect(screen.getByText(/Zuletzt gesehen:\s*20\.05\.2026/)).toBeInTheDocument();
  });

  it('hard-deletes a user after confirmation and removes the row', async () => {
    getUsers.mockResolvedValue([baseRow]);          // baseRow.id !== currentUserId
    // Code now uses useConfirm (not window.confirm) — mock via the ConfirmDialog mock
    confirmMock.mockResolvedValue(true);
    deleteUser.mockResolvedValue(undefined);
    render(<UserApprovalPanel currentUserId={1} />);
    const btn = await screen.findByRole('button', { name: /Konto .* löschen/ });
    fireEvent.click(btn);
    await waitFor(() => expect(deleteUser).toHaveBeenCalledWith(baseRow.id));
    await waitFor(() => expect(screen.queryByText(baseRow.email)).not.toBeInTheDocument());
  });

  it('does not render a delete button for the current admin', async () => {
    getUsers.mockResolvedValue([{ ...baseRow, id: 1 }]);  // id === currentUserId
    render(<UserApprovalPanel currentUserId={1} />);
    // The row shows "pending@example.com (du)" so use regex to find it
    await screen.findByText(/pending@example\.com/);
    expect(screen.queryByRole('button', { name: /löschen/ })).not.toBeInTheDocument();
  });
});
