// Service Worker for Sports Betting Analyzer PWA
const CACHE_NAME = 'sba-cache-v2';
const urlsToCache = [
    '/',
    '/app.css',
    '/manifest.json'
];

// Install - cache essential files
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('PWA: Caching essential files');
                return cache.addAll(urlsToCache);
            })
            .catch(err => console.log('PWA: Cache failed', err))
    );
    self.skipWaiting();
});

// Activate - clean old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('PWA: Removing old cache', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
    self.clients.claim();
});

// Fetch - network first, fallback to cache
self.addEventListener('fetch', event => {
    // Skip non-GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    // Skip API calls - let them go through normally
    if (event.request.url.includes('/db/') ||
        event.request.url.includes('/api/') ||
        event.request.url.includes('backend:8000') ||
        event.request.url.includes('localhost:8000')) {
        return;
    }

    // Skip non-HTTP schemes (like chrome-extension://)
    const url = new URL(event.request.url);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then(response => {
                // Clone and cache successful responses
                if (response && response.status === 200 && response.type === 'basic') {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then(cache => {
                        cache.put(event.request, responseClone);
                    });
                }
                return response;
            })
            .catch(() => {
                // Fallback to cache when offline
                return caches.match(event.request);
            })
    );
});
