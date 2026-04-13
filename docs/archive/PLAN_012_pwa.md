# PLAN 012 — Progressive Web App (Homescreen + Fullscreen)

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-13 |
| Human | approved | 2026-04-13 |

## Context & Goal

The app is actively used on mobile (Android). Adding PWA support enables:
- **Add to Homescreen** — app icon on the phone, no browser bookmarks needed
- **Fullscreen / standalone mode** — no browser chrome, feels like a native app
- **Offline shell** — the app shell (HTML/CSS/JS) loads instantly; data still requires network

**Out of scope:** Push notifications (separate future plan).

## Breaking Changes

**No.** This is purely additive — existing browser usage is unaffected.

## Steps

### Step 1 — Generate PNG icons from existing favicon.svg

The existing `favicon.svg` (lightning bolt, purple #863bff) needs to be converted to PNG icons for PWA manifest and Apple devices.

**Required icon sizes:**
- `icons/icon-192.png` — Android homescreen icon (required by PWA spec)
- `icons/icon-512.png` — Android splash screen (required by PWA spec)
- `icons/icon-maskable-192.png` — Maskable variant for adaptive icons (with safe-zone padding)
- `icons/icon-maskable-512.png` — Maskable variant large
- `icons/apple-touch-icon-180.png` — iOS homescreen icon (180x180)

All placed in `frontend/public/icons/`.

**Generation approach:** Use the `favicon.svg` as source. For maskable icons, add a solid `#0f0f23` background circle/rect with the SVG centered in the safe zone (inner 80%).

### Step 2 — Create `manifest.json`

File: `frontend/public/manifest.json`

```json
{
  "name": "RC-Network Scout",
  "short_name": "RC Scout",
  "description": "Dein persönlicher RC-Flohmarkt-Scout",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0f0f23",
  "theme_color": "#0f0f23",
  "orientation": "portrait",
  "icons": [
    {
      "src": "/icons/icon-192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any"
    },
    {
      "src": "/icons/icon-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "any"
    },
    {
      "src": "/icons/icon-maskable-192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "maskable"
    },
    {
      "src": "/icons/icon-maskable-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "maskable"
    }
  ]
}
```

Key decisions:
- `display: "standalone"` — fullscreen without browser chrome (but keeps status bar, unlike `fullscreen` which hides everything)
- `background_color: "#0f0f23"` — matches the aurora dark background for seamless splash screen
- `theme_color: "#0f0f23"` — matches the app's dark theme for Android status bar
- `orientation: "portrait"` — the app is designed for portrait mobile use

### Step 3 — Update `index.html` with PWA meta tags

Add to `<head>` in `frontend/index.html`:

```html
<!-- PWA -->
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0f0f23">

<!-- iOS PWA support -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="RC Scout">
<link rel="apple-touch-icon" href="/icons/apple-touch-icon-180.png">
```

### Step 4 — Add a minimal Service Worker

A basic service worker is required for the browser to show the "Add to Homescreen" prompt. Without it, Chrome won't treat the app as installable.

File: `frontend/public/sw.js`

```js
const CACHE_NAME = 'rc-scout-shell-v1';
const SHELL_ASSETS = [
  '/',
  '/index.html',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  // Network-first strategy: always try network, fall back to cache for shell
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .catch(() => caches.match('/index.html'))
    );
  }
});
```

Strategy: **Network-first for navigation** — always fetch fresh content, only fall back to cached shell when offline. API calls and assets pass through without interception (no stale data risk).

### Step 5 — Register Service Worker in app

Add registration in `frontend/src/main.tsx` (after React render):

```typescript
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js');
  });
}
```

### Step 6 — Update nginx cache headers

The service worker file must never be cached by the browser (or updates won't propagate). Add to `frontend/nginx.conf`:

```nginx
location = /sw.js {
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
```

Note: nginx `add_header` in a location block replaces the parent server block headers, so security headers must be repeated here.

## Verification

```bash
# 1. Build frontend locally
cd frontend && npm run build

# 2. Check manifest is in output
ls dist/manifest.json dist/sw.js dist/icons/

# 3. After deploy — Lighthouse PWA audit (Chrome DevTools > Lighthouse > PWA)
# Expected: "Installable" badge, all PWA criteria met

# 4. Mobile test: open https://rcn-scout.d2x-labs.de in Chrome Android
#    → three-dot menu should show "Add to Home screen" or "Install app"
#    → after install: app opens standalone without browser chrome
```

## Assumptions & Risks

| Risk | Mitigation |
|------|-----------|
| Icon generation needs image tooling (sharp, Inkscape, etc.) | Can use any online SVG-to-PNG converter or generate programmatically with sharp |
| Service worker caches stale shell after deploy | Network-first strategy + `skipWaiting()` ensures updates propagate on next visit |
| iOS has limited PWA support (no install prompt) | Manual "Share → Add to Home Screen" flow still works; meta tags ensure proper icon/title |
