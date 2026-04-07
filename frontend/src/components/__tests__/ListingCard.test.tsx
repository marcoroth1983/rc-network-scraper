import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ListingCard from '../ListingCard';
import type { ListingSummary } from '../../types/api';

const base: ListingSummary = {
  id: 130,
  external_id: '12113834',
  url: 'https://www.rc-network.de/threads/test',
  title: 'F-18 LX Modells',
  price: '280',
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
    renderCard({ price: null });
    expect(screen.getByTestId('price')).toHaveTextContent('–');
  });

  it('shows raw price string as-is', () => {
    renderCard({ price: '480,00 EUR VB' });
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

  it('shows author', () => {
    renderCard();
    expect(screen.getByTestId('author')).toHaveTextContent('MI77');
  });
});
