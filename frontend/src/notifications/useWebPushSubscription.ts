import { useCallback, useEffect, useState } from 'react';
import { pushSupported } from '../lib/pwa-detect';
import { notificationsApi } from './api';
import { getDeviceLabel } from './device-label';

export type PushState =
  | { status: 'unsupported' }
  | { status: 'default' }
  | { status: 'denied' }
  | { status: 'granted-no-subscription' }
  | { status: 'granted-subscribed'; endpoint: string };

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const safe = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(safe);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function useWebPushSubscription() {
  // Lazy initializer: if push is not supported we start in 'unsupported' immediately,
  // so the component never flashes a 'default' state on unsupported browsers.
  const [state, setState] = useState<PushState>(() =>
    pushSupported() ? { status: 'default' } : { status: 'unsupported' },
  );
  // Derive `supported` from the same predicate so it stays consistent with the initial state.
  const supported = pushSupported();

  const refresh = useCallback(async () => {
    if (!pushSupported()) return setState({ status: 'unsupported' });
    if (Notification.permission === 'denied') return setState({ status: 'denied' });
    if (Notification.permission === 'default') return setState({ status: 'default' });
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (!sub) return setState({ status: 'granted-no-subscription' });
    setState({ status: 'granted-subscribed', endpoint: sub.endpoint });
  }, []);

  useEffect(() => {
    // Async effect: refresh() reads browser APIs and calls setState asynchronously.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const subscribe = useCallback(async () => {
    if (!pushSupported()) throw new Error('Push wird in diesem Browser nicht unterstützt');
    const { public_key } = await notificationsApi.getVapidPublicKey();
    if (!public_key) throw new Error('VAPID-Schlüssel nicht verfügbar');

    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      await refresh();
      return;
    }

    const reg = await navigator.serviceWorker.ready;
    const applicationServerKey = urlBase64ToUint8Array(public_key) as unknown as BufferSource;
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey });
    const json = sub.toJSON();
    await notificationsApi.createSubscription({
      endpoint: json.endpoint!,
      keys: { p256dh: json.keys!['p256dh'], auth: json.keys!['auth'] },
      user_agent: navigator.userAgent,
      device_label: getDeviceLabel(),
    });
    await refresh();
  }, [refresh]);

  const unsubscribeCurrent = useCallback(async () => {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      // Remove from browser push service first, then clean up the backend record
      // so we don't leave an orphaned subscription that would cause silent delivery failures.
      await sub.unsubscribe();
      try {
        const backendSubs = await notificationsApi.listSubscriptions();
        const match = backendSubs.find((s) => s.endpoint === sub.endpoint);
        if (match) await notificationsApi.deleteSubscription(match.id);
      } catch {
        // Non-fatal: browser-side unsubscription already succeeded; backend cleanup
        // is best-effort. The push service will eventually reject dead endpoints.
      }
    }
    await refresh();
  }, [refresh]);

  return { state, supported, subscribe, unsubscribeCurrent, refresh };
}
