import { useState, useEffect, useMemo } from 'react';
import {
  getSavedSearches,
  createSavedSearch,
  updateSavedSearch,
  deleteSavedSearch,
  toggleSavedSearch,
  markSearchesViewed,
} from '../api/client';
import type { SavedSearch, SearchCriteria } from '../types/api';

export interface UseSavedSearchesResult {
  searches: SavedSearch[];
  totalUnread: number;
  load: () => Promise<void>;
  save: (criteria: SearchCriteria) => Promise<void>;
  update: (id: number, criteria: SearchCriteria) => Promise<void>;
  remove: (id: number) => Promise<void>;
  toggleActive: (id: number) => Promise<void>;
  markViewed: () => Promise<void>;
}

export function useSavedSearches(): UseSavedSearchesResult {
  const [searches, setSearches] = useState<SavedSearch[]>([]);

  const load = async () => {
    const result = await getSavedSearches();
    setSearches(result);
  };

  // Load on mount
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async (criteria: SearchCriteria) => {
    await createSavedSearch(criteria);
    await load();
  };

  const update = async (id: number, criteria: SearchCriteria) => {
    await updateSavedSearch(id, criteria);
    await load();
  };

  const remove = async (id: number) => {
    await deleteSavedSearch(id);
    await load();
  };

  const toggleActive = async (id: number) => {
    const search = searches.find((s) => s.id === id);
    if (!search) return;
    await toggleSavedSearch(id, !search.is_active);
    await load();
  };

  const markViewed = async () => {
    await markSearchesViewed();
    await load();
  };

  // Sum of match_count only for active searches
  const totalUnread = useMemo(
    () => searches.filter((s) => s.is_active).reduce((acc, s) => acc + s.match_count, 0),
    [searches],
  );

  return { searches, totalUnread, load, save, update, remove, toggleActive, markViewed };
}
