const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const source = fs.readFileSync(path.join(__dirname, '../api/web/sw.js'), 'utf8');

function createWorker({ failAsset = null, delayAsset = null, networkFails = true } = {}) {
  const handlers = {};
  const shellCaches = new Map([
    ['smsd-shell-v6', new Map()],
    ['smsd-shell-v7', new Map([['/', new Response('previous complete release')]])],
    ['smsd-shell-v8', new Map([['/', new Response('immediately previous release')]])],
    ['smsd-shell-v9', new Map([['/', new Response('last released shell')]])],
    ['smsd-shell-v10', new Map([['/', new Response('previous release with comparison and checklist')]])],
    ['smsd-shell-v11', new Map([['/', new Response('previous release with privacy preview')]])],
    ['smsd-shell-v12', new Map([['/', new Response('previous release with live service status')]])],
    ['smsd-shell-v13', new Map([['/', new Response('previous release with spam signal wording')]])],
    ['smsd-shell-v14', new Map([['/', new Response('previous release with modular frontend')]])],
  ]);
  const deleted = [];
  let skippedWaiting = false;
  let finishDelayedAsset;
  const cacheKey = (request) => {
    const url = new URL(typeof request === 'string' ? request : request.url, 'http://detector.test');
    return `${url.pathname}${url.search}`;
  };
  const caches = {
    async open(name) {
      if (!shellCaches.has(name)) shellCaches.set(name, new Map());
      const cacheData = shellCaches.get(name);
      return {
        async add(asset) {
          if (asset === failAsset) throw new Error('fixture network failure');
          if (asset === delayAsset) await new Promise((resolve) => { finishDelayedAsset = resolve; });
          cacheData.set(cacheKey(asset), new Response(`cached:${asset}`));
        },
        async put(request, response) { cacheData.set(cacheKey(request), response); },
      };
    },
    async delete(name) { deleted.push(name); return shellCaches.delete(name); },
    async keys() { return [...shellCaches.keys()]; },
    async match(request, options) {
      assert.equal(options.cacheName, 'smsd-shell-v16');
      return shellCaches.get(options.cacheName)?.get(cacheKey(request)) || null;
    },
  };
  const self = {
    location: { origin: 'http://detector.test' },
    clients: { async claim() {} },
    async skipWaiting() { skippedWaiting = true; },
    addEventListener(name, callback) { handlers[name] = callback; },
  };
  const context = vm.createContext({
    self,
    caches,
    URL,
    Response,
    async fetch() {
      if (networkFails) throw new Error('fixture offline');
      return new Response('network shell');
    },
  });
  vm.runInContext(source, context);
  return {
    handlers, caches, shellCaches, deleted,
    get cacheData() { return shellCaches.get('smsd-shell-v16'); },
    finishDelayedAsset() { finishDelayedAsset(); },
    get skippedWaiting() { return skippedWaiting; },
  };
}

(async () => {
  const interrupted = createWorker({ failAsset: '/manifest.webmanifest', delayAsset: '/' });
  let install;
  interrupted.handlers.install({ waitUntil(promise) { install = promise; } });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(interrupted.deleted, [], 'failed install waits for in-flight cache writes to settle');
  interrupted.finishDelayedAsset();
  await assert.rejects(install, /static shell asset could not be cached/);
  assert.deepEqual(interrupted.deleted, ['smsd-shell-v16']);
  assert.equal(interrupted.shellCaches.has('smsd-shell-v16'), false, 'failed candidate cache is removed');
  assert.equal(await (await interrupted.shellCaches.get('smsd-shell-v13').get('/').text()), 'previous release with spam signal wording',
    'failed update leaves the previous complete release intact');
  assert.equal(interrupted.skippedWaiting, false, 'partial shell must not activate');

  const worker = createWorker();
  let activation;
  worker.handlers.install({ waitUntil(promise) { activation = promise; } });
  await activation;
  assert.equal(worker.skippedWaiting, true, 'complete shell activates');
  let cleanup;
  worker.handlers.activate({ waitUntil(promise) { cleanup = promise; } });
  await cleanup;
  assert.deepEqual(worker.deleted, ['smsd-shell-v6', 'smsd-shell-v7', 'smsd-shell-v8', 'smsd-shell-v9', 'smsd-shell-v10', 'smsd-shell-v11', 'smsd-shell-v12', 'smsd-shell-v13', 'smsd-shell-v14'], 'old releases are removed only after new install completed');
  assert.equal(worker.shellCaches.has('smsd-shell-v16'), true, 'new complete release is active after upgrade');

  let apiIntercepted = false;
  worker.handlers.fetch({
    request: { method: 'POST', url: 'http://detector.test/analyze' },
    respondWith() { apiIntercepted = true; },
  });
  assert.equal(apiIntercepted, false, 'message-bearing POST must not be intercepted');

  worker.handlers.fetch({
    request: { method: 'GET', url: 'http://detector.test/unknown' },
    respondWith() { apiIntercepted = true; },
  });
  assert.equal(apiIntercepted, false, 'unknown same-origin GET must not be cached');

  let cachedResponse;
  worker.handlers.fetch({
    request: { method: 'GET', url: 'http://detector.test/static/app.js?v=ui16-model-details-20261024' },
    respondWith(promise) { cachedResponse = promise; },
  });
  const response = await cachedResponse;
  assert.equal(await response.text(), 'cached:/static/app.js?v=ui16-model-details-20261024');
  assert.equal(worker.cacheData.get('/static/app.js?v=ui16-model-details-20261024').status, 200,
    'network responses must not overwrite immutable release assets');
  for (const asset of ['api-client.js', 'i18n.js', 'privacy-preview.js', 'history-store.js', 'connection-status.js', 'result-format.js']) {
    const request = { method: 'GET', url: `http://detector.test/static/${asset}?v=ui16-model-details-20261024` };
    let moduleResponse;
    worker.handlers.fetch({ request, respondWith(promise) { moduleResponse = promise; } });
    assert.equal(await (await moduleResponse).text(), `cached:/static/${asset}?v=ui16-model-details-20261024`);
  }

  let uncachedResponse;
  worker.handlers.fetch({
    request: { method: 'GET', url: 'http://detector.test/static/styles.css?v=unknown' },
    respondWith(promise) { uncachedResponse = promise; },
  });
  assert.equal(uncachedResponse, undefined, 'unknown asset versions bypass the worker');
  worker.cacheData.delete('/static/styles.css?v=ui16-model-details-20261024');
  let unavailableResponse;
  worker.handlers.fetch({
    request: { method: 'GET', url: 'http://detector.test/static/styles.css?v=ui16-model-details-20261024' },
    respondWith(promise) { unavailableResponse = promise; },
  });
  const unavailable = await unavailableResponse;
  assert.equal(unavailable.status, 503);
  assert.match(unavailable.headers.get('content-type'), /text\/plain/);
})().catch((error) => { console.error(error); process.exitCode = 1; });
