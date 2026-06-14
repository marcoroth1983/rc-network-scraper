import { Navigate, Link } from 'react-router-dom';
import type { AuthUser } from '../hooks/useAuth';
import { LLMAdminPanel } from '../components/LLMAdminPanel';
import { MetricsPanel } from '../components/MetricsPanel';

interface Props {
  user: AuthUser;
}

export function AdminPage({ user }: Props) {
  // Admin-only: members and unauthenticated-but-approved users are redirected home.
  if (user.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  return (
    <div
      className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 sm:pt-8 pb-12"
      style={{ color: '#F8FAFC' }}
    >
      {/* Page heading — hidden on mobile (bottom nav already indicates context) */}
      <h1 className="hidden sm:block text-2xl font-bold mb-8" style={{ color: '#F8FAFC' }}>
        Admin-Bereich
      </h1>

      <div className="flex flex-col gap-4 sm:gap-6 min-w-0">
        <MetricsPanel />
        <LLMAdminPanel />
        <Link
          to="/admin/users"
          className="w-full rounded-2xl p-4 sm:p-6 flex items-center justify-between transition-colors"
          style={{
            background: 'rgba(15, 15, 35, 0.6)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
          }}
        >
          <span className="text-sm font-semibold" style={{ color: '#A78BFA' }}>Benutzer-Verwaltung</span>
          <span aria-hidden="true" style={{ color: 'rgba(248,250,252,0.6)' }}>→</span>
        </Link>
      </div>
    </div>
  );
}
