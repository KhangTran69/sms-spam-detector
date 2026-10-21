/* PH SMS Scam Detector service worker — atomic, static-only offline shell.
 * SMS messages and API responses are never written to Cache Storage.
 */
"use strict";

const CACHE_NAME = "smsd-shell-v10";
const SHELL_ASSETS = [
  "/",
  "/static/styles.css?v=ui10-safety-guidance-20261021",
  "/static/app.js?v=ui10-safety-guidance-20261021",
  "/manifest.webmanifest",
];
const SHELL_REQUESTS = new Set(SHELL_ASSETS.map((asset) => {
  const url = new URL(asset, self.location.origin);
  return `${url.pathname}${url.search}`;
}));
const NEVER_CACHE_PATHS = ["/analyze", "/analyze/batch", "/predict", "/feedback", "/model-info", "/health", "/ready"];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(CACHE_NAME);
      // Wait for every write to settle before deleting a failed candidate cache.
      // Promise.all rejects early while other add() calls can still be running.
      const results = await Promise.allSettled(SHELL_ASSETS.map((asset) => cache.add(asset)));
      if (results.some((result) => result.status === "rejected")) {
        throw new Error("A static shell asset could not be cached.");
      }
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
  if (!SHELL_REQUESTS.has(`${url.pathname}${url.search}`)) return;

  // Serve the immutable release installed by this worker. Do not cache runtime
  // network responses: an online release change must not mix files in this shell.
  event.respondWith((async () => {
    const cached = await caches.match(request, { cacheName: CACHE_NAME });
    if (cached) return cached;
    try {
      return await fetch(request);
    } catch {
      return new Response("Offline and this app asset is not cached.", {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    }
  })());
});
