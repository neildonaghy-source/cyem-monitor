/* CyEM Monitor service worker: makes the app installable and keeps the shell
   available if the tailnet drops. Network-first for everything; only the static
   shell is cached as a fallback. API responses are never cached. */
const CACHE = 'cyem-shell-v15';
const SHELL = ['/', '/static/style.css?v=2026-09-23n', '/static/app.js?v=2026-09-23n', '/static/vendor/leaflet.js', '/static/vendor/leaflet.css', '/static/vendor/marked.umd.js', '/static/manifest.webmanifest'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => null)); self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok && (url.pathname === '/' || url.pathname.startsWith('/static/'))) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => null); }
    return r;
  }).catch(() => caches.match(e.request).then((m) => m || (url.pathname === '/' ? caches.match('/') : undefined))));
});
