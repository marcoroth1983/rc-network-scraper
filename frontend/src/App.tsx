import { Routes, Route, Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { useState, useCallback } from 'react';
import ListingsPage from './pages/ListingsPage';
import DetailPage from './pages/DetailPage';
import LoginPage from './pages/LoginPage';
import ScrapeLog from './components/ScrapeLog';
import FavoritesModal from './components/FavoritesModal';
import PlzBar from './components/PlzBar';
import AuroraBackground from './components/AuroraBackground';
import { useAuth, type AuthUser } from './hooks/useAuth';
import { useSavedSearches } from './hooks/useSavedSearches';
import type { SearchCriteria, SavedSearch } from './types/api';
import { writeFiltersToParams } from './hooks/useListings';

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

// Inner component so useSearchParams and useNavigate work inside the Router context
function AuthenticatedAppInner({ user, logout }: { user: AuthUser; logout: () => void }) {
  const [favoritesOpen, setFavoritesOpen] = useState(false);
  const [activeSavedSearchId, setActiveSavedSearchId] = useState<number | null>(null);
  const { searches, totalUnread, load, save, update, remove, toggleActive, markViewed } =
    useSavedSearches();

  const navigate = useNavigate();
  const [, setSearchParams] = useSearchParams();

  // Derive the active saved search criteria object from the searches array
  const activeSavedSearchCriteria: SavedSearch | undefined = activeSavedSearchId != null
    ? searches.find((s) => s.id === activeSavedSearchId)
    : undefined;

  const handleActivateSearch = useCallback(
    (id: number, criteria: SearchCriteria) => {
      setActiveSavedSearchId(id);
      setFavoritesOpen(false);
      // Navigate to / and apply the saved search criteria as URL params
      navigate('/');
      // Build the params from the criteria. We need to do this after navigation
      // so we use a short timeout to let the route settle first, then write params.
      // We call writeFiltersToParams with a ListingsFilter-compatible shape.
      setTimeout(() => {
        writeFiltersToParams(
          {
            search: criteria.search ?? '',
            plz: criteria.plz ?? '',
            sort: (criteria.sort as 'date' | 'price' | 'distance') ?? 'date',
            sort_dir: (criteria.sort_dir as 'asc' | 'desc') ?? 'desc',
            max_distance: criteria.max_distance != null ? String(criteria.max_distance) : '',
            page: 1,
          },
          setSearchParams,
        );
      }, 0);
    },
    [navigate, setSearchParams],
  );

  const handleClearActiveSavedSearch = useCallback(() => {
    setActiveSavedSearchId(null);
  }, []);

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
      <PlzBar
        onOpenFavorites={() => setFavoritesOpen(true)}
        totalUnread={totalUnread}
        suppressPlzRestore={activeSavedSearchId != null}
      />
      <main className="max-w-6xl mx-auto px-3 py-4 sm:px-4 sm:py-6">
        <Routes>
          <Route
            path="/"
            element={
              <ListingsPage
                activeSavedSearchId={activeSavedSearchId}
                activeSavedSearchCriteria={activeSavedSearchCriteria}
                onSaveSearch={save}
                onUpdateSearch={update}
                onClearActiveSavedSearch={handleClearActiveSavedSearch}
              />
            }
          />
          <Route path="/listings/:id" element={<DetailPage />} />
        </Routes>
      </main>
      <FavoritesModal
        open={favoritesOpen}
        onClose={() => setFavoritesOpen(false)}
        searches={searches}
        onLoadSearches={load}
        onRemoveSearch={remove}
        onToggleSearchActive={toggleActive}
        onMarkViewed={markViewed}
        onActivateSearch={handleActivateSearch}
      />
    </AuroraBackground>
  );
}

function AuthenticatedApp({ user, logout }: { user: AuthUser; logout: () => void }) {
  return <AuthenticatedAppInner user={user} logout={logout} />;
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
