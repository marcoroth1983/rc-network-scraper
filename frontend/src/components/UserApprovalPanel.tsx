import { useCallback, useEffect, useState } from 'react';
import type { UserRow } from '../types/api';
import { getUsers, setUserApproval } from '../api/client';
import { useConfirm } from './ConfirmDialog';

const cardStyle: React.CSSProperties = {
  background: 'rgba(15, 15, 35, 0.6)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
};

interface Props {
  currentUserId: number;
}

export function UserApprovalPanel({ currentUserId }: Props) {
  const confirm = useConfirm();
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Single refetch codepath: used by the mount effect AND by Task 5's
  // pull-to-refresh onRefresh callback. Manages loading + clears prior error so
  // both entry points behave identically (loading indicator shows on PTR too).
  // Resolves so PTR can await it.
  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getUsers();
      setRows(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  async function handleToggle(u: UserRow) {
    const next = !u.is_approved;
    if (!next) {
      const ok = await confirm({
        title: 'Freischaltung entziehen?',
        message: `„${u.email}" verliert den Zugang zur App.`,
        confirmLabel: 'Entziehen',
        destructive: true,
      });
      if (!ok) return;
    }
    // Optimistic update with rollback on failure
    setRows((rs) => rs?.map((r) => (r.id === u.id ? { ...r, is_approved: next } : r)) ?? rs);
    try {
      const updated = await setUserApproval(u.id, next);
      setRows((rs) => rs?.map((r) => (r.id === updated.id ? updated : r)) ?? rs);
    } catch (err: unknown) {
      setRows((rs) => rs?.map((r) => (r.id === u.id ? { ...r, is_approved: u.is_approved } : r)) ?? rs);
      setError(err instanceof Error ? err.message : 'Aktualisierung fehlgeschlagen');
    }
  }

  return (
    <section className="w-full rounded-2xl p-4 sm:p-6" style={cardStyle}>
      <p className="text-sm font-semibold mb-4" style={{ color: '#A78BFA' }}>
        Benutzer-Freischaltung
      </p>

      {loading && (
        <p className="text-sm text-center py-6" style={{ color: 'rgba(248,250,252,0.35)' }}>
          Lade Benutzer…
        </p>
      )}

      {!loading && error && (
        <p role="alert" className="text-sm text-center py-6" style={{ color: '#EC4899' }}>
          Fehler: {error}
        </p>
      )}

      {!loading && !error && rows && (
        <ul className="flex flex-col gap-3">
          {rows.map((u) => {
            const isSelf = u.id === currentUserId;
            return (
              <li key={u.id} className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm truncate" style={{ color: 'rgba(248,250,252,0.85)' }}>
                    {u.email}{isSelf ? ' (du)' : ''}
                  </p>
                  {u.name && (
                    <p className="text-xs truncate" style={{ color: 'rgba(248,250,252,0.45)' }}>
                      {u.name}
                    </p>
                  )}
                  <p className="text-[11px] mt-0.5" style={{ color: 'rgba(248,250,252,0.35)' }}>
                    Registriert: {new Date(u.created_at).toLocaleDateString('de-DE')}
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={u.is_approved}
                  aria-label={`Freischaltung für ${u.email}`}
                  disabled={isSelf}
                  onClick={() => { void handleToggle(u); }}
                  className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{
                    background: u.is_approved
                      ? 'linear-gradient(135deg, rgba(99,102,241,0.9), rgba(139,92,246,0.9))'
                      : 'rgba(255,255,255,0.1)',
                    border: u.is_approved
                      ? '1px solid rgba(139,92,246,0.5)'
                      : '1px solid rgba(255,255,255,0.15)',
                  }}
                >
                  <span className="inline-block h-3.5 w-3.5 rounded-full transition-transform duration-200"
                    style={{
                      background: '#fff',
                      transform: u.is_approved ? 'translateX(18px)' : 'translateX(2px)',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
                    }}
                    aria-hidden="true" />
                </button>
              </li>
            );
          })}
          {rows.length === 0 && (
            <li className="py-6 text-center text-xs" style={{ color: 'rgba(248,250,252,0.3)' }}>
              Keine Benutzer
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
