import { useEffect, useRef, useState } from 'react';
import type { LLMModelRow } from '../types/api';
import { getLLMModels, refreshLLMModels } from '../api/client';
import { formatRelativeTime } from '../utils/format';

// --- helpers ---

/**
 * Return true when disabled_until is set and lies in the future.
 */
function isCurrentlyDisabled(row: LLMModelRow): boolean {
  if (!row.disabled_until) return false;
  return new Date(row.disabled_until).getTime() > Date.now();
}

/**
 * German-language countdown: "noch X Std Y Min" / "noch X Min" / "noch < 1 Min"
 */
function formatCountdown(iso: string): string {
  const diffMs = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(diffMs) || diffMs <= 0) return '';
  const totalMin = Math.ceil(diffMs / 60_000);
  if (totalMin >= 60) {
    const hrs = Math.floor(totalMin / 60);
    const min = totalMin % 60;
    return min > 0 ? `noch ${hrs} Std ${min} Min` : `noch ${hrs} Std`;
  }
  if (totalMin < 1) return 'noch < 1 Min';
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

// --- sub-component: badge ---

interface BadgeProps {
  row: LLMModelRow;
}

function ActiveBadge({ row }: BadgeProps) {
  if (row.active_now) {
    return (
      <span
        className="px-2 py-0.5 rounded-full text-[10px] font-semibold"
        style={{ background: 'rgba(45,212,191,0.15)', color: '#2DD4BF', border: '1px solid rgba(45,212,191,0.35)' }}
      >
        Aktiv
      </span>
    );
  }
  if (isCurrentlyDisabled(row)) {
    const until = new Date(row.disabled_until!).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    return (
      <span
        className="px-2 py-0.5 rounded-full text-[10px] font-semibold whitespace-nowrap"
        style={{ background: 'rgba(251,146,60,0.15)', color: '#FB923C', border: '1px solid rgba(251,146,60,0.35)' }}
      >
        Pausiert bis {until}
      </span>
    );
  }
  return (
    <span
      className="px-2 py-0.5 rounded-full text-[10px] font-semibold"
      style={{ background: 'rgba(236,72,153,0.15)', color: '#EC4899', border: '1px solid rgba(236,72,153,0.35)' }}
    >
      Inaktiv
    </span>
  );
}

// --- main component ---

export function LLMAdminPanel() {
  const [rows, setRows] = useState<LLMModelRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  // Tick every 30 s to update countdowns in-place without refetching
  const [tick, setTick] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getLLMModels()
      .then((data) => { if (!cancelled) { setRows(data); setLoading(false); } })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, []);

  // 30 s countdown ticker — only while there are disabled rows
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
      setRows(updated);
    } catch (err: unknown) {
      setRefreshError(err instanceof Error ? err.message : 'Refresh fehlgeschlagen');
    } finally {
      setRefreshing(false);
    }
  }

  const lastRefresh = rows ? latestRefreshAt(rows) : null;

  return (
    <div
      className="w-full rounded-2xl p-4 sm:p-6"
      style={{
        background: 'rgba(15,15,35,0.6)',
        border: '1px solid rgba(255,255,255,0.08)',
        backdropFilter: 'blur(20px)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
      }}
    >
      {/* Panel header */}
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <p className="text-sm font-semibold" style={{ color: '#A78BFA' }}>
            LLM-Kaskade
          </p>
          {lastRefresh && (
            <p className="text-[11px] mt-0.5" style={{ color: 'rgba(248,250,252,0.4)' }}>
              Letzte Aktualisierung: {formatRelativeTime(lastRefresh)}
            </p>
          )}
        </div>

        {/* Refresh button */}
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing || loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
          style={{
            background: 'rgba(167,139,250,0.08)',
            border: '1px solid rgba(167,139,250,0.35)',
            color: '#A78BFA',
          }}
          onPointerEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(167,139,250,0.16)'; }}
          onPointerLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(167,139,250,0.08)'; }}
          aria-label="LLM-Modelle aktualisieren"
        >
          {refreshing ? (
            // Simple spinner via CSS animation
            <span
              className="inline-block w-3 h-3 rounded-full border-2"
              style={{
                borderColor: 'rgba(167,139,250,0.3)',
                borderTopColor: '#A78BFA',
                animation: 'spin 0.7s linear infinite',
              }}
              aria-hidden="true"
            />
          ) : (
            // Refresh icon
            <svg className="w-3 h-3" fill="none" viewBox="0 0 16 16" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 2.5A6.5 6.5 0 1 1 2.5 8" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 2.5V6H10" />
            </svg>
          )}
          Aktualisieren
        </button>
      </div>

      {/* Inline refresh error */}
      {refreshError && (
        <p className="text-xs mb-3 px-3 py-2 rounded-lg" style={{ background: 'rgba(236,72,153,0.1)', color: '#EC4899', border: '1px solid rgba(236,72,153,0.25)' }}>
          {refreshError}
        </p>
      )}

      {/* Loading state */}
      {loading && (
        <p className="text-sm text-center py-6" style={{ color: 'rgba(248,250,252,0.35)' }}>
          Lade Modelle…
        </p>
      )}

      {/* Fetch error state */}
      {!loading && error && (
        <p className="text-sm text-center py-6" style={{ color: '#EC4899' }}>
          Fehler: {error}
        </p>
      )}

      {/* Table */}
      {!loading && !error && rows && (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse" style={{ minWidth: '480px' }}>
            <thead>
              <tr>
                {(['Modell', 'Aktiv', 'Context', 'Fehler', 'Pausiert', 'Stand'] as const).map((col) => (
                  <th
                    key={col}
                    className="pb-2 pr-4 last:pr-0 text-[10px] tracking-widest uppercase font-medium"
                    style={{ color: 'rgba(248,250,252,0.3)' }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.model_id}
                  style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}
                >
                  {/* Model ID */}
                  <td className="py-2 pr-4 text-xs font-mono" style={{ color: 'rgba(248,250,252,0.75)', maxWidth: '180px', wordBreak: 'break-all' }}>
                    {row.model_id}
                  </td>

                  {/* Active badge */}
                  <td className="py-2 pr-4">
                    <ActiveBadge row={row} />
                  </td>

                  {/* Context length */}
                  <td className="py-2 pr-4 text-xs" style={{ color: 'rgba(248,250,252,0.5)' }}>
                    {row.context_length != null ? `${Math.round(row.context_length / 1000)}k` : '–'}
                  </td>

                  {/* Last error — truncated, full text on title */}
                  <td className="py-2 pr-4 text-xs" style={{ color: 'rgba(236,72,153,0.85)', maxWidth: '140px' }}>
                    {row.last_error ? (
                      <span title={row.last_error} style={{ cursor: 'help' }}>
                        {row.last_error.length > 40 ? row.last_error.slice(0, 40) + '…' : row.last_error}
                      </span>
                    ) : (
                      <span style={{ color: 'rgba(248,250,252,0.25)' }}>–</span>
                    )}
                  </td>

                  {/* Disabled-until countdown — only shown when in future */}
                  <td className="py-2 pr-4 text-xs" style={{ color: '#FB923C' }}>
                    {isCurrentlyDisabled(row) ? formatCountdown(row.disabled_until!) : (
                      <span style={{ color: 'rgba(248,250,252,0.25)' }}>–</span>
                    )}
                  </td>

                  {/* Last refresh relative time */}
                  <td className="py-2 text-xs" style={{ color: 'rgba(248,250,252,0.4)', whiteSpace: 'nowrap' }}>
                    {formatRelativeTime(row.last_refresh_at)}
                  </td>
                </tr>
              ))}

              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-xs" style={{ color: 'rgba(248,250,252,0.3)' }}>
                    Keine Modelle in der Kaskade
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

    </div>
  );
}
