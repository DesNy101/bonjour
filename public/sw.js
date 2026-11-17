/* Bonjour Bakery service worker.
   - Caches ONLY the static application shell (HTML/CSS/JS/images).
   - Never caches /api/* responses, uploads, or anything authenticated: private data is not stored offline.
   - When offline, API calls fail honestly (the UI shows an offline banner and refuses to submit). */
const VERSION = "bonjour-shell-v1";
const SHELL = ["/", "/styles.css", "/app.js", "/js/core.js", "/js/charts.js", "/js/store.js", "/js/staff.js", "/js/pages.js", "/js/pages2.js", "/js/driver.js",
  "/manifest.webmanifest", "/assets/bonjour-logo-sm.png", "/assets/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/uploads/") || url.pathname === "/health") return; // network only
  // network-first for the shell so updates apply, fall back to cache when offline
  e.respondWith(
    fetch(req).then((res) => {
      if (res.ok && (SHELL.includes(url.pathname) || url.pathname.startsWith("/assets/"))) {
        const copy = res.clone();
        caches.open(VERSION).then((c) => c.put(req, copy));
      }
      return res;
    }).catch(() => caches.match(req).then((r) => r || (req.mode === "navigate" ? caches.match("/") : Response.error())))
  );
});
