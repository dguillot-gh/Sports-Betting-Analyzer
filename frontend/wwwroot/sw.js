// sw.js — Service Worker for Web Push Notifications
// Registered by the frontend to receive background push messages.

self.addEventListener('install', (event) => {
    // Activate immediately — no waiting for existing clients to close
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
    if (!event.data) return;

    let payload;
    try {
        payload = event.data.json();
    } catch {
        payload = { title: 'Sports Betting Analyzer', body: event.data.text() };
    }

    const title = payload.title || 'Notification';
    const options = {
        body: payload.body || '',
        icon: payload.icon || '/icon-192.png',
        badge: payload.badge || '/icon-badge.png',
        tag: 'sba-' + (payload.severity || 'info'),
        data: { url: payload.url || '/notifications' },
        vibrate: [200, 100, 200],
        requireInteraction: payload.severity === 'error',
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

// Click handler — opens/focuses the relevant page
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    const targetUrl = event.notification.data?.url || '/notifications';

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            // Focus existing window if open
            for (const client of clientList) {
                if (client.url.includes(targetUrl) && 'focus' in client) {
                    return client.focus();
                }
            }
            // Otherwise open a new window
            return self.clients.openWindow(targetUrl);
        })
    );
});
