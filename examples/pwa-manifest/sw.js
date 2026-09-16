/**
 * High-Performance Production Service Worker
 * Tiered Caching Strategy:
 * - HTML Documents: Stale-While-Revalidate with offline fallback
 * - Static Assets (CSS, JS, Fonts, Images): Cache-First (1 year)
 * - API / Dynamic JSON: Network-First with Cache Fallback
 */

const CACHE_NAME = 'cwv-speed-cache-v1.0.0';

const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/offline.html',
  '/site.webmanifest',
  '/favicon.svg',
];

// 1. Install Event: Precache Application Shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// 2. Activate Event: Clean Stale Caches & Claim Clients
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames
            .filter((name) => name !== CACHE_NAME)
            .map((name) => caches.delete(name))
        );
      })
      .then(() => self.clients.claim())
  );
});

// 3. Fetch Event: Routing & Caching Strategies
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Skip non-GET and browser-extension requests
  if (request.method !== 'GET' || !url.protocol.startsWith('http')) return;

  // A. Navigation (HTML Pages): Stale-While-Revalidate + Offline Fallback
  if (request.mode === 'navigate') {
    event.respondWith(
      caches.open(CACHE_NAME).then(async (cache) => {
        const cachedResponse = await cache.match(request);
        const networkPromise = fetch(request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              cache.put(request, networkResponse.clone());
            }
            return networkResponse;
          })
          .catch(() => cachedResponse || caches.match('/offline.html'));

        return cachedResponse || networkPromise;
      })
    );
    return;
  }

  // B. Fingerprinted Static Assets (CSS, JS, Fonts, WebP, AVIF, SVG): Cache-First
  if (url.pathname.match(/\.(?:js|css|woff2|woff|ttf|webp|avif|png|jpg|jpeg|svg)$/i)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        });
      })
    );
    return;
  }

  // C. API Endpoints: Network-First with Cache Fallback
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Default: Network with Cache Fallback
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});
