/* Lectra — service worker
   Cache-first for static assets, network-first for pages & API. */

var CACHE_NAME = 'lectra-v3';
var APP_SHELL = [
  '/static/css/variables.css',
  '/static/css/style.css',
  '/static/css/mobile.css',
  '/static/js/app.js',
  '/static/js/mobile.js',
  '/manifest.json',
  '/static/images/icon-192.png',
  '/static/images/apple-touch-icon.png'
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(APP_SHELL);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (key) {
          return key !== CACHE_NAME;
        }).map(function (key) {
          return caches.delete(key);
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function (event) {
  var request = event.request;

  if (request.method !== 'GET') {
    return;
  }

  var url = new URL(request.url);

  if (url.origin !== location.origin) {
    return;
  }

  // API calls and HTML pages: network first, fall back to cache.
  if (url.pathname.startsWith('/api/') || request.headers.get('accept').indexOf('text/html') !== -1) {
    event.respondWith(
      fetch(request)
        .then(function (response) {
          var copy = response.clone();
          caches.open(CACHE_NAME).then(function (cache) {
            cache.put(request, copy);
          });
          return response;
        })
        .catch(function () {
          return caches.match(request).then(function (cached) {
            return cached || caches.match('/dashboard');
          });
        })
    );
    return;
  }

  // Static assets: cache first.
  event.respondWith(
    caches.match(request).then(function (cached) {
      if (cached) {
        return cached;
      }
      return fetch(request).then(function (response) {
        var copy = response.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(request, copy);
        });
        return response;
      });
    })
  );
});

self.addEventListener('push', function (event) {
  var payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (error) { payload = {}; }
  event.waitUntil(self.registration.showNotification(payload.title || 'Lectra', {
    body: payload.body || 'You have a new reminder.',
    icon: '/static/images/icon-192.png',
    badge: '/static/images/icon-192.png',
    tag: payload.tag || 'lectra-reminder',
    data: { url: payload.url || '/dashboard' }
  }));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});

self.addEventListener('sync', function (event) {
  if (event.tag !== 'sync-schedules') {
    return;
  }
  event.waitUntil(
    self.clients.matchAll().then(function (clients) {
      clients.forEach(function (client) {
        client.postMessage({ type: 'flush-queue' });
      });
    })
  );
});
