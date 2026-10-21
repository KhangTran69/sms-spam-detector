const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const net = require('node:net');
const path = require('node:path');

const root = path.resolve(__dirname, '..');

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => server.listen(0, '127.0.0.1', resolve).once('error', reject));
  const { port } = server.address();
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function waitForServer(base, process) {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (process.exitCode !== null) throw new Error(`uvicorn exited early with ${process.exitCode}`);
    try {
      const response = await fetch(`${base}/health`);
      if (response.ok) return;
    } catch { /* retry while the local server starts */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('local FastAPI server did not start');
}

function analysis(message) {
  const modelMismatch = message.includes('[different-model]');
  const matches = [];
  const brandStart = message.indexOf('BDO.example');
  if (brandStart >= 0) {
    const start = Array.from(message.slice(0, brandStart)).length;
    matches.push({ type: 'url', start, end: start + Array.from('BDO.example').length });
    matches.push({ type: 'brand', start, end: start + 3 });
  }
  const urgency = message.toLowerCase().indexOf('today');
  if (urgency >= 0) {
    const start = Array.from(message.slice(0, urgency)).length;
    matches.push({ type: 'urgency', start, end: start + 5 });
  }
  return {
    message,
    prediction: modelMismatch ? 'ham' : 'spam',
    spam_probability: modelMismatch ? 0.15 : /official app|never share|out for delivery/i.test(message) ? 0.15 : 0.82,
    probability: modelMismatch ? 0.15 : 0.82,
    probability_calibrated: !modelMismatch,
    decision_threshold: modelMismatch ? 0.55 : 0.6,
    suspicious_threshold: modelMismatch ? 0.3 : 0.4,
    margin: 0.22,
    confidence: 'high',
    risk_band: modelMismatch || /official app|never share|out for delivery/i.test(message) ? 'looks_safe' : 'likely_scam',
    flags: [],
    matches,
    brands: [],
    model_version: modelMismatch ? 'browser-fixture-v2' : 'browser-fixture-v1',
  };
}

async function main() {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(process.env.PYTHON || 'python', [
    '-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', String(port),
  ], { cwd: root, stdio: 'ignore', env: { ...process.env, SMSD_MODEL_PATH: path.join(root, 'missing-browser-fixture.pkl') } });
  let browser;
  try {
    await waitForServer(base, server);
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 360, height: 800 },
      deviceScaleFactor: 1,
      isMobile: true,
      hasTouch: true,
      acceptDownloads: true,
      serviceWorkers: 'block',
    });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', (error) => console.error('browser page error:', error.message));
    let releaseModelInfo;
    let delayNextAnalysis = false;
    let delayNextBatch = false;
    await page.route('**/model-info', async (route) => {
      await new Promise((resolve) => { releaseModelInfo = resolve; });
      await route.fulfill({ json: {
        model_version: 'late-metadata-model',
        decision_threshold: 0.9,
        suspicious_threshold: 0.8,
        bands: { likely_scam: 0.9, suspicious: 0.8, looks_safe: 0 },
        data_note: 'Synthetic browser fixture only.',
        probability_calibrated: false,
        feedback_enabled: false,
      } });
    });
    await page.route('**/analyze/batch', async (route) => {
      const { messages } = route.request().postDataJSON();
      if (delayNextBatch) {
        delayNextBatch = false;
        await new Promise((resolve) => setTimeout(resolve, 700));
      }
      try {
        await route.fulfill({ json: {
          count: messages.length,
          results: messages.map(analysis),
          model_version: 'browser-fixture-v1',
          decision_threshold: 0.6,
        } });
      } catch { /* request may have been aborted after input editing or tab switch */ }
    });
    await page.route('**/analyze', async (route) => {
      const { message } = route.request().postDataJSON();
      if (delayNextAnalysis) {
        delayNextAnalysis = false;
        await new Promise((resolve) => setTimeout(resolve, 700));
      }
      try {
        await route.fulfill({ json: analysis(message) });
      } catch { /* a slower request may have been aborted by the newer input */ }
    });

    await page.goto(base, { waitUntil: 'domcontentloaded' });
    console.log('browser-smoke: initial page loaded');
    await page.locator('#message-input').fill('Fixture check completes before model info.');
    await page.locator('#btn-check').click();
    await page.locator('#result').waitFor({ state: 'visible' });
    await page.waitForFunction(() => typeof window.currentAnalysis === 'object');
    console.log('browser-smoke: delayed metadata did not block result');
    releaseModelInfo();
    await page.waitForTimeout(50);
    if ((await page.locator('#risk-meter').getAttribute('aria-label')) !== 'Calibrated spam score') {
      throw new Error('late model-info response overwrote the calibration wording of the displayed result');
    }
    if (!(await page.locator('#model-version').textContent()).includes('browser-fixture-v1')) {
      throw new Error('late model-info response overwrote the result model version');
    }
    if (!(await page.locator('#model-thresholds').textContent()).includes('60%')) {
      throw new Error('late model-info response overwrote the result thresholds');
    }
    if (!(await page.locator('#model-note').textContent()).includes('unavailable')) {
      throw new Error('provenance from a different model version was attached to the existing result');
    }
    const resultBands = await page.locator('#risk-meter').evaluate((meter) => ({
      likely: meter.style.getPropertyValue('--scam'),
      suspicious: meter.style.getPropertyValue('--suspect'),
    }));
    if (resultBands.likely !== '60%' || resultBands.suspicious !== '40%') {
      throw new Error(`meter zones did not use the analysis thresholds: ${JSON.stringify(resultBands)}`);
    }
    if ((await page.locator('#history-list li').count()) !== 0) throw new Error('history must start opt-in and empty');

    const scam = page.locator('[data-example="scam"]');
    const safe = page.locator('[data-example="safe"]');
    delayNextAnalysis = true;
    await scam.click();
    const firstScam = await page.locator('#message-input').inputValue();
    await safe.click();
    if ((await page.locator('#message-input').inputValue()) === firstScam) throw new Error('safe cycle did not advance independently');
    await scam.click();
    const secondScam = await page.locator('#message-input').inputValue();
    if (firstScam === secondScam) throw new Error('scam examples did not advance on repeated clicks');
    const latestScam = await page.locator('#message-input').inputValue();
    await page.waitForFunction((expected) => document.querySelector('#highlighted').textContent === expected, latestScam);
    await page.waitForTimeout(750);
    if (await page.locator('#highlighted').textContent() !== latestScam) throw new Error('slow stale response replaced the latest example result');

    await page.locator('#btn-lang').click();
    if ((await page.locator('#risk-meter').getAttribute('aria-label')) !== 'Calibrated na spam score') {
      throw new Error('language change lost the displayed score calibration state');
    }
    if (await page.evaluate(() => localStorage.getItem('smsd_lang_v1')) !== 'taglish') {
      throw new Error('language preference was not persisted');
    }
    await page.locator('#btn-lang').click();
    await page.locator('#btn-theme').click();
    if (await page.locator('html').getAttribute('data-theme') !== 'dark') throw new Error('dark theme did not activate');
    if (await page.evaluate(() => localStorage.getItem('smsd_theme_v1')) !== 'dark') {
      throw new Error('dark theme preference was not persisted');
    }
    if ((await page.locator('#btn-theme').getAttribute('aria-label')) !== 'Switch to light mode') throw new Error('dark theme control name is wrong');
    await page.locator('#btn-theme').click();
    if (await page.locator('html').getAttribute('data-theme') !== 'light') throw new Error('light theme did not restore');

    await page.locator('#message-input').fill('Old result should clear after editing.');
    if (await page.locator('#result').isVisible()) throw new Error('editing left a stale result visible');
    await page.locator('#btn-clear').click();
    if (await page.locator('#message-input').inputValue()) throw new Error('clear button left old input');
    if (await page.locator('#result').isVisible()) throw new Error('clear button left a stale result visible');

    await page.locator('#tab-history').click();
    await page.locator('#history-optin').check();
    await page.locator('#tab-check').click();
    await page.locator('#message-input').fill('Opt-in history browser fixture.');
    await page.locator('#btn-check').click();
    await page.locator('#result').waitFor({ state: 'visible' });
    await page.locator('#tab-history').click();
    const historyEntry = page.locator('#history-list li').first();
    await historyEntry.waitFor({ state: 'visible' });
    const historyLabel = await historyEntry.getAttribute('aria-label');
    if (!historyLabel || !historyLabel.includes('calibrated spam score') || /\{[^}]+\}/.test(historyLabel)) {
      const markup = await historyEntry.evaluate((item) => item.outerHTML);
      throw new Error(`history accessible label is incomplete: ${historyLabel}; ${markup}`);
    }
    page.on('dialog', (dialog) => dialog.accept());
    await page.locator('#btn-clear-history').click();
    if (await page.locator('#history-list li').count()) throw new Error('clear history did not delete saved entries');

    await page.locator('#tab-compare').click();
    await page.locator('#btn-compare-run').click();
    if (!(await page.locator('#compare-error').textContent()).includes('Enter both messages')) {
      throw new Error('empty comparison did not provide a clear validation message');
    }
    await page.locator('#compare-message-a').fill('😀 BDO.example says act today. <img src=x onerror=alert(1)>');
    await page.locator('#compare-message-b').fill('Your OTP is [CODE]. Never share it; use the official app.');
    if ((await page.locator('#compare-count-a').textContent()) !== '58 / 10000') throw new Error('Unicode code-point counter is incorrect');
    delayNextBatch = true;
    await page.locator('#btn-compare-run').click();
    if (!(await page.locator('#btn-compare-run').isDisabled())) throw new Error('comparison button was not disabled during submission');
    await page.waitForTimeout(100);
    await page.locator('#compare-message-b').fill('Edited while request was running.');
    if (await page.locator('#compare-results').isVisible()) throw new Error('editing left stale comparison results visible');
    await page.waitForTimeout(750);
    if (await page.locator('#compare-results').isVisible()) throw new Error('stale comparison response restored edited results');

    await page.locator('[data-compare-example="delivery"]').click();
    const exampleA = await page.locator('#compare-message-a').inputValue();
    const exampleB = await page.locator('#compare-message-b').inputValue();
    if (!exampleA.includes('official courier app') || !exampleB.includes('parcel-release.example')) {
      throw new Error('fictional delivery comparison pair did not load');
    }
    delayNextBatch = true;
    await page.locator('#btn-compare-run').click();
    await page.waitForTimeout(100);
    await page.locator('#tab-check').click();
    await page.waitForTimeout(750);
    if (await page.locator('#compare-results').isVisible()) throw new Error('tab switch allowed a stale partial comparison');
    await page.locator('#tab-compare').click();
    await page.locator('[data-compare-example="account"]').click();
    await page.locator('#btn-compare-run').click();
    await page.locator('#compare-result-cards').waitFor({ state: 'visible' });
    if (await page.locator('#compare-result-cards article').count() !== 2) throw new Error('comparison did not render both result cards');
    if (!(await page.locator('#compare-summary').textContent()).includes('percentage points')) throw new Error('compatible scores did not show a difference');
    if (await page.locator('#compare-result-cards img').count()) throw new Error('untrusted SMS markup created an image element');
    if ((await page.locator('.compare-provenance').allTextContents()).some((text) => text.includes('Synthetic browser fixture only'))) {
      throw new Error('comparison borrowed provenance from a different model version');
    }
    const mobileColumns = await page.locator('#compare-result-cards').evaluate((item) => getComputedStyle(item).gridTemplateColumns.split(' ').length);
    if (mobileColumns !== 1) throw new Error(`comparison cards do not stack at 360px: ${mobileColumns} columns`);
    await page.setViewportSize({ width: 1280, height: 900 });
    const desktopColumns = await page.locator('#compare-result-cards').evaluate((item) => getComputedStyle(item).gridTemplateColumns.split(' ').length);
    if (desktopColumns !== 2) throw new Error(`comparison cards are not side-by-side at desktop width: ${desktopColumns} columns`);
    await page.setViewportSize({ width: 360, height: 800 });
    if (await page.locator('#history-list li').count()) throw new Error('comparison was unexpectedly saved to history');
    await page.locator('#btn-lang').click();
    if (!(await page.locator('#compare-results-heading').textContent()).includes('paghahambing')) throw new Error('comparison title did not switch to Taglish');
    await page.locator('#btn-lang').click();
    await page.locator('#btn-compare-clear').click();
    if (await page.locator('#compare-message-a').inputValue() || await page.locator('#compare-message-b').inputValue()) throw new Error('clear-all did not clear both fields');
    if (await page.locator('#compare-results').isVisible()) throw new Error('clear-all left a stale comparison');
    await page.locator('#compare-message-a').fill('x'.repeat(10001));
    await page.locator('#compare-message-b').fill('valid');
    await page.locator('#btn-compare-run').click();
    if (!(await page.locator('#compare-error').textContent()).includes('limit is 10,000')) throw new Error('oversized comparison was not rejected');
    await page.locator('#btn-compare-clear').click();

    // Model-version/calibration mismatch must suppress percentage-point arithmetic.
    await page.locator('#compare-message-a').fill('😀 BDO.example alert <img src=x onerror=alert(1)>');
    await page.locator('#compare-message-b').fill('[different-model] old fixture');
    await page.locator('#btn-compare-run').click();
    await page.locator('#compare-result-cards').waitFor({ state: 'visible' });
    if (!(await page.locator('#compare-summary').textContent()).includes('cannot be compared directly')) {
      throw new Error('incompatible model scores were compared directly');
    }
    await page.locator('#btn-compare-copy').click();
    await page.waitForFunction(() => Boolean(document.querySelector('#compare-copy-status').textContent));
    if (!await page.locator('#compare-copy-status').textContent()) throw new Error('explicit copy action did not report status');
    await page.locator('#btn-compare-clear').click();

    await page.locator('#tab-batch').click();
    await page.locator('#batch-input').fill('=SUM(1,1) "quoted"\nOrdinary fixture message');
    await page.locator('#btn-batch').click();
    await page.locator('#batch-results').waitFor({ state: 'visible' });
    await page.locator('#batch-tbody tr[aria-label]').first().waitFor({ state: 'visible' });
    const rowLabel = await page.locator('#batch-tbody tr[aria-label]').first().getAttribute('aria-label');
    if (!rowLabel || !rowLabel.includes('calibrated spam score') || /\{[^}]+\}/.test(rowLabel)) {
      const markup = await page.locator('#batch-tbody tr[aria-label]').first().evaluate((item) => item.outerHTML);
      throw new Error(`batch accessible label is incomplete: ${rowLabel}; ${markup}`);
    }
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.locator('#btn-csv').click(),
    ]);
    const csv = await fs.readFile(await download.path(), 'utf8');
    if (!csv.includes("'=SUM(1,1) \"\"quoted\"\"")) throw new Error('CSV did not protect formula-like SMS content and escape quotes');
    if (!csv.includes('calibrated spam score')) throw new Error('CSV omitted the score interpretation');
    if (!csv.includes('60%') || !csv.includes('40%') || !csv.includes('browser-fixture-v1')) {
      throw new Error('CSV omitted the result-specific thresholds or model version');
    }

    const touchSizes = await page.locator('.btn, .tab, .example-chip, #history-optin').evaluateAll((items) =>
      items.filter((item) => item.getClientRects().length).map((item) => {
        const rect = item.getBoundingClientRect();
        return { name: item.id || item.textContent.trim(), width: rect.width, height: rect.height };
      }));
    if (touchSizes.some((item) => item.width < 44 || item.height < 44)) throw new Error(`small touch target at 360px: ${JSON.stringify(touchSizes)}`);
    const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    if (horizontalOverflow) throw new Error('360px mobile view has horizontal overflow');

    await page.locator('#tab-check').focus();
    await page.keyboard.press('ArrowRight');
    if (await page.locator('#tab-batch').getAttribute('aria-selected') !== 'true') throw new Error('arrow-key tab navigation failed');
    const focusOutline = await page.locator('#tab-batch').evaluate((item) => getComputedStyle(item).outlineWidth);
    if (focusOutline === '0px') throw new Error('keyboard focus outline is not visible');
    await context.close();
    console.log('browser-smoke: interactions, privacy, and mobile checks passed');

    // Test the actual service worker cache and offline reload in a clean context.
    const pwaContext = await browser.newContext({ viewport: { width: 360, height: 800 } });
    const offlinePage = await pwaContext.newPage();
    await offlinePage.goto(base, { waitUntil: 'domcontentloaded' });
    await Promise.race([
      offlinePage.evaluate(() => navigator.serviceWorker.ready),
      new Promise((_, reject) => setTimeout(() => reject(new Error('service worker did not become ready')), 10000)),
    ]);
    await offlinePage.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
    await pwaContext.setOffline(true);
    await offlinePage.reload({ waitUntil: 'domcontentloaded' });
    if (!(await offlinePage.locator('.brand').isVisible())) {
      throw new Error('offline reload did not render the cached shell');
    }
    if (!(await offlinePage.locator('#tab-compare').isVisible())) {
      throw new Error('offline cached shell does not include the comparison release');
    }
    await pwaContext.close();
    console.log('browser-smoke: offline reload passed');
    await browser.close();
    browser = null;
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise((resolve) => server.once('exit', resolve));
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
