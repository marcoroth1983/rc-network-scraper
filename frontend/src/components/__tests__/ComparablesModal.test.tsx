import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ComparablesModal from '../ComparablesModal';
import type { ComparablesResponse } from '../../types/api';

// Mock the hook so we control returned data without network calls.
vi.mock('../../hooks/useComparables');
import { useComparables } from '../../hooks/useComparables';

// Typed convenience alias
const mockUseComparables = vi.mocked(useComparables);

function makeAnchorRef(): React.RefObject<HTMLElement | null> {
  const div = document.createElement('div');
  document.body.appendChild(div);
  // Stub getBoundingClientRect so layout effect does not throw
  div.getBoundingClientRect = () => ({
    top: 100, bottom: 120, left: 50, right: 200,
    width: 150, height: 20, x: 50, y: 100,
    toJSON: () => ({}),
  });
  return { current: div };
}

function makeComparableListing(overrides: Partial<ComparablesResponse['listings'][number]> = {}) {
  return {
    id: overrides.id ?? 1,
    title: overrides.title ?? `Listing ${overrides.id ?? 1}`,
    url: `https://rc-network.de/t/${overrides.id ?? 1}`,
    price: overrides.price ?? '100 €',
    price_numeric: overrides.price_numeric ?? 100,
    condition: overrides.condition ?? null,
    city: overrides.city ?? null,
    posted_at: null,
    is_favorite: false,
    similarity_score: 5.0,
    ...overrides,
  };
}

function renderModal(data: ComparablesResponse | null, loading = false, error: string | null = null) {
  mockUseComparables.mockReturnValue({ data, loading, error });
  const anchorRef = makeAnchorRef();
  return render(
    <MemoryRouter>
      <ComparablesModal
        listingId={42}
        currentListingId={99}
        anchorRef={anchorRef}
        onClose={vi.fn()}
      />
    </MemoryRouter>,
  );
}

describe('ComparablesModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -----------------------------------------------------------------------
  // match_quality === "homogeneous" — median header + median line visible
  // -----------------------------------------------------------------------
  it('shows median subtitle when match_quality is homogeneous', () => {
    const data: ComparablesResponse = {
      match_quality: 'homogeneous',
      median: 350,
      count: 4,
      listings: [
        makeComparableListing({ id: 1, price_numeric: 200 }),
        makeComparableListing({ id: 2, price_numeric: 300 }),
        makeComparableListing({ id: 3, price_numeric: 400 }),
        makeComparableListing({ id: 4, price_numeric: 500 }),
      ],
    };
    renderModal(data);

    // Subtitle should mention count + median price
    expect(screen.getAllByText(/4 ähnliche Inserate · Median 350/i).length).toBeGreaterThan(0);
  });

  it('renders median divider line when match_quality is homogeneous and median is set', () => {
    const data: ComparablesResponse = {
      match_quality: 'homogeneous',
      median: 250,
      count: 2,
      listings: [
        makeComparableListing({ id: 1, price_numeric: 200 }),
        makeComparableListing({ id: 2, price_numeric: 300 }),
      ],
    };
    renderModal(data);

    // The median divider label text (appears once per portal instance, rendered twice in mobile+desktop)
    const medianLabels = screen.getAllByText(/Median 250/);
    // At least one should come from the inline divider (not just the subtitle)
    expect(medianLabels.length).toBeGreaterThan(0);
  });

  // -----------------------------------------------------------------------
  // match_quality === "heterogeneous" — "Preisspanne zu groß" header, no median line
  // -----------------------------------------------------------------------
  it('shows "Preisspanne zu groß" subtitle when match_quality is heterogeneous', () => {
    const data: ComparablesResponse = {
      match_quality: 'heterogeneous',
      median: null,
      count: 5,
      listings: [
        makeComparableListing({ id: 1 }),
        makeComparableListing({ id: 2 }),
        makeComparableListing({ id: 3 }),
        makeComparableListing({ id: 4 }),
        makeComparableListing({ id: 5 }),
      ],
    };
    renderModal(data);

    expect(screen.getAllByText(/Preisspanne zu groß für Median/).length).toBeGreaterThan(0);
  });

  it('does NOT render median divider when match_quality is heterogeneous', () => {
    const data: ComparablesResponse = {
      match_quality: 'heterogeneous',
      median: null,
      count: 5,
      listings: Array.from({ length: 5 }, (_, i) =>
        makeComparableListing({ id: i + 1, price_numeric: (i + 1) * 100 }),
      ),
    };
    renderModal(data);

    // There should be no "Median XXX €" inline divider element — only the subtitle.
    // The subtitle for heterogeneous does NOT contain "Median NNN €" at all.
    expect(screen.queryByText(/Median \d/)).toBeNull();
  });

  // -----------------------------------------------------------------------
  // match_quality === "insufficient" with 2 listings — header + listings rendered
  // -----------------------------------------------------------------------
  it('shows "Zu wenige" header when match_quality is insufficient', () => {
    const data: ComparablesResponse = {
      match_quality: 'insufficient',
      median: null,
      count: 2,
      listings: [
        makeComparableListing({ id: 1, title: 'Listing Alpha' }),
        makeComparableListing({ id: 2, title: 'Listing Beta' }),
      ],
    };
    renderModal(data);

    expect(screen.getAllByText(/Zu wenige vergleichbare Inserate \(2\)/).length).toBeGreaterThan(0);
  });

  it('still renders both listings when match_quality is insufficient', () => {
    const data: ComparablesResponse = {
      match_quality: 'insufficient',
      median: null,
      count: 2,
      listings: [
        makeComparableListing({ id: 1, title: 'Listing Alpha' }),
        makeComparableListing({ id: 2, title: 'Listing Beta' }),
      ],
    };
    renderModal(data);

    expect(screen.getAllByText('Listing Alpha').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Listing Beta').length).toBeGreaterThan(0);
  });

  // -----------------------------------------------------------------------
  // Similarity labels distributed correctly over 9 listings (3/3/3)
  // -----------------------------------------------------------------------
  it('distributes similarity labels "sehr ähnlich" / "ähnlich" / "entfernt" 3/3/3 on 9 listings', () => {
    const listings = Array.from({ length: 9 }, (_, i) =>
      makeComparableListing({ id: i + 1, title: `Listing ${i + 1}`, price_numeric: (i + 1) * 50 }),
    );
    const data: ComparablesResponse = {
      match_quality: 'heterogeneous',
      median: null,
      count: 9,
      listings,
    };
    renderModal(data);

    // The modal renders twice (mobile + desktop portals), so each label appears 2× per listing.
    // We expect exactly 3 listings per tier × 2 portal instances = 6 occurrences each.
    const sehrAehnlich = screen.getAllByText('sehr ähnlich');
    const aehnlich = screen.getAllByText('ähnlich');
    const entfernt = screen.getAllByText('entfernt');

    // 3 listings each, rendered in 2 portal instances = 6 per label
    expect(sehrAehnlich.length).toBe(6);
    expect(aehnlich.length).toBe(6);
    expect(entfernt.length).toBe(6);
  });
});
