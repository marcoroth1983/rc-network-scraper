import { useEffect, useCallback, useRef, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { isDirectHit } from '../lib/modalLocation';

interface Props { children: ReactNode }

export default function ListingDetailModal({ children }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const directHit = isDirectHit(location);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  const close = useCallback(() => {
    if (directHit) {
      // No (or unreliable) history behind us — drop the modal and land on `/`.
      navigate('/', { replace: true });
    } else {
      navigate(-1);
    }
  }, [navigate, directHit]);

  // Scroll-lock on mount, restore previous value on unmount.
  // Empty deps — effect runs once per modal lifetime so that mid-modal
  // pathname changes (nested A → B) do NOT toggle overflow between renders.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  // Close on Escape.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [close]);

  // When the modal's pathname changes (nested card navigation), reset the
  // modal's own scroll position to the top so detail B does not open half-scrolled.
  useEffect(() => {
    if (wrapperRef.current) wrapperRef.current.scrollTop = 0;
  }, [location.pathname]);

  return (
    <div
      ref={wrapperRef}
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-[60] overflow-y-auto"
      style={{ background: '#0F0F23', overscrollBehavior: 'contain' }}
    >
      <div className="max-w-screen-2xl mx-auto px-3 pt-3 pb-20 sm:px-4 lg:px-6">
        {children}
      </div>
    </div>
  );
}
