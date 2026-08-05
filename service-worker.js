importScripts('https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.sw.js');

var CACHE_NAME = 'lectra-v6';
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

var OFFLINE_PAGE = '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width, initial-scale=1">' +
  '<title>Lectra — offline</title></head>' +
  '<body style="font-family:sans-serif;padding:2rem;text-align:center">' +
  '<h1>You&rsquo;re offline</h1>' +
  '<p>Lectra needs a connection to load your roster and account. Reconnect and try again.</p>' +
  '</body></html>';

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return Promise.all(
        APP_SHELL.map(function (url) {
          return cache.add(url)['catch'](function () {});
        })
      );
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

  var accept = request.headers.get('accept') || '';
  var isHtml = accept.indexOf('text/html') !== -1;

  // HTML pages and API responses are personal to the signed-in user, so they
  // are always fetched from the network and never cached. Serving a cached
  // page could show one account's dashboard/roster to a different account
  // (e.g. the admin's page being replayed after logging in as a lecturer).
  if (isHtml || url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)['catch'](function () {
        if (isHtml) {
          return new Response(OFFLINE_PAGE, {
            headers: { 'Content-Type': 'text/html; charset=utf-8' }
          });
        }
        return new Response('{"data":[]}', {
          headers: { 'Content-Type': 'application/json' }
        });
      })
    );
    return;
  }

  // Static assets: cache first for speed and offline app-shell rendering.
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
