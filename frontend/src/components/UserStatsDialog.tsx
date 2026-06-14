import { useEffect, useState } from 'react';
import type { UserStats } from '../types/api';
import { getUserStats } from '../api/client';
import { formatDate } from '../utils/format';

interface Props {
  userId: number;
  email: string;
  onClose: () => void;
}

export function UserStatsDialog({ userId, email, onClose }: Props) {
  const [stats, setStats] = useState<UserStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getUserStats(userId)
      .then((s) => { if (active) setStats(s); })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Fehler'); });
    return () => { active = false; };
  }, [userId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const rows: [string, string][] = stats ? [
    ['Gespeicherte Suchen', String(stats.saved_searches)],
    ['Favoriten', String(stats.favorites)],
    ['Push-Geräte', String(stats.push_devices)],
    ['Logins gesamt', String(stats.logins_total)],
    ['Logins (30 T)', String(stats.logins_30d)],
    ['Registriert', formatDate(stats.created_at)],
    ['Zuletzt gesehen', formatDate(stats.last_seen_at)],
  ] : [];

  return (
    <div role="dialog" aria-modal="true" aria-label={`Analyse ${email}`}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.6)' }} onClick={onClose}>
      <div className="w-full max-w-sm rounded-2xl p-6" onClick={(e) => e.stopPropagation()}
        style={{ background: 'rgba(15,15,35,0.85)', border: '1px solid rgba(255,255,255,0.1)',
                 backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)' }}>
        <div className="flex items-start justify-between mb-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold" style={{ color: '#A78BFA' }}>Nutzer-Analyse</p>
            <p className="text-xs truncate" style={{ color: 'rgba(248,250,252,0.5)' }}>{email}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Schließen" autoFocus
            className="text-lg leading-none px-2" style={{ color: 'rgba(248,250,252,0.6)' }}>×</button>
        </div>
        {error && <p role="alert" className="text-sm" style={{ color: '#EC4899' }}>Fehler: {error}</p>}
        {!error && !stats && <p className="text-sm" style={{ color: 'rgba(248,250,252,0.35)' }}>Lade…</p>}
        {stats && (
          <dl className="flex flex-col gap-2">
            {rows.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between">
                <dt className="text-sm" style={{ color: 'rgba(248,250,252,0.6)' }}>{k}</dt>
                <dd className="text-sm font-semibold tabular-nums" style={{ color: '#F8FAFC' }}>{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  );
}
