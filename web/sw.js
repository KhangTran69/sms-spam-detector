/* PH SMS Scam Detector service worker — offline static shell.
 *
 * Privacy rules baked into this file:
 * - Only GET requests for the static shell (/, /static/*, /manifest.webmanifest)
 *   are ever cached.
 * - POST requests (message analysis, feedback) are never intercepted or cached,
 *   so SMS text never reaches the cache.
 * - /model-info, /health, /ready are always fetched from the network so the UI
 *   shows the deployed model's thresholds, never a stale copy.
 */
"use strict";

const CACHE_NAME = "smsd-shell-v3";
const SHELL_ASSETS = [
  "/",
  "/static/styles.css?v=ui3-20261020",
  "/static/app.js?v=ui3-20261020",
  "/manifest.webmanifest",
];
const NEVER_CACHE_PATHS = ["/analyze", "/analyze/batch", "/predict", "/feedback", "/model-info", "/health", "/ready"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      // Add assets individually so one failure does not block installation.
      await Promise.allSettled(SHELL_ASSETS.map((asset) => cache.add(asset)));
    }),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
    ),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return; // never touch POST bodies (messages)
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (NEVER_CACHE_PATHS.some((path) => url.pathname === path || url.pathname.startsWith(`${path}/`))) return;
  if (url.pathname.startsWith("/docs") || url.pathname.startsWith("/openapi")) return;

  // Network-first with cache fallback: updates land on reload, shell survives offline.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok && (url.pathname === "/" || url.pathname.startsWith("/static"))) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() =>
        caches.match(request).then((cached) => cached || caches.match("/")),
      ),
  );
});
