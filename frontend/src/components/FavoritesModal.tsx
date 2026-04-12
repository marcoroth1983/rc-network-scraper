import { useEffect, useState, useCallback } from 'react';
import { getFavorites } from '../api/client';
import type { ListingSummary } from '../types/api';
import FavoriteCard from './FavoriteCard';

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function FavoritesModal({ open, onClose }: Props) {
  const [favorites, setFavorites] = useState<ListingSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setFavorites(await getFavorites());
    } catch {
      setLoadError('Merkliste konnte nicht geladen werden.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  function handleRemove(id: number) {
    setFavorites((prev) => prev.filter((f) => f.id !== id));
  }

  // "Aufräumen" removes sold items from the local list view only.
  // Sold favorites will reappear on next modal open (re-fetched from API).
  // To permanently remove, use the individual "Von Merkliste entfernen" button.
  function handleCleanup() {
    setFavorites((prev) => prev.filter((f) => !f.is_sold));
  }

  if (!open) return null;

  const soldCount = favorites.filter((f) => f.is_sold).length;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Meine Merkliste"
      className="fixed inset-0 z-50 flex items-stretch sm:items-start justify-center overflow-hidden sm:overflow-y-auto py-0 sm:py-8 px-0 sm:px-4"
      style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="relative w-full sm:max-w-2xl rounded-none sm:rounded-2xl shadow-2xl flex flex-col max-h-[100dvh] sm:max-h-[90vh]"
        style={{
          background: 'rgba(15, 15, 35, 0.85)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          backdropFilter: 'blur(20px) saturate(1.2)',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}
        >
          <h2 className="text-lg font-bold" style={{ color: '#F8FAFC' }}>
            Meine Merkliste
            {favorites.length > 0 && (
              <span className="ml-2 text-sm font-normal" style={{ color: 'rgba(248,250,252,0.35)' }}>
                ({favorites.length})
              </span>
            )}
          </h2>
          <button
            onClick={onClose}
            className="transition-colors p-1 rounded-lg"
            style={{ color: 'rgba(248,250,252,0.5)' }}
            aria-label="Schließen"
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = '#F8FAFC'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.5)'; }}
          >
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-3 min-h-0 flex-1 overflow-y-auto">
          {loading && (
            <div className="flex justify-center py-8">
              <div
                className="animate-spin h-6 w-6 border-2 rounded-full"
                style={{ borderColor: '#A78BFA', borderTopColor: 'transparent' }}
              />
            </div>
          )}
          {!loading && loadError && (
            <p className="text-center py-8" style={{ color: '#EC4899' }}>{loadError}</p>
          )}
          {!loading && !loadError && favorites.length === 0 && (
            <p className="text-center py-8" style={{ color: 'rgba(248,250,252,0.35)' }}>
              Keine Favoriten gespeichert
            </p>
          )}
          {!loading && favorites.map((listing) => (
            <FavoriteCard key={listing.id} listing={listing} onRemove={handleRemove} />
          ))}
        </div>

        {/* Footer — Aufräumen hides sold items locally for current session */}
        {soldCount > 0 && (
          <div
            className="px-6 py-3 flex items-center gap-3"
            style={{ borderTop: '1px solid rgba(255,255,255,0.08)' }}
          >
            <button
              onClick={handleCleanup}
              className="flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-semibold transition-all duration-200"
              style={{
                background: 'rgba(45,212,191,0.1)',
                border: '1px solid rgba(45,212,191,0.3)',
                color: '#2DD4BF',
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = 'rgba(45,212,191,0.2)';
                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(45,212,191,0.5)';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = 'rgba(45,212,191,0.1)';
                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(45,212,191,0.3)';
              }}
            >
              Aufräumen
            </button>
            <span className="text-xs" style={{ color: 'rgba(248,250,252,0.35)' }}>
              Nicht mehr verfügbare Anzeigen entfernen
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
