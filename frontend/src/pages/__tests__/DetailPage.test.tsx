/**
 * DetailPage.test.tsx — cases 12, 13, 14, 15, 16
 *
 * Tests for the share button and author-listings split on DetailPage.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import type { ListingDetail, ListingSummary } from '../../types/api';

// ---------------------------------------------------------------------------
// Mocks — declared before any imports that depend on them
// ---------------------------------------------------------------------------
vi.mock('../../api/client');
vi.mock('../../hooks/useAuth', () => ({
  useAuth: vi.fn().mockReturnValue({
    user: { id: 1, email: 'admin@example.com', name: 'Admin', role: 'admin' },
    loading: false,
    logout: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Import AFTER mocks
// ---------------------------------------------------------------------------
import * as client from '../../api/client';
import DetailPage from '../../pages/DetailPage';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const baseListing: ListingDetail = {
  id: 42,
  external_id: 'ext42',
  url: 'https://rc-network.de/t/42',
  title: 'Testflieger Deluxe',
  price: '350 €',
  price_numeric: 350,
  condition: 'gut',
  shipping: 'Versand möglich',
  description: 'Sehr gepflegtes Modell.',
  images: [],
  author: 'seller1',
  posted_at: '2026-03-01T10:00:00Z',
  posted_at_raw: '01.03.2026',
  plz: '80331',
  city: 'München',
  latitude: 48.1,
  longitude: 11.6,
  scraped_at: '2026-04-01T10:00:00Z',
  tags: [],
  is_sold: false,
  is_favorite: false,
  category: 'flugmodelle',
  manufacturer: null,
  model_name: null,
  model_type: null,
  model_subtype: null,
  drive_type: null,
  completeness: null,
  attributes: {},
  price_indicator: null,
  price_indicator_median: null,
  price_indicator_count: null,
};

function makeAuthorListing(overrides: Partial<ListingSummary> = {}): ListingSummary {
  return {
    id: 10,
    external_id: 'extA',
    url: 'https://rc-network.de/t/10',
    title: 'Anderes Modell',
    price: '200 €',
    price_numeric: 200,
    condition: 'gut',
    plz: '80331',
    city: 'München',
    latitude: 48.1,
    longitude: 11.6,
    author: 'seller1',
    posted_at: '2026-02-01T10:00:00Z',
    scraped_at: '2026-04-01T10:00:00Z',
    distance_km: null,
    images: [],
    is_sold: false,
    is_favorite: false,
    category: 'flugmodelle',
    manufacturer: null,
    model_name: null,
    model_type: null,
    model_subtype: null,
    drive_type: null,
    completeness: null,
    shipping_available: null,
    price_indicator: null,
    price_indicator_median: null,
    price_indicator_count: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Render helper
// ---------------------------------------------------------------------------
function renderDetailPage() {
  return render(
    <MemoryRouter initialEntries={['/listings/42']} initialIndex={0}>
      <Routes>
        <Route path="/listings/:id" element={<DetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function waitForListing() {
  await waitFor(() => {
    expect(screen.getByText('Testflieger Deluxe')).toBeTruthy();
  });
}

// ---------------------------------------------------------------------------
// Case 12 — share via navigator.share
// ---------------------------------------------------------------------------
describe('DetailPage — case 12: share via navigator.share', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.getListing).mockResolvedValue({ ...baseListing });
    vi.mocked(client.getListingsByAuthor).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('calls navigator.share with the listing URL and title', async () => {
    const shareMock = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', {
      ...navigator,
      share: shareMock,
    });

    renderDetailPage();
    await waitForListing();

    const shareButton = screen.getByRole('button', { name: /teilen/i });
    await act(async () => {
      fireEvent.click(shareButton);
    });

    expect(shareMock).toHaveBeenCalledWith({
      url: `${window.location.origin}/listings/42`,
      title: 'Testflieger Deluxe',
    });
  });
});

// ---------------------------------------------------------------------------
// Case 13 — clipboard fallback + check-mark icon for ~2s
// ---------------------------------------------------------------------------
describe('DetailPage — case 13: clipboard fallback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.getListing).mockResolvedValue({ ...baseListing });
    vi.mocked(client.getListingsByAuthor).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    // Always restore real timers so no leak into subsequent tests
    vi.useRealTimers();
  });

  it('writes to clipboard and shows check-mark icon, then reverts after 2s', async () => {
    const clipboardWriteText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', {
      ...navigator,
      share: undefined,
      clipboard: {
        writeText: clipboardWriteText,
      },
    });

    // Load the component with real timers
    renderDetailPage();
    await waitForListing();

    const shareButton = screen.getByRole('button', { name: /teilen/i });

    // Switch to fake timers AFTER the component has loaded
    vi.useFakeTimers();

    await act(async () => {
      fireEvent.click(shareButton);
      // Drain the clipboard.writeText promise (mockResolvedValue resolves in one tick)
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(clipboardWriteText).toHaveBeenCalledWith(
      `${window.location.origin}/listings/42`,
    );

    // shareCopied === true → check-mark polyline should be present
    // The component renders <polyline points="20 6 9 17 4 12"> when shareCopied
    const checkmark = document.querySelector('polyline[points="20 6 9 17 4 12"]');
    expect(checkmark).toBeTruthy();

    // Advance timers past the 2s reset
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });

    // Check-mark should be gone
    const checkmarkAfter = document.querySelector('polyline[points="20 6 9 17 4 12"]');
    expect(checkmarkAfter).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Case 14 — AbortError is swallowed
// ---------------------------------------------------------------------------
describe('DetailPage — case 14: AbortError swallowed', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.getListing).mockResolvedValue({ ...baseListing });
    vi.mocked(client.getListingsByAuthor).mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('does not show error UI or call clipboard when navigator.share rejects with AbortError', async () => {
    const clipboardWriteText = vi.fn();
    const abortError = new DOMException('', 'AbortError');

    vi.stubGlobal('navigator', {
      ...navigator,
      share: vi.fn().mockRejectedValue(abortError),
      clipboard: {
        writeText: clipboardWriteText,
      },
    });

    renderDetailPage();
    await waitForListing();

    const shareButton = screen.getByRole('button', { name: /teilen/i });
    await act(async () => {
      fireEvent.click(shareButton);
      // Drain microtasks so the rejected promise settles
      await Promise.resolve();
      await Promise.resolve();
    });

    // No error UI
    expect(screen.queryByText(/fehler/i)).toBeNull();
    // Clipboard was NOT called — AbortError must not fall through
    expect(clipboardWriteText).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Case 15 — author listings split into aktuell / vergangen
// ---------------------------------------------------------------------------
describe('DetailPage — case 15: author listings split', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('shows two sections (aktuell + vergangen) with correct items', async () => {
    vi.clearAllMocks();
    vi.mocked(client.getListing).mockResolvedValue({ ...baseListing });
    vi.mocked(client.getListingsByAuthor).mockResolvedValue([
      makeAuthorListing({ id: 10, title: 'Aktives Modell', is_sold: false }),
      makeAuthorListing({ id: 11, title: 'Verkauftes Modell', is_sold: true }),
    ]);

    renderDetailPage();
    await waitForListing();

    await waitFor(() => {
      expect(screen.getByText(/weitere aktuelle inserate/i)).toBeTruthy();
    });
    await waitFor(() => {
      expect(screen.getByText(/vergangene inserate/i)).toBeTruthy();
    });

    expect(screen.getByText('Aktives Modell')).toBeTruthy();
    expect(screen.getByText('Verkauftes Modell')).toBeTruthy();
  });

  it('shows only aktuell section when all listings are active', async () => {
    vi.clearAllMocks();
    vi.mocked(client.getListing).mockResolvedValue({ ...baseListing });
    vi.mocked(client.getListingsByAuthor).mockResolvedValue([
      makeAuthorListing({ id: 10, title: 'Aktives Modell 1', is_sold: false }),
      makeAuthorListing({ id: 11, title: 'Aktives Modell 2', is_sold: false }),
    ]);

    renderDetailPage();
    await waitForListing();

    await waitFor(() => {
      expect(screen.getByText(/weitere aktuelle inserate/i)).toBeTruthy();
    });
    expect(screen.queryByText(/vergangene inserate/i)).toBeNull();
  });

  it('shows only vergangen section when all listings are sold', async () => {
    vi.clearAllMocks();
    vi.mocked(client.getListing).mockResolvedValue({ ...baseListing });
    vi.mocked(client.getListingsByAuthor).mockResolvedValue([
      makeAuthorListing({ id: 10, title: 'Verkauft 1', is_sold: true }),
    ]);

    renderDetailPage();
    await waitForListing();

    await waitFor(() => {
      expect(screen.getByText(/vergangene inserate/i)).toBeTruthy();
    });
    expect(screen.queryByText(/weitere aktuelle inserate/i)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Case 16 — desktop layout class smoke-test
// ---------------------------------------------------------------------------
describe('DetailPage — case 16: desktop 3-column layout', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('3-column grid container has lg:grid-cols-12 class at 1280px viewport', async () => {
    vi.clearAllMocks();
    vi.mocked(client.getListing).mockResolvedValue({ ...baseListing });
    vi.mocked(client.getListingsByAuthor).mockResolvedValue([]);

    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 1280,
    });
    window.dispatchEvent(new Event('resize'));

    renderDetailPage();
    await waitForListing();

    // The plan specifies a grid div with class containing "lg:grid-cols-12"
    const gridContainer = document.querySelector('.lg\\:grid-cols-12');
    expect(gridContainer).toBeTruthy();
  });
});
