/* UI state for browser connectivity, API reachability, and model readiness. */
export function createConnectionStatus({ element, translate, browserOnline, offlineBanner }) {
  let apiAvailability = null;
  let modelReadiness = null;
  let apiSequence = 0;
  let modelSequence = 0;

  function showOfflineBanner() {
    offlineBanner.classList.remove("hidden");
  }

  function hideOfflineBanner() {
    offlineBanner.classList.add("hidden");
  }

  function render() {
    const api = element("api-status");
    const model = element("readiness-status");
    const browser = element("browser-status");
    const online = browserOnline();
    browser.textContent = typeof online === "boolean"
      ? translate(online ? "service.browserOnline" : "service.browserOffline")
      : translate("service.modelUnknown");
    api.textContent = apiAvailability === null ? translate("service.checking")
      : apiAvailability === true ? translate("service.apiAvailable")
        : apiAvailability === "timeout" ? translate("service.apiSlow") : translate("service.apiUnavailable");
    model.textContent = modelReadiness === null ? translate("service.checking")
      : modelReadiness === true ? translate("service.modelReady")
        : modelReadiness === false ? translate("service.modelUnavailable") : translate("service.modelUnknown");
    api.dataset.state = apiAvailability === true ? "ready"
      : apiAvailability === false ? "error" : apiAvailability === "timeout" ? "warning" : "checking";
    model.dataset.state = modelReadiness === true ? "ready" : modelReadiness === false ? "error" : "checking";
  }

  function setApiAvailability(value, sequence) {
    if (sequence < apiSequence) return false;
    apiSequence = sequence;
    apiAvailability = value;
    render();
    return true;
  }

  function setModelReadiness(value, sequence) {
    if (sequence < modelSequence) return false;
    modelSequence = sequence;
    modelReadiness = value;
    render();
    return true;
  }

  function reset() {
    apiAvailability = null;
    modelReadiness = null;
    render();
  }

  return Object.freeze({
    render,
    reset,
    setApiAvailability,
    setModelReadiness,
    showOfflineBanner,
    hideOfflineBanner,
    snapshot: () => ({ api: apiAvailability, model: modelReadiness }),
  });
}
