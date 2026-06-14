import { Navigate, Link } from 'react-router-dom';
import type { AuthUser } from '../hooks/useAuth';
import { UserApprovalPanel } from '../components/UserApprovalPanel';

interface Props {
  user: AuthUser;
}

export function AdminUsersPage({ user }: Props) {
  if (user.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  return (
    <div
      className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 sm:pt-8 pb-12"
      style={{ color: '#F8FAFC' }}
    >
      <Link to="/admin" className="inline-block text-sm mb-4 sm:mb-6"
            style={{ color: 'rgba(248,250,252,0.6)' }}>
        ← Dashboard
      </Link>
      <h1 className="hidden sm:block text-2xl font-bold mb-8" style={{ color: '#F8FAFC' }}>
        Benutzer-Verwaltung
      </h1>
      <UserApprovalPanel currentUserId={user.id} />
    </div>
  );
}
