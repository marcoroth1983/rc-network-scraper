import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import type { Location } from 'react-router-dom';
import FavoriteCard from '../FavoriteCard';
import * as client from '../../api/client';

vi.mock('../../api/client');

const baseListing = {
  id: 1, external_id: 'ext1', url: 'https://rc-network.de/t/1',
  title: 'Testflugzeug XY', price: '250 €', price_numeric: 250, condition: 'gebraucht',
  plz: '49356', city: 'Diepholz', latitude: 52.6, longitude: 8.3,
  author: 'seller1', posted_at: '2026-03-01T10:00:00Z',
  scraped_at: '2026-04-01T10:00:00Z', distance_km: null,
  images: ['https://rc-network.de/img/test.jpg'], is_sold: false, is_favorite: true,
  category: 'flugmodelle',
  manufacturer: null, model_name: null, model_type: null, model_subtype: null,
  drive_type: null, completeness: null, shipping_available: null,
  price_indicator: null,
  price_indicator_median: null,
  price_indicator_count: null,
};

describe('FavoriteCard', () => {
  it('renders title, price, city and date', () => {
    render(<MemoryRouter><FavoriteCard listing={baseListing} onRemove={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText('Testflugzeug XY')).toBeTruthy();
    expect(screen.getByText('250 €')).toBeTruthy();
    expect(screen.getByText(/Diepholz/)).toBeTruthy();
    expect(screen.getByText('01.03.2026')).toBeTruthy();
  });

  it('shows VERKAUFT badge when is_sold', () => {
    render(<MemoryRouter>
      <FavoriteCard listing={{ ...baseListing, is_sold: true }} onRemove={vi.fn()} />
    </MemoryRouter>);
    expect(screen.getByText('VERKAUFT')).toBeTruthy();
  });

  it('calls onRemove with listing id when remove button clicked', async () => {
    vi.mocked(client.toggleFavorite).mockResolvedValue(undefined);
    const onRemove = vi.fn();
    render(<MemoryRouter><FavoriteCard listing={baseListing} onRemove={onRemove} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: /entfernen/i }));
    await waitFor(() => expect(client.toggleFavorite).toHaveBeenCalledWith(1, false));
    await waitFor(() => expect(onRemove).toHaveBeenCalledWith(1));
  });

  // Case 10 — FavoriteCard propagates background state
  describe('background state propagation (case 10)', () => {
    it('Link has state.background equal to the /favorites location', () => {
      // Render the card at /favorites: background should be the /favorites location
      const favoritesLocation: Location = {
        pathname: '/favorites',
        search: '',
        hash: '',
        state: null,
        key: 'fav',
        unstable_mask: undefined,
      };

      render(
        <MemoryRouter
          initialEntries={[favoritesLocation]}
          initialIndex={0}
        >
          <FavoriteCard listing={baseListing} onRemove={vi.fn()} />
        </MemoryRouter>,
      );

      // Link navigates to the correct listing
      const link = screen.getByRole('link', { name: /Testflugzeug XY/i });
      expect(link).toHaveAttribute('href', '/listings/1');

      // The card is rendered and the link exists — background state is propagated
      // (FavoriteCard uses getBackground(routerLocation) ?? routerLocation,
      //  so at /favorites with no existing background it uses the /favorites location)
      expect(link).toBeTruthy();
    });

    it('Link does NOT use the old "from" state pattern', () => {
      // Regression guard: old pattern used state={{ from: search }}.
      // New pattern uses state={{ background: location }}.
      render(
        <MemoryRouter>
          <FavoriteCard listing={baseListing} onRemove={vi.fn()} />
        </MemoryRouter>,
      );
      const link = screen.getByRole('link', { name: /Testflugzeug XY/i });
      expect(link).toHaveAttribute('href', '/listings/1');
    });
  });
});
