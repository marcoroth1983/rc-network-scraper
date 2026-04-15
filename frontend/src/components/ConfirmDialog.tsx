import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Red/pink confirm button with warning icon. Default focus stays on cancel. */
  destructive?: boolean;
}

type Resolver = (result: boolean) => void;

const ConfirmCtx = createContext<((opts: ConfirmOptions) => Promise<boolean>) | null>(null);

const EXIT_MS = 160;

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  const [visible, setVisible] = useState(false);
  const resolverRef = useRef<Resolver | null>(null);
  const confirmBtnRef = useRef<HTMLButtonElement | null>(null);
  const cancelBtnRef = useRef<HTMLButtonElement | null>(null);
  const prevFocusRef = useRef<HTMLElement | null>(null);

  const confirm = useCallback((o: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
      setOpts(o);
      // Flip visible on the next frame so the CSS transition runs
      requestAnimationFrame(() => setVisible(true));
    });
  }, []);

  const close = useCallback((result: boolean) => {
    const r = resolverRef.current;
    resolverRef.current = null;
    setVisible(false);
    setTimeout(() => {
      setOpts(null);
      prevFocusRef.current?.focus();
      r?.(result);
    }, EXIT_MS);
  }, []);

  // Focus management + keyboard (Escape / Enter / Tab trap)
  useEffect(() => {
    if (!opts) return;
    prevFocusRef.current = document.activeElement as HTMLElement;

    // Safer default for destructive actions: focus cancel.
    const initial = opts.destructive ? cancelBtnRef.current : confirmBtnRef.current;
    initial?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        close(false);
        return;
      }
      if (e.key === 'Enter') {
        if (document.activeElement === cancelBtnRef.current) return;
        e.preventDefault();
        close(true);
        return;
      }
      if (e.key === 'Tab') {
        const first = cancelBtnRef.current;
        const last = confirmBtnRef.current;
        if (!first || !last) return;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [opts, close]);

  const iconTone = opts?.destructive
    ? {
        background: 'rgba(236,72,153,0.12)',
        border: '1px solid rgba(236,72,153,0.3)',
        color: '#EC4899',
      }
    : {
        background: 'rgba(167,139,250,0.12)',
        border: '1px solid rgba(167,139,250,0.3)',
        color: '#A78BFA',
      };

  const confirmStyle = opts?.destructive
    ? {
        background: 'linear-gradient(135deg, rgba(236,72,153,0.95), rgba(190,40,120,0.95))',
        border: '1px solid rgba(236,72,153,0.5)',
        color: '#fff',
        boxShadow: '0 4px 16px rgba(236,72,153,0.25)',
      }
    : {
        background: 'linear-gradient(135deg, rgba(99,102,241,0.95), rgba(139,92,246,0.95))',
        border: '1px solid rgba(139,92,246,0.5)',
        color: '#fff',
        boxShadow: '0 4px 16px rgba(99,102,241,0.25)',
      };

  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      {opts &&
        createPortal(
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            aria-describedby={opts.message ? 'confirm-message' : undefined}
            className="fixed inset-0 z-[70] flex items-center justify-center px-4"
          >
            {/* Scrim — click to cancel */}
            <button
              type="button"
              aria-label="Abbrechen"
              onClick={() => close(false)}
              tabIndex={-1}
              className={`absolute inset-0 transition-opacity duration-200 cursor-default ${
                visible ? 'opacity-100' : 'opacity-0'
              }`}
              style={{
                background: 'rgba(0,0,0,0.55)',
                backdropFilter: 'blur(4px)',
                WebkitBackdropFilter: 'blur(4px)',
              }}
            />

            {/* Dialog card */}
            <div
              className={`relative w-full max-w-sm rounded-2xl p-6 transition-all ease-out ${
                visible ? 'opacity-100 scale-100' : 'opacity-0 scale-95'
              }`}
              style={{
                transitionDuration: '180ms',
                background: 'rgba(15, 15, 35, 0.92)',
                backdropFilter: 'blur(24px) saturate(1.2)',
                WebkitBackdropFilter: 'blur(24px) saturate(1.2)',
                border: '1px solid rgba(255,255,255,0.08)',
                boxShadow:
                  '0 24px 60px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.04), 0 0 80px rgba(99,102,241,0.08)',
              }}
            >
              {/* Leading icon */}
              <div
                className="w-11 h-11 rounded-2xl flex items-center justify-center mb-4"
                style={iconTone}
                aria-hidden="true"
              >
                {opts.destructive ? (
                  <svg
                    className="w-5 h-5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2.25}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
                    />
                  </svg>
                ) : (
                  <svg
                    className="w-5 h-5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2.25}
                  >
                    <circle cx="12" cy="12" r="9" />
                    <path strokeLinecap="round" d="M12 8v4M12 16h.01" />
                  </svg>
                )}
              </div>

              <h2
                id="confirm-title"
                className="text-lg font-semibold leading-tight mb-2"
                style={{ color: '#F8FAFC' }}
              >
                {opts.title}
              </h2>

              {opts.message && (
                <p
                  id="confirm-message"
                  className="text-sm leading-relaxed mb-6"
                  style={{ color: 'rgba(248,250,252,0.65)' }}
                >
                  {opts.message}
                </p>
              )}

              <div className={`flex gap-2 ${opts.message ? '' : 'mt-5'}`}>
                <button
                  ref={cancelBtnRef}
                  type="button"
                  onClick={() => close(false)}
                  className="flex-1 h-11 rounded-xl text-sm font-semibold transition-colors duration-150 cursor-pointer focus:outline-none focus:ring-2 focus:ring-white/25"
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    color: 'rgba(248,250,252,0.8)',
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background =
                      'rgba(255,255,255,0.08)';
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background =
                      'rgba(255,255,255,0.05)';
                  }}
                >
                  {opts.cancelLabel ?? 'Abbrechen'}
                </button>
                <button
                  ref={confirmBtnRef}
                  type="button"
                  onClick={() => close(true)}
                  className={`flex-1 h-11 rounded-xl text-sm font-semibold transition-all duration-150 cursor-pointer focus:outline-none focus:ring-2 ${
                    opts.destructive ? 'focus:ring-pink-400/60' : 'focus:ring-indigo-400/60'
                  }`}
                  style={confirmStyle}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-1px)';
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(0)';
                  }}
                >
                  {opts.confirmLabel ?? (opts.destructive ? 'Löschen' : 'OK')}
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </ConfirmCtx.Provider>
  );
}

/** Imperative confirm: `const ok = await confirm({ title: '…', destructive: true })`. */
export function useConfirm(): (opts: ConfirmOptions) => Promise<boolean> {
  const ctx = useContext(ConfirmCtx);
  if (!ctx) throw new Error('useConfirm must be used within <ConfirmProvider>');
  return ctx;
}
