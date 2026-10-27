// Keeps the app shell and place photos available offline / on repeat visits.
// API data is cached separately in IndexedDB (src/api/cache.ts); API requests are never cached here.
// Also shows web-push visit reminders (notifications/send_visit_reminders) and opens the ticket on click.
const SHELL = 'aa-shell-v3';
const IMAGES = 'aa-images-v1';
const MAX_IMAGES = 400;

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(['/', '/favicon.svg', '/manifest.webmanifest', '/icon-192.png'])));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => ![SHELL, IMAGES].includes(k)).map((k) => caches.delete(k)))),
  );
  self.clients.claim();
});

async function trimImages() {
  const cache = await caches.open(IMAGES);
  const keys = await cache.keys();
  for (const req of keys.slice(0, Math.max(0, keys.length - MAX_IMAGES))) await cache.delete(req);
}

function cacheFirst(request, cacheName) {
  return caches.match(request).then(
    (hit) =>
      hit ||
      fetch(request).then((res) => {
        if (res.ok || res.type === 'opaque') {
          const copy = res.clone();
          caches.open(cacheName).then((c) => c.put(request, copy)).then(() => cacheName === IMAGES && trimImages());
        }
        return res;
      }),
  );
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  // Place photos from Wikimedia: they never change at a given URL, so cache first.
  if (request.destination === 'image' && url.hostname.endsWith('wikimedia.org')) {
    event.respondWith(cacheFirst(request, IMAGES));
    return;
  }

  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/django-admin/')) return;

  if (request.mode === 'navigate') {
    // Network first for pages; fall back to the cached shell (SPA routes all serve index.html).
    event.respondWith(
      fetch(request)
        .then((res) => {
          const copy = res.clone();
          caches.open(SHELL).then((c) => c.put('/', copy));
          return res;
        })
        .catch(() => caches.match('/')),
    );
    return;
  }

  if (url.pathname.startsWith('/assets/')) event.respondWith(cacheFirst(request, SHELL)); // hashed build files
});

// ---------------------------------------------------------------- web push

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { body: event.data ? event.data.text() : '' };
  }
  const title = data.title || 'Ancient Antiquity';
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      tag: data.tag || undefined,
      data: { url: data.url || '/my-bookings' },
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin);
  if (target.origin !== self.location.origin) return; // only ever open our own pages
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if (new URL(w.url).origin === target.origin && 'focus' in w) {
          return w.focus().then((c) => (c && 'navigate' in c ? c.navigate(target.href) : c));
        }
      }
      return self.clients.openWindow(target.href);
    }),
  );
});
