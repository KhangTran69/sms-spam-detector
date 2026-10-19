const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
function element() {
  const classes = new Set();
  return { dataset: {}, value: '', textContent: '', disabled: false, childNodes: [],
    classList: { add: c => classes.add(c), remove: c => classes.delete(c),
      contains: c => classes.has(c), toggle: (c, yes) => yes ? classes.add(c) : classes.delete(c) },
    setAttribute() {}, removeAttribute() {}, focus() {}, append(...nodes) { this.childNodes.push(...nodes); },
    replaceChildren() { this.childNodes = []; } };
}
const elements = new Map();
const context = vm.createContext({ console, window: { matchMedia: () => ({matches: false}) },
  document: { getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    addEventListener() {}, createElement: element, createTextNode: text => ({ textContent: text }) } });
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
  assert.equal(run('$("highlighted").childNodes[1].textContent'), 'BDO');
  assert.equal(run('$("highlighted").childNodes.map(n => n.textContent).join("")'), '😀 BDO now');
  run('$("message-input").value = "😀"; updateCharCount()');
  assert.equal(run('$("char-count").textContent'), '1 / 10000');
})().catch(error => { console.error(error); process.exitCode = 1; });
