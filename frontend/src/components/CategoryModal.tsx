import { useEffect } from 'react';
import type { Category } from '../types/api';

interface CategoryModalProps {
  open: boolean;
  categories: Category[];
  // "all" or a category key. Called when the user picks a category.
  onSelect: (categoryKey: string) => void;
  // Whether the user has previously selected a category (localStorage already set).
  // When true, a close button is shown — the user can dismiss without changing selection.
  closeable: boolean;
  onClose: () => void;
}

function CloseIcon() {
  return (
    <svg
      className="w-5 h-5"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

export default function CategoryModal({
  open,
  categories,
  onSelect,
  closeable,
  onClose,
}: CategoryModalProps) {
  // Lock body scroll while modal is open
  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  // Close on Escape — only when closeable (first visit has no escape route)
  useEffect(() => {
    if (!open || !closeable) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, closeable, onClose]);

  if (!open) return null;

  function handleSelect(key: string) {
    localStorage.setItem('rcn_category', key);
    onSelect(key);
  }

  // "Alle Kategorien" synthetic entry — always first in the grid
  const totalCount = categories.reduce((sum, c) => sum + c.count, 0);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Kategorie auswählen"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(12px)' }}
      onClick={closeable ? (e) => { if (e.target === e.currentTarget) onClose(); } : undefined}
    >
      <div
        className="relative w-full max-w-2xl rounded-2xl shadow-2xl"
        style={{
          background: 'rgba(15, 15, 35, 0.92)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          backdropFilter: 'blur(20px) saturate(1.2)',
        }}
      >
        {/* Header */}
        <div
          className="px-6 pt-5 pb-4"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}
        >
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold" style={{ color: '#F8FAFC' }}>
                Was suchst du?
              </h2>
              <p className="text-sm mt-0.5" style={{ color: 'rgba(248,250,252,0.45)' }}>
                Wähle eine Kategorie — du kannst sie jederzeit wechseln.
              </p>
            </div>
            {closeable && (
              <button
                type="button"
                onClick={onClose}
                className="ml-4 p-1.5 rounded-lg transition-colors flex-shrink-0"
                style={{ color: 'rgba(248,250,252,0.4)' }}
                aria-label="Schließen"
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.color = '#F8FAFC';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.4)';
                }}
              >
                <CloseIcon />
              </button>
            )}
          </div>
        </div>

        {/* Grid */}
        <div className="p-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {/* "Alle Kategorien" — always first */}
          <button
            type="button"
            onClick={() => handleSelect('all')}
            className="flex flex-col items-start gap-1 px-4 py-3 rounded-xl text-left transition-all duration-150"
            style={{
              background: 'rgba(99,102,241,0.1)',
              border: '1px solid rgba(99,102,241,0.25)',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(99,102,241,0.2)';
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(99,102,241,0.5)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(99,102,241,0.1)';
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(99,102,241,0.25)';
            }}
          >
            <span className="text-sm font-semibold leading-tight" style={{ color: '#F8FAFC' }}>
              Alle Kategorien
            </span>
            <span className="text-xs" style={{ color: 'rgba(248,250,252,0.4)' }}>
              {totalCount.toLocaleString('de-DE')} Anzeigen
            </span>
          </button>

          {categories.map((cat) => (
            <button
              key={cat.key}
              type="button"
              onClick={() => handleSelect(cat.key)}
              className="flex flex-col items-start gap-1 px-4 py-3 rounded-xl text-left transition-all duration-150"
              style={{
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.08)',
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.09)';
                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(167,139,250,0.4)';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.04)';
                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.08)';
              }}
            >
              <span className="text-sm font-semibold leading-tight" style={{ color: '#F8FAFC' }}>
                {cat.label}
              </span>
              <span className="text-xs" style={{ color: 'rgba(248,250,252,0.4)' }}>
                {cat.count.toLocaleString('de-DE')} Anzeigen
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
