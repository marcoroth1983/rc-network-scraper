import { useCallback, useEffect, useRef, useState } from 'react';

const THRESHOLD = 70;          // px the user must pull before a release triggers refresh
const MAX_PULL = 110;          // px hard cap on the rendered indicator travel
const RESISTANCE = 0.5;        // dampening factor applied to raw finger travel

export interface UsePullToRefreshResult {
  /** Attach to the scrollable container that hosts the list. */
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** Current (dampened, capped) pull distance in px — drive the indicator with this. */
  pullDistance: number;
  /** True while the onRefresh promise is in flight. */
  refreshing: boolean;
}

/**
 * Mobile-only pull-to-refresh for a scrollable container.
 *
 * Touch-only by design (no mouse-drag), so desktop is unaffected. The gesture
 * engages ONLY when the container is scrolled to the very top at touchstart, so
 * it never steals a normal upward scroll. On release past THRESHOLD it awaits
 * onRefresh() and shows a refreshing state until the promise settles.
 */
export function usePullToRefresh(onRefresh: () => Promise<void>): UsePullToRefreshResult {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const startYRef = useRef<number | null>(null); // non-null only while a valid pull is active
  const pullRef = useRef(0);                      // mirrors pullDistance for the touchend handler
  const refreshingRef = useRef(false);            // mirrors `refreshing` so the touch handlers read it without re-binding
  const [pullDistance, setPullDistance] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  // Single source of truth for the refreshing flag: write the ref AND the state
  // together so the touch handlers (which read the ref) and the JSX (which reads
  // state) never diverge. The ref lets onTouchStart see the live value without
  // putting `refreshing` in the effect dep-array (which would churn listeners).
  const setRefreshingBoth = useCallback((value: boolean) => {
    refreshingRef.current = value;
    setRefreshing(value);
  }, []);

  const reset = useCallback(() => {
    startYRef.current = null;
    pullRef.current = 0;
    setPullDistance(0);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (el == null) return;

    const onTouchStart = (e: TouchEvent) => {
      // Engage only when already at the top; otherwise let native scroll run.
      // Read refreshingRef (not the `refreshing` state) so this handler stays
      // valid without re-binding the effect on every refreshing flip.
      if (el.scrollTop <= 0 && !refreshingRef.current) {
        startYRef.current = e.touches[0].clientY;
      } else {
        startYRef.current = null;
      }
    };

    const onTouchMove = (e: TouchEvent) => {
      if (startYRef.current === null) return;
      const raw = e.touches[0].clientY - startYRef.current;
      if (raw <= 0) {
        // Pulling up / no downward travel — abandon, let native scroll resume.
        pullRef.current = 0;
        setPullDistance(0);
        return;
      }
      // Downward pull from the top: dampen, cap, and suppress native overscroll.
      const dist = Math.min(raw * RESISTANCE, MAX_PULL);
      pullRef.current = dist;
      setPullDistance(dist);
      e.preventDefault();
    };

    const onTouchEnd = () => {
      if (startYRef.current === null) return;
      const shouldRefresh = pullRef.current >= THRESHOLD;
      if (shouldRefresh) {
        setRefreshingBoth(true);
        setPullDistance(THRESHOLD); // hold indicator at threshold while refreshing
        startYRef.current = null;
        void onRefresh().finally(() => {
          setRefreshingBoth(false);
          pullRef.current = 0;
          setPullDistance(0);
        });
      } else {
        reset();
      }
    };

    // touchmove must be non-passive so preventDefault() can tame native pull-to-refresh.
    el.addEventListener('touchstart', onTouchStart, { passive: true });
    el.addEventListener('touchmove', onTouchMove, { passive: false });
    el.addEventListener('touchend', onTouchEnd);
    return () => {
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchmove', onTouchMove);
      el.removeEventListener('touchend', onTouchEnd);
    };
    // `refreshing` deliberately omitted — read via refreshingRef inside the
    // handlers so the listeners are bound once and never churn.
  }, [onRefresh, reset, setRefreshingBoth]);

  return { containerRef, pullDistance, refreshing };
}
