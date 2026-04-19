import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import ComparablesModal from '../ComparablesModal';
import type { ComparablesResponse } from '../../types/api';

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

function makeData(overrides: Partial<ComparablesResponse> = {}): ComparablesResponse {
  return {
    count: overrides.count ?? 2,
    listings: overrides.listings ?? [
      { id: 1, title: 'Flieger Alpha', url: 'https://rc-network.de/t/1', price: '100 €', price_numeric: 100, posted_at: null },
      { id: 2, title: 'Flieger Beta', url: 'https://rc-network.de/t/2', price: '200 €', price_numeric: 200, posted_at: null },
    ],
  };
}

function renderModal(data: ComparablesResponse) {
  const anchorRef = makeAnchorRef();
  return render(
    <ComparablesModal
      data={data}
      anchorRef={anchorRef}
      onClose={vi.fn()}
    />,
  );
}

describe('ComparablesModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // 1. Renders each listing with title + price + link button
  it('renders each listing with title, price, and external-link button', () => {
    renderModal(makeData());

    // Both titles appear (modal renders in two portals: mobile + desktop)
    expect(screen.getAllByText('Flieger Alpha').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Flieger Beta').length).toBeGreaterThan(0);

    // Prices appear
    expect(screen.getAllByText('100 €').length).toBeGreaterThan(0);
    expect(screen.getAllByText('200 €').length).toBeGreaterThan(0);

    // Link buttons to each listing
    const linkButtons = screen.getAllByRole('link', { name: /zum inserat öffnen/i });
    expect(linkButtons.length).toBeGreaterThan(0);
  });

  // 2. Renders subtitle with count
  it('renders "{count} ähnliche Inserate" subtitle', () => {
    renderModal(makeData({ count: 5 }));

    const subtitles = screen.getAllByText('5 ähnliche Inserate');
    expect(subtitles.length).toBeGreaterThan(0);
  });

  // 3. Link buttons have target="_blank" and rel="noopener noreferrer"
  it('link button has target="_blank" and rel="noopener noreferrer"', () => {
    renderModal(makeData());

    const linkButtons = screen.getAllByRole('link', { name: /zum inserat öffnen/i });
    // Check the first occurrence
    const link = linkButtons[0];
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  // 4. Empty state
  it('shows "Keine vergleichbaren Inserate." when count=0 and listings=[]', () => {
    renderModal(makeData({ count: 0, listings: [] }));

    const emptyMessages = screen.getAllByText('Keine vergleichbaren Inserate.');
    expect(emptyMessages.length).toBeGreaterThan(0);
  });

  // 5. Clicking a row does NOT navigate — only the <a> on the link icon navigates
  it('list rows have no Link wrapper — only the external-link <a> navigates', () => {
    renderModal(makeData());

    // Title spans should not be anchor tags (they are <span> elements)
    const titleElements = screen.getAllByText('Flieger Alpha');
    titleElements.forEach((el) => {
      // Each title should be a span, not an anchor
      expect(el.tagName.toLowerCase()).not.toBe('a');
    });

    // The only links present are the external-link buttons
    const allLinks = screen.getAllByRole('link');
    // All links must be "Zum Inserat öffnen" links — no row-level navigation links
    allLinks.forEach((link) => {
      expect(link).toHaveAttribute('aria-label', 'Zum Inserat öffnen');
    });
  });
});
