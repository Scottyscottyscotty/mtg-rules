// Service Worker for MTG Rules Engine PWA
const CACHE_NAME = 'mtg-rules-v1';
const STATIC_ASSETS = [
    '/',
    '/static/style.css',
    '/static/app.js',
    '/static/manifest.json',
];

// Install: cache static assets
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch: network-first for API calls, cache-first for static assets
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // API calls and Scryfall: always network
    if (url.pathname.startsWith('/api/') || url.hostname !== location.hostname) {
        event.respondWith(fetch(event.request));
        return;
    }

    // Static assets: cache-first, fallback to network
    event.respondWith(
        caches.match(event.request).then(cached => {
            if (cached) return cached;
            return fetch(event.request).then(response => {
                const clone = response.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                return response;
            });
        })
    );
});
