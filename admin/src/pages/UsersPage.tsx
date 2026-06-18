import { useCallback, useEffect, useState } from 'react';
import type { UserRow } from '@/types/api';
import { getUsers, setUserApproval, deleteUser } from '@/api/client';
import { useAuth } from '@/hooks/useAuth';
import { formatDate } from '@/lib/format';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { UserStatsDialog } from '@/components/UserStatsDialog';

export function UsersPage() {
  const { user } = useAuth();
  // user is guaranteed non-null inside RequireAdmin
  const currentUserId = user!.id;

  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dialog state
  const [statsUser, setStatsUser] = useState<UserRow | null>(null);
  const [pendingToggle, setPendingToggle] = useState<UserRow | null>(null);
  const [pendingDelete, setPendingDelete] = useState<UserRow | null>(null);

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
    void (async () => { await loadUsers(); })();
  }, [loadUsers]);

  // Executes the actual toggle after confirmation (or immediately for approve).
  const performToggle = useCallback(async (u: UserRow) => {
    const next = !u.is_approved;
    // Optimistic update with rollback on failure
    setRows((rs) => rs?.map((r) => (r.id === u.id ? { ...r, is_approved: next } : r)) ?? rs);
    try {
      const updated = await setUserApproval(u.id, next);
      setRows((rs) => rs?.map((r) => (r.id === updated.id ? updated : r)) ?? rs);
    } catch (err: unknown) {
      setRows((rs) =>
        rs?.map((r) => (r.id === u.id ? { ...r, is_approved: u.is_approved } : r)) ?? rs,
      );
      setError(err instanceof Error ? err.message : 'Aktualisierung fehlgeschlagen');
    }
  }, []);

  const handleToggle = useCallback(
    (u: UserRow) => {
      const next = !u.is_approved;
      if (!next) {
        // Revoking approval — show confirmation dialog first
        setPendingToggle(u);
      } else {
        // Granting approval — proceed immediately
        void performToggle(u);
      }
    },
    [performToggle],
  );

  const handleToggleConfirm = useCallback(() => {
    if (!pendingToggle) return;
    const u = pendingToggle;
    setPendingToggle(null);
    void performToggle(u);
  }, [pendingToggle, performToggle]);

  const handleDelete = useCallback((u: UserRow) => {
    setPendingDelete(u);
  }, []);

  const performDelete = useCallback(async (u: UserRow) => {
    setRows((rs) => rs?.filter((r) => r.id !== u.id) ?? rs); // optimistic removal
    try {
      await deleteUser(u.id);
    } catch (err: unknown) {
      // Rollback by re-inserting the row functionally — avoids clobbering concurrent state changes
      setRows((rs) => (rs && !rs.some((r) => r.id === u.id) ? [...rs, u] : rs));
      setError(err instanceof Error ? err.message : 'Löschen fehlgeschlagen');
    }
  }, []);

  const handleDeleteConfirm = useCallback(() => {
    if (!pendingDelete) return;
    const u = pendingDelete;
    setPendingDelete(null);
    void performDelete(u);
  }, [pendingDelete, performDelete]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-text-primary">Nutzer</h1>

      {error && (
        <p role="alert" className="text-sm text-danger">
          Fehler: {error}
        </p>
      )}

      {loading && (
        <p className="text-sm text-text-secondary">Lade Benutzer…</p>
      )}

      {!loading && rows && (
        <div className="rounded-card border border-border bg-surface overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>E-Mail</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Registriert</TableHead>
                <TableHead>Zuletzt gesehen</TableHead>
                <TableHead>Aktionen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-text-secondary">
                    Keine Benutzer
                  </TableCell>
                </TableRow>
              )}
              {rows.map((u) => {
                const isSelf = u.id === currentUserId;
                return (
                  <TableRow key={u.id}>
                    <TableCell className="text-text-primary font-medium">
                      {u.email}
                      {isSelf && (
                        <span className="ml-1 text-text-secondary font-normal">(du)</span>
                      )}
                    </TableCell>
                    <TableCell className="text-text-secondary">{u.name ?? '–'}</TableCell>
                    <TableCell className="text-text-secondary">
                      {new Date(u.created_at).toLocaleDateString('de-DE')}
                    </TableCell>
                    <TableCell className="text-text-secondary">
                      {formatDate(u.last_seen_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setStatsUser(u)}
                          aria-label={`Analyse ${u.email}`}
                        >
                          Analyse
                        </Button>
                        <Switch
                          checked={u.is_approved}
                          onCheckedChange={() => handleToggle(u)}
                          disabled={isSelf}
                          aria-label={`Freischaltung für ${u.email}`}
                        />
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={isSelf}
                          onClick={() => handleDelete(u)}
                          aria-label={`Konto ${u.email} löschen`}
                        >
                          Löschen
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Revoke approval confirmation */}
      <AlertDialog open={!!pendingToggle} onOpenChange={(open) => { if (!open) setPendingToggle(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Freischaltung entziehen?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingToggle && `„${pendingToggle.email}" verliert den Zugang zur App.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Abbrechen</AlertDialogCancel>
            <AlertDialogAction
              className="bg-danger text-white hover:bg-danger/90"
              onClick={handleToggleConfirm}
            >
              Entziehen
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete confirmation */}
      <AlertDialog open={!!pendingDelete} onOpenChange={(open) => { if (!open) setPendingDelete(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Konto endgültig löschen?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete &&
                `„${pendingDelete.email}" und alle zugehörigen Daten (Suchen, Favoriten, Geräte) werden unwiderruflich gelöscht (DSGVO).`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Abbrechen</AlertDialogCancel>
            <AlertDialogAction
              className="bg-danger text-white hover:bg-danger/90"
              onClick={handleDeleteConfirm}
            >
              Endgültig löschen
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Stats dialog */}
      {statsUser && (
        <UserStatsDialog
          open={!!statsUser}
          onOpenChange={(open) => { if (!open) setStatsUser(null); }}
          userId={statsUser.id}
          email={statsUser.email}
        />
      )}
    </div>
  );
}
