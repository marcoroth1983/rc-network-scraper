import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { usePullToRefresh } from '../usePullToRefresh';

// jsdom lacks TouchEvent with touches[]; build a minimal Event carrying clientY.
function touch(type: string, clientY: number): Event {
  const e = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(e, 'touches', { value: [{ clientY }] });
  Object.defineProperty(e, 'changedTouches', { value: [{ clientY }] });
  return e;
}

function makeContainer(scrollTop: number): HTMLDivElement {
  const el = document.createElement('div');
  Object.defineProperty(el, 'scrollTop', { value: scrollTop, writable: true });
  document.body.appendChild(el);
  return el;
}

describe('usePullToRefresh', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('calls onRefresh when pulled past the threshold from the top', async () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const el = makeContainer(0);

    // Render a harness component that puts the element in the ref before the
    // effect runs, so listeners are bound on the first render.
    const { result } = renderHook(() => {
      const hookResult = usePullToRefresh(onRefresh);
      // Assign the ref synchronously during render so useEffect sees it.
      (hookResult.containerRef as React.MutableRefObject<HTMLDivElement | null>).current = el;
      return hookResult;
    });

    // Confirm ref is assigned and listeners are active.
    expect(result.current.containerRef.current).toBe(el);

    act(() => {
      el.dispatchEvent(touch('touchstart', 0));
      el.dispatchEvent(touch('touchmove', 300)); // 300 * 0.5 = 150 → capped to MAX_PULL, well past 70
      el.dispatchEvent(touch('touchend', 300));
    });
    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
  });

  it('does nothing when the container is not at the top (scrollTop > 0)', () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const el = makeContainer(50);

    renderHook(() => {
      const hookResult = usePullToRefresh(onRefresh);
      (hookResult.containerRef as React.MutableRefObject<HTMLDivElement | null>).current = el;
      return hookResult;
    });

    act(() => {
      el.dispatchEvent(touch('touchstart', 0));
      el.dispatchEvent(touch('touchmove', 300));
      el.dispatchEvent(touch('touchend', 300));
    });
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it('does nothing when released below the threshold', () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const el = makeContainer(0);

    renderHook(() => {
      const hookResult = usePullToRefresh(onRefresh);
      (hookResult.containerRef as React.MutableRefObject<HTMLDivElement | null>).current = el;
      return hookResult;
    });

    act(() => {
      el.dispatchEvent(touch('touchstart', 0));
      el.dispatchEvent(touch('touchmove', 40)); // 40 * 0.5 = 20 < 70
      el.dispatchEvent(touch('touchend', 40));
    });
    expect(onRefresh).not.toHaveBeenCalled();
  });
});
