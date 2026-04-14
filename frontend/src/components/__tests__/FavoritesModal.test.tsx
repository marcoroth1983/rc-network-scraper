import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import FavoritesModal from '../FavoritesModal';
import * as client from '../../api/client';

vi.mock('../../api/client');

const makeListing = (overrides = {}) => ({
  id: 1, external_id: 'ext1', url: 'https://rc-network.de/t/1',
  title: 'Flieger Alpha', price: '150 €', price_numeric: 150, condition: 'gut',
  plz: '80331', city: 'München', latitude: 48.1, longitude: 11.6,
  author: 'seller1', posted_at: '2026-03-01T10:00:00Z',
  scraped_at: '2026-04-01T10:00:00Z', distance_km: null,
  images: [], is_sold: false, is_favorite: true, category: 'flugmodelle',
  manufacturer: null, model_name: null, model_type: null, model_subtype: null,
  drive_type: null, completeness: null, shipping_available: null,
  price_indicator: null,
  price_indicator_median: null,
  price_indicator_count: null,
  ...overrides,
});

const defaultSearchProps = {
  searches: [] as never[],
  onLoadSearches: vi.fn().mockResolvedValue(undefined),
  onRemoveSearch: vi.fn().mockResolvedValue(undefined),
  onToggleSearchActive: vi.fn().mockResolvedValue(undefined),
  onMarkViewed: vi.fn().mockResolvedValue(undefined),
  onActivateSearch: vi.fn(),
};

function renderModal(props: { open: boolean; onClose?: () => void }) {
  return render(
    <MemoryRouter>
      <FavoritesModal open={props.open} onClose={props.onClose ?? vi.fn()} categories={[]} {...defaultSearchProps} />
    </MemoryRouter>
  );
}

describe('FavoritesModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when closed', () => {
    vi.mocked(client.getFavorites).mockResolvedValue([]);
    renderModal({ open: false });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders dialog with title when open', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([]);
    renderModal({ open: true });
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getByText('Meine Listen')).toBeTruthy();
  });

  it('shows loading spinner while fetching', async () => {
    // Never resolves during this check
    vi.mocked(client.getFavorites).mockReturnValue(new Promise(() => {}));
    renderModal({ open: true });
    // spinner is an animated div — verify it exists via its class
    const spinner = document.querySelector('.animate-spin');
    expect(spinner).toBeTruthy();
  });

  it('shows empty state when no favorites', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([]);
    renderModal({ open: true });
    await waitFor(() =>
      expect(screen.getByText('Keine Favoriten gespeichert')).toBeTruthy()
    );
  });

  it('renders favorite cards after loading', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([makeListing()]);
    renderModal({ open: true });
    await waitFor(() => expect(screen.getByText('Flieger Alpha')).toBeTruthy());
  });

  it('shows count in title when favorites exist', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([
      makeListing({ id: 1, title: 'Flieger Alpha' }),
      makeListing({ id: 2, title: 'Flieger Beta' }),
    ]);
    renderModal({ open: true });
    await waitFor(() => expect(screen.getByText('(2)')).toBeTruthy());
  });

  it('removes card from list when onRemove fires', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([makeListing()]);
    vi.mocked(client.toggleFavorite).mockResolvedValue(undefined);

    renderModal({ open: true });
    await waitFor(() => expect(screen.getByText('Flieger Alpha')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /entfernen/i }));
    await waitFor(() => expect(screen.queryByText('Flieger Alpha')).toBeNull());
  });

  it('calls onClose when close button clicked', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([]);
    const onClose = vi.fn();
    renderModal({ open: true, onClose });

    await waitFor(() => screen.getByRole('dialog'));
    fireEvent.click(screen.getByRole('button', { name: /schließen/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when Escape key pressed', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([]);
    const onClose = vi.fn();
    renderModal({ open: true, onClose });

    await waitFor(() => screen.getByRole('dialog'));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when backdrop clicked', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([]);
    const onClose = vi.fn();
    renderModal({ open: true, onClose });

    await waitFor(() => screen.getByRole('dialog'));
    // The dialog div itself is the backdrop — clicking it (not a child) triggers onClose
    fireEvent.click(screen.getByRole('dialog'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does NOT close when clicking inside the modal content', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([]);
    const onClose = vi.fn();
    renderModal({ open: true, onClose });

    await waitFor(() => screen.getByRole('dialog'));
    // Click the heading (inner content) — the e.target !== e.currentTarget guard must block close
    fireEvent.click(screen.getByText('Meine Listen'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shows error message when getFavorites fails', async () => {
    vi.mocked(client.getFavorites).mockRejectedValue(new Error('Network error'));
    renderModal({ open: true });

    await waitFor(() =>
      expect(screen.getByText('Merkliste konnte nicht geladen werden.')).toBeTruthy()
    );
  });

  it('shows Aufräumen button when sold favorites exist', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([
      makeListing({ is_sold: true }),
    ]);
    renderModal({ open: true });
    await waitFor(() => expect(screen.getByText('Aufräumen')).toBeTruthy());
  });

  it('Aufräumen removes sold entries from list view', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([
      makeListing({ id: 1, title: 'Verkauft', is_sold: true }),
      makeListing({ id: 2, title: 'Noch verfügbar', is_sold: false }),
    ]);
    renderModal({ open: true });

    await waitFor(() => expect(screen.getByText('Aufräumen')).toBeTruthy());
    await act(async () => {
      fireEvent.click(screen.getByText('Aufräumen'));
    });

    expect(screen.queryByText('Verkauft')).toBeNull();
    expect(screen.getByText('Noch verfügbar')).toBeTruthy();
  });

  it('refetches favorites each time modal opens', async () => {
    vi.mocked(client.getFavorites).mockResolvedValue([]);
    const { rerender } = render(
      <MemoryRouter>
        <FavoritesModal open={false} onClose={vi.fn()} categories={[]} {...defaultSearchProps} />
      </MemoryRouter>
    );

    rerender(
      <MemoryRouter>
        <FavoritesModal open={true} onClose={vi.fn()} categories={[]} {...defaultSearchProps} />
      </MemoryRouter>
    );
    await waitFor(() => expect(client.getFavorites).toHaveBeenCalledTimes(1));

    rerender(
      <MemoryRouter>
        <FavoritesModal open={false} onClose={vi.fn()} categories={[]} {...defaultSearchProps} />
      </MemoryRouter>
    );
    rerender(
      <MemoryRouter>
        <FavoritesModal open={true} onClose={vi.fn()} categories={[]} {...defaultSearchProps} />
      </MemoryRouter>
    );
    await waitFor(() => expect(client.getFavorites).toHaveBeenCalledTimes(2));
  });
});
