import { useEffect, useRef, useState } from 'react';
import { startScrape, getScrapeStatus } from '../api/client';
import type { ScrapePhase, ScrapeStatus } from '../types/api';

const POLL_INTERVAL_MS = 3000;

export default function ScrapeButton({ onDone }: { onDone?: () => void }) {
  const [status, setStatus] = useState<ScrapeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isRunning = status?.status === 'running';
  const isDone = status?.status === 'done';

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function startPolling() {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const s = await getScrapeStatus();
        setStatus(s);
        if (s.status === 'done' || s.status === 'error') {
          stopPolling();
          if (s.status === 'done') onDone?.();
        }
      } catch {
        stopPolling();
        setError('Verbindung unterbrochen');
      }
    }, POLL_INTERVAL_MS);
  }

  useEffect(() => () => stopPolling(), []);

  async function handleClick() {
    setError(null);
    setStatus(null);
    try {
      const result = await startScrape();
      // Both 'started' and 'already_running' proceed to polling —
      // fetch status immediately so UI shows "running" without waiting 3s.
      if (result.status === 'already_running') {
        // Job was already in progress — attach to it directly
        const s = await getScrapeStatus();
        setStatus(s);
        startPolling();
        return;
      }
      const s = await getScrapeStatus();
      setStatus(s);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    }
  }

  function phaseLabel(phase: ScrapePhase): string {
    if (phase === 'phase1') return 'Neue Inserate…';
    if (phase === 'phase2') return 'Sold-Check…';
    if (phase === 'phase3') return 'Aufräumen…';
    return 'Läuft…';
  }

  const hasError = status?.status === 'error' || !!error;

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={handleClick}
        disabled={isRunning}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-brand text-white text-sm font-semibold hover:bg-brand-dark active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isRunning && (
          <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
        )}
        {isRunning ? phaseLabel(status?.phase ?? null) : 'Scrape starten'}
      </button>

      {isRunning && status?.progress && (
        <span className="text-xs text-gray-500 max-w-xs truncate">{status.progress}</span>
      )}

      {isDone && status?.summary && (
        <span className="text-xs text-gray-600">
          ✓ {status.summary.new} neu · {status.summary.rechecked} geprüft · {status.summary.sold_found} verkauft
        </span>
      )}

      {hasError && (
        <span className="text-xs text-red-500">
          Fehler: {error ?? status?.error}
        </span>
      )}
    </div>
  );
}
