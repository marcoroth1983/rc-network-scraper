import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ListingCard from '../ListingCard';
import type { ListingSummary } from '../../types/api';
import * as client from '../../api/client';

vi.mock('../../api/client');

const base: ListingSummary = {
  id: 130,
  external_id: '12113834',
  url: 'https://www.rc-network.de/threads/test',
  title: 'F-18 LX Modells',
  price: '280',
  price_numeric: null,
  condition: 'Gut',
  plz: null,
  city: 'Würzburg',
  latitude: null,
  longitude: null,
  author: 'MI77',
  posted_at: '2026-04-06T19:22:16Z',
  scraped_at: '2026-04-06T20:54:50.935574Z',
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
};

function renderCard(props: Partial<ListingSummary> = {}) {
  return render(
    <MemoryRouter>
      <ListingCard listing={{ ...base, ...props }} />
    </MemoryRouter>,
  );
}

describe('ListingCard', () => {
  it('renders without crashing with all fields present', () => {
    renderCard();
    expect(screen.getByText('F-18 LX Modells')).toBeInTheDocument();
  });

  it('renders title as a link to /listings/:id', () => {
    renderCard();
    const link = screen.getByRole('link', { name: /F-18 LX Modells/i });
    expect(link).toHaveAttribute('href', '/listings/130');
  });

  it('shows "–" when price is null', () => {
    renderCard({ price: null, price_numeric: null });
    expect(screen.getByTestId('price')).toHaveTextContent('–');
  });

  it('shows raw price string as-is when price_numeric is null', () => {
    renderCard({ price: '480,00 EUR VB', price_numeric: null });
    expect(screen.getByTestId('price')).toHaveTextContent('480,00 EUR VB');
  });

  it('shows "–" when condition is null', () => {
    renderCard({ condition: null });
    expect(screen.getByTestId('condition')).toHaveTextContent('–');
  });

  it('shows "–" when distance_km is null', () => {
    renderCard({ distance_km: null });
    expect(screen.getByTestId('distance')).toHaveTextContent('–');
  });

  it('shows distance formatted to 1 decimal', () => {
    renderCard({ distance_km: 42.7 });
    expect(screen.getByTestId('distance')).toHaveTextContent('42.7 km');
  });

  it('shows city when present', () => {
    renderCard({ city: 'München' });
    expect(screen.getByTestId('location')).toHaveTextContent('München');
  });

  it('shows "–" when both city and plz are null', () => {
    renderCard({ city: null, plz: null });
    expect(screen.getByTestId('location')).toHaveTextContent('–');
  });

  describe('star / favorite button', () => {
    it('renders the star button with aria-label "Merken" when not favorited', () => {
      renderCard({ is_favorite: false });
      const btn = screen.getByRole('button', { name: /merken/i });
      expect(btn).toBeInTheDocument();
    });

    it('calls toggleFavorite with (id, true) when clicking the unfavorited star', async () => {
      vi.mocked(client.toggleFavorite).mockResolvedValue(undefined);
      renderCard({ is_favorite: false });
      const btn = screen.getByRole('button', { name: /merken/i });
      fireEvent.click(btn);
      await waitFor(() =>
        expect(client.toggleFavorite).toHaveBeenCalledWith(130, true),
      );
    });

    it('optimistically shows filled star (aria-label changes to "Von Merkliste entfernen") after click', async () => {
      // Delay resolution so we can observe the optimistic state before the promise settles
      vi.mocked(client.toggleFavorite).mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, 50)),
      );
      renderCard({ is_favorite: false });
      const btn = screen.getByRole('button', { name: /merken/i });
      fireEvent.click(btn);
      // Optimistic update is synchronous — label should change immediately
      await waitFor(() =>
        expect(
          screen.getByRole('button', { name: /von merkliste entfernen/i }),
        ).toBeInTheDocument(),
      );
    });

    it('renders aria-label "Von Merkliste entfernen" when already favorited', () => {
      renderCard({ is_favorite: true });
      expect(
        screen.getByRole('button', { name: /von merkliste entfernen/i }),
      ).toBeInTheDocument();
    });

    it('reverts star to original state when toggleFavorite rejects', async () => {
      vi.mocked(client.toggleFavorite).mockRejectedValue(new Error('fail'));
      renderCard({ is_favorite: false });
      const btn = screen.getByRole('button', { name: /merken/i });
      fireEvent.click(btn);
      // Optimistic update: label changes to "Von Merkliste entfernen"
      await waitFor(() =>
        expect(
          screen.getByRole('button', { name: /von merkliste entfernen/i }),
        ).toBeInTheDocument(),
      );
      // After rejection, must revert back to "Merken"
      await waitFor(() =>
        expect(
          screen.getByRole('button', { name: /^merken$/i }),
        ).toBeInTheDocument(),
      );
    });
  });
});
