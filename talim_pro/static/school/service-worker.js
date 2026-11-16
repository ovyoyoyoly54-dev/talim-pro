const CACHE_NAME = "talim-pro-shell-v2";
const OFFLINE_PAGE = "/offline/";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.add(OFFLINE_PAGE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_PAGE)));
    return;
  }

  // Only public static assets are eligible for cache. Authenticated HTML stays network-only.
  // Stale-while-revalidate: keshdagi nusxa darhol beriladi, fonda yangisi olinadi —
  // shu sababli yangilangan CSS/JS keyingi ochilishda albatta ko'rinadi.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(caches.open(CACHE_NAME).then((cache) => cache.match(request).then((cached) => {
      const fresh = fetch(request).then((response) => {
        if (response.ok) cache.put(request, response.clone());
        return response;
      });
      if (cached) {
        event.waitUntil(fresh.catch(() => {}));
        return cached;
      }
      return fresh;
    })));
  }
});

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  const title = data.title || "TA'LIM PRO";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/static/school/icon-192.png",
    data: { url: typeof data.url === "string" && data.url.startsWith("/") ? data.url : "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const client of list) {
      if (new URL(client.url).pathname === target && "focus" in client) return client.focus();
    }
    return self.clients.openWindow(target);
  }));
});
