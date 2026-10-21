/* PH SMS Scam Detector service worker — atomic, static-only offline shell.
 * SMS messages and API responses are never written to Cache Storage.
 */
"use strict";

const CACHE_NAME = "smsd-shell-v7";
const SHELL_ASSETS = [
  "/",
  "/static/styles.css?v=ui7-spam-score-20261021",
  "/static/app.js?v=ui7-spam-score-20261021",
  "/manifest.webmanifest",
];
const SHELL_PATHS = new Set(["/", "/static/styles.css", "/static/app.js", "/manifest.webmanifest"]);
const NEVER_CACHE_PATHS = ["/analyze", "/analyze/batch", "/predict", "/feedback", "/model-info", "/health", "/ready"];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(CACHE_NAME);
      await Promise.all(SHELL_ASSETS.map((asset) => cache.add(asset)));
      await self.skipWaiting();
    } catch (error) {
      // Do not activate a partial shell; retain the previously active worker.
      await caches.delete(CACHE_NAME);
      throw error;
    }
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    await self.clients.claim();
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith("smsd-shell-") && key !== CACHE_NAME)
      .map((key) => caches.delete(key)));
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (NEVER_CACHE_PATHS.some((path) => url.pathname === path || url.pathname.startsWith(`${path}/`))) return;
  if (!SHELL_PATHS.has(url.pathname)) return;

  // Network-first delivers matched HTML/CSS/JS versions together; a complete
  // installed shell remains available when offline or an update is interrupted.
  event.respondWith((async () => {
    try {
      const response = await fetch(request);
      if (response && response.ok) {
        const cache = await caches.open(CACHE_NAME);
        await cache.put(request, response.clone());
      }
      return response;
    } catch {
      const cached = await caches.match(request);
      if (cached) return cached;
      return new Response("Offline and this app asset is not cached.", {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    }
  })());
});
