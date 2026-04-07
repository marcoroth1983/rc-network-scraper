import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FilterPanel from '../FilterPanel';
import type { ListingsFilter } from '../../hooks/useListings';
import * as client from '../../api/client';

const defaultFilter: ListingsFilter = {
  search: '',
  plz: '',
  sort: 'date',
  max_distance: '',
  page: 1,
};

function renderPanel(filter = defaultFilter, onChange = vi.fn()) {
  return render(
    <MemoryRouter>
      <FilterPanel filter={filter} onChange={onChange} />
    </MemoryRouter>,
  );
}

describe('FilterPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('renders search input', () => {
    renderPanel();
    expect(screen.getByPlaceholderText(/Suche/i)).toBeInTheDocument();
  });

  it('renders PLZ input', () => {
    renderPanel();
    expect(screen.getByPlaceholderText(/PLZ/i)).toBeInTheDocument();
  });

  it('calls onChange with updated search value', () => {
    const onChange = vi.fn();
    renderPanel(defaultFilter, onChange);
    const input = screen.getByPlaceholderText(/Suche/i);
    fireEvent.change(input, { target: { value: 'F-18' } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ search: 'F-18', page: 1 }),
    );
  });

  it('max_distance input is disabled when PLZ is empty', () => {
    renderPanel();
    expect(screen.getByLabelText(/Max.*Entfernung/i)).toBeDisabled();
  });

  it('max_distance input is enabled when filter.plz is set', () => {
    renderPanel({ ...defaultFilter, plz: '97070' });
    expect(screen.getByLabelText(/Max.*Entfernung/i)).not.toBeDisabled();
  });

  it('shows city name after successful PLZ validation', async () => {
    vi.spyOn(client, 'resolvePlz').mockResolvedValue({
      plz: '97070',
      city: 'Würzburg',
      lat: 49.7,
      lon: 9.9,
    });
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText(/PLZ/i), {
      target: { value: '97070' },
    });
    fireEvent.blur(screen.getByPlaceholderText(/PLZ/i));
    await waitFor(() =>
      expect(screen.getByText('Würzburg')).toBeInTheDocument(),
    );
  });

  it('shows error message when PLZ not found (404)', async () => {
    const { ApiError } = await import('../../types/api');
    vi.spyOn(client, 'resolvePlz').mockRejectedValue(new ApiError(404, 'PLZ not found'));
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText(/PLZ/i), {
      target: { value: '00000' },
    });
    fireEvent.blur(screen.getByPlaceholderText(/PLZ/i));
    await waitFor(() =>
      expect(screen.getByText(/PLZ nicht gefunden/i)).toBeInTheDocument(),
    );
  });

  it('localStorage restore on mount calls onChange with the saved PLZ', async () => {
    localStorage.setItem('rcn_ref_plz', '97070');
    vi.spyOn(client, 'resolvePlz').mockResolvedValue({
      plz: '97070',
      city: 'Würzburg',
      lat: 49.7,
      lon: 9.9,
    });
    const onChange = vi.fn();
    renderPanel(defaultFilter, onChange);
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ plz: '97070', page: 1 }),
      ),
    );
  });

  it('PLZ clear resets sort from distance to date and clears max_distance', () => {
    const onChange = vi.fn();
    renderPanel({ ...defaultFilter, plz: '97070', sort: 'distance', max_distance: '50' }, onChange);
    fireEvent.click(screen.getByLabelText('PLZ löschen'));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ plz: '', sort: 'date', max_distance: '', page: 1 }),
    );
  });

  it('distance sort option shows PLZ required label when hasValidPlz is false', () => {
    renderPanel();
    expect(screen.getByRole('option', { name: /PLZ erforderlich/i })).toBeInTheDocument();
  });

  it('PLZ clear button is hidden while validation is in progress', async () => {
    let resolve!: (v: ReturnType<typeof client.resolvePlz> extends Promise<infer R> ? R : never) => void;
    vi.spyOn(client, 'resolvePlz').mockReturnValue(
      new Promise((r) => { resolve = r; }),
    );
    renderPanel();
    fireEvent.change(screen.getByPlaceholderText(/PLZ/i), { target: { value: '97070' } });
    fireEvent.blur(screen.getByPlaceholderText(/PLZ/i));
    // While validating: clear button should not be visible
    expect(screen.queryByLabelText('PLZ löschen')).not.toBeInTheDocument();
    // Resolve to clean up
    resolve({ plz: '97070', city: 'Würzburg', lat: 49.7, lon: 9.9 });
  });
});
