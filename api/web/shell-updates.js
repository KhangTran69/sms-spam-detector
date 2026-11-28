/* ---------- Shell update discovery and user notification ----------
   The service worker activates with skipWaiting + clients.claim, so a
   redeploy silently takes over long-lived tabs. This module is the counterweight:
   it discovers updated shells (registration.update on focus/timer and the
   controllerchange event) and either reloads a hidden, idle tab automatically or
   shows a polite banner that never interrupts an in-flight analysis.

   Import-time safety: this module never touches the DOM or browser globals at
   module scope, so it can be unit-tested through a data: URL import. */
export const RELOAD_GUARD_PREFIX = "smsd_reloaded_for_";
export const UPDATE_CHECK_INTERVAL_MS = 15 * 60 * 1000;

/* Pure decision: hidden tabs with no in-flight requests reload themselves once
   per shell generation; anything else shows the banner instead. */
export function shouldAutoReload({ documentHidden, activeRequests = 0, reloadKey = "", hasReloadedBefore = false }) {
  if (!documentHidden) return false;
  if (activeRequests > 0) return false;
  if (!reloadKey) return false;
  return !hasReloadedBefore;
}

export function createShellUpdates({
  serviceWorker = (typeof navigator !== "undefined" && navigator.serviceWorker) || null,
  documentRef = (typeof document !== "undefined" && document) || null,
  sessionStorageRef = (typeof sessionStorage !== "undefined" && sessionStorage) || null,
  activeRequestCount = () => 0,
  translate,
  onReload = () => location.reload(),
  banner,
  reloadButton,
  updateIntervalMs = UPDATE_CHECK_INTERVAL_MS,
} = {}) {
  let hadController = Boolean(serviceWorker && serviceWorker.controller);
  let latestCacheName = "";
  let attached = false;
  let intervalId = null;
  let updateVisibilityHandler = null;
  let controllerChangeHandler = null;
  let messageHandler = null;
  let bannerShown = false;

  function reloadGuardKey() {
    return RELOAD_GUARD_PREFIX + (latestCacheName || "unknown");
  }

  function markReloaded() {
    try {
      sessionStorageRef.setItem(reloadGuardKey(), "1");
    } catch {
      /* Storage may be unavailable; the guard simply never suppresses reloads. */
    }
  }

  function hasReloadedBefore() {
    try {
      return sessionStorageRef.getItem(reloadGuardKey()) !== null;
    } catch {
      return false;
    }
  }

  function showBanner() {
    if (!banner || !reloadButton) return;
    banner.classList.remove("hidden");
    reloadButton.textContent = translate("update.reloadButton");
    bannerShown = true;
  }

  function handleShellChanged() {
    const decision = shouldAutoReload({
      documentHidden: documentRef.hidden === true,
      activeRequests: activeRequestCount(),
      reloadKey: latestCacheName,
      hasReloadedBefore: hasReloadedBefore(),
    });
    if (decision) {
      markReloaded();
      onReload();
      return;
    }
    showBanner();
  }

  function checkForUpdates() {
    if (!attached) return;
    try {
      const result = registrationRef && registrationRef.update();
      if (result && typeof result.catch === "function") result.catch(() => {});
    } catch {
      /* Discovery is best-effort; offline or failed checks keep the current shell. */
    }
  }

  let registrationRef = null;

  function attach(registration) {
    if (attached || !serviceWorker || !documentRef) return;
    attached = true;
    registrationRef = registration;
    controllerChangeHandler = () => {
      if (!hadController) {
        // First claim after a fresh page load is not an update.
        hadController = true;
        return;
      }
      handleShellChanged();
    };
    serviceWorker.addEventListener("controllerchange", controllerChangeHandler);
    messageHandler = (event) => {
      if (event.data && event.data.type === "shell-activated" && typeof event.data.cache === "string") {
        latestCacheName = event.data.cache;
      }
    };
    serviceWorker.addEventListener("message", messageHandler);
    updateVisibilityHandler = () => {
      if (!documentRef.hidden) checkForUpdates();
    };
    documentRef.addEventListener("visibilitychange", updateVisibilityHandler);
    intervalId = setInterval(checkForUpdates, updateIntervalMs);
    checkForUpdates();
  }

  function dispose() {
    if (!attached || !serviceWorker || !documentRef) return;
    attached = false;
    if (controllerChangeHandler) serviceWorker.removeEventListener("controllerchange", controllerChangeHandler);
    if (messageHandler) serviceWorker.removeEventListener("message", messageHandler);
    if (updateVisibilityHandler) documentRef.removeEventListener("visibilitychange", updateVisibilityHandler);
    if (intervalId) clearInterval(intervalId);
    registrationRef = null;
  }

  function applyReload() {
    markReloaded();
    onReload();
  }

  if (banner && reloadButton) {
    banner.classList.add("hidden");
    reloadButton.addEventListener("click", applyReload);
  }

  return Object.freeze({
    attach,
    dispose,
    showBanner,
    applyReload,
    snapshot: () => ({ attached, bannerShown, latestCacheName }),
  });
}
