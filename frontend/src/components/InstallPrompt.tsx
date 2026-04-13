import { useState, useEffect, useCallback } from 'react';

const DISMISSED_KEY = 'rcn_install_dismissed';

/** Days before showing the prompt again after dismissal. */
const SNOOZE_DAYS = 7;

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

function isStandalone(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    (navigator as unknown as { standalone?: boolean }).standalone === true
  );
}

function isIos(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

function isDismissed(): boolean {
  const raw = localStorage.getItem(DISMISSED_KEY);
  if (!raw) return false;
  const ts = Number(raw);
  if (Number.isNaN(ts)) return false;
  return Date.now() - ts < SNOOZE_DAYS * 86_400_000;
}

export function InstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [showIosHint, setShowIosHint] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Already installed or recently dismissed — bail
    if (isStandalone() || isDismissed()) return;

    // Android/Chrome: capture the install prompt
    function handler(e: Event) {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
      setVisible(true);
    }
    window.addEventListener('beforeinstallprompt', handler);

    // iOS: no native prompt — show manual hint after short delay
    if (isIos()) {
      const timer = setTimeout(() => {
        setShowIosHint(true);
        setVisible(true);
      }, 2000);
      return () => {
        clearTimeout(timer);
        window.removeEventListener('beforeinstallprompt', handler);
      };
    }

    return () => window.removeEventListener('beforeinstallprompt', handler);
  }, []);

  const handleInstall = useCallback(async () => {
    if (!deferredPrompt) return;
    await deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      setVisible(false);
    }
    setDeferredPrompt(null);
  }, [deferredPrompt]);

  const handleDismiss = useCallback(() => {
    localStorage.setItem(DISMISSED_KEY, String(Date.now()));
    setVisible(false);
  }, []);

  if (!visible) return null;

  // Only show on mobile (<640px)
  return (
    <div
      className="sm:hidden fixed bottom-[72px] left-3 right-3 z-50 flex items-center gap-3 rounded-xl px-4 py-3"
      style={{
        background: 'rgba(15, 15, 35, 0.92)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(99, 102, 241, 0.3)',
        boxShadow: '0 -4px 24px rgba(0, 0, 0, 0.4)',
      }}
    >
      {/* Icon */}
      <div
        className="flex-shrink-0 flex items-center justify-center rounded-lg"
        style={{
          width: 36,
          height: 36,
          background: 'linear-gradient(135deg, rgba(99,102,241,0.3), rgba(147,51,234,0.3))',
          border: '1px solid rgba(255,255,255,0.1)',
        }}
      >
        <svg
          className="w-5 h-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#A78BFA"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12l7-7 7 7" />
        </svg>
      </div>

      {/* Text */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium" style={{ color: '#F8FAFC' }}>
          App installieren
        </p>
        <p className="text-xs" style={{ color: 'rgba(248, 250, 252, 0.45)' }}>
          {showIosHint
            ? 'Teilen → Zum Home-Bildschirm'
            : 'Direkt vom Startbildschirm öffnen'}
        </p>
      </div>

      {/* Actions */}
      {deferredPrompt && (
        <button
          onClick={handleInstall}
          className="flex-shrink-0 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
          style={{
            background: 'rgba(99, 102, 241, 0.2)',
            border: '1px solid rgba(99, 102, 241, 0.4)',
            color: '#A78BFA',
          }}
        >
          Installieren
        </button>
      )}

      <button
        onClick={handleDismiss}
        className="flex-shrink-0 p-1 transition-colors"
        style={{ color: 'rgba(248, 250, 252, 0.3)' }}
        aria-label="Schließen"
      >
        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" d="M18 6L6 18M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
