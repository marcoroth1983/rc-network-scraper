import { useRef, useLayoutEffect, useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useComparables } from '../hooks/useComparables';

interface Props {
  listingId: number | null;
  currentListingId: number;
  anchorRef: React.RefObject<HTMLSpanElement | null>;
  onClose: () => void;
}

export default function ComparablesModal({ listingId, currentListingId, anchorRef, onClose }: Props) {
  const isOpen = listingId !== null;
  const { data, loading, error } = useComparables(listingId);
  const closeRef = useRef<HTMLButtonElement>(null);
  const swipeStartY = useRef<number | null>(null);
  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({});

  useLayoutEffect(() => {
    if (!isOpen || !anchorRef.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    const POPOVER_WIDTH = 400;
    const POPOVER_MAX_H = window.innerHeight * 0.6;
    const spaceBelow = window.innerHeight - rect.bottom - 8;
    const top = spaceBelow >= POPOVER_MAX_H
      ? rect.bottom + window.scrollY + 6
      : rect.top + window.scrollY - POPOVER_MAX_H - 6;
    const left = Math.min(
      rect.left + window.scrollX,
      window.innerWidth + window.scrollX - POPOVER_WIDTH - 16,
    );
    setPopoverStyle({ top, left, width: POPOVER_WIDTH });
  }, [isOpen, anchorRef, data]);

  useEffect(() => {
    if (!isOpen) return;
    closeRef.current?.focus();
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose(); }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [isOpen]);

  if (!isOpen) return null;

  const medianValue = data?.median ?? 0;
  let medianInsertIdx = -1;
  if (data) {
    for (let i = data.listings.length - 1; i >= 0; i--) {
      const p = data.listings[i].price_numeric;
      if (p !== null && p <= medianValue) { medianInsertIdx = i; break; }
    }
  }

  const panelStyle: React.CSSProperties = {
    background: 'rgba(12, 12, 28, 0.98)',
    backdropFilter: 'blur(24px)',
    WebkitBackdropFilter: 'blur(24px)',
    border: '1px solid rgba(255,255,255,0.1)',
    boxShadow: '0 8px 40px rgba(0,0,0,0.6)',
  };

  const header = data ? (
    <div className="px-4 py-3 flex items-center justify-between shrink-0"
      style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
      <div>
        <p className="text-xs font-semibold" style={{ color: '#F8FAFC' }}>{data.group_label}</p>
        <p className="text-[10px]" style={{ color: 'rgba(248,250,252,0.4)' }}>
          {data.count} {data.count === 1 ? 'Inserat' : 'Inserate'}{' · '}Median{' '}
          {data.median.toLocaleString('de-DE', { maximumFractionDigits: 0 })} €
        </p>
      </div>
      <button ref={closeRef} onClick={onClose} aria-label="Schließen"
        className="p-1 rounded-full" style={{ color: 'rgba(248,250,252,0.4)' }}>
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  ) : null;

  const listBody = (
    <>
      {loading && (
        <div className="flex justify-center py-10">
          <div className="animate-spin h-6 w-6 border-4 rounded-full"
            style={{ borderColor: '#A78BFA', borderTopColor: 'transparent' }} />
        </div>
      )}
      {error && (
        <p className="px-4 py-6 text-sm text-center" style={{ color: '#EC4899' }}>
          Fehler: {error}
        </p>
      )}
      {data && data.listings.length === 0 && !loading && (
        <p className="px-4 py-6 text-sm text-center" style={{ color: 'rgba(248,250,252,0.4)' }}>
          Keine Vergleichsinserate gefunden.
        </p>
      )}
      {data?.listings.map((item, idx) => (
        <div key={item.id}>
          {idx === medianInsertIdx && (
            <div className="flex items-center gap-2 px-4 py-1">
              <div className="flex-1 h-px" style={{ background: 'rgba(167,139,250,0.35)' }} />
              <span className="text-[10px] font-semibold" style={{ color: '#A78BFA' }}>
                Median {data.median.toLocaleString('de-DE', { maximumFractionDigits: 0 })} €
              </span>
              <div className="flex-1 h-px" style={{ background: 'rgba(167,139,250,0.35)' }} />
            </div>
          )}
          <Link
            to={`/listings/${item.id}`}
            onClick={onClose}
            className="flex items-center justify-between gap-3 px-4 py-2.5 transition-colors hover:bg-white/5"
            style={{
              background: item.id === currentListingId ? 'rgba(99,102,241,0.12)' : 'transparent',
              borderLeft: item.id === currentListingId ? '2px solid #6366F1' : '2px solid transparent',
            }}
          >
            <span className="text-sm line-clamp-1 flex-1"
              style={{ color: item.id === currentListingId ? '#F8FAFC' : 'rgba(248,250,252,0.75)' }}>
              {item.title}
            </span>
            <div className="flex items-center gap-2 shrink-0">
              {item.condition && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                  style={{ background: 'rgba(255,255,255,0.07)', color: 'rgba(248,250,252,0.5)' }}>
                  {item.condition}
                </span>
              )}
              {item.city && (
                <span className="text-[10px]" style={{ color: 'rgba(248,250,252,0.4)' }}>{item.city}</span>
              )}
              <span className="text-sm font-bold" style={{ color: '#FDE68A' }}>
                {item.price_numeric != null
                  ? item.price_numeric.toLocaleString('de-DE', { maximumFractionDigits: 0 }) + ' €'
                  : (item.price ?? '–')}
              </span>
            </div>
          </Link>
        </div>
      ))}
    </>
  );

  return createPortal(
    <>
      {/* Mobile bottom sheet (< sm) */}
      <div className="fixed inset-0 z-40 sm:hidden"
        style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(3px)' }}
        onClick={onClose} aria-hidden="true" />
      <div
        role="dialog" aria-modal="true" aria-label="Preisvergleich"
        className="fixed bottom-0 left-0 right-0 z-50 sm:hidden rounded-t-2xl flex flex-col"
        style={{
          ...panelStyle,
          borderBottom: 'none',
          maxHeight: '75vh',
          paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 1.5rem)',
        }}
        onTouchStart={(e) => { swipeStartY.current = e.touches[0].clientY; }}
        onTouchEnd={(e) => {
          if (swipeStartY.current === null) return;
          const delta = e.changedTouches[0].clientY - swipeStartY.current;
          swipeStartY.current = null;
          if (delta > 60) onClose();
        }}
      >
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 rounded-full" style={{ background: 'rgba(255,255,255,0.18)' }} aria-hidden="true" />
        </div>
        {header}
        <div className="flex-1 overflow-y-auto">{listBody}</div>
      </div>

      {/* Desktop popover (>= sm) */}
      <div className="fixed inset-0 z-40 hidden sm:block"
        onClick={onClose} aria-hidden="true" />
      <div
        role="dialog" aria-modal="true" aria-label="Preisvergleich"
        className="fixed z-50 hidden sm:flex flex-col rounded-xl overflow-hidden"
        style={{ ...popoverStyle, maxHeight: '60vh', ...panelStyle }}
        onClick={(e) => e.stopPropagation()}
      >
        {header}
        <div className="flex-1 overflow-y-auto">{listBody}</div>
      </div>
    </>,
    document.body,
  );
}
