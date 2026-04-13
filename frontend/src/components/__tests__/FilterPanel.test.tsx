import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FilterPanel from '../FilterPanel';
import type { ListingsFilter } from '../../hooks/useListings';

const defaultFilter: ListingsFilter = {
  search: '',
  plz: '',
  sort: 'date',
  sort_dir: 'desc',
  max_distance: '',
  price_min: '',
  price_max: '',
  page: 1,
  category: 'all',
};

function renderPanel(filter = defaultFilter, onChange = vi.fn()) {
  return render(
    <MemoryRouter>
      <FilterPanel
        filter={filter}
        onChange={onChange}
        activeCategoryLabel="Alle Kategorien"
        onOpenCategoryModal={vi.fn()}
      />
    </MemoryRouter>,
  );
}

describe('FilterPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders search input', () => {
    renderPanel();
    expect(screen.getByPlaceholderText(/Suche/i)).toBeInTheDocument();
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

  it('distance sort options show PLZ required label when hasValidPlz is false', () => {
    renderPanel();
    const opts = screen.getAllByRole('option', { name: /PLZ erforderlich/i });
    expect(opts.length).toBeGreaterThanOrEqual(1);
  });
});
