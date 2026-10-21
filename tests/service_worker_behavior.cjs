const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const source = fs.readFileSync(path.join(__dirname, '../api/web/sw.js'), 'utf8');

function createWorker({ failAsset = null, networkFails = true } = {}) {
  const handlers = {};
  const cacheData = new Map();
  const deleted = [];
  let skippedWaiting = false;
  const cacheKey = (request) => {
    const url = new URL(typeof request === 'string' ? request : request.url, 'http://detector.test');
    return `${url.pathname}${url.search}`;
  };
  const cache = {
    async add(asset) {
      if (asset === failAsset) throw new Error('fixture network failure');
      cacheData.set(cacheKey(asset), new Response(`cached:${asset}`));
    },
    async put(request, response) { cacheData.set(cacheKey(request), response); },
  };
  const caches = {
    async open() { return cache; },
    async delete(name) { deleted.push(name); return true; },
    async keys() { return ['smsd-shell-v6', 'smsd-shell-v7']; },
    async match(request) { return cacheData.get(cacheKey(request)) || null; },
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
  return { handlers, caches, cacheData, deleted, get skippedWaiting() { return skippedWaiting; } };
}

(async () => {
  const interrupted = createWorker({ failAsset: '/manifest.webmanifest' });
  let install;
  interrupted.handlers.install({ waitUntil(promise) { install = promise; } });
  await assert.rejects(install, /fixture network failure/);
  assert.deepEqual(interrupted.deleted, ['smsd-shell-v7']);
  assert.equal(interrupted.skippedWaiting, false, 'partial shell must not activate');

  const worker = createWorker();
  let activation;
  worker.handlers.install({ waitUntil(promise) { activation = promise; } });
  await activation;
  assert.equal(worker.skippedWaiting, true, 'complete shell activates');

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
    request: { method: 'GET', url: 'http://detector.test/static/app.js?v=ui7-spam-score-20261021' },
    respondWith(promise) { cachedResponse = promise; },
  });
  const response = await cachedResponse;
  assert.equal(await response.text(), 'cached:/static/app.js?v=ui7-spam-score-20261021');

  let uncachedResponse;
  worker.handlers.fetch({
    request: { method: 'GET', url: 'http://detector.test/static/styles.css?v=unknown' },
    respondWith(promise) { uncachedResponse = promise; },
  });
  const unavailable = await uncachedResponse;
  assert.equal(unavailable.status, 503);
  assert.match(unavailable.headers.get('content-type'), /text\/plain/);
})().catch((error) => { console.error(error); process.exitCode = 1; });
