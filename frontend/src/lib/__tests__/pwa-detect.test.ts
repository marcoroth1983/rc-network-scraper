import { describe, it, expect, vi, afterEach } from 'vitest';
import { isIos, isStandalone, pushSupported } from '../pwa-detect';

afterEach(() => vi.unstubAllGlobals());

describe('pwa-detect', () => {
  it('isIos true for iPhone UA', () => {
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS …)' });
    expect(isIos()).toBe(true);
  });

  it('isIos false for Android UA', () => {
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Linux; Android 13)' });
    expect(isIos()).toBe(false);
  });

  it('isStandalone reads display-mode media query', () => {
    vi.stubGlobal('window', { ...window, matchMedia: () => ({ matches: true } as MediaQueryList) });
    vi.stubGlobal('navigator', {});
    expect(isStandalone()).toBe(true);
  });

  it('pushSupported false when serviceWorker missing', () => {
    vi.stubGlobal('navigator', {});
    expect(pushSupported()).toBe(false);
  });

  it('pushSupported true when SW + PushManager + Notification present', () => {
    vi.stubGlobal('navigator', { serviceWorker: {} });
    vi.stubGlobal('window', { ...window, PushManager: class {}, Notification: class {} });
    expect(pushSupported()).toBe(true);
  });
});
