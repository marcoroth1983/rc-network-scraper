import { useState } from 'react';
import { useWebPushSubscription } from '../notifications/useWebPushSubscription';

const cardStyle: React.CSSProperties = {
  background: 'rgba(15, 15, 35, 0.6)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
};

export function NotificationsPanel() {
  const { state, supported, subscribe } = useWebPushSubscription();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubscribe = () => {
    setError(null);
    setBusy(true);
    void subscribe()
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Fehler'))
      .finally(() => setBusy(false));
  };

  return (
    <section className="w-full rounded-2xl p-4 sm:p-6" style={cardStyle}>
      <p className="text-sm font-semibold mb-4" style={{ color: '#A78BFA' }}>
        Benachrichtigungen (Web Push)
      </p>

      {!supported && (
        <p className="text-sm" style={{ color: 'rgba(248, 250, 252, 0.55)' }}>
          Dein Browser unterstützt keine Web-Push-Benachrichtigungen.
        </p>
      )}

      {supported && state.status === 'default' && (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm" style={{ color: 'rgba(248, 250, 252, 0.65)' }}>
            Push ist auf diesem Gerät noch nicht aktiviert.
          </p>
          <button type="button" onClick={handleSubscribe} disabled={busy}
            className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150"
            style={{ background: 'rgba(99, 102, 241, 0.2)', border: '1px solid rgba(99, 102, 241, 0.4)', color: '#A78BFA' }}>
            {busy ? 'Wird aktiviert …' : 'Aktivieren'}
          </button>
        </div>
      )}

      {supported && state.status === 'denied' && (
        <p className="text-sm" style={{ color: 'rgba(248, 250, 252, 0.65)' }}>
          Benachrichtigungen sind im Browser blockiert. Erlaube sie in den Site-Settings deines
          Browsers für RC Scout und lade die Seite neu.
        </p>
      )}

      {supported && state.status === 'granted-no-subscription' && (
        <button type="button" onClick={handleSubscribe} disabled={busy}
          className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150"
          style={{ background: 'rgba(99, 102, 241, 0.2)', border: '1px solid rgba(99, 102, 241, 0.4)', color: '#A78BFA' }}>
          {busy ? 'Wird aktiviert …' : 'Auf diesem Gerät aktivieren'}
        </button>
      )}

      {supported && state.status === 'granted-subscribed' && (
        <p className="text-sm" style={{ color: 'rgba(248, 250, 252, 0.75)' }}>
          {'✅'} Benachrichtigungen sind auf diesem Gerät aktiv.
        </p>
      )}

      {error && (
        <p role="alert" className="text-xs mt-2" style={{ color: '#F87171' }}>
          Fehler: {error}
        </p>
      )}
    </section>
  );
}
