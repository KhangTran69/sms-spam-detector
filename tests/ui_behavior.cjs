const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
function element(tagName = 'div') {
  const classes = new Set();
  let ownText = '';
  return { tagName, dataset: {}, value: '', disabled: false, childNodes: [], listeners: {}, attributes: {},
    get textContent() { return this.childNodes.length ? this.childNodes.map(child => child.textContent).join('') : ownText; },
    set textContent(value) { ownText = String(value); this.childNodes = []; },
    addEventListener(type, handler) { this.listeners[type] = handler; },
    classList: { add: c => classes.add(c), remove: c => classes.delete(c),
      contains: c => classes.has(c), toggle: (c, yes) => yes ? classes.add(c) : classes.delete(c) },
    setAttribute(name, value) { this.attributes[name] = String(value); },
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
const context = vm.createContext({ console, window: { matchMedia: () => ({matches: false}) },
  document: { getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    querySelectorAll(selector) { return selector === '.example-chip' ? exampleChips : []; },
    addEventListener() {}, createElement: tagName => element(tagName), createTextNode: text => ({ textContent: text }) } });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8'), context);
vm.runInContext(`
  var pending = [];
  var rendered = [];
  postJson = () => new Promise((resolve, reject) => pending.push({resolve, reject}));
  renderAnalysis = analysis => rendered.push(analysis.message);
  renderBatch = rows => rendered.push(rows[0].message);
`, context);
const run = code => vm.runInContext(code, context);
(async () => {
  run('$("message-input").value = "old"; var oldRequest = runCheck(); invalidateSingle();');
  run('pending.shift().resolve({message: "old"})');
  await run('oldRequest');
  assert.equal(run('rendered.length'), 0, 'cleared request must not restore results');
  run('$("message-input").value = "new"; var first = runCheck(); var second = runCheck();');
  run('pending.shift().reject(new Error("stale error"))');
  await run('first');
  assert.equal(run('$("btn-check").disabled'), true, 'old finally must not unlock newer request');
  run('pending.shift().resolve({message: "new"})');
  await run('second');
  assert.equal(run('rendered.join()'), 'new');
  run('$("batch-input").value = "old batch"; var batch = runBatch(); invalidateBatch(); pending.shift().resolve({results:[{message:"old batch"}]});');
  await run('batch');
  assert.equal(run('rendered.join()'), 'new', 'edited batch must discard old results');
  run('$("batch-input").value = Array(21).fill("x".repeat(10000)).join("\\n"); var oversizedBatch = runBatch();');
  await run('oversizedBatch');
  assert.equal(run('pending.length'), 0, 'oversized batches must not be sent');
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
  assert.match(run('$("example-status").textContent'), /scam example 2 of 6/);
  exampleChips[1].listeners.click();
  assert.match(run('$("example-status").textContent'), /safe example 1 of 6/);
  assert.equal(run('demoChecks'), 3, 'each example click should trigger analysis');
  run('invalidateSingle()');
  assert.equal(run('$("highlighted").childNodes.length'), 0, 'editing invalidates stale highlights');
  assert.equal(run('$("signals").childNodes.length'), 0, 'editing clears stale signal details');
})().catch(error => { console.error(error); process.exitCode = 1; });
