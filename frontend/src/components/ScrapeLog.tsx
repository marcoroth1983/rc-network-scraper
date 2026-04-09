import { useEffect, useRef, useState } from 'react';
import { getScrapeLog } from '../api/client';
import type { ScrapeLogEntry } from '../types/api';

const POLL_MS = 60_000;
const MAX_DISPLAY = 10;

function formatEntry(entry: ScrapeLogEntry): string {
  if (entry.error) return 'Fehler';
  const s = entry.summary;
  if (!s) return '—';
  if (entry.job_type === 'update') {
    return `${s.new} neu`;
  }
  const parts: string[] = [];
  if (s.rechecked > 0) parts.push(`${s.rechecked} geprüft`);
  if (s.sold_found > 0) parts.push(`${s.sold_found} verkauft`);
  const deleted = (s.deleted_sold ?? 0) + (s.deleted_stale ?? 0);
  if (deleted > 0) parts.push(`${deleted} gelöscht`);
  return parts.length > 0 ? parts.join(' · ') : 'keine Änderungen';
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

export default function ScrapeLog() {
  const [entries, setEntries] = useState<ScrapeLogEntry[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  async function fetchLog() {
    try {
      const data = await getScrapeLog();
      setEntries(data.slice(0, MAX_DISPLAY));
    } catch {
      // silently ignore — non-critical
    }
  }

  useEffect(() => {
    fetchLog();
    const id = setInterval(fetchLog, POLL_MS);
    return () => clearInterval(id);
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        title="Scrape-Verlauf"
        className="p-2 rounded-lg text-gray-500 hover:text-brand hover:bg-gray-100 transition-colors"
        aria-label="Scrape-Verlauf anzeigen"
      >
        {/* Clock icon */}
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 3" strokeLinecap="round" />
        </svg>
        {entries.length > 0 && (
          <span className="sr-only">{entries.length} Einträge</span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 z-50 w-72 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
          <div className="px-3 py-2 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Scrape-Verlauf
          </div>
          {entries.length === 0 ? (
            <div className="px-3 py-4 text-sm text-gray-400 text-center">Noch keine Läufe</div>
          ) : (
            <ul className="divide-y divide-gray-50 max-h-72 overflow-y-auto">
              {entries.map((entry, i) => (
                <li key={i} className="flex items-baseline justify-between px-3 py-2 text-sm">
                  <span>
                    <span
                      className={`font-mono text-xs px-1.5 py-0.5 rounded mr-2 ${
                        entry.job_type === 'update'
                          ? 'bg-blue-50 text-blue-700'
                          : 'bg-green-50 text-green-700'
                      }`}
                    >
                      {entry.job_type === 'update' ? 'update' : 'regular'}
                    </span>
                    <span className={entry.error ? 'text-red-500' : 'text-gray-700'}>
                      {formatEntry(entry)}
                    </span>
                  </span>
                  <span className="text-xs text-gray-400 ml-2 shrink-0">
                    {formatTime(entry.finished_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
