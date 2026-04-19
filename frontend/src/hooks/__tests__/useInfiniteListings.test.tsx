/**
 * useInfiniteListings.test.tsx
 *
 * Regression tests for the filter-to-API-call mapping in useInfiniteListings.
 * These tests verify the network-call-level guarantee: every filter dimension
 * set in the URL is forwarded to getListings() without being dropped.
 *
 * This test suite would have caught the bug where only_sold and show_outdated
 * were silently omitted from the getListings() call.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';
import type { PaginatedResponse } from '../../types/api';

// ---------------------------------------------------------------------------
// Mock the API client BEFORE any component/hook imports that depend on it
// ---------------------------------------------------------------------------
vi.mock('../../api/client', () => ({
  getListings: vi.fn(),
}));

// Mocking lib/modalLocation so the hook uses the real URL (no background override)
vi.mock('../../lib/modalLocation', () => ({
  getBackground: () => null,
}));

import { useInfiniteListings } from '../useInfiniteListings';
import * as client from '../../api/client';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const emptyPage: PaginatedResponse = {
  items: [],
  total: 0,
  page: 1,
  per_page: 20,
};

/**
 * Build a wrapper that renders the hook inside a MemoryRouter initialised
 * with the given search string (e.g. "?only_sold=true").
 */
function makeWrapper(search: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={[`/${search}`]}>
        {children}
      </MemoryRouter>
    );
  };
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  // Simulate "user has already chosen a category" so the fetch gate passes.
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key) => {
    if (key === 'rcn_category') return 'all';
    return null;
  });
  (client.getListings as ReturnType<typeof vi.fn>).mockResolvedValue(emptyPage);
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useInfiniteListings — filter forwarding to getListings', () => {
  it('passes only_sold=true to getListings when set in URL', async () => {
    renderHook(() => useInfiniteListings(), {
      wrapper: makeWrapper('?only_sold=true'),
    });

    await waitFor(() => {
      expect(client.getListings).toHaveBeenCalled();
    });

    const call = (client.getListings as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.only_sold).toBe(true);
  });

  it('passes show_outdated=true to getListings when set in URL', async () => {
    renderHook(() => useInfiniteListings(), {
      wrapper: makeWrapper('?show_outdated=true'),
    });

    await waitFor(() => {
      expect(client.getListings).toHaveBeenCalled();
    });

    const call = (client.getListings as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.show_outdated).toBe(true);
  });

  it('passes both only_sold=true and show_outdated=true together', async () => {
    renderHook(() => useInfiniteListings(), {
      wrapper: makeWrapper('?only_sold=true&show_outdated=true'),
    });

    await waitFor(() => {
      expect(client.getListings).toHaveBeenCalled();
    });

    const call = (client.getListings as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.only_sold).toBe(true);
    expect(call.show_outdated).toBe(true);
  });

  it('passes model_type to getListings (sanity baseline for existing fields)', async () => {
    renderHook(() => useInfiniteListings(), {
      wrapper: makeWrapper('?model_type=airplane'),
    });

    await waitFor(() => {
      expect(client.getListings).toHaveBeenCalled();
    });

    const call = (client.getListings as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.model_type).toBe('airplane');
  });

  it('does NOT pass only_sold when absent from URL', async () => {
    renderHook(() => useInfiniteListings(), {
      wrapper: makeWrapper('?model_type=airplane'),
    });

    await waitFor(() => {
      expect(client.getListings).toHaveBeenCalled();
    });

    const call = (client.getListings as ReturnType<typeof vi.fn>).mock.calls[0][0];
    // should be undefined / falsy — not true
    expect(call.only_sold).toBeFalsy();
    expect(call.show_outdated).toBeFalsy();
  });
});
