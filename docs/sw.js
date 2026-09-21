// Service worker: de app werkt offline (laatst geziene schermen) en toont meldingen.
const CACHE = "pokedeals-v2-1";
const CORE = ["./", "index.html", "style.css", "config.js", "manifest.webmanifest", "icons/icon-192.png",
  "js/main.js", "js/api.js", "js/ui.js", "js/model.js", "js/prefs.js", "js/push.js", "js/chart.js", "js/components.js",
  "js/ocr.js", "js/add.js", "js/scan.js", "js/views/home.js", "js/views/search.js", "js/views/collection.js",
  "js/views/detail.js", "js/views/settings.js", "js/views/track.js", "js/views/login.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CORE).catch(() => {})).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

// Eigen bestanden: eerst het netwerk (zodat updates direct doorkomen), anders de opgeslagen versie.
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
    return res;
  }).catch(() => caches.match(req).then((r) => r || caches.match("index.html"))));
});

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || "Pokédeals", {
    body: d.body || "", tag: d.tag, icon: "icons/icon-192.png", badge: "icons/icon-192.png", data: { url: d.url || "./" } }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || "./", self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((cs) => {
    const c = cs[0];
    if (c) { c.focus(); c.postMessage({ type: "nav", url }); return; }
    return self.clients.openWindow(url);
  }));
});
