import type { ListingsFilter } from '../hooks/useListings';
import type { SavedSearch, SearchCriteria } from '../types/api';

/** Serialise the in-app filter state into the API payload for save/update. */
export function criteriaFromFilter(filter: ListingsFilter): SearchCriteria {
  return {
    search: filter.search || null,
    plz: filter.plz || null,
    max_distance: filter.max_distance ? parseInt(filter.max_distance, 10) : null,
    sort: filter.sort,
    sort_dir: filter.sort_dir,
    // undefined (not "all") so the backend stores NULL for "all categories"
    category: filter.category !== 'all' ? filter.category : undefined,
    price_min: filter.price_min ? parseFloat(filter.price_min) : null,
    price_max: filter.price_max ? parseFloat(filter.price_max) : null,
    drive_type: filter.drive_type ?? null,
    completeness: filter.completeness ?? null,
    shipping_available: filter.shipping_available ?? null,
    model_type: filter.model_type ?? null,
    model_subtype: filter.model_subtype ?? null,
    show_outdated: filter.show_outdated ?? null,
    only_sold: filter.only_sold ?? null,
  };
}

/** Hydrate a ListingsFilter from a SavedSearch row.
 *
 * `currentCategory` is intentionally passed in (rather than read from the saved
 * row) because saved searches do not override the user's currently selected
 * category — that lives in localStorage and is global to the listings UI. */
export function filterFromSavedSearch(saved: SavedSearch, currentCategory: string): ListingsFilter {
  const sort: ListingsFilter['sort'] =
    saved.sort === 'price' || saved.sort === 'distance' ? saved.sort : 'date';
  const sort_dir: 'asc' | 'desc' = saved.sort_dir === 'asc' ? 'asc' : 'desc';
  return {
    search: saved.search ?? '',
    plz: saved.plz ?? '',
    sort,
    sort_dir,
    max_distance: saved.max_distance != null ? String(saved.max_distance) : '',
    page: 1,
    category: currentCategory,
    price_min: saved.price_min != null ? String(saved.price_min) : '',
    price_max: saved.price_max != null ? String(saved.price_max) : '',
    drive_type: saved.drive_type ?? undefined,
    completeness: saved.completeness ?? undefined,
    shipping_available: saved.shipping_available ?? undefined,
    model_type: saved.model_type ?? undefined,
    model_subtype: saved.model_subtype ?? undefined,
    show_outdated: saved.show_outdated ?? undefined,
    only_sold: saved.only_sold ?? undefined,
  };
}

/** Returns true if the live filter differs from the saved search criteria. */
export function criteriaDiffers(filter: ListingsFilter, saved: SavedSearch): boolean {
  const a = criteriaFromFilter(filter);
  // Compare against the same shape the backend would receive on update.
  const b = criteriaFromFilter(filterFromSavedSearch(saved, filter.category));
  const keys = Object.keys(a) as (keyof SearchCriteria)[];
  return keys.some((k) => (a[k] ?? null) !== (b[k] ?? null));
}
