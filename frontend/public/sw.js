// Minimal service worker — enables PWA installability (Add to Homescreen).
// No aggressive caching — network-first for everything.

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', () => self.clients.claim());
