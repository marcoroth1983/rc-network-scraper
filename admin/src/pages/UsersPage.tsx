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

  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dialog state
  const [statsUser, setStatsUser] = useState<UserRow | null>(null);
  const [pendingToggle, setPendingToggle] = useState<UserRow | null>(null);
  const [pendingDelete, setPendingDelete] = useState<UserRow | null>(null);

  // Mirror loadUsers from UserApprovalPanel.tsx:32-43 (verbatim logic).
  // setState calls wrapped in async IIFE to satisfy react-hooks/set-state-in-effect.
  // Active flag guards against setState on unmounted tree.
  useEffect(() => {
    let active = true;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await getUsers();
        if (active) setRows(data);
      } catch (err: unknown) {
        if (active) setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  // Mirror handleToggle from UserApprovalPanel.tsx:51-71.
  // Executes the actual toggle after confirmation (or immediately for approve).
  const performToggle = useCallback(async (u: UserRow) => {
    const next = !u.is_approved;
    setError(null);
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
        // Granting approval — proceed immediately without confirmation
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

  // Mirror handleDelete from UserApprovalPanel.tsx:73-91.
  const performDelete = useCallback(async (u: UserRow) => {
    setError(null);
    setRows((rs) => rs?.filter((r) => r.id !== u.id) ?? rs); // optimistic removal
    try {
      await deleteUser(u.id);
    } catch (err: unknown) {
      // Rollback by re-inserting the row functionally — avoids clobbering any
      // concurrent state change that a captured snapshot of `rows` would overwrite.
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

  // Named onOpenChange callbacks — avoids new function references on every render
  const handleToggleDialogChange = useCallback(
    (open: boolean) => { if (!open) setPendingToggle(null); },
    [],
  );
  const handleDeleteDialogChange = useCallback(
    (open: boolean) => { if (!open) setPendingDelete(null); },
    [],
  );
  const handleStatsDialogChange = useCallback(
    (open: boolean) => { if (!open) setStatsUser(null); },
    [],
  );

  // user is guaranteed non-null inside RequireAdmin — guard placed after all hooks.
  if (!user) return null;
  const currentUserId = user.id;

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
                          type="button"
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
                          type="button"
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

      {/* Revoke approval confirmation — verbatim German strings from UserApprovalPanel.tsx:54-59 */}
      <AlertDialog open={!!pendingToggle} onOpenChange={handleToggleDialogChange}>
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

      {/* Delete confirmation — verbatim German strings from UserApprovalPanel.tsx:74-79 */}
      <AlertDialog open={!!pendingDelete} onOpenChange={handleDeleteDialogChange}>
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

      {/* Stats dialog — mounted unconditionally so Radix can animate the close transition */}
      <UserStatsDialog
        open={!!statsUser}
        onOpenChange={handleStatsDialogChange}
        userId={statsUser?.id ?? 0}
        email={statsUser?.email ?? ''}
      />
    </div>
  );
}
