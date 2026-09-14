// Service worker. Makes the app usable with no signal, which is the condition
// it is actually meant to be used in.
//
// CACHE is stamped with a hash of the built page at deploy time, so a new
// version invalidates the old cache instead of serving stale arithmetic. That
// matters more here than on most pages: a cached bet ramp from two rule changes
// ago is worse than no bet ramp.

const CACHE = "ramp-ruin-__BUILD__";

// Everything the app needs from this origin. The page carries the whole engine
// inline, so this list is short by construction.
const CORE = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/apple-touch-icon.png",
  "./icons/favicon-32.png",
];

// Google Fonts. Best-effort: if these fail the install still succeeds and the
// page falls back to the stacks declared alongside every font-family.
const FONT_HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(CORE);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names.filter((n) => n.startsWith("ramp-ruin-") && n !== CACHE)
        .map((n) => caches.delete(n)),
    );
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  // A navigation offline must still open the app, whatever path was asked for.
  if (request.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(request);
        const cache = await caches.open(CACHE);
        cache.put("./index.html", fresh.clone());
        return fresh;
      } catch {
        const cached = await caches.match("./index.html");
        return cached || Response.error();
      }
    })());
    return;
  }

  if (FONT_HOSTS.includes(url.hostname)) {
    // Font URLs are immutable, so cache-first with a background fill.
    event.respondWith((async () => {
      const cached = await caches.match(request);
      if (cached) return cached;
      try {
        const fresh = await fetch(request);
        const cache = await caches.open(CACHE);
        cache.put(request, fresh.clone());
        return fresh;
      } catch {
        return cached || Response.error();
      }
    })());
    return;
  }

  if (url.origin !== self.location.origin) return;

  event.respondWith((async () => {
    const cached = await caches.match(request);
    if (cached) return cached;
    try {
      return await fetch(request);
    } catch {
      return Response.error();
    }
  })());
});
