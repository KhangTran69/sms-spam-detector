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
  const { createApiClient } = await import(apiUrl);
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
  console.log('ui-modules: opt-in history, stale-safe status, shared results, and timeout recovery passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
