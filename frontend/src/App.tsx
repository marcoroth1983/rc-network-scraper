import { Routes, Route, Link, Navigate, useNavigate, useLocation } from 'react-router-dom';
import ListingDetailModal from './components/ListingDetailModal';
import { getBackground } from './lib/modalLocation';
import { useState, useCallback, useEffect } from 'react';
import ListingsPage from './pages/ListingsPage';
import DetailPage from './pages/DetailPage';
import LoginPage from './pages/LoginPage';
import { ProfilePage } from './pages/ProfilePage';
import { FavoritesPage } from './pages/FavoritesPage';
import ScrapeLog from './components/ScrapeLog';
import FavoritesModal from './components/FavoritesModal';
import CategoryModal from './components/CategoryModal';
import { MobileFooter } from './components/MobileFooter';
import { InstallPrompt } from './components/InstallPrompt';
import PlzBar from './components/PlzBar';
import AuroraBackground from './components/AuroraBackground';
import { useAuth, type AuthUser } from './hooks/useAuth';
import { useSavedSearches } from './hooks/useSavedSearches';
import type { Category, SearchCriteria, SavedSearch } from './types/api';
import { getCategories } from './api/client';

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
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.35-4.35" strokeLinecap="round" />
    </svg>
  );
}

// Inner component so useSearchParams and useNavigate work inside the Router context
function AuthenticatedAppInner({ user, logout, reloadUser }: { user: AuthUser; logout: () => void; reloadUser: () => void }) {
  const [favoritesOpen, setFavoritesOpen] = useState(false);
  const [categoryModalOpen, setCategoryModalOpen] = useState(false);
  const [categories, setCategories] = useState<Category[]>([]);
  const [activeSavedSearchId, setActiveSavedSearchId] = useState<number | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>(
    localStorage.getItem('rcn_category') ?? 'all',
  );
  const { searches, totalUnread, load, save, update, remove, toggleActive, markViewed } =
    useSavedSearches();

  // Fetch categories once on mount
  useEffect(() => {
    getCategories()
      .then(setCategories)
      .catch(() => {
        // Non-fatal — modal will just show no counts
      });
  }, []);

  // Keep activeCategory in sync when CategoryModal writes to localStorage
  useEffect(() => {
    function handleCategoryChanged() {
      setActiveCategory(localStorage.getItem('rcn_category') ?? 'all');
    }
    window.addEventListener('rcn_category_changed', handleCategoryChanged);
    return () => window.removeEventListener('rcn_category_changed', handleCategoryChanged);
  }, []);

  const navigate = useNavigate();
  const location = useLocation();
  const background = getBackground(location);
  const effectiveLocation = background ?? location;
  const isListingsPage = effectiveLocation.pathname === '/';

  // Derive the active saved search criteria object from the searches array
  const activeSavedSearchCriteria: SavedSearch | undefined = activeSavedSearchId != null
    ? searches.find((s) => s.id === activeSavedSearchId)
    : undefined;

  const handleActivateSearch = useCallback(
    (id: number, criteria: SearchCriteria) => {
      setActiveSavedSearchId(id);
      setFavoritesOpen(false);
      const p = new URLSearchParams();
      if (criteria.search) p.set('search', criteria.search);
      if (criteria.plz) p.set('plz', criteria.plz);
      if (criteria.sort && criteria.sort !== 'date') p.set('sort', criteria.sort);
      if (criteria.sort_dir && criteria.sort_dir !== 'desc') p.set('sort_dir', criteria.sort_dir);
      if (criteria.max_distance != null) p.set('max_distance', String(criteria.max_distance));
      // Preserve the currently active category — saved searches don't override it
      const cat = localStorage.getItem('rcn_category') ?? 'all';
      if (cat !== 'all') p.set('category', cat);
      const qs = p.toString();
      navigate(qs ? `/?${qs}` : '/');
    },
    [navigate],
  );

  const handleClearActiveSavedSearch = useCallback(() => {
    setActiveSavedSearchId(null);
  }, []);

  return (
    <AuroraBackground>
      <header
        className="hidden sm:block sticky top-0 z-40 backdrop-blur-lg border-b"
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
            <div className="inline-flex items-center justify-center w-8 h-8 rounded-xl border"
                 style={{
                   background: 'linear-gradient(135deg, rgba(99,102,241,0.3), rgba(236,72,153,0.3))',
                   borderColor: 'rgba(255,255,255,0.1)',
                 }}>
              <PlaneIcon />
            </div>
            RC-Network Scraper
          </Link>
          <div className="flex items-center gap-3">
            <ScrapeLog />
            <button
              onClick={() => setFavoritesOpen(true)}
              className="relative flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors duration-150"
              style={{
                background: 'rgba(167,139,250,0.08)',
                border: '1px solid rgba(167,139,250,0.25)',
                color: '#A78BFA',
              }}
              aria-label="Merkliste öffnen"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} fill="none" aria-hidden="true">
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
              </svg>
              <span>Merkliste</span>
              {totalUnread > 0 && (
                <span
                  className="ml-0.5 text-xs font-bold px-1.5 py-0.5 rounded-full"
                  style={{ background: '#EC4899', color: '#F8FAFC' }}
                  aria-label={`${totalUnread > 99 ? '99+' : totalUnread} neue Treffer`}
                >
                  {totalUnread > 99 ? '99+' : totalUnread}
                </span>
              )}
            </button>
          </div>
        </div>
      </header>
      {isListingsPage && (
        <PlzBar
          suppressPlzRestore={activeSavedSearchId != null}
          activeCategoryLabel={
            activeCategory === 'all'
              ? 'Alle Kategorien'
              : (categories.find((c) => c.key === activeCategory)?.label ?? 'Alle Kategorien')
          }
          onOpenCategoryModal={() => setCategoryModalOpen(true)}
          onLogout={logout}
          userEmail={user.email}
        />
      )}
      <main className="max-w-6xl mx-auto px-3 pt-0 pb-20 sm:px-4 sm:py-6 sm:pb-0">
        <Routes location={effectiveLocation}>
          <Route
            path="/"
            element={
              <ListingsPage
                activeSavedSearchId={activeSavedSearchId}
                activeSavedSearchCriteria={activeSavedSearchCriteria}
                onSaveSearch={save}
                onUpdateSearch={update}
                onClearActiveSavedSearch={handleClearActiveSavedSearch}
                categories={categories}
                onOpenCategoryModal={() => setCategoryModalOpen(true)}
              />
            }
          />
          <Route path="/listings/:id" element={<DirectHitDetailRedirect />} />
          <Route path="/profile" element={<ProfilePage user={user} onLogout={logout} onUserReload={reloadUser} />} />
          <Route path="/favorites" element={<FavoritesPage />} />
        </Routes>
        {background && (
          <Routes>
            <Route
              path="/listings/:id"
              element={
                <ListingDetailModal>
                  <DetailPage />
                </ListingDetailModal>
              }
            />
          </Routes>
        )}
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
        categories={categories}
      />
      <CategoryModal
        open={categoryModalOpen}
        categories={categories}
        closeable={activeCategory !== 'all' || localStorage.getItem('rcn_category') !== null}
        onSelect={(key) => {
          // CategoryModal already wrote to localStorage.
          // Update local state so activeCategoryLabel re-renders immediately.
          setActiveCategory(key);
          // Notify ListingsPage that the category changed via the window custom event.
          // useInfiniteListings listens for this to pick up the new value.
          window.dispatchEvent(new Event('rcn_category_changed'));
          setCategoryModalOpen(false);
        }}
        onClose={() => setCategoryModalOpen(false)}
      />
      <InstallPrompt />
      <MobileFooter totalUnread={totalUnread} />
    </AuroraBackground>
  );
}

function DirectHitDetailRedirect() {
  const location = useLocation();
  // Synthesize a background of "/" and flag this entry as a direct hit.
  // The modal close handler reads `isDirectHit` to decide between navigate(-1)
  // (normal in-app navigation, has history) and navigate('/', { replace: true })
  // (cold-open share link, no history to go back to).
  // `key: ''` satisfies the Location type; this synthesized object is only
  // consumed by route matching, never pushed into the history stack.
  return (
    <Navigate
      to={location.pathname + location.search}
      replace
      state={{
        background: { pathname: '/', search: '', hash: '', state: null, key: '' },
        isDirectHit: true,
      }}
    />
  );
}

function AuthenticatedApp({ user, logout, reloadUser }: { user: AuthUser; logout: () => void; reloadUser: () => void }) {
  return <AuthenticatedAppInner user={user} logout={logout} reloadUser={reloadUser} />;
}

export default function App() {
  const { user, loading, logout, reloadUser } = useAuth(); // reloadUser passed to AuthenticatedApp

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
            <AuthenticatedApp user={user} logout={logout} reloadUser={reloadUser} />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
    </Routes>
  );
}
