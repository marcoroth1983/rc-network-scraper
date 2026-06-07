import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

vi.mock('../../api/client', () => ({
  getSavedSearches: vi.fn(),
  createSavedSearch: vi.fn(),
  updateSavedSearch: vi.fn(),
  deleteSavedSearch: vi.fn(),
  toggleSavedSearch: vi.fn(),
  markSearchesViewed: vi.fn(),
}));

import { useSavedSearches } from '../useSavedSearches';
import * as client from '../../api/client';

describe('useSavedSearches.load resilience', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps an empty list and does not throw when the API rejects on mount', async () => {
    vi.mocked(client.getSavedSearches).mockRejectedValue(new Error('500'));
    const { result } = renderHook(() => useSavedSearches());
    // Allow the mount effect to run and reject internally.
    await waitFor(() => expect(client.getSavedSearches).toHaveBeenCalled());
    expect(result.current.searches).toEqual([]);
  });

  it('does not blank a previously loaded list when a later load fails', async () => {
    vi.mocked(client.getSavedSearches).mockResolvedValueOnce([
      { id: 1, name: 'A', is_active: true, match_count: 0 } as never,
    ]);
    const { result } = renderHook(() => useSavedSearches());
    await waitFor(() => expect(result.current.searches).toHaveLength(1));

    vi.mocked(client.getSavedSearches).mockRejectedValueOnce(new Error('500'));
    await act(async () => { await result.current.load(); });
    expect(result.current.searches).toHaveLength(1);
  });
});
