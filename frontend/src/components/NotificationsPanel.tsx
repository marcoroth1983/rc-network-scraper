import { useState, useCallback, useEffect } from 'react';
import { useWebPushSubscription } from '../notifications/useWebPushSubscription';
import { notificationsApi } from '../notifications/api';
import { getNotificationPrefs, updateNotificationPrefs } from '../api/client';
import type { NotificationPrefs, PushSubscriptionDto } from '../types/api';

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
  const [subs, setSubs] = useState<PushSubscriptionDto[]>([]);
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);

  const reloadSubs = useCallback(async () => {
    try { setSubs(await notificationsApi.listSubscriptions()); } catch { /* non-fatal */ }
  }, []);

  const reloadPrefs = useCallback(async () => {
    try { setPrefs(await getNotificationPrefs()); } catch { /* non-fatal */ }
  }, []);

  useEffect(() => {
    if (state.status === 'granted-subscribed' || state.status === 'granted-no-subscription') {
      void reloadSubs();
    }
    void reloadPrefs();
  }, [state.status, reloadSubs, reloadPrefs]);

  const handleDelete = (id: number) => {
    void notificationsApi.deleteSubscription(id).then(reloadSubs);
  };

  const handleTogglePush = (value: boolean) => {
    const previous = prefs?.web_push_enabled;
    setPrefs((p) => (p ? { ...p, web_push_enabled: value } : p));
    void updateNotificationPrefs({ web_push_enabled: value })
      .then(setPrefs)
      .catch(() => {
        if (previous !== undefined) setPrefs((p) => (p ? { ...p, web_push_enabled: previous } : p));
      });
  };

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

      {(state.status === 'granted-subscribed' || state.status === 'granted-no-subscription') && subs.length > 0 && (
        <div className="mt-5">
          <p className="text-[10px] font-semibold uppercase tracking-widest mb-2"
             style={{ color: 'rgba(248, 250, 252, 0.35)' }}>
            Registrierte Geräte
          </p>
          <ul className="flex flex-col gap-2">
            {subs.map((s) => (
              <li key={s.id} className="flex items-center justify-between text-sm">
                <span style={{ color: 'rgba(248, 250, 252, 0.8)' }}>
                  {s.device_label ?? 'Unbekanntes Gerät'}
                </span>
                <button type="button" onClick={() => handleDelete(s.id)}
                  aria-label={`Gerät ${s.device_label ?? s.id} entfernen`}
                  className="text-xs" style={{ color: 'rgba(248, 250, 252, 0.45)' }}>
                  Entfernen
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {prefs && (
        <div className="mt-5 flex items-center justify-between">
          <span className="text-sm" style={{ color: 'rgba(248,250,252,0.75)' }}>
            Push-Benachrichtigungen empfangen
          </span>
          <button type="button" role="switch" aria-checked={prefs.web_push_enabled} aria-label="Push aktiv"
            onClick={() => handleTogglePush(!prefs.web_push_enabled)}
            className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200"
            style={{
              background: prefs.web_push_enabled
                ? 'linear-gradient(135deg, rgba(99,102,241,0.9), rgba(139,92,246,0.9))'
                : 'rgba(255,255,255,0.1)',
              border: prefs.web_push_enabled
                ? '1px solid rgba(139,92,246,0.5)'
                : '1px solid rgba(255,255,255,0.15)',
            }}>
            <span className="inline-block h-3.5 w-3.5 rounded-full transition-transform duration-200"
              style={{
                background: '#fff',
                transform: prefs.web_push_enabled ? 'translateX(18px)' : 'translateX(2px)',
                boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
              }}
              aria-hidden="true" />
          </button>
        </div>
      )}
    </section>
  );
}
