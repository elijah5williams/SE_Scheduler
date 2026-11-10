/* Service worker for the installable app. Rendered by planner/pwa.py.

   - Pages always come from the network, so schedules are never stale. Pages are NOT
     saved on the phone, because they hold private schedule data.
   - With no connection, the app shows a friendly offline page instead of an error.
   - CSS, JavaScript and icons are cached so the app opens quickly. */
const VERSION = "{{ version|escapejs }}";
const CACHE = `athlete-planner-${VERSION}`;
const OFFLINE_URL = "/offline/";
const PRECACHE = [{% for url in precache %}"{{ url|escapejs }}"{% if not forloop.last %}, {% endif %}{% endfor %}];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    // Serve the saved copy right away and refresh it in the background.
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(request).then((cached) => {
          const network = fetch(request).then((response) => {
            if (response.ok) cache.put(request, response.clone());
            return response;
          });
          if (cached) {
            event.waitUntil(network.catch(() => undefined));
            return cached;
          }
          return network;
        })
      )
    );
  }
});
