/* ---------- API access ----------
   Requests stay in memory; this module never persists request or response data. */
export const API = Object.freeze({
  modelInfo: "/model-info",
  ready: "/ready",
  analyze: "/analyze",
  analyzeBatch: "/analyze/batch",
  feedback: "/feedback",
});

/* In-flight request count across every client instance. The shell-update
   module reads it so an auto-reload never interrupts an analysis. */
let activeRequests = 0;
export function activeRequestCount() {
  return activeRequests;
}

export function createApiClient({
  translate,
  setApiAvailability,
  setModelReadiness,
  hideOfflineBanner,
  showOfflineBanner,
  onStaleShell = null,
  timeoutMs = 20000,
}) {
  let requestSequence = 0;

  /* Stale-shell guard: a response whose shape this shell does not recognize
     means the deployed backend is newer than the running page. The caller
     surfaces the shell-update banner; the error still carries staleShell so
     describeError can produce the right copy. */
  function assertKnownShape(path, data) {
    const known = data && typeof data === "object" && typeof data.model_version === "string";
    if (path === API.modelInfo) {
      if (!known) throwStaleShell();
      return;
    }
    if (path === API.analyze) {
      if (!known || typeof data.risk_band !== "string") throwStaleShell();
      return;
    }
    if (path === API.analyzeBatch) {
      const first = known && Array.isArray(data.results) ? data.results[0] : null;
      if (!first || typeof first.risk_band !== "string" || typeof first.model_version !== "string") throwStaleShell();
    }
  }

  function throwStaleShell() {
    if (typeof onStaleShell === "function") {
      try {
        onStaleShell();
      } catch {
        /* Notification is best-effort. */
      }
    }
    const failure = new Error(translate("update.staleShellError"));
    failure.staleShell = true;
    throw failure;
  }

  function errorMessageFromResponse(data, response) {
    const error = data && typeof data.error === "object" && data.error ? data.error : null;
    if (error && error.code === "rate_limiter_unavailable") return translate("error.protection503");
    if (error && error.code === "service_busy") return translate("error.busy503");
    if (response.status === 429) return translate("error.rate429");
    if (response.status === 408) return translate("error.upload408");
    if (error && typeof error.message === "string" && error.message.trim()) return error.message.trim();
    const detail = data ? data.detail : null;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item && typeof item.msg === "string" ? item.msg : null))
        .filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
    if (response.status === 503) return translate("error.service503");
    return translate("error.http", { status: response.status });
  }

  async function parseResponse(response) {
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      data = null;
    }
    if (!response.ok) {
      const error = data && typeof data.error === "object" && data.error ? data.error : null;
      const failure = new Error(errorMessageFromResponse(data, response));
      failure.status = response.status;
      failure.code = error && typeof error.code === "string" ? error.code : null;
      throw failure;
    }
    return data;
  }

  async function requestJson(path, options = {}) {
    const sequence = ++requestSequence;
    activeRequests += 1;
    const controller = new AbortController();
    const externalSignal = options.signal;
    let callerAborted = false;
    let timedOut = false;
    const abortFromCaller = () => {
      callerAborted = true;
      controller.abort();
    };
    if (externalSignal) {
      if (externalSignal.aborted) abortFromCaller();
      else externalSignal.addEventListener("abort", abortFromCaller, { once: true });
    }
    const timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    let response;
    try {
      response = await fetch(path, { ...options, cache: "no-store", signal: controller.signal });
    } catch (throwable) {
      clearTimeout(timeoutId);
      if (externalSignal) externalSignal.removeEventListener("abort", abortFromCaller);
      if (callerAborted || (throwable && throwable.name === "AbortError" && !timedOut)) {
        const aborted = new Error("Request aborted");
        aborted.aborted = true;
        throw aborted;
      }
      if (timedOut) {
        const failure = new Error(translate("error.timeout"));
        failure.timeout = true;
        if (setApiAvailability("timeout", sequence)) setModelReadiness("unknown", sequence);
        throw failure;
      }
      const failure = new Error(translate("error.reach"));
      failure.apiUnavailable = true;
      if (setApiAvailability(false, sequence)) {
        setModelReadiness("unknown", sequence);
        if (window.navigator.onLine === false) showOfflineBanner();
      }
      throw failure;
    }
    if (setApiAvailability(true, sequence)) hideOfflineBanner();
    try {
      const data = await parseResponse(response);
      assertKnownShape(path, data);
      if (path === API.ready) setModelReadiness(true, sequence);
      return data;
    } catch (failure) {
      if (callerAborted || (failure && failure.name === "AbortError" && !timedOut)) {
        const aborted = new Error("Request aborted");
        aborted.aborted = true;
        throw aborted;
      }
      if (timedOut) {
        const timeoutFailure = new Error(translate("error.timeout"));
        timeoutFailure.timeout = true;
        if (setApiAvailability("timeout", sequence)) setModelReadiness("unknown", sequence);
        throw timeoutFailure;
      }
      if (failure && failure.code === "model_unavailable") {
        setModelReadiness(false, sequence);
      } else if (failure && failure.status === 503) {
        setModelReadiness("unknown", sequence);
      }
      throw failure;
    } finally {
      activeRequests = Math.max(0, activeRequests - 1);
      clearTimeout(timeoutId);
      if (externalSignal) externalSignal.removeEventListener("abort", abortFromCaller);
    }
  }

  function postJson(path, body, { signal } = {}) {
    return requestJson(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  }

  return { requestJson, postJson };
}
