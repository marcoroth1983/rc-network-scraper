import { useEffect, useRef, useState } from 'react';
import { getScrapeLog } from '../api/client';
import { useAuth } from '../hooks/useAuth';
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
  const { user } = useAuth();
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
    // eslint-disable-next-line react-hooks/set-state-in-effect
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

  if (user?.role !== 'admin') return null;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        title="Scrape-Verlauf"
        className="p-2 rounded-lg transition-all duration-200"
        aria-label="Scrape-Verlauf anzeigen"
        style={{
          color: 'rgba(248,250,252,0.5)',
          background: open ? 'rgba(255,255,255,0.08)' : 'transparent',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.color = '#A78BFA';
          if (!open) (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.06)';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.5)';
          if (!open) (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
        }}
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
        <div
          className="absolute right-0 top-10 z-50 w-64 sm:w-72 rounded-xl overflow-hidden"
          style={{
            background: 'rgba(15, 15, 35, 0.9)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            backdropFilter: 'blur(20px) saturate(1.2)',
            boxShadow: '0 0 60px rgba(99,102,241,0.06), 0 4px 16px rgba(0,0,0,0.4)',
          }}
        >
          <div
            className="px-3 py-2 text-xs font-semibold uppercase tracking-wide"
            style={{
              color: 'rgba(248,250,252,0.35)',
              borderBottom: '1px solid rgba(255,255,255,0.06)',
            }}
          >
            Scrape-Verlauf
          </div>
          {entries.length === 0 ? (
            <div className="px-3 py-4 text-sm text-center" style={{ color: 'rgba(248,250,252,0.35)' }}>
              Noch keine Läufe
            </div>
          ) : (
            <ul className="max-h-72 overflow-y-auto">
              {entries.map((entry, i) => (
                <li
                  key={i}
                  className="flex items-baseline justify-between px-3 py-2 text-sm"
                  style={i > 0 ? { borderTop: '1px solid rgba(255,255,255,0.06)' } : undefined}
                >
                  <span>
                    <span
                      className="font-mono text-xs px-1.5 py-0.5 rounded mr-2"
                      style={
                        entry.job_type === 'update'
                          ? { background: 'rgba(99,102,241,0.15)', color: '#A78BFA' }
                          : { background: 'rgba(45,212,191,0.12)', color: '#2DD4BF' }
                      }
                    >
                      {entry.job_type === 'update' ? 'update' : 'regular'}
                    </span>
                    <span style={{ color: entry.error ? '#EC4899' : 'rgba(248,250,252,0.65)' }}>
                      {formatEntry(entry)}
                    </span>
                  </span>
                  <span className="text-xs ml-2 shrink-0" style={{ color: 'rgba(248,250,252,0.35)' }}>
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
