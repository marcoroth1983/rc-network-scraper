import { useEffect, useRef, useState } from 'react';
import { CircleCheck, CircleX, PauseCircle, RefreshCw } from 'lucide-react';
import type { LLMModelRow } from '../types/api';
import { getLLMModels, refreshLLMModels } from '../api/client';
import { formatRelativeTime } from '../lib/format';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';

// --- helpers ---

/**
 * Return true when disabled_until is set and lies in the future.
 */
function isCurrentlyDisabled(row: LLMModelRow): boolean {
  if (!row.disabled_until) return false;
  return new Date(row.disabled_until).getTime() > Date.now();
}

/**
 * German-language countdown: "noch X Std Y Min" / "noch X Min"
 *
 * Uses Math.floor so a model disabled for e.g. 59m30s shows "noch 59 Min"
 * rather than being rounded up into the hours branch by Math.ceil.
 */
function formatCountdown(iso: string): string {
  const diffMs = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(diffMs) || diffMs <= 0) return '';
  const totalMin = Math.floor(diffMs / 60_000);
  if (totalMin >= 60) {
    const hrs = Math.floor(totalMin / 60);
    const min = totalMin % 60;
    return min > 0 ? `noch ${hrs} Std ${min} Min` : `noch ${hrs} Std`;
  }
  return `noch ${totalMin} Min`;
}

/** Pick the max last_refresh_at across all rows for the panel header. */
function latestRefreshAt(rows: LLMModelRow[]): string | null {
  if (rows.length === 0) return null;
  return rows.reduce<string>(
    (max, r) =>
      new Date(r.last_refresh_at).getTime() > new Date(max).getTime()
        ? r.last_refresh_at
        : max,
    rows[0].last_refresh_at,
  );
}

// --- main component ---

export function LlmPage() {
  const [rows, setRows] = useState<LLMModelRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  // Tick every 30 s to update countdowns in-place without refetching
  const [tick, setTick] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
      try {
        const data = await getLLMModels();
        if (!cancelled) {
          setRows(data);
          setLoading(false);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
          setLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // 30 s countdown ticker — keeps disabled-until countdowns current without refetching
  useEffect(() => {
    intervalRef.current = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => {
      if (intervalRef.current !== null) clearInterval(intervalRef.current);
    };
  }, []);

  // suppress lint: tick is used to force re-render for countdown display
  void tick;

  async function handleRefresh() {
    setRefreshing(true);
    setRefreshError(null);
    try {
      const updated = await refreshLLMModels();
      if (mountedRef.current) setRows(updated);
    } catch (err: unknown) {
      if (mountedRef.current) setRefreshError(err instanceof Error ? err.message : 'Refresh fehlgeschlagen');
    } finally {
      if (mountedRef.current) setRefreshing(false);
    }
  }

  const lastRefresh = rows ? latestRefreshAt(rows) : null;

  return (
    <div>
      <div className="rounded-card bg-surface border border-border p-6">
        {/* Page header */}
        <div className="flex items-start justify-between gap-3 mb-6">
          <div>
            <p className="text-[18px] font-semibold text-text-primary">LLM-Kaskade</p>
            {rows && lastRefresh && (
              <p className="text-sm text-text-secondary mt-0.5">
                Letzte Aktualisierung: {formatRelativeTime(lastRefresh)}
              </p>
            )}
          </div>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => { void handleRefresh(); }}
            disabled={refreshing || loading}
            aria-label="LLM-Modelle aktualisieren"
          >
            <RefreshCw className={refreshing ? 'animate-spin' : ''} />
            Aktualisieren
          </Button>
        </div>

        {/* Inline refresh error */}
        {refreshError && (
          <p className="text-sm mb-4 px-3 py-2 rounded-control text-danger bg-[rgba(247,85,85,0.08)] border border-[rgba(247,85,85,0.25)]">
            {refreshError}
          </p>
        )}

        {/* Loading state */}
        {loading && (
          <p className="text-sm text-center py-8 text-text-tertiary">Lade Modelle…</p>
        )}

        {/* Fetch error state */}
        {!loading && error && (
          <p className="text-sm text-center py-8 text-danger">Fehler: {error}</p>
        )}

        {/* Table */}
        {!loading && !error && rows && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Modell</TableHead>
                <TableHead>Aktiv</TableHead>
                <TableHead>Context</TableHead>
                <TableHead>Fehler</TableHead>
                <TableHead>Pausiert</TableHead>
                <TableHead>Stand</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-text-tertiary">
                    Keine Modelle in der Kaskade
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => (
                  <TableRow key={row.model_id}>
                    {/* Model ID */}
                    <TableCell className="font-mono text-xs text-text-primary truncate max-w-[180px]" title={row.model_id}>
                      {row.model_id}
                    </TableCell>

                    {/* Status badge */}
                    <TableCell>
                      {row.active_now ? (
                        <Badge variant="success">
                          <CircleCheck className="size-3" />
                          Aktiv
                        </Badge>
                      ) : isCurrentlyDisabled(row) ? (
                        <Badge variant="warning">
                          <PauseCircle className="size-3" />
                          Pausiert bis {new Date(row.disabled_until!).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}
                        </Badge>
                      ) : (
                        <Badge variant="danger">
                          <CircleX className="size-3" />
                          Inaktiv
                        </Badge>
                      )}
                    </TableCell>

                    {/* Context length */}
                    <TableCell className="tabular-nums text-text-secondary">
                      {row.context_length != null ? `${Math.round(row.context_length / 1000)}k` : '–'}
                    </TableCell>

                    {/* Last error */}
                    <TableCell className="text-danger max-w-[160px]">
                      {row.last_error ? (
                        <span title={row.last_error} className="cursor-help text-xs">
                          {row.last_error.length > 40 ? row.last_error.slice(0, 40) + '…' : row.last_error}
                        </span>
                      ) : (
                        <span className="text-text-tertiary">–</span>
                      )}
                    </TableCell>

                    {/* Disabled-until countdown */}
                    <TableCell className="tabular-nums text-warning">
                      {isCurrentlyDisabled(row) ? (
                        formatCountdown(row.disabled_until!)
                      ) : (
                        <span className="text-text-tertiary">–</span>
                      )}
                    </TableCell>

                    {/* Last refresh relative time */}
                    <TableCell className="tabular-nums text-text-secondary whitespace-nowrap">
                      {formatRelativeTime(row.last_refresh_at)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
