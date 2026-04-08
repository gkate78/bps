/* BPS PWA service worker: cache shell assets only (no API data). */
const SW_VERSION = "bps-sw-v1";
const SHELL_ASSETS = [
  "/auth/signin",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/favicon.svg",
  "/manifest.webmanifest",
  "https://cdn.datatables.net/2.0.8/css/dataTables.dataTables.min.css",
  "https://cdn.datatables.net/2.0.8/js/dataTables.min.js",
  "https://code.jquery.com/jquery-3.7.1.min.js"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SW_VERSION).then((cache) => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== SW_VERSION)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Never cache auth/admin API calls or non-GET requests.
  if (req.method !== "GET" || url.pathname.startsWith("/api/")) {
    return;
  }

  // Cache-first for static assets and CDN shell dependencies.
  const isStatic =
    url.pathname.startsWith("/static/") ||
    url.pathname === "/manifest.webmanifest" ||
    url.pathname === "/favicon.ico" ||
    url.origin.includes("cdn.datatables.net") ||
    url.origin.includes("code.jquery.com");

  if (isStatic) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((response) => {
          const cloned = response.clone();
          caches.open(SW_VERSION).then((cache) => cache.put(req, cloned));
          return response;
        });
      })
    );
    return;
  }

  // Network-first for HTML pages to keep app state fresh.
  event.respondWith(
    fetch(req).catch(() => caches.match(req).then((cached) => cached || caches.match("/auth/signin")))
  );
});
