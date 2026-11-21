/* Universal Converter: service worker dell'app installabile (PWA).
   Serve solo a ricevere i file condivisi dal menu "Condividi" del sistema (Web Share Target): il sistema manda
   un POST a ./share con i file; qui li mettiamo da parte nella cache "uc-share" e apriamo la pagina su #shared,
   che li prende e li aggiunge alla lista. Nient'altro viene messo in cache: la pagina e l'API vanno sempre al server. */
"use strict";
const SHARE_CACHE = "uc-share";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method === "POST" && url.pathname === new URL("share", self.registration.scope).pathname) {
    e.respondWith(receiveShare(e.request));
  }
});

async function receiveShare(request) {
  const back = new URL("./#shared", self.registration.scope).href;
  try {
    const form = await request.formData();
    const cache = await caches.open(SHARE_CACHE);
    for (const key of await cache.keys()) await cache.delete(key);  // condivisioni vecchie mai lette
    let i = 0;
    for (const f of form.getAll("files")) {
      if (!(f instanceof File) || !f.size) continue;
      await cache.put(new URL(`shared/${i++}`, self.registration.scope).href,
        new Response(f, {headers: {"Content-Type": f.type || "application/octet-stream", "X-Name": encodeURIComponent(f.name || "file")}}));
    }
    const info = {title: form.get("title") || "", text: form.get("text") || "", url: form.get("url") || ""};
    if (info.text || info.url) await cache.put(new URL("shared/info", self.registration.scope).href, new Response(JSON.stringify(info)));
  } catch (err) { /* condivisione illeggibile: si apre comunque la pagina */ }
  return Response.redirect(back, 303);
}
