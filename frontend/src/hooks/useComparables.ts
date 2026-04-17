import { useState, useEffect } from 'react';
import { getComparables } from '../api/client';
import type { ComparablesResponse } from '../types/api';

interface UseComparablesResult {
  data: ComparablesResponse | null;
  loading: boolean;
  error: string | null;
}

export function useComparables(listingId: number | null): UseComparablesResult {
  const [data, setData] = useState<ComparablesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (listingId === null) { setData(null); setLoading(false); setError(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    getComparables(listingId)
      .then((res) => { if (!cancelled) { setData(res); setLoading(false); } })
      .catch((err: Error) => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [listingId]);

  return { data, loading, error };
}
