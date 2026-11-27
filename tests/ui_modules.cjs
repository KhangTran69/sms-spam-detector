const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const sourcePath = path.resolve(__dirname, '../api/web/history-store.js');
  const source = fs.readFileSync(sourcePath, 'utf8');
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
  const { createHistoryStore } = await import(moduleUrl);
  const connectionSource = fs.readFileSync(path.resolve(__dirname, '../api/web/connection-status.js'), 'utf8');
  const connectionUrl = `data:text/javascript;base64,${Buffer.from(connectionSource).toString('base64')}`;
  const { createConnectionStatus } = await import(connectionUrl);
  const resultSource = fs.readFileSync(path.resolve(__dirname, '../api/web/result-format.js'), 'utf8');
  const resultUrl = `data:text/javascript;base64,${Buffer.from(resultSource).toString('base64')}`;
  const { createResultFormatting, normalizeModelInfo } = await import(resultUrl);
  const apiSource = fs.readFileSync(path.resolve(__dirname, '../api/web/api-client.js'), 'utf8');
  const apiUrl = `data:text/javascript;base64,${Buffer.from(apiSource).toString('base64')}`;
  const { createApiClient, activeRequestCount } = await import(apiUrl);
  const shellSource = fs.readFileSync(path.resolve(__dirname, '../api/web/shell-updates.js'), 'utf8');
  const shellUrl = `data:text/javascript;base64,${Buffer.from(shellSource).toString('base64')}`;
  const { shouldAutoReload, createShellUpdates, RELOAD_GUARD_PREFIX } = await import(shellUrl);
  const donationSource = fs.readFileSync(path.resolve(__dirname, '../api/web/donate.js'), 'utf8');
  const donationUrl = `data:text/javascript;base64,${Buffer.from(donationSource).toString('base64')}`;
  const { buildDonationPayload, createDonationForm, formatPiiFinding, PRIVACY_NOTICE_VERSION } = await import(donationUrl);
  assert.equal(PRIVACY_NOTICE_VERSION, '2026-11-01-v4');
  assert.deepEqual(buildDonationPayload({
    message: 'Synthetic local fixture', labelHint: 'spam', language: 'tl', consent: true,
    authorizedToShare: true,
  }), {
    message: 'Synthetic local fixture', label_hint: 'spam', language: 'tl', consent: true,
    authorized_to_share: true, model_research_consent: false,
    notice_version: '2026-11-01-v4',
  });
  assert.throws(() => buildDonationPayload({ message: 'Fixture', consent: false }), /Consent is required/);
  assert.throws(() => buildDonationPayload({ message: 'Fixture', consent: true }), /authorized to share/);
  assert.equal(formatPiiFinding({ category: 'phone', value: '0917-123-4567' }), 'phone: 0917-123-4567');

  function donationDocument() {
    const selectors = [
      '#donation-form', '#donation-message', '#donation-label-hint', '#donation-language',
      '#donation-consent', '#donation-authorized', '#donation-research-consent',
      '#donation-submit', '#donation-status', '#donation-pii-findings',
      '#donation-withdrawal-form', '#donation-withdrawal-id', '#donation-withdraw',
    ];
    const nodes = Object.fromEntries(selectors.map((selector) => [selector, {
      value: selector === '#donation-message' ? 'Synthetic local fixture' : '',
      checked: selector === '#donation-consent' || selector === '#donation-authorized',
      disabled: false,
      hidden: selector === '#donation-pii-findings',
      dataset: {},
      handlers: {},
      addEventListener(type, callback) { this.handlers[type] = callback; },
      replaceChildren() {},
      append() {},
      reportValidity() { return true; },
    }]));
    return {
      nodes,
      querySelector(selector) { return nodes[selector] || null; },
      createElement() { return { textContent: '' }; },
    };
  }

  async function submit(element) {
    await element.handlers.submit({ preventDefault() {} });
  }

  const stalledSubmitDocument = donationDocument();
  let stalledSubmitRequests = 0;
  createDonationForm({
    documentRef: stalledSubmitDocument,
    timeoutMs: 5,
    fetchImpl: (_url, { signal }) => {
      stalledSubmitRequests += 1;
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      }, { once: true }));
    },
  });
  stalledSubmitDocument.nodes['#donation-withdrawal-id'].value = 'b'.repeat(32);
  await submit(stalledSubmitDocument.nodes['#donation-form']);
  assert.equal(stalledSubmitRequests, 1, 'a timed-out donation request is never automatically resent');
  assert.equal(stalledSubmitDocument.nodes['#donation-submit'].disabled, false,
    'submission control is restored after timeout');
  assert.match(stalledSubmitDocument.nodes['#donation-status'].textContent, /outcome may be uncertain/i,
    'timeout explains that server-side acceptance may have happened');
  assert.equal(stalledSubmitDocument.nodes['#donation-message'].value, 'Synthetic local fixture',
    'the user retains control of text after an uncertain timeout');
  assert.equal(stalledSubmitDocument.nodes['#donation-withdrawal-id'].value, '',
    'a stale withdrawal ID is cleared when a new valid submission begins');

  const stalledWithdrawalDocument = donationDocument();
  let stalledWithdrawalRequests = 0;
  createDonationForm({
    documentRef: stalledWithdrawalDocument,
    timeoutMs: 5,
    fetchImpl: (url, { method, body, signal }) => {
      stalledWithdrawalRequests += 1;
      if (url === '/donate' && method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ record_id: 'a'.repeat(32), retention_days: 90 }),
        });
      }
      assert.equal(url, '/donate', 'withdrawal capability is not placed in a URL path');
      assert.equal(method, 'DELETE');
      assert.deepEqual(JSON.parse(body), { record_id: 'a'.repeat(32) },
        'withdrawal ID is sent only in the JSON request body');
      return new Promise((_resolve, reject) => signal.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      }, { once: true }));
    },
  });
  await submit(stalledWithdrawalDocument.nodes['#donation-form']);
  assert.equal(stalledWithdrawalDocument.nodes['#donation-withdrawal-id'].value, 'a'.repeat(32),
    'withdrawal ID is displayed in a user-copyable field');
  assert.equal(stalledWithdrawalDocument.nodes['#donation-consent'].checked, false,
    'review consent must be re-selected for each donation');
  assert.equal(stalledWithdrawalDocument.nodes['#donation-authorized'].checked, false,
    'sharing authorization must be re-selected for each donation');
  assert.equal(stalledWithdrawalDocument.nodes['#donation-research-consent'].checked, false,
    'optional research consent must reset after submission');
  await submit(stalledWithdrawalDocument.nodes['#donation-withdrawal-form']);
  assert.equal(stalledWithdrawalRequests, 2, 'a timed-out withdrawal is never automatically resent');
  assert.equal(stalledWithdrawalDocument.nodes['#donation-withdraw'].disabled, false,
    'withdrawal control is restored after timeout');
  assert.match(stalledWithdrawalDocument.nodes['#donation-status'].textContent, /could not confirm/i,
    'withdrawal timeout does not claim deletion failed or succeeded');

  const researchConsentDocument = donationDocument();
  researchConsentDocument.nodes['#donation-research-consent'].checked = true;
  let submittedDonation = null;
  createDonationForm({
    documentRef: researchConsentDocument,
    fetchImpl: async (_url, options) => {
      submittedDonation = JSON.parse(options.body);
      return { ok: true, json: async () => ({ record_id: 'c'.repeat(32), retention_days: 90 }) };
    },
  });
  await submit(researchConsentDocument.nodes['#donation-form']);
  assert.equal(submittedDonation.model_research_consent, true,
    'optional research consent is sent only when selected');
  assert.match(researchConsentDocument.nodes['#donation-status'].textContent,
    /separate model-research choice was recorded/i,
    'success wording must match the submitted consent choice');
  assert.equal(researchConsentDocument.nodes['#donation-research-consent'].checked, false,
    'optional research consent resets after a successful submission');

  const values = new Map();
  const storage = {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, value); },
    removeItem(key) { values.delete(key); },
  };
  const store = createHistoryStore(() => storage, { limit: 2 });
  assert.deepEqual(store.load(), [], 'history starts disabled');
  store.save([{ message: 'must not persist' }]);
  assert.equal(values.has('smsd_history_v1'), false, 'save while disabled removes legacy content');
  assert.equal(store.setEnabled(true), true);
  assert.deepEqual(store.save([{ message: 'one' }, { message: 'two' }, { message: 'three' }]), [
    { message: 'one' }, { message: 'two' },
  ], 'saved history is capped at the configured limit');
  assert.deepEqual(store.load(), [{ message: 'one' }, { message: 'two' }]);
  store.setEnabled(false);
  assert.equal(values.has('smsd_history_v1'), false, 'disabling history erases stored message text');
  const unavailable = createHistoryStore(() => { throw new Error('storage denied'); });
  assert.deepEqual(unavailable.load(), [], 'blocked browser storage fails closed');
  const nodes = Object.fromEntries(['api-status', 'readiness-status', 'browser-status'].map((id) => [id, { textContent: '', dataset: {} }]));
  const banner = { classes: new Set(['hidden']), classList: {
    remove(name) { banner.classes.delete(name); }, add(name) { banner.classes.add(name); },
  } };
  const status = createConnectionStatus({
    element: (id) => nodes[id], translate: (key) => key,
    browserOnline: () => false, offlineBanner: banner,
  });
  status.setApiAvailability(true, 2);
  status.setModelReadiness(false, 2);
  assert.equal(status.setModelReadiness(true, 1), false, 'stale readiness response is ignored');
  assert.equal(status.setApiAvailability('timeout', 1), false, 'stale reachability response is ignored');
  assert.equal(nodes['api-status'].textContent, 'service.apiAvailable');
  assert.equal(nodes['readiness-status'].textContent, 'service.modelUnavailable');
  assert.equal(nodes['browser-status'].textContent, 'service.browserOffline');
  status.showOfflineBanner();
  assert.equal(banner.classes.has('hidden'), false);
  status.hideOfflineBanner();
  assert.equal(banner.classes.has('hidden'), true);
  const validFraction = (value) => typeof value === 'number' && value >= 0 && value <= 1 ? value : null;
  const modelInfo = normalizeModelInfo({
    model_version: 'fixture-v1', decision_threshold: 0.7,
    bands: { likely_scam: 0.7, suspicious: 0.4 }, probability_calibrated: false,
  }, validFraction);
  const results = createResultFormatting({
    translate: (key) => key, validFraction, getModelInfo: () => modelInfo,
    matchesLoadedModel: (analysis) => analysis.model_version === modelInfo.model_version,
  });
  assert.equal(results.bandOf({ model_version: 'fixture-v1', spam_probability: 0.55 }), 'suspicious');
  assert.equal(results.bandOf({ model_version: 'old-v0', spam_probability: 0.55 }), 'unavailable',
    'metadata from a different model cannot supply missing thresholds');
  assert.equal(results.bandOf({ risk_band: 'likely_scam', spam_probability: 0.1 }), 'likely_scam',
    'the API verdict remains authoritative when present');
  assert.equal(results.scoreLabel({ probability_calibrated: false }), 'verdict.score.uncalibrated');
  assert.equal(results.isKnownBand('unsafe'), false);
  const previousFetch = globalThis.fetch;
  const previousWindow = globalThis.window;
  const timeoutStatuses = [];
  globalThis.window = { navigator: { onLine: true } };
  globalThis.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => {
      const error = new Error('aborted');
      error.name = 'AbortError';
      reject(error);
    }, { once: true });
  });
  try {
    const api = createApiClient({
      translate: (key) => key,
      setApiAvailability: (value) => timeoutStatuses.push(['api', value]),
      setModelReadiness: (value) => timeoutStatuses.push(['model', value]),
      hideOfflineBanner() {}, showOfflineBanner() {}, timeoutMs: 5,
    });
    await assert.rejects(api.requestJson('/model-info'), (error) => error.timeout === true);
  } finally {
    globalThis.fetch = previousFetch;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
  assert.deepEqual(timeoutStatuses, [['api', 'timeout'], ['model', 'unknown']],
    'request timeout marks reachability as slow and model readiness as unknown');
  const outageStatuses = [];
  globalThis.window = { navigator: { onLine: true } };
  let nextResponse = new Response(JSON.stringify({
    error: { code: 'rate_limiter_unavailable', message: 'Request protection is temporarily unavailable.' },
  }), { status: 503, headers: { 'Content-Type': 'application/json' } });
  globalThis.fetch = async () => nextResponse;
  try {
    const api = createApiClient({
      translate: (key) => key,
      setApiAvailability: (value) => outageStatuses.push(['api', value]),
      setModelReadiness: (value) => outageStatuses.push(['model', value]),
      hideOfflineBanner() {}, showOfflineBanner() {},
    });
    await assert.rejects(api.requestJson('/ready'), (error) => error.code === 'rate_limiter_unavailable');
    assert.deepEqual(outageStatuses, [['api', true], ['model', 'unknown']],
      'request protection outage is neither browser offline nor a proven model failure');
    outageStatuses.length = 0;
    nextResponse = new Response(JSON.stringify({ error: { code: 'model_unavailable', message: 'No model' } }),
      { status: 503, headers: { 'Content-Type': 'application/json' } });
    await assert.rejects(api.requestJson('/ready'), (error) => error.code === 'model_unavailable');
    assert.deepEqual(outageStatuses, [['api', true], ['model', false]]);
    outageStatuses.length = 0;
    nextResponse = new Response(JSON.stringify({ status: 'ready', model_loaded: true }),
      { status: 200, headers: { 'Content-Type': 'application/json' } });
    await api.requestJson('/ready');
    assert.deepEqual(outageStatuses, [['api', true], ['model', true]], 'readiness recovers on success');
  } finally {
    globalThis.fetch = previousFetch;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }

  /* ---------- shell update discovery (stale-shell self-healing) ---------- */
  assert.equal(shouldAutoReload({ documentHidden: true, activeRequests: 0, reloadKey: 'v9', hasReloadedBefore: false }),
    true, 'hidden idle tab auto-reloads once per shell generation');
  assert.equal(shouldAutoReload({ documentHidden: false, activeRequests: 0, reloadKey: 'v9', hasReloadedBefore: false }),
    false, 'visible tabs always get the banner, never an auto-reload');
  assert.equal(shouldAutoReload({ documentHidden: true, activeRequests: 2, reloadKey: 'v9', hasReloadedBefore: false }),
    false, 'auto-reload never interrupts an in-flight analysis');
  assert.equal(shouldAutoReload({ documentHidden: true, activeRequests: 0, reloadKey: 'v9', hasReloadedBefore: true }),
    false, 'the reload guard suppresses repeat reloads for the same generation');
  assert.equal(shouldAutoReload({ documentHidden: true, activeRequests: 0, reloadKey: '', hasReloadedBefore: false }),
    false, 'an unknown shell generation must not auto-reload; it shows the banner');

  function shellFakeServiceWorker(initialController) {
    const listeners = {};
    return {
      controller: initialController || null,
      addEventListener(type, callback) { (listeners[type] ||= []).push(callback); },
      removeEventListener(type, callback) {
        listeners[type] = (listeners[type] || []).filter((entry) => entry !== callback);
      },
      emit(type, event) { for (const callback of listeners[type] || []) callback(event); },
    };
  }

  function shellBannerDocument(hidden) {
    return { hidden: hidden === true, addEventListener() {}, removeEventListener() {} };
  }

  function shellStorage() {
    const map = new Map();
    return {
      getItem: (key) => (map.has(key) ? map.get(key) : null),
      setItem: (key, value) => map.set(key, String(value)),
    };
  }

  function shellBannerNodes() {
    return {
      banner: { classList: { add() {}, remove() {} } },
      reloadButton: { textContent: '', handlers: {}, addEventListener(type, callback) { this.handlers[type] = callback; } },
    };
  }

  {
    // Scenario 1: a tab whose first claim arrives after attach is a fresh load,
    // not an update. The next claim (with a known generation) auto-reloads it
    // because the document fixture is hidden and idle.
    const worker = shellFakeServiceWorker(null);
    const { banner, reloadButton } = shellBannerNodes();
    let reloads = 0;
    const updates = createShellUpdates({
      serviceWorker: worker,
      documentRef: shellBannerDocument(true),
      sessionStorageRef: shellStorage(),
      activeRequestCount: () => 0,
      translate: (key) => key,
      onReload: () => { reloads += 1; },
      banner,
      reloadButton,
      updateIntervalMs: 60_000,
    });
    const registration = { update: async () => {} };
    try {
      updates.attach(registration);
      worker.emit('controllerchange', {});
      assert.equal(updates.snapshot().bannerShown, false, 'initial claim must not be reported as an update');
      assert.equal(reloads, 0, 'initial claim must not reload');
      worker.emit('message', { data: { type: 'shell-activated', cache: 'smsd-shell-v99' } });
      worker.emit('controllerchange', {});
      assert.equal(reloads, 1, 'hidden idle tab reloads for a known new shell generation');
      worker.emit('controllerchange', {});
      assert.equal(reloads, 1, 'reload guard suppresses a repeat reload for the same generation');
      updates.showBanner();
      assert.equal(updates.snapshot().bannerShown, true, 'banner can be forced (stale-shell API responses)');
    } finally {
      updates.dispose();
    }
  }

  {
    // Scenario 2: a visible tab and an in-flight analysis never auto-reload.
    const worker = shellFakeServiceWorker({ scriptURL: 'old' });
    const { banner, reloadButton } = shellBannerNodes();
    let reloads = 0;
    const updates = createShellUpdates({
      serviceWorker: worker,
      documentRef: shellBannerDocument(false),
      sessionStorageRef: shellStorage(),
      activeRequestCount: () => 1,
      translate: (key) => key,
      onReload: () => { reloads += 1; },
      banner,
      reloadButton,
      updateIntervalMs: 60_000,
    });
    const registration = { update: async () => {} };
    try {
      updates.attach(registration);
      worker.emit('message', { data: { type: 'shell-activated', cache: 'smsd-shell-v100' } });
      worker.emit('controllerchange', {});
      assert.equal(reloads, 0, 'visible or busy tabs must not auto-reload');
      assert.equal(updates.snapshot().bannerShown, true, 'busy tabs get the banner instead');
      assert.equal(reloadButton.textContent, 'update.reloadButton', 'banner labels its reload action via i18n');
    } finally {
      updates.dispose();
    }
  }

  {
    // Scenario 3: the in-flight counter tracks concurrent API client requests
    // (isolated client; the earlier suite leaves one fire-and-forget request).
    const previousFetch = globalThis.fetch;
    let releasePending;
    const pending = new Promise((resolve) => { releasePending = resolve; });
    globalThis.fetch = () => pending.then(() => new Response(JSON.stringify({
        model_version: 'fixture', risk_band: 'looks_safe', spam_probability: 0.1, prediction: 'ham',
      }), { status: 200 }));
    const previousWindow = globalThis.window;
    globalThis.window = { navigator: { onLine: true } };
    try {
      const client = createApiClient({
        translate: (key) => key,
        setApiAvailability() {}, setModelReadiness() {},
        hideOfflineBanner() {}, showOfflineBanner() {},
      });
      const before = activeRequestCount();
      const inFlight = client.requestJson('/analyze');
      assert.equal(activeRequestCount(), before + 1, 'a started request raises the in-flight count');
      releasePending();
      await inFlight;
      assert.equal(activeRequestCount(), before, 'a settled request restores the in-flight count');
    } finally {
      globalThis.fetch = previousFetch;
      if (previousWindow === undefined) delete globalThis.window;
      else globalThis.window = previousWindow;
    }
  }

  console.log('ui-modules: privacy, result formatting, timeout, dependency-outage and shell-update recovery passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
