/* PH SMS Scam Detector service worker — atomic, static-only offline shell.
 * Submitted SMS messages and API responses are never written to Cache Storage.
 */
"use strict";

const CACHE_NAME = "smsd-shell-v31";
const SHELL_ASSETS = [
  "/",
  "/static/tokens.css?v=ui23-meter-clip-20261128",
  "/static/styles.css?v=ui23-meter-clip-20261128",
  "/static/app.js?v=ui23-meter-clip-20261128",
  "/static/shell-updates.js?v=ui23-meter-clip-20261128",
  "/static/fonts/BricolageGrotesque-var-latin.woff2",
  "/static/fonts/SourceSerif4-var-latin.woff2",
  "/static/fonts/SourceSerif4-Italic-var-latin.woff2",
  "/static/theme-init.js?v=theme-v1",
  "/static/api-client.js?v=ui23-meter-clip-20261128",
  "/static/i18n.js?v=ui23-meter-clip-20261128",
  "/static/privacy-preview.js?v=ui23-meter-clip-20261128",
  "/static/history-store.js?v=ui23-meter-clip-20261128",
  "/static/connection-status.js?v=ui23-meter-clip-20261128",
  "/static/result-format.js?v=ui23-meter-clip-20261128",
  "/static/demo-examples.js?v=ui23-meter-clip-20261128",
  "/static/donate.js?v=donate-v9",
  "/static/donate.css?v=donate-v6",
  "/manifest.webmanifest",
];
const SHELL_REQUESTS = new Set(SHELL_ASSETS.map((asset) => {
  const url = new URL(asset, self.location.origin);
  return `${url.pathname}${url.search}`;
}));
const NEVER_CACHE_PATHS = [
  "/analyze",
  "/analyze/batch",
  "/predict",
  "/feedback",
  "/donate",
  "/privacy-notice",
  "/model-info",
  "/health",
  "/ready",
  "/metrics",
  "/metrics/distribution",
  "/metrics/operations",
  "/v1/analyze",
  "/v1/analyze/batch",
  "/v1/predict",
  "/v1/feedback",
  "/v1/model-info",
  "/v1/health",
  "/v1/ready",
  "/v1/metrics",
  "/v1/metrics/distribution",
  "/v1/metrics/operations",
];

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
    // Tell every open tab which shell generation is active so shell-updates.js
    // can name the reload guard key and decide between banner and auto-reload.
    const clients = await self.clients.matchAll({ includeUncontrolled: true });
    for (const client of clients) {
      client.postMessage({ type: "shell-activated", cache: CACHE_NAME });
    }
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
