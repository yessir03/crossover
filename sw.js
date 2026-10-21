/* Crossover service worker: makes the game installable and lets it open without a connection.
   - The page itself (index.html, which also carries the player data) is network-first, so fixes
     and the monthly data update reach players right away; the cached copy is only the fallback.
   - Icons, the manifest, fonts and the pinned supabase-js build are cache-first.
   - Supabase traffic (realtime matchmaking) is never touched.
   Bump VERSION when the list in SHELL changes. */
const VERSION = 'v1';
const CACHE = 'crossover-' + VERSION;
const SHELL = ['./', 'index.html', 'manifest.webmanifest', 'icon.svg', 'icon-192.png', 'icon-512.png', 'icon-maskable-512.png', 'apple-touch-icon.png'];
const CDN = ['https://cdn.jsdelivr.net/', 'https://fonts.googleapis.com/', 'https://fonts.gstatic.com/'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k.startsWith('crossover-') && k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function networkFirst(req) {
  const cache = await caches.open(CACHE);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put('./', res.clone());
    return res;
  } catch (err) {
    return (await cache.match('./')) || (await cache.match('index.html')) || Response.error();
  }
}

async function cacheFirst(req) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok || res.type === 'opaque') cache.put(req, res.clone());
  return res;
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const scope = new URL(self.registration.scope);

  if (req.mode === 'navigate' && url.origin === scope.origin) { e.respondWith(networkFirst(req)); return; }
  if (url.origin === scope.origin && url.pathname.startsWith(scope.pathname)) { e.respondWith(cacheFirst(req)); return; }
  if (CDN.some(p => req.url.startsWith(p))) { e.respondWith(cacheFirst(req)); return; }
  // everything else (Supabase, Wikidata, …) goes straight to the network
});
