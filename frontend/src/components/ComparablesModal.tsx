import { useRef, useLayoutEffect, useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import type { ComparablesResponse } from '../types/api';

interface Props {
  data: ComparablesResponse;
  anchorRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
}

export default function ComparablesModal({ data, anchorRef, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const swipeStartY = useRef<number | null>(null);
  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({});

  useLayoutEffect(() => {
    if (!anchorRef.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    const POPOVER_WIDTH = Math.min(640, window.innerWidth - 32);
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
  }, [anchorRef, data]);

  useEffect(() => {
    closeRef.current?.focus();
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose(); }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  const panelStyle: React.CSSProperties = {
    background: 'rgba(12, 12, 28, 0.98)',
    backdropFilter: 'blur(24px)',
    WebkitBackdropFilter: 'blur(24px)',
    border: '1px solid rgba(255,255,255,0.1)',
    boxShadow: '0 8px 40px rgba(0,0,0,0.6)',
  };

  const isEmpty = data.count === 0 || data.listings.length === 0;

  const header = (
    <div className="px-4 py-3 flex items-center justify-between shrink-0"
      style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
      <div>
        <p className="text-xs font-semibold" style={{ color: '#F8FAFC' }}>Preisvergleich</p>
        <p className="text-[10px]" style={{ color: 'rgba(248,250,252,0.4)' }}>
          {data.count} ähnliche Inserate
        </p>
      </div>
      <button ref={closeRef} onClick={onClose} aria-label="Schließen"
        className="p-1 rounded-full" style={{ color: 'rgba(248,250,252,0.4)' }}>
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  );

  const listBody = isEmpty ? (
    <p className="px-4 py-6 text-sm text-center" style={{ color: 'rgba(248,250,252,0.4)' }}>
      Keine vergleichbaren Inserate.
    </p>
  ) : (
    <ul>
      {data.listings.map((listing) => (
        <li
          key={listing.id}
          className="flex items-center gap-3 px-4 py-2 border-b last:border-0 border-white/5"
        >
          <span className="flex-1 truncate text-sm text-white/90">{listing.title}</span>
          <span className="shrink-0 text-sm tabular-nums text-white/70">
            {listing.price ?? '—'}
          </span>
          <a
            href={listing.url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 p-1.5 rounded hover:bg-white/10 text-white/50 hover:text-white/90 transition"
            aria-label="Zum Inserat öffnen"
            onClick={(e) => e.stopPropagation()}
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path d="M14 3h7v7M10 14L21 3M21 14v5a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h5" />
            </svg>
          </a>
        </li>
      ))}
    </ul>
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
