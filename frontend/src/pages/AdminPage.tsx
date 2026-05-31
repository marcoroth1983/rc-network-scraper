import { Navigate } from 'react-router-dom';
import type { AuthUser } from '../hooks/useAuth';
import { LLMAdminPanel } from '../components/LLMAdminPanel';
import { UserApprovalPanel } from '../components/UserApprovalPanel';

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
        <LLMAdminPanel />
        <UserApprovalPanel currentUserId={user.id} />
      </div>
    </div>
  );
}
