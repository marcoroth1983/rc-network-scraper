import { useEffect, useState } from 'react';
import { useWebPushSubscription } from './useWebPushSubscription';
import { isIos, isStandalone } from '../lib/pwa-detect';

const FLAG = 'rcn_notif_asked';

export function FirstStartPushPrompt() {
  const { state, subscribe } = useWebPushSubscription();
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(FLAG) === 'true');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const blockedByIos = isIos() && !isStandalone();
  const visible = !dismissed && !blockedByIos && state.status === 'default';

  useEffect(() => {
    if (state.status === 'granted-subscribed' || state.status === 'denied') {
      localStorage.setItem(FLAG, 'true');
    }
  }, [state.status]);

  if (!visible) return null;

  const dismiss = () => {
    localStorage.setItem(FLAG, 'true');
    setDismissed(true);
  };

  const enable = () => {
    setError(null);
    setBusy(true);
    void subscribe()
      .then(() => dismiss())
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Aktivierung fehlgeschlagen'))
      .finally(() => setBusy(false));
  };

  return (
    <div
      role="region"
      aria-live="polite"
      aria-label="Benachrichtigungen aktivieren"
      className="sm:hidden fixed bottom-[140px] left-3 right-3 z-50 rounded-xl px-4 py-3"
      style={{
        background: 'rgba(15, 15, 35, 0.92)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(99, 102, 241, 0.3)',
        boxShadow: '0 -4px 24px rgba(0, 0, 0, 0.4)',
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="flex-shrink-0 flex items-center justify-center rounded-lg"
          style={{
            width: 36, height: 36,
            background: 'linear-gradient(135deg, rgba(99,102,241,0.3), rgba(147,51,234,0.3))',
            border: '1px solid rgba(255,255,255,0.1)',
          }}
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="#A78BFA" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M15 17h5l-1.4-1.4A2 2 0 0118 14V11a6 6 0 10-12 0v3a2 2 0 01-.6 1.4L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium" style={{ color: '#F8FAFC' }}>
            Benachrichtigungen aktivieren?
          </p>
          <p className="text-xs" style={{ color: 'rgba(248, 250, 252, 0.45)' }}>
            Bei neuen Treffern für deine gespeicherten Suchen.
          </p>
          {error && (
            <p className="text-xs mt-1" role="alert" style={{ color: '#F87171' }}>
              Fehler: {error}
            </p>
          )}
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-3">
        <button type="button" onClick={dismiss} disabled={busy}
          className="rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
          style={{ color: 'rgba(248, 250, 252, 0.55)' }}>
          Später
        </button>
        <button type="button" onClick={enable} disabled={busy}
          className="rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
          style={{
            background: 'rgba(99, 102, 241, 0.2)',
            border: '1px solid rgba(99, 102, 241, 0.4)',
            color: '#A78BFA',
          }}>
          {busy ? 'Wird aktiviert …' : 'Aktivieren'}
        </button>
      </div>
    </div>
  );
}
