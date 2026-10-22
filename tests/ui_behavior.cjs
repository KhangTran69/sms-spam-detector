const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
function element(tagName = 'div') {
  const classes = new Set();
  let ownText = '';
  return { tagName, dataset: {}, value: '', disabled: false, childNodes: [], listeners: {}, attributes: {},
    style: { setProperty() {}, left: '', color: '' },
    get textContent() { return this.childNodes.length ? this.childNodes.map(child => child.textContent).join('') : ownText; },
    set textContent(value) { ownText = String(value); this.childNodes = []; },
    addEventListener(type, handler) { this.listeners[type] = handler; },
    classList: { add: c => classes.add(c), remove: c => classes.delete(c),
      contains: c => classes.has(c), toggle: (c, yes) => yes ? classes.add(c) : classes.delete(c) },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; },
    removeAttribute(name) { delete this.attributes[name]; }, focus() {},
    append(...nodes) { ownText = ''; this.childNodes.push(...nodes); },
    replaceChildren(...nodes) { ownText = ''; this.childNodes = nodes; } };
}
const elements = new Map();
const exampleChips = ['scam', 'safe'].map(kind => {
  const chip = element();
  chip.dataset.example = kind;
  return chip;
});
const tabs = ['check', 'batch', 'compare', 'history'].map(name => {
  const tab = element('button');
  tab.dataset.tab = name;
  return tab;
});
const panels = ['check', 'batch', 'compare', 'history'].map(name => {
  const panel = element('section');
  panel.id = `panel-${name}`;
  return panel;
});
const busyCheckButton = element('button');
busyCheckButton.id = 'btn-check';
busyCheckButton.dataset.idleLabel = 'Check message';
busyCheckButton.dataset.i18n = 'check.run';
busyCheckButton.setAttribute('aria-busy', 'true');
const storedValues = new Map();
const requests = [];
let copiedClipboard = '';
const context = vm.createContext({ console, AbortController, tabs, panels, busyCheckButton, requests,
  navigator: { clipboard: { async writeText(value) { copiedClipboard = value; } } },
  localStorage: { getItem: key => storedValues.get(key) || null,
    setItem(key, value) { storedValues.set(key, String(value)); }, removeItem: key => storedValues.delete(key) },
  window: { matchMedia: () => ({matches: false}) },
  document: { getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    querySelectorAll(selector) {
      if (selector === '.example-chip') return exampleChips;
      if (selector === '[data-compare-example]') return [];
      if (selector === '[role="tab"]') return tabs;
      if (selector === '.panel') return panels;
      if (selector === 'button[data-idle-label]') return [busyCheckButton];
      if (selector === '[data-i18n]') return [busyCheckButton];
      return [];
    },
    documentElement: element('html'),
    addEventListener() {}, createElement: tagName => element(tagName), createTextNode: text => ({ textContent: text }) } });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../api/web/app.js'), 'utf8'), context);
vm.runInContext(`
  var pending = [];
  var rendered = [];
  postJson = (path, body) => { requests.push({path, body}); return new Promise((resolve, reject) => pending.push({resolve, reject})); };
  renderAnalysis = analysis => rendered.push(analysis.message);
  renderBatch = rows => rendered.push(rows[0].message);
`, context);
const run = code => vm.runInContext(code, context);
assert.equal(run('EXAMPLES.scam.length'), 20, 'the scam example set must contain 20 examples');
assert.equal(run('EXAMPLES.safe.length'), 20, 'the safe example set must contain 20 examples');
assert.equal(run('new Set(EXAMPLES.scam).size'), 20, 'scam examples must be distinct');
assert.equal(run('new Set(EXAMPLES.safe).size'), 20, 'safe examples must be distinct');
assert.equal(run('EXAMPLES.safe.length'), 20, 'safe examples should cycle independently');
assert.equal(run(`csvCell(${JSON.stringify('a, b "quoted"')})`), '"a, b ""quoted"""', 'CSV must escape quotes and delimiters');
assert.equal(run('csvCell("=SUM(1,1)")'), '"\'=SUM(1,1)"', 'formula-like text must be exported as text');
assert.equal(run('csvCell("  @SUM(1,1)")'), '"\'  @SUM(1,1)"', 'leading whitespace must not bypass formula protection');
assert.equal(run(`csvCell(${JSON.stringify('\uFEFF=1+1')})`), '"\'\uFEFF=1+1"', 'Unicode BOM must not bypass formula protection');
assert.match(run('t("examples.status", {kind: t("examples.scamKind"), index: 1, total: 20})'), /Loaded fictional scam message 1 of 20/);
const privacyFixture = '😀 OTP is 123456. Call 0917-123-4567 or email user@example.test. Reference no: TX-12345; amount ₱500 on 2026-10-21.';
const privacySpans = Array.from(run(`detectSensitiveSpans(${JSON.stringify(privacyFixture)})`), span => ({
  type: span.type,
  value: privacyFixture.slice(span.start, span.end),
  start: span.start,
  end: span.end,
}));
assert.deepEqual(privacySpans.map(span => [span.type, span.value]), [
  ['code', '123456'], ['phone', '0917-123-4567'], ['email', 'user@example.test'], ['reference', 'TX-12345'],
], 'privacy suggestions cover contextual codes, Philippine phones, email, and references while leaving ordinary amounts and dates alone');
assert.equal(run(`applyPrivacyMasks(${JSON.stringify(privacyFixture)}, detectSensitiveSpans(${JSON.stringify(privacyFixture)}))`),
  '😀 OTP is [CODE]. Call [PHONE] or email [EMAIL]. Reference no: [REFERENCE]; amount ₱500 on 2026-10-21.',
  'Unicode offsets preserve surrounding text and replace only selected sensitive spans');
assert.deepEqual(Array.from(run(`detectSensitiveSpans(${JSON.stringify('Payment of ₱500 due 2026-10-21; code word is ordinary here.')})`)), [],
  'amounts, dates, and ordinary code wording do not trigger suggestions by themselves');
assert.deepEqual(Array.from(run(`detectSensitiveSpans(${JSON.stringify('OTP code is 4321; transaction pending; 123456789012345.')})`), span => span.type), ['code'],
  'OTP code phrasing is supported without masking unrelated status words or long digit strings');
assert.deepEqual(Array.from(run(`detectSensitiveSpans(${JSON.stringify('OTP mo ay 4321. One-time PIN: 9876.')})`), span => span.type), ['code', 'code'],
  'Taglish OTP wording and one-time PINs are detected locally');
assert.equal(run(`applyPrivacyMasks("ABCDEFGHI", [{start:0,end:5,type:"reference"},{start:3,end:9,type:"phone",manual:true}])`),
  '[PHONE]', 'overlapping selections collapse to one placeholder');
assert.match(run('t("privacy.title")'), /Local privacy preview/);
run('lang = "taglish"');
assert.match(run('t("privacy.title")'), /Privacy preview sa browser/);
run('lang = "en"');
(async () => {
  run(`lang = "en";
    var lowScoreResult = {message:"private SMS fixture", spam_probability:0.05, risk_band:"looks_safe"};
    var guidanceMount = document.createElement("div");
    renderSafetyGuidance(guidanceMount, lowScoreResult, "unit");
    var guidanceRoot = guidanceMount.childNodes[0];`);
  const guidanceRoot = run('guidanceRoot');
  const descendants = (node) => (node.childNodes || []).flatMap(child => [child, ...descendants(child)]);
  const guidanceNodes = descendants(guidanceRoot);
  assert.equal(guidanceNodes.filter(node => node.tagName === 'fieldset').length, 6,
    'the four questions and next-step choice use semantic fieldsets');
  assert.equal(guidanceNodes.filter(node => node.tagName === 'input').length, 16,
    'each categorical question and next-step action has radio controls');
  for (const field of ['expected', 'sensitive', 'payment', 'verified']) {
    const choices = guidanceNodes.filter(node => node.tagName === 'input' && node.type === 'radio' && node.dataset.guidanceField === field);
    assert.deepEqual(choices.map(node => node.value), ['yes', 'no', 'unsure'],
      `${field} should offer Yes, No, and Not sure`);
    for (const answer of ['yes', 'no', 'unsure']) {
      const choice = choices.find(node => node.value === answer);
      guidanceRoot.listeners.change({target: choice});
      assert.equal(run(`guidanceStateFor(lowScoreResult).${field}`), answer,
        `${field} should retain the ${answer} answer in memory`);
    }
  }
  const secretYes = guidanceNodes.find(node => node.tagName === 'input' && node.dataset.guidanceField === 'sensitive' && node.value === 'yes');
  guidanceRoot.listeners.change({target: secretYes});
  assert.match(run('guidanceRecommendations(guidanceStateFor(lowScoreResult)).join(" ")'), /asks for a secret code or password/,
    'sensitive-information guidance remains strong for a low spam score');
  assert.match(run('guidanceRecommendations(guidanceStateFor(lowScoreResult)).join(" ")'), /cannot verify the sender/,
    'guidance does not treat a safe band as sender verification');
  const advice = guidanceNodes.find(node => node.className && node.className.includes('guidance-advice'));
  assert.match(advice.textContent, /asks for a secret code or password/);
  const selectGuidanceAction = (value) => {
    const control = guidanceNodes.find(node => node.tagName === 'input' && node.dataset.guidanceField === 'action' && node.value === value);
    control.checked = true;
    guidanceRoot.listeners.change({target: control});
  };
  selectGuidanceAction('openedLink');
  assert.match(run('guidanceRecommendations(guidanceStateFor(lowScoreResult)).join(" ")'), /Opening a link alone does not prove/);
  selectGuidanceAction('sharedSensitive');
  assert.match(run('guidanceRecommendations(guidanceStateFor(lowScoreResult)).join(" ")'), /Act promptly/);
  selectGuidanceAction('sentMoney');
  assert.match(run('guidanceRecommendations(guidanceStateFor(lowScoreResult)).join(" ")'), /recovery is not guaranteed/);
  assert.equal(run('guidanceStateFor(lowScoreResult).actions.length'), 3, 'multiple user actions can be represented together');
  selectGuidanceAction('notInteracted');
  assert.deepEqual(Array.from(run('guidanceStateFor(lowScoreResult).actions')), ['notInteracted'],
    'not-interacted is mutually exclusive with reported actions');
  run('guidanceStateFor(lowScoreResult).expected = "no"; guidanceStateFor(lowScoreResult).verified = "unsure"');
  assert.match(run('guidanceRecommendations(guidanceStateFor(lowScoreResult)).join(" ")'), /You were not expecting it/,
    'unexpected and uncertain context produces cautious advice');
  run('lang = "taglish"');
  assert.match(run('guidanceRecommendations(guidanceStateFor(lowScoreResult)).join(" ")'), /Hindi mo ito inaasahan/,
    'guidance is available in Taglish');
  run('var independentGuidance = {message:"second result"}; guidanceStateFor(independentGuidance)');
  assert.equal(run('guidanceStateFor(independentGuidance).expected'), null,
    'one result does not inherit another result’s answers');
  run('lang = "en"; renderSafetyGuidance(guidanceMount, lowScoreResult, "unit")');
  assert.equal(descendants(run('guidanceMount.childNodes[0]')).find(node => node.tagName === 'input' && node.dataset.guidanceField === 'sensitive' && node.value === 'yes').checked, true,
    'rerendering in a new language keeps the same result’s in-memory answers');
  const copyButton = descendants(run('guidanceMount.childNodes[0]')).find(node => node.tagName === 'button');
  await copyButton.listeners.click();
  assert.doesNotMatch(copiedClipboard, /private SMS fixture|\byes\b|\bno\b|not sure/i,
    'copying guidance excludes message text and literal answer values');
  const copyStatus = descendants(run('guidanceMount.childNodes[0]')).find(node => node.tagName === 'span');
  assert.match(copyStatus.textContent, /Message text and your answers were not copied/);
  assert.deepEqual([...storedValues.keys()], [], 'guidance does not write preferences or answers to localStorage');

  run('$("message-input").value = "old"; var oldRequest = runCheck(); invalidateSingle();');
  run('pending.shift().resolve({message: "old"})');
  await run('oldRequest');
  assert.equal(run('rendered.length'), 0, 'cleared request must not restore results');
  run(`$("message-input").value = "tab stale"; var tabPending = runCheck(); selectTab(tabs[1]);`);
  assert.equal(run('$("btn-check").disabled'), false, 'leaving the single tab releases its busy state');
  run('pending.shift().resolve({message: "tab stale"})');
  await run('tabPending');
  assert.equal(run('rendered.length'), 0, 'a response from a tab left mid-request must be discarded');
  run('$("message-input").value = "new"; var first = runCheck(); var second = runCheck();');
  run('pending.shift().reject(new Error("stale error"))');
  await run('first');
  assert.equal(run('$("btn-check").disabled'), true, 'old finally must not unlock newer request');
  run('pending.shift().resolve({message: "new"})');
  await run('second');
  assert.equal(run('rendered.join()'), 'new');
  assert.equal(JSON.stringify(requests.at(-1)), JSON.stringify({path: '/analyze', body: {message: 'new'}}),
    'analysis requests contain only the message field, never checklist context');
  run('selectTab(tabs[1])');
  assert.equal(run('rendered.join()'), 'new', 'leaving a completed request must preserve its result');
  run('$("batch-input").value = "old batch"; var batch = runBatch(); invalidateBatch(); pending.shift().resolve({results:[{message:"old batch"}]});');
  await run('batch');
  assert.equal(run('rendered.join()'), 'new', 'edited batch must discard old results');
  run('$("batch-input").value = Array(21).fill("x".repeat(10000)).join("\\n"); var oversizedBatch = runBatch();');
  await run('oversizedBatch');
  assert.equal(run('pending.length'), 0, 'oversized batches must not be sent');
  run('$("batch-input").value = Array(11).fill("sample").join("\\n"); var progressBatch = runBatch();');
  assert.match(run('$("batch-progress").textContent'), /0 of 11/);
  run('pending.shift().resolve({results:Array(10).fill({message:"sample"})})');
  await Promise.resolve();
  assert.equal(run('pending.length'), 1, 'the next chunk starts only after the first completes');
  assert.match(run('$("batch-progress").textContent'), /10 of 11/);
  run('pending.shift().resolve({results:[{message:"sample"}]})');
  await run('progressBatch');
  assert.match(run('$("batch-progress").textContent'), /11 of 11/);
  run('renderHighlighted({message:"😀 BDO now", matches:[{type:"brand",start:2,end:5}]})');
  assert.equal(run('$("highlighted").childNodes[1].tagName'), 'mark');
  assert.equal(run('$("highlighted").childNodes[1].childNodes[0].textContent'), 'BDO');
  assert.equal(run('$("highlighted").childNodes.map(n => n.textContent).join("")'), '😀 BDO now');
  run(`var signalMessage = "😀 BDO.example now";
    renderHighlighted({message:signalMessage,matches:[
      {type:"url",start:2,end:13},{type:"brand",start:2,end:5},
      {type:"url",start:20,end:30},{type:"fake",start:0,end:2}
    ]});
    renderSignals({message:signalMessage,matches:[
      {type:"url",start:2,end:13},{type:"brand",start:2,end:5},
      {type:"url",start:20,end:30},{type:"fake",start:0,end:2}
    ]});`);
  assert.equal(run('$("highlighted").childNodes.map(n => n.textContent).join("")'), '😀 BDO.example now');
  assert.equal(run('$("highlighted").childNodes[1].attributes["aria-describedby"]'), 'signal-1 signal-2');
  assert.equal(run('$("signals").childNodes.length'), 2, 'one detail row per valid match');
  assert.equal(run('$("signals").childNodes[0].childNodes[0].textContent'), '1');
  assert.equal(run('$("signals").childNodes[0].childNodes[0].attributes["aria-label"]'), 'Signal 1');
  assert.equal(run('$("signals").childNodes[0].childNodes[2].textContent'),
    'A brand is mentioned. This does not verify the sender or prove impersonation.');
  assert.equal(run('$("signals").childNodes[0].childNodes[3].textContent'), 'BDO');
  assert.equal(run('$("signals").childNodes[1].childNodes[3].textContent'), 'BDO.example');
  run(`renderHighlighted({message:"<img src=x onerror=alert(1)>",matches:[]});
    renderSignals({message:"<img src=x onerror=alert(1)>",matches:[]});`);
  assert.equal(run('$("highlighted").childNodes[0].textContent'), '<img src=x onerror=alert(1)>');
  assert.equal(run('$("highlighted").childNodes[0].tagName'), undefined, 'SMS markup stays a text node');
  assert.match(run('$("signals").childNodes[0].textContent'), /No supported text patterns/);
  assert.match(run('signalSummary({message:"Link link",matches:[{type:"url",start:0,end:4},{type:"url",start:5,end:9}]})'), /Link ×2/);
  run('$("message-input").value = "😀"; updateCharCount()');
  assert.equal(run('$("char-count").textContent'), '1 / 10000');
  run('var demoChecks = 0; runCheck = () => { demoChecks += 1; }; initSingleCheck();');
  exampleChips[0].listeners.click();
  const firstScamExample = run('$("message-input").value');
  exampleChips[0].listeners.click();
  assert.notEqual(run('$("message-input").value'), firstScamExample,
    'repeated scam clicks should load a different example');
  assert.equal(run('EXAMPLES.scam.length'), 20, 'the scam example set should contain 20 messages');
  assert.equal(run('new Set(EXAMPLES.scam).size'), 20, 'scam examples should not be duplicated');
  assert.match(run('$("example-status").textContent'), /scam message 2 of 20/);
  for (let index = 0; index < 18; index += 1) exampleChips[0].listeners.click();
  assert.match(run('$("example-status").textContent'), /scam message 20 of 20/);
  exampleChips[0].listeners.click();
  assert.match(run('$("example-status").textContent'), /scam message 1 of 20/, 'scam examples should wrap around');
  exampleChips[1].listeners.click();
  assert.equal(run('EXAMPLES.safe.length'), 20, 'the safe example set should contain 20 messages');
  assert.equal(run('new Set(EXAMPLES.safe).size'), 20, 'safe examples should not be duplicated');
  assert.match(run('$("example-status").textContent'), /safe message 1 of 20/);
  assert.equal(run('demoChecks'), 22, 'each example click should trigger analysis');
  run('lang = "en"; renderMeter({spam_probability:0.35,probability_calibrated:true,prediction:"ham",risk_band:"looks_safe"})');
  assert.equal(run('$("risk-meter").getAttribute("aria-label")'), 'Calibrated spam score');
  assert.match(run('$("risk-meter").getAttribute("aria-valuetext")'), /calibrated spam score/);
  run('lang = "taglish"; renderMeter({spam_probability:0.35,probability_calibrated:false,prediction:"ham",risk_band:"looks_safe"})');
  assert.equal(run('$("risk-meter").getAttribute("aria-label")'), 'Uncalibrated na spam model score');

  run('window.currentAnalysis = {probability_calibrated:true}; modelInfo.probability_calibrated = false; lang = "en"; renderModelInfo(window.currentAnalysis)');
  assert.equal(run('$("risk-meter").getAttribute("aria-label")'), 'Calibrated spam score',
    'late metadata rendering must not overwrite the displayed result interpretation');
  run('modelInfo.model_version = "late-model"; modelInfo.decision_threshold = 0.9; modelInfo.suspicious_threshold = 0.8; modelInfo.bands = {likely_scam:0.9,suspicious:0.8,looks_safe:0}; window.currentAnalysis = {model_version:"result-model", decision_threshold:0.65, suspicious_threshold:0.35, probability_calibrated:true, spam_probability:0.7, prediction:"spam", risk_band:"likely_scam"}; renderModelInfo(window.currentAnalysis); renderMeter(window.currentAnalysis)');
  assert.match(run('$("model-version").textContent'), /result-model/);
  assert.match(run('$("model-thresholds").textContent'), /65%/);
  assert.match(run('$("model-thresholds").textContent'), /35%/);
  assert.match(run('buildSummaryText(window.currentAnalysis)'), /Model version: result-model/);
  assert.match(run('buildSummaryText(window.currentAnalysis)'), /Decision threshold: 65%/);
  assert.match(run('buildSummaryText(window.currentAnalysis)'), /Suspicious band threshold: 35%/);
  run('historyEnabled = true; modelInfo.model_version = "m1"; addHistory({message:"fixture", prediction:"spam", spam_probability:0.9, probability_calibrated:true, model_version:"m1", risk_band:"likely_scam"}, "single", {render:false}); var savedEntry = loadHistory()[0]');
  assert.equal(run('savedEntry.probability_calibrated'), true, 'history must preserve score calibration state');
  assert.equal(run('savedEntry.model_version'), 'm1', 'history must preserve model version');
  assert.match(run('scoreLabel(savedEntry)'), /calibrated spam score/);
  run('lang = "taglish"; renderModelInfo(window.currentAnalysis)');
  assert.equal(run('$("risk-meter").getAttribute("aria-label")'), 'Calibrated na spam score',
    'language changes must preserve the displayed result calibration state');
  run('lang = "en"; currentTheme = "light"; toggleTheme()');
  assert.equal(run('currentTheme'), 'dark');
  assert.equal(run('document.documentElement.getAttribute("data-theme")'), 'dark');
  assert.equal(run('localStorage.getItem(THEME_KEY)'), 'dark', 'dark preference should persist');
  assert.equal(run('$("btn-theme").textContent'), '☀️');
  assert.equal(run('$("btn-theme").getAttribute("aria-label")'), 'Switch to light mode');
  run('toggleTheme()');
  assert.equal(run('currentTheme'), 'light');
  assert.equal(run('document.documentElement.getAttribute("data-theme")'), 'light');
  assert.equal(run('localStorage.getItem(THEME_KEY)'), 'light', 'light preference should persist');
  assert.equal(run('$("btn-theme").textContent'), '🌙');
  assert.equal(run('$("btn-theme").getAttribute("aria-label")'), 'Switch to dark mode');
  storedValues.set('smsd_theme_v1', 'auto');
  assert.equal(run('readTheme()'), 'light', 'legacy auto setting should resolve to the two-mode default');
  assert.equal(run('pct(null)'), 'Unavailable', 'missing result thresholds and scores must not display 0%');
  assert.equal(run('scoreLabel({})'), 'score interpretation unavailable', 'legacy entries without calibration metadata remain explicit');
  run('modelInfoLoaded = true; modelInfo.model_version = "current"; window.currentAnalysis = {model_version:"old", spam_probability:0.8, probability_calibrated:true}; renderModelInfo(window.currentAnalysis)');
  assert.match(run('$ ("model-note").textContent'), /provenance is unavailable/);
  assert.equal(run('bandsForAnalysis(window.currentAnalysis)'), null, 'a different model must not lend thresholds to a historical result');

  run(`modelInfoLoaded = true; modelInfo.model_version = "compare-v1"; modelInfo.decision_threshold = 0.6;
    modelInfo.suspicious_threshold = 0.4; modelInfo.bands = {likely_scam:0.6,suspicious:0.4,looks_safe:0};
    modelInfo.data_note = "Matching model provenance."; modelInfo.warnings = [];
    initComparison();
    const left = {message:"😀 <img src=x>", prediction:"spam", spam_probability:0.8, probability_calibrated:true,
      decision_threshold:0.6, suspicious_threshold:0.4, model_version:"compare-v1", risk_band:"likely_scam",
      matches:[{type:"brand",start:3,end:7}], flags:[], brands:[]};
    const right = {message:"Safe fixture", prediction:"ham", spam_probability:0.2, probability_calibrated:true,
      decision_threshold:0.6, suspicious_threshold:0.4, model_version:"compare-v1", risk_band:"looks_safe",
      matches:[], flags:[], brands:[]};
    $("compare-message-a").value=left.message; $("compare-message-b").value=right.message;
    var comparePromise = runComparison();`);
  assert.equal(run('pending.length'), 1, 'comparison submits both messages through one batch request');
  run('pending.shift().resolve({results:[left,right]})');
  await run('comparePromise');
  assert.equal(run('$ ("compare-result-cards").childNodes.length'), 2, 'both cards render only after complete response');
  assert.match(run('$ ("compare-summary").textContent'), /60.0 percentage points/);
  assert.equal(run('compareScoreInterpretation(left,{...right,probability_calibrated:false})'), false,
    'different calibration states cannot be compared directly');
  assert.equal(run('$ ("compare-signal-differences").childNodes.length'), 1, 'detected signal differences render');
  assert.equal(run('$ ("compare-result-cards").childNodes[0].childNodes[6].childNodes.map(n => n.textContent).join("")'), '😀 <img src=x>',
    'comparison message content remains intact when safely highlighted');
  assert.equal(run('$ ("compare-result-cards").childNodes[0].childNodes[6].childNodes.some(n => n.tagName === "img")'), false,
    'untrusted message markup is never parsed as an element');
  run('renderComparison([left,{...right,model_version:"other-model"}])');
  assert.match(run('$ ("compare-summary").textContent'), /cannot be compared directly/);
  assert.equal(run('compareScoreInterpretation({...left,model_version:"unknown"},{...right,model_version:"unknown"})'), false,
    'unknown model versions are not considered compatible');
  run('lang = "taglish"; renderComparison([left,right])');
  assert.match(run('$ ("compare-summary").textContent'), /Pagkakaiba ng score/);
  run('lang = "en"; $("compare-message-a").value = "stale"; var pendingCompare = runComparison(); selectTab(tabs[0]); pending.shift().resolve({results:[left,right]});');
  await run('pendingCompare');
  assert.equal(run('$ ("compare-results").classList.contains("hidden")'), true, 'clearing while pending suppresses a stale comparison');
  assert.equal(run('compareAbortController'), null, 'tab switching aborts the pending comparison');
  run('$ ("offline-banner").classList.add("hidden"); apiAvailable = null; fetch = async () => { throw new TypeError("failed to fetch"); }; var apiFailure = requestJson("/model-info");');
  let apiFailure;
  try { await run('apiFailure'); } catch (error) { apiFailure = error; }
  assert.equal(apiFailure.apiUnavailable, true, 'a failed API request is reported as an API failure');
  assert.equal(apiFailure.offline, undefined, 'an API request failure is not labeled as browser offline status');
  assert.equal(run('$ ("offline-banner").classList.contains("hidden")'), true,
    'an API request failure does not show the browser offline banner');
  assert.equal(run('$ ("api-status").dataset.state'), 'error', 'the API status announces request reachability');
  run('selectTab(tabs[2]); $("compare-message-a").value="A"; $("compare-message-b").value="B"; var partialCompare = runComparison(); pending.shift().resolve({results:[left]});');
  await run('partialCompare');
  assert.equal(run('$ ("compare-results").classList.contains("hidden")'), true, 'incomplete response is never shown as a complete comparison');
  assert.match(run('$ ("compare-error").textContent'), /no partial comparison/);
  run('$ ("compare-message-a").value="A"; $("compare-message-b").value="B"; initComparison(); $("btn-compare-swap").listeners.click();');
  assert.equal(run('$ ("compare-message-a").value'), 'B', 'swap exchanges the two inputs');
  run('$ ("btn-compare-clear").listeners.click()');
  assert.equal(run('$ ("compare-message-a").value + $("compare-message-b").value'), '', 'clear-all empties both inputs');
  run('invalidateSingle()');
  assert.equal(run('$("highlighted").childNodes.length'), 0, 'editing invalidates stale highlights');
  assert.equal(run('$("signals").childNodes.length'), 0, 'editing clears stale signal details');
  run(`$("history-status").textContent = "old language announcement";
    $("copy-status").textContent = "Copied!"; setLanguage("taglish");`);
  assert.equal(run('$("history-status").textContent'), '', 'language changes clear stale history announcements');
  assert.equal(run('$("copy-status").textContent'), '', 'language changes clear stale copy status');
  assert.equal(busyCheckButton.textContent, 'Sinusuri…', 'busy labels change language immediately');
  run('setBusy(busyCheckButton, false, t("check.run"))');
  assert.equal(busyCheckButton.textContent, 'I-check ang mensahe ayon sa pagkakasulat', 'busy buttons return to the translated idle label');
})().catch(error => { console.error(error); process.exitCode = 1; });
