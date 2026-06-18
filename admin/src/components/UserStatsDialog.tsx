import { useEffect, useState } from 'react';
import type { UserStats } from '@/types/api';
import { getUserStats } from '@/api/client';
import { formatDate } from '@/lib/format';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  userId: number;
  email: string;
}

export function UserStatsDialog({ open, onOpenChange, userId, email }: Props) {
  const [stats, setStats] = useState<UserStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reset state and fetch fresh on each userId change (each open for a new user).
  useEffect(() => {
    if (!open) return;
    let active = true;
    void (async () => {
      setStats(null);
      setError(null);
      try {
        const s = await getUserStats(userId);
        if (active) setStats(s);
      } catch (e: unknown) {
        if (active) setError(e instanceof Error ? e.message : 'Fehler');
      }
    })();
    return () => { active = false; };
  }, [userId, open]);

  const rows: [string, string][] = stats
    ? [
        ['Gespeicherte Suchen', String(stats.saved_searches)],
        ['Favoriten', String(stats.favorites)],
        ['Push-Geräte', String(stats.push_devices)],
        ['Logins gesamt', String(stats.logins_total)],
        ['Logins (30 T)', String(stats.logins_30d)],
        ['Registriert', formatDate(stats.created_at)],
        ['Zuletzt gesehen', formatDate(stats.last_seen_at)],
      ]
    : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Nutzer-Analyse</DialogTitle>
          <DialogDescription className="truncate">{email}</DialogDescription>
        </DialogHeader>

        {error && (
          <p role="alert" className="text-sm text-danger">
            Fehler: {error}
          </p>
        )}

        {!error && !stats && (
          <p className="text-sm text-text-secondary">Lade…</p>
        )}

        {stats && (
          <dl className="flex flex-col gap-2">
            {rows.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between">
                <dt className="text-sm text-text-secondary">{k}</dt>
                <dd className="text-sm font-semibold tabular-nums text-text-primary">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </DialogContent>
    </Dialog>
  );
}
