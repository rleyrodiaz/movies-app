// Service worker mínimo — solo existe para que el sitio califique como instalable.
// No hace caching offline; cada request va directo a la red.

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
