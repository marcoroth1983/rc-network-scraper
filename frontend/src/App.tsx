import { Routes, Route, Link, Navigate } from 'react-router-dom';
import { useState } from 'react';
import ListingsPage from './pages/ListingsPage';
import DetailPage from './pages/DetailPage';
import LoginPage from './pages/LoginPage';
import ScrapeLog from './components/ScrapeLog';
import FavoritesModal from './components/FavoritesModal';
import PlzBar from './components/PlzBar';
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
    <div className="min-h-screen bg-surface text-gray-900 antialiased">
      <header className="sticky top-0 z-40 bg-white/90 backdrop-blur-sm border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
          <Link
            to="/"
            className="flex items-center gap-2 text-brand font-bold text-lg tracking-tight"
          >
            <PlaneIcon />
            RC-Network Scraper
          </Link>
          <div className="flex items-center gap-4">
            <ScrapeLog />
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <span>{user.email}</span>
              <button onClick={logout} className="text-brand hover:underline">
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
    </div>
  );
}

export default function App() {
  const { user, loading, logout } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <span className="text-gray-400 text-sm">Lade…</span>
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
