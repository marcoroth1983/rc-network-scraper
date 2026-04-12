import { Routes, Route, Link, Navigate } from 'react-router-dom';
import { useState } from 'react';
import ListingsPage from './pages/ListingsPage';
import DetailPage from './pages/DetailPage';
import LoginPage from './pages/LoginPage';
import ScrapeLog from './components/ScrapeLog';
import FavoritesModal from './components/FavoritesModal';
import PlzBar from './components/PlzBar';
import AuroraBackground from './components/AuroraBackground';
import { useAuth, type AuthUser } from './hooks/useAuth';

function PlaneIcon() {
  return (
    <svg
      className="w-6 h-6"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path d="M5 3l14 9-14 9V3z" />
    </svg>
  );
}

function AuthenticatedApp({ user, logout }: { user: AuthUser; logout: () => void }) {
  const [favoritesOpen, setFavoritesOpen] = useState(false);

  return (
    <AuroraBackground>
      <header
        className="sticky top-0 z-40 backdrop-blur-lg border-b"
        style={{
          background: 'rgba(15, 15, 35, 0.8)',
          borderBottomColor: 'rgba(255, 255, 255, 0.06)',
        }}
      >
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
          <Link
            to="/"
            className="flex items-center gap-2 font-bold text-lg tracking-tight"
            style={{ color: '#A78BFA' }}
          >
            <PlaneIcon />
            RC-Network Scraper
          </Link>
          <div className="flex items-center gap-4">
            <ScrapeLog />
            <div className="flex items-center gap-3 text-sm">
              <span style={{ color: 'rgba(248, 250, 252, 0.5)' }}>{user.email}</span>
              <button
                onClick={logout}
                className="hover:underline transition-colors"
                style={{ color: '#A78BFA' }}
              >
                Abmelden
              </button>
            </div>
          </div>
        </div>
      </header>
      <PlzBar onOpenFavorites={() => setFavoritesOpen(true)} />
      <main className="max-w-6xl mx-auto px-3 py-4 sm:px-4 sm:py-6">
        <Routes>
          <Route path="/" element={<ListingsPage />} />
          <Route path="/listings/:id" element={<DetailPage />} />
        </Routes>
      </main>
      <FavoritesModal open={favoritesOpen} onClose={() => setFavoritesOpen(false)} />
    </AuroraBackground>
  );
}

export default function App() {
  const { user, loading, logout } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-aurora-deep flex items-center justify-center">
        <span className="text-sm" style={{ color: 'rgba(248, 250, 252, 0.35)' }}>Lade…</span>
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          user ? (
            <AuthenticatedApp user={user} logout={logout} />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
    </Routes>
  );
}
