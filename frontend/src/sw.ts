/// <reference lib="webworker" />
import { precacheAndRoute } from 'workbox-precaching';

declare const self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Belt-and-suspenders: receive SKIP_WAITING from workbox-window if a future
// registerType change ever leaves a new SW in "waiting".
self.addEventListener('message', (event) => {
  if ((event.data as { type?: string } | null)?.type === 'SKIP_WAITING') {
    // skipWaiting() returns a Promise<void> but it is not an async operation that needs
    // to block the install phase — wrapping it in waitUntil() is unnecessary and misleading.
    void self.skipWaiting();
  }
});

interface PushPayload {
  title: string;
  body: string;
  url?: string;
  tag?: string;
}

/** Only allow in-app relative paths ("/..."). Blocks open-redirect via push URL. */
function safeUrl(url: string | undefined): string {
  if (typeof url === 'string' && url.startsWith('/') && !url.startsWith('//')) return url;
  return '/';
}

self.addEventListener('push', (event) => {
  let data: PushPayload = { title: 'RC Scout', body: 'Neue Treffer' };
  try {
    if (event.data) data = { ...data, ...(event.data.json() as PushPayload) };
  } catch {
    if (event.data) data.body = event.data.text();
  }

  const options: NotificationOptions = {
    body: data.body,
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    tag: data.tag,
    data: { url: safeUrl(data.url) },
  };

  event.waitUntil(self.registration.showNotification(data.title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = safeUrl((event.notification.data as { url?: string } | undefined)?.url);
  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      const existing = all.find((c) => {
        try {
          return new URL(c.url).pathname === new URL(target, self.location.origin).pathname;
        } catch {
          return false;
        }
      });
      if (existing && 'focus' in existing) return existing.focus();
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })(),
  );
});
