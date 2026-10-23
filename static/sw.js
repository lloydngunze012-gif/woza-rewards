const CACHE = "woza-v22";
const PRECACHE = [
  "/",
  "/static/manifest.json",
  "/static/icon.svg",
  "/static/woza-card.css",
  "/static/woza-card.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return;

  if (url.pathname === "/" || url.pathname.endsWith(".html")) {
    e.respondWith(staleWhileRevalidate(e.request));
    return;
  }

  e.respondWith(
    caches.match(e.request).then((cached) => {
      const net = fetch(e.request)
        .then((r) => {
          if (r.ok) {
            const copy = r.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy));
          }
          return r;
        })
        .catch(() => cached);
      return cached || net;
    })
  );
});

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((r) => {
      if (r.ok) cache.put(request, r.clone());
      return r;
    })
    .catch(() => null);
  if (cached) {
    network.catch(() => {});
    return cached;
  }
  const fresh = await network;
  return fresh || new Response("Offline", { status: 503, statusText: "Offline" });
}
