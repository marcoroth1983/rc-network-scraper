import { useEffect, type ReactNode } from 'react';
import { useAuth } from '../hooks/useAuth';

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  // Redirect to Google login as a side-effect, never during render (Strict-Mode safe).
  useEffect(() => {
    if (!loading && !user) {
      window.location.href = '/api/auth/google?return_to=' + encodeURIComponent(window.location.origin);
    }
  }, [loading, user]);
  if (loading || !user) {
    return <div className="min-h-dvh grid place-items-center text-text-tertiary">Lade…</div>;
  }
  if (user.role !== 'admin') {
    return (
      <div className="min-h-dvh grid place-items-center p-6 text-center">
        <div>
          <p className="text-lg font-semibold text-text-primary">Kein Zugriff</p>
          <p className="mt-2 text-sm text-text-secondary">Dieser Bereich ist Administratoren vorbehalten.</p>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
