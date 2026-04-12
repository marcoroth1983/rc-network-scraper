import { Routes, Route, Link } from 'react-router-dom';
import ListingsPage from './pages/ListingsPage';
import DetailPage from './pages/DetailPage';
import ScrapeLog from './components/ScrapeLog';
import FavoritesModal from './components/FavoritesModal';
import PlzBar from './components/PlzBar';
import { useState } from 'react';

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

function Header() {
  return (
    <header className="sticky top-0 z-40 bg-white/90 backdrop-blur-sm border-b border-gray-200">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
        <Link
          to="/"
          className="flex items-center gap-2 text-brand font-bold text-lg tracking-tight"
        >
          <PlaneIcon />
          RC-Network Scraper
        </Link>
        <ScrapeLog />
      </div>
    </header>
  );
}

export default function App() {
  const [favoritesOpen, setFavoritesOpen] = useState(false);

  return (
    <div className="min-h-screen bg-surface text-gray-900 antialiased">
      <Header />
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
