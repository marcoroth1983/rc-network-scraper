import { describe, it, expect } from 'vitest';
import {
  criteriaFromFilter,
  filterFromSavedSearch,
  criteriaDiffers,
} from './savedSearchCriteria';
import type { ListingsFilter } from '../hooks/useListings';
import type { SavedSearch } from '../types/api';

const baseFilter: ListingsFilter = {
  search: '',
  plz: '',
  sort: 'date',
  sort_dir: 'desc',
  max_distance: '',
  page: 1,
  category: 'all',
  price_min: '',
  price_max: '',
};

const baseSaved: SavedSearch = {
  id: 1,
  user_id: 1,
  name: null,
  search: null,
  plz: null,
  max_distance: null,
  sort: 'date',
  sort_dir: 'desc',
  is_active: true,
  last_checked_at: null,
  last_viewed_at: null,
  created_at: '2026-04-28T00:00:00Z',
  match_count: 0,
  category: null,
};

describe('criteriaFromFilter', () => {
  it('serialises all filter fields including model_type/subtype', () => {
    const out = criteriaFromFilter({
      ...baseFilter,
      plz: '49356',
      sort: 'distance',
      sort_dir: 'asc',
      max_distance: '50',
      model_type: 'flugzeug',
      model_subtype: 'Jet',
    });
    expect(out.model_type).toBe('flugzeug');
    expect(out.model_subtype).toBe('Jet');
    expect(out.plz).toBe('49356');
    expect(out.sort).toBe('distance');
    expect(out.sort_dir).toBe('asc');
    expect(out.max_distance).toBe(50);
  });

  it('passes undefined for category="all"', () => {
    expect(criteriaFromFilter(baseFilter).category).toBeUndefined();
  });

  it('parses price strings into numbers', () => {
    const out = criteriaFromFilter({ ...baseFilter, price_min: '100', price_max: '500' });
    expect(out.price_min).toBe(100);
    expect(out.price_max).toBe(500);
  });
});

describe('filterFromSavedSearch', () => {
  it('hydrates ListingsFilter from a SavedSearch with full filter set', () => {
    const f = filterFromSavedSearch(
      {
        ...baseSaved,
        search: 'Multiplex',
        plz: '49356',
        max_distance: 50,
        sort: 'distance',
        sort_dir: 'asc',
        price_min: 100,
        price_max: 500,
        drive_type: 'elektro',
        completeness: 'rtf',
        shipping_available: true,
        model_type: 'flugzeug',
        model_subtype: 'Jet',
        show_outdated: false,
        only_sold: false,
      },
      'all',
    );
    expect(f.model_type).toBe('flugzeug');
    expect(f.model_subtype).toBe('Jet');
    expect(f.max_distance).toBe('50');
    expect(f.price_min).toBe('100');
    expect(f.sort).toBe('distance');
    expect(f.sort_dir).toBe('asc');
  });

  it('preserves currentCategory and ignores saved.category', () => {
    const f = filterFromSavedSearch({ ...baseSaved, category: 'flugzeuge' }, 'autos');
    expect(f.category).toBe('autos');
  });
});

describe('criteriaDiffers', () => {
  it('returns false when filter matches saved', () => {
    const saved = { ...baseSaved, model_type: 'flugzeug', model_subtype: 'Jet' };
    const filter = filterFromSavedSearch(saved, 'all');
    expect(criteriaDiffers(filter, saved)).toBe(false);
  });

  it('detects model_type change', () => {
    const saved = { ...baseSaved, model_type: 'flugzeug' };
    const filter = { ...filterFromSavedSearch(saved, 'all'), model_type: 'auto' };
    expect(criteriaDiffers(filter, saved)).toBe(true);
  });
});
