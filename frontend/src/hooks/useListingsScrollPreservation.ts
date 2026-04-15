import { useEffect, useLayoutEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { getBackground } from '../lib/modalLocation';

// Session-storage key. We keep a single slot (not per-URL) because the listings
// page is a singleton — there is never more than one "listings scroll" to
// remember. Keying by URL would drop scroll whenever the user tweaks a filter,
// which is not what we want.
const KEY = 'rcn_listings_scrollY';

/**
 * Manual scroll preservation for the listings page.
 *
 * Why not rely on browser-native scroll restoration?
 * Opening the detail modal toggles `html { overflow: hidden }` as a scroll-
 * lock. Chromium preserves window.scrollY across that toggle; Firefox and
 * iOS Safari do not — they clamp scrollY to the new max (0 while locked),
 * then fail to restore on history.back(). Manual preservation bypasses the
 * engine-specific behaviour entirely.
 *
 * Flow:
 *   - `history.scrollRestoration = 'manual'` (set in main.tsx) disables the
 *     browser's own save/restore so we don't fight it.
 *   - While listings is the foreground route, a scroll listener continuously
 *     writes window.scrollY to sessionStorage.
 *   - When we detect we've just returned from a modal (background was set on
 *     the previous render, and now the URL is back on `/`), we restore scrollY
 *     synchronously in a layout effect so the user never sees the "snap to
 *     top" flicker.
 *
 * The hook is a no-op (writes/reads skipped) while a modal is open, because:
 *   1. The listings page is not the visible route → no need to save.
 *   2. If we saved while the modal was open, the scroll listener would
 *      overwrite our saved value with the value-at-modal-open (which may have
 *      been clamped to 0 by Firefox/Safari).
 */
export function useListingsScrollPreservation(ready: boolean): void {
  const location = useLocation();
  const modalOpen = getBackground(location) != null;

  // Track previous modalOpen state so we can detect the transition
  // "modal was open → now closed" and restore scroll at that exact moment.
  const prevModalOpenRef = useRef(modalOpen);

  // Restore BEFORE paint to avoid flicker.
  useLayoutEffect(() => {
    const wasOpen = prevModalOpenRef.current;
    prevModalOpenRef.current = modalOpen;
    if (!ready) return;
    if (wasOpen && !modalOpen) {
      const raw = sessionStorage.getItem(KEY);
      if (raw != null) {
        const y = parseInt(raw, 10);
        if (!Number.isNaN(y)) {
          // Schedule on the next frame as well to cover engines that re-clamp
          // scrollTop during the overflow cleanup after the synchronous restore.
          window.scrollTo(0, y);
          requestAnimationFrame(() => window.scrollTo(0, y));
        }
      }
    }
    // Also restore on first mount (e.g. hard reload while on the listings
    // route with a remembered scroll) — only once ready.
    else if (!wasOpen && !modalOpen && ready) {
      // No-op: we only restore on modal-close; first-load should start at top.
    }
  }, [modalOpen, ready]);

  // Continuously save scrollY while listings is the foreground route and
  // content is ready. Skip while modal is open (see rationale above).
  useEffect(() => {
    if (modalOpen || !ready) return;

    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        sessionStorage.setItem(KEY, String(window.scrollY));
      });
    };
    // Persist current position immediately so the first save is captured
    // even if the user never scrolls again before opening a detail.
    sessionStorage.setItem(KEY, String(window.scrollY));
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [modalOpen, ready]);
}
