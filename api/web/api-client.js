/* ---------- API access ----------
   Requests stay in memory; this module never persists request or response data. */
export const API = Object.freeze({
  modelInfo: "/model-info",
  ready: "/ready",
  analyze: "/analyze",
  analyzeBatch: "/analyze/batch",
  feedback: "/feedback",
});

export function createApiClient({ translate, setApiAvailability, setModelReadiness, hideOfflineBanner, showOfflineBanner }) {
  const timeoutMs = 20000;
  let requestSequence = 0;

  function errorMessageFromResponse(data, response) {
    const error = data && typeof data.error === "object" && data.error ? data.error : null;
    if (error && typeof error.message === "string" && error.message.trim()) return error.message.trim();
    const detail = data ? data.detail : null;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item && typeof item.msg === "string" ? item.msg : null))
        .filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
    if (response.status === 503) return translate("error.model503");
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
      response = await fetch(path, { ...options, signal: controller.signal });
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
      if (failure && (failure.status === 503 || failure.code === "model_unavailable")) {
        setModelReadiness(false, sequence);
      }
      throw failure;
    } finally {
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
