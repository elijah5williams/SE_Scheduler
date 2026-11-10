/* Service worker for the installed app. Rendered by planner/pwa.py.

   - Pages always come from the network, so schedules are never stale. Whole pages are
     NOT saved on the phone.
   - The installed app asks for /app/offline-data.json (the next two weeks of the user's own
     schedule). That one response is kept in a private cache so the offline page can show it
     with no signal. It's deleted when the user logs out.
   - CSS, JavaScript and icons are cached so the app opens quickly.
   - Shows phone notifications sent by the server, and opens the right page when tapped. */
const VERSION = "{{ version|escapejs }}";
const CACHE = `athlete-planner-${VERSION}`;
const PRIVATE_CACHE = "athlete-planner-private";
const OFFLINE_URL = "/offline/";
const OFFLINE_DATA_URL = "/app/offline-data.json";
const ICON = "{{ icon|escapejs }}";
const BADGE = "{{ badge|escapejs }}";
const PRECACHE = [{% for url in precache %}"{{ url|escapejs }}"{% if not forloop.last %}, {% endif %}{% endfor %}];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key !== CACHE && key !== PRIVATE_CACHE).map((key) => caches.delete(key))
      ))
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

  if (url.pathname === OFFLINE_DATA_URL) {
    event.respondWith(
      fetch(request).then((response) => {
        // Only keep it when the installed app asked (header set in app-mode.js).
        if (response.ok && request.headers.get("X-App-Save") === "1") {
          const copy = response.clone();
          event.waitUntil(caches.open(PRIVATE_CACHE).then((cache) => cache.put(OFFLINE_DATA_URL, copy)));
        }
        return response;
      }).catch(() => caches.open(PRIVATE_CACHE).then((cache) => cache.match(OFFLINE_DATA_URL))
        .then((saved) => saved || Response.error()))
    );
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

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  const title = data.title || "Athlete Planner";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: ICON,
    badge: BADGE,
    tag: data.tag || undefined,
    renotify: Boolean(data.tag),
    data: { url: data.url || "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data && event.notification.data.url || "/", self.location.origin);
  if (target.origin !== self.location.origin) return;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin && "focus" in client) {
          return client.navigate(target.href).then((c) => (c || client).focus());
        }
      }
      return self.clients.openWindow(target.href);
    })
  );
});
