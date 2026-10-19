/* PH SMS Scam Detector — UI logic (no build step, vanilla JS). */
"use strict";

/* Endpoints served by api/main.py. Keep this list in sync with the API routes;
   tests/test_web_contract.py asserts every path here exists on the API. */
const API = {
  modelInfo: "/model-info",
  analyze: "/analyze",
  analyzeBatch: "/analyze/batch",
};

const HISTORY_KEY = "smsd_history_v1";
const HISTORY_PREF_KEY = "smsd_history_enabled_v1";
const HISTORY_LIMIT = 50;
const BATCH_LIMIT = 50;
const MAX_MESSAGE_LENGTH = 10000;

const SYNTHETIC_DATA_NOTE =
  "This model is trained and evaluated on synthetic Philippine data; it is not proof of real-world accuracy. Treat every verdict as a hint, not a fact.";
const HISTORY_OFF_NOTE =
  "History is off. Turn it on to keep the last 50 checks in this browser.";

/* Fallback thresholds mirror the API default; the authoritative values are
   fetched from GET /model-info on load (decision_threshold, suspicious_threshold
   and the risk `bands`). These constants only cover a metadata fetch failure. */
const FALLBACK_BANDS = { likely_scam: 0.7, suspicious: 0.4, looks_safe: 0.0 };
const FALLBACK_MODEL_INFO = {
  model_version: "unknown",
  decision_threshold: 0.5,
  suspicious_threshold: 0.4,
  bands: { ...FALLBACK_BANDS },
  data_note: SYNTHETIC_DATA_NOTE,
};

/* API risk_band -> presentation. Titles/icons live here so every view is
   consistent; cutoffs always come from modelInfo.bands. */
const BAND_VIEW = {
  likely_scam: { css: "spam", title: "Likely scam", icon: "🚨" },
  suspicious: { css: "suspicious", title: "Suspicious", icon: "⚠️" },
  looks_safe: { css: "safe", title: "Looks safe", icon: "✅" },
};

const SIGNALS = {
  url: { label: "Link" },
  phone: { label: "Phone number" },
  money: { label: "Money amount" },
  urgency: { label: "Urgency" },
  brand: { label: "Brand mention" },
};

const SIGNAL_SHORT = { url: "link", phone: "phone", money: "₱", urgency: "urgent", brand: "brand" };

const BRANDS = {
  bdo: "BDO", bpi: "BPI", metrobank: "Metrobank", unionbank: "UnionBank", rcbc: "RCBC",
  pnb: "PNB", landbank: "Landbank", gcash: "GCash", maya: "Maya", paymaya: "PayMaya",
  shopeepay: "ShopeePay", shopee: "Shopee", lazada: "Lazada", foodpanda: "foodpanda",
  lbc: "LBC", "j&t": "J&T Express", philpost: "PhilPost", meralco: "Meralco",
  maynilad: "Maynilad", pldt: "PLDT", globe: "Globe", pcso: "PCSO", dswd: "DSWD",
  sss: "SSS", philhealth: "PhilHealth", lto: "LTO", "pag-ibig": "Pag-IBIG", gma: "GMA",
  netflix: "Netflix", paypal: "PayPal", facebook: "Facebook", samsung: "Samsung",
  iphone: "iPhone", cebuana: "Cebuana Lhuillier",
};

const EXAMPLES = {
  scam: "BDO: Your account will be PERMANENTLY LOCKED in 24 hours. Verify now at http://bdo-secure-ph.xyz/login or call 09171234567 immediately.",
  safe: "Your BDO OTP is 294831. Do not share this code with anyone.",
};

const $ = (id) => document.getElementById(id);

let modelInfo = normalizeModelInfo(FALLBACK_MODEL_INFO);
let historyEnabled = false;

/* ---------- Small helpers ---------- */
function numberOr(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function pct(value) {
  return `${Math.round(numberOr(value, 0) * 100)}%`;
}

function prefersReducedMotion() {
  return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

function normalizeModelInfo(info) {
  const safe = info && typeof info === "object" ? info : {};
  const bands = safe.bands && typeof safe.bands === "object" ? safe.bands : {};
  const dataNote = typeof safe.data_note === "string" && safe.data_note.trim()
    ? safe.data_note.trim()
    : SYNTHETIC_DATA_NOTE;
  return {
    raw: safe,
    model_version: typeof safe.model_version === "string" && safe.model_version
      ? safe.model_version
      : FALLBACK_MODEL_INFO.model_version,
    decision_threshold: numberOr(safe.decision_threshold, FALLBACK_MODEL_INFO.decision_threshold),
    suspicious_threshold: numberOr(safe.suspicious_threshold, FALLBACK_MODEL_INFO.suspicious_threshold),
    bands: {
      likely_scam: numberOr(bands.likely_scam, numberOr(safe.decision_threshold, FALLBACK_BANDS.likely_scam)),
      suspicious: numberOr(bands.suspicious, numberOr(safe.suspicious_threshold, FALLBACK_BANDS.suspicious)),
      looks_safe: numberOr(bands.looks_safe, FALLBACK_BANDS.looks_safe),
    },
    data_note: dataNote,
  };
}

/* ---------- API access ---------- */
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
  if (response.status === 503) {
    return "The model is not available on this server. If you run this project locally, train it with: python -m src.train";
  }
  return `Request failed (HTTP ${response.status}). Please try again.`;
}

async function parseResponse(response) {
  let data = null;
  try {
    data = await response.json();
  } catch {
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

async function requestJson(path, options) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    const failure = new Error("Could not reach the detector API. Check that the server is running and try again.");
    failure.offline = true;
    throw failure;
  }
  return parseResponse(response);
}

function postJson(path, body) {
  return requestJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function describeError(failure) {
  if (!failure) return "Something went wrong. Please try again.";
  let message = failure.message || "Something went wrong. Please try again.";
  const modelUnavailable = failure.status === 503 || failure.code === "model_unavailable";
  if (modelUnavailable && !message.includes("src.train")) {
    message += " If you run this project locally, train the model with: python -m src.train";
  }
  return message;
}

/* ---------- Status banners ---------- */
function showBanner(banner, message) {
  banner.textContent = message;
  banner.classList.remove("hidden");
}

function hideBanner(banner) {
  banner.textContent = "";
  banner.classList.add("hidden");
}

function setBusy(button, busy, busyLabel) {
  if (busy) {
    if (!button.dataset.idleLabel) button.dataset.idleLabel = button.textContent;
    button.textContent = busyLabel;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    return;
  }
  button.textContent = button.dataset.idleLabel || button.textContent;
  button.disabled = false;
  button.removeAttribute("aria-busy");
}

/* ---------- Tabs (ARIA tablist with arrow/Home/End navigation) ---------- */
function tabElements() {
  return Array.from(document.querySelectorAll('[role="tab"]'));
}

function selectTab(tab) {
  const name = tab.dataset.tab;
  for (const candidate of tabElements()) {
    const selected = candidate === tab;
    candidate.classList.toggle("active", selected);
    candidate.setAttribute("aria-selected", String(selected));
    candidate.tabIndex = selected ? 0 : -1;
  }
  for (const panel of document.querySelectorAll(".panel")) {
    const active = panel.id === `panel-${name}`;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  }
}

function switchTab(name) {
  const tab = tabElements().find((candidate) => candidate.dataset.tab === name);
  if (tab) selectTab(tab);
}

function initTabs() {
  const tabs = tabElements();
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (event) => {
      let nextIndex = null;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") nextIndex = 0;
      else if (event.key === "End") nextIndex = tabs.length - 1;
      if (nextIndex === null) return;
      event.preventDefault();
      const next = tabs[nextIndex];
      next.focus();
      selectTab(next);
    });
  });
  if (tabs.length) selectTab(tabs[0]);
}

/* ---------- Model information ---------- */
function renderModelInfo() {
  $("model-version").textContent = `Model version: ${modelInfo.model_version}`;
  $("model-note").textContent = modelInfo.data_note;
  $("model-thresholds").textContent =
    `Decision threshold ${pct(modelInfo.decision_threshold)} · risk bands: likely scam ≥ ` +
    `${pct(modelInfo.bands.likely_scam)}, suspicious ≥ ${pct(modelInfo.bands.suspicious)}.`;
}

async function loadModelInfo() {
  const warning = $("model-warning");
  try {
    const info = await requestJson(API.modelInfo);
    modelInfo = normalizeModelInfo(info);
    warning.textContent = "";
    warning.classList.add("hidden");
  } catch (failure) {
    modelInfo = normalizeModelInfo(FALLBACK_MODEL_INFO);
    warning.textContent =
      `${describeError(failure)} Using built-in fallback thresholds until model information is available.`;
    warning.classList.remove("hidden");
  }
  renderModelInfo();
}

/* ---------- Banding ---------- */
function bandFromProbability(probability) {
  const value = numberOr(probability, 0);
  if (value >= modelInfo.bands.likely_scam) return "likely_scam";
  if (value >= modelInfo.bands.suspicious) return "suspicious";
  return "looks_safe";
}

/* Prefer the API's own verdict band and fall back to the thresholds. */
function bandOf(analysis) {
  if (analysis && typeof analysis.risk_band === "string" && BAND_VIEW[analysis.risk_band]) {
    return analysis.risk_band;
  }
  return bandFromProbability(analysis ? analysis.spam_probability : 0);
}

function bandView(band) {
  return BAND_VIEW[band] || BAND_VIEW.looks_safe;
}

/* ---------- Single-check rendering ---------- */
function renderVerdict(analysis) {
  const band = bandOf(analysis);
  const view = bandView(band);
  $("verdict-card").className = `card verdict ${view.css}`;
  $("verdict-icon").textContent = view.icon;
  $("verdict-title").textContent = view.title;
  const confidence = typeof analysis.confidence === "string" ? analysis.confidence : "unknown";
  const decisionThreshold = numberOr(analysis.decision_threshold, modelInfo.decision_threshold);
  $("verdict-sub").textContent =
    `${pct(analysis.spam_probability)} scam probability · model verdict: ${analysis.prediction} · ` +
    `${confidence} confidence · decision threshold ${pct(decisionThreshold)}`;
}

function renderMeter(analysis) {
  const probability = numberOr(analysis.spam_probability, 0);
  const value = Math.round(probability * 100);
  const band = bandOf(analysis);
  const meter = $("risk-meter");
  meter.style.setProperty("--suspect", `${Math.round(modelInfo.bands.suspicious * 100)}%`);
  meter.style.setProperty("--scam", `${Math.round(modelInfo.bands.likely_scam * 100)}%`);
  meter.setAttribute("aria-valuenow", String(value));
  meter.setAttribute("aria-valuetext", `${value}% estimated scam probability — ${bandView(band).title}`);
  $("meter-marker").style.left = `${value}%`;
  const output = $("meter-value");
  output.textContent = `${value}%`;
  output.style.color = { spam: "var(--red)", suspicious: "var(--amber)", safe: "var(--green)" }[bandView(band).css];
}

function renderHighlighted(analysis) {
  const container = $("highlighted");
  const message = typeof analysis.message === "string" ? analysis.message : "";
  container.replaceChildren();
  const matches = Array.isArray(analysis.matches) ? analysis.matches : [];
  let position = 0;
  for (const match of matches) {
    const start = numberOr(match.start, -1);
    const end = numberOr(match.end, -1);
    if (start < position || end <= start || end > message.length) continue;
    if (start > position) container.append(document.createTextNode(message.slice(position, start)));
    const mark = document.createElement("mark");
    mark.className = `sig sig-${match.type}`;
    mark.textContent = message.slice(start, end);
    mark.title = `${(SIGNALS[match.type] && SIGNALS[match.type].label) || match.type} signal`;
    container.append(mark);
    position = end;
  }
  if (position < message.length) container.append(document.createTextNode(message.slice(position)));
  if (!container.childNodes.length) container.append(document.createTextNode(message));
}

function renderSignals(analysis) {
  const container = $("signals");
  container.replaceChildren();
  const matches = Array.isArray(analysis.matches) ? analysis.matches : [];
  const counts = {};
  for (const match of matches) counts[match.type] = (counts[match.type] || 0) + 1;
  const dotColor = { url: "#2563eb", phone: "#7c3aed", money: "#d97706", urgency: "#dc2626", brand: "#db2777" };
  for (const [type, count] of Object.entries(counts)) {
    const chip = document.createElement("span");
    chip.className = `chip chip-${type}`;
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = dotColor[type] || "#94a3b8";
    const label = (SIGNALS[type] && SIGNALS[type].label) || type;
    chip.append(dot, document.createTextNode(`${label}${count > 1 ? ` ×${count}` : ""}`));
    container.append(chip);
  }
  const brands = Array.isArray(analysis.brands) ? analysis.brands : [];
  if (brands.length) {
    const names = brands.map((brand) => BRANDS[brand] || String(brand).toUpperCase()).join(", ");
    const brandChip = document.createElement("span");
    const risky = bandOf(analysis) !== "looks_safe";
    brandChip.className = `chip ${risky ? "chip-brands-warn" : "chip-brand"}`;
    brandChip.textContent = risky ? `⚠ Possibly impersonating ${names}` : `Mentions: ${names}`;
    container.append(brandChip);
  }
  if (!container.childNodes.length) {
    const clean = document.createElement("span");
    clean.className = "chip chip-clean";
    clean.textContent = "No classic scam markers — verdict comes from the model's text analysis";
    container.append(clean);
  }
}

function buildTips(analysis) {
  const tips = [];
  const flags = new Set(Array.isArray(analysis.flags) ? analysis.flags : []);
  const risky = bandOf(analysis) !== "looks_safe";
  const brands = Array.isArray(analysis.brands) ? analysis.brands : [];
  const brandNames = brands.map((brand) => BRANDS[brand] || String(brand).toUpperCase());
  if (risky) {
    tips.push("Do not reply, tap links, or call the number in this message.");
    if (brandNames.length) {
      tips.push(`Scammers impersonate ${brandNames.join(", ")} — verify any account claim in the official app or via the hotline on their website, never a number or link from this message.`);
    }
  }
  if (flags.has("has_url")) tips.push("Don't open links from unexpected texts. Open the official app or type the address yourself.");
  if (flags.has("has_money")) tips.push("Real prizes or refunds are never released in exchange for a fee, gift cards, or account details.");
  if (flags.has("has_phone")) tips.push("Replying or calling back confirms your number is active and invites more scam texts.");
  if (flags.has("has_urgency")) tips.push("Pressure to act right now is a classic scam tactic — slow down and double-check first.");
  tips.push("Never share OTPs, PINs, or passwords — banks and e-wallets will never ask for them.");
  if (!risky) tips.push("Even safe-looking senders can be spoofed; confirm money or account changes through the official channel.");
  return tips;
}

function renderTips(analysis) {
  const list = $("tips");
  list.replaceChildren();
  list.className = `tips${bandOf(analysis) !== "looks_safe" ? " warn" : ""}`;
  for (const tip of buildTips(analysis)) {
    const item = document.createElement("li");
    item.textContent = tip;
    list.append(item);
  }
}

function renderAnalysis(analysis, { save = true } = {}) {
  $("result").classList.remove("hidden");
  renderVerdict(analysis);
  renderMeter(analysis);
  renderHighlighted(analysis);
  renderSignals(analysis);
  renderTips(analysis);
  if (save) addHistory(analysis);
}

/* ---------- History (browser-only, opt-in) ---------- */
function readHistoryPreference() {
  try {
    return localStorage.getItem(HISTORY_PREF_KEY) === "1";
  } catch {
    return false;
  }
}

function persistHistoryPreference(enabled) {
  try {
    localStorage.setItem(HISTORY_PREF_KEY, enabled ? "1" : "0");
  } catch {
    /* Storage may be unavailable (private mode / disabled); history stays off. */
  }
}

function clearStoredHistory() {
  try {
    localStorage.removeItem(HISTORY_KEY);
  } catch {
    /* ignore */
  }
}

function loadHistory() {
  if (!historyEnabled) return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((entry) => entry && typeof entry.message === "string");
  } catch {
    return [];
  }
}

function saveHistory(entries) {
  if (!historyEnabled) {
    clearStoredHistory();
    return [];
  }
  const trimmed = entries.slice(0, HISTORY_LIMIT);
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(trimmed));
  } catch {
    /* Ignore quota/storage errors; the UI must keep working. */
  }
  return trimmed;
}

function addHistory(analysis, source = "single", { render = true } = {}) {
  if (!historyEnabled) return;
  const entries = loadHistory();
  const newest = entries[0];
  const duplicate = newest &&
    newest.message === analysis.message &&
    newest.source === source &&
    Math.abs(numberOr(newest.spam_probability, -1) - numberOr(analysis.spam_probability, -2)) < 0.005;
  if (!duplicate) {
    entries.unshift({
      t: Date.now(),
      message: analysis.message,
      prediction: analysis.prediction,
      spam_probability: numberOr(analysis.spam_probability, 0),
      risk_band: bandOf(analysis),
      decision_threshold: numberOr(analysis.decision_threshold, modelInfo.decision_threshold),
      flags: Array.isArray(analysis.flags) ? analysis.flags : [],
      source,
    });
    saveHistory(entries);
  }
  if (render) {
    renderHistory();
    updateHistoryBadge();
    announceHistory(`Saved in this browser: ${loadHistory().length} of ${HISTORY_LIMIT} checks.`);
  }
}

function announceHistory(message) {
  $("history-status").textContent = message;
}

function updateHistoryBadge() {
  const count = historyEnabled ? loadHistory().length : 0;
  const badge = $("history-count");
  badge.textContent = String(count);
  badge.classList.toggle("hidden", count === 0);
}

function verdictPill(band) {
  const view = bandView(band);
  const pill = document.createElement("span");
  pill.className = `verdict-pill ${view.css}`;
  pill.textContent = view.title;
  return pill;
}

function miniMeter(probability) {
  const band = bandFromProbability(probability);
  const wrap = document.createElement("div");
  wrap.className = "mini-meter";
  const fill = document.createElement("div");
  fill.style.width = `${Math.round(numberOr(probability, 0) * 100)}%`;
  fill.style.background = { spam: "var(--red)", suspicious: "var(--amber)", safe: "var(--green)" }[bandView(band).css];
  wrap.append(fill);
  return wrap;
}

function openSavedEntry(entry) {
  $("message-input").value = entry.message;
  updateCharCount();
  switchTab("check");
  runCheck({ save: false });
}

function renderHistory() {
  const entries = historyEnabled ? loadHistory() : [];
  const list = $("history-list");
  list.replaceChildren();
  const empty = $("history-empty");
  empty.classList.toggle("hidden", entries.length > 0);
  empty.textContent = historyEnabled
    ? "No saved checks yet. Check a message and it will appear here."
    : HISTORY_OFF_NOTE;
  $("btn-clear-history").disabled = entries.length === 0;
  for (const entry of entries) {
    const band = BAND_VIEW[entry.risk_band] ? entry.risk_band : bandFromProbability(entry.spam_probability);
    const timestamp = new Date(numberOr(entry.t, Date.now())).toLocaleString();
    const item = document.createElement("li");
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.setAttribute("aria-label",
      `Reopen saved check from ${timestamp} — ${bandView(band).title}, ${pct(entry.spam_probability)} scam probability`);
    const main = document.createElement("div");
    main.className = "history-item-main";
    const message = document.createElement("div");
    message.className = "history-msg";
    message.textContent = entry.message;
    const meta = document.createElement("div");
    meta.className = "history-meta";
    meta.textContent = `${timestamp}${entry.source === "batch" ? " · batch" : ""}`;
    main.append(message, meta);
    const risk = document.createElement("span");
    risk.className = `history-risk ${bandView(band).css}`;
    risk.textContent = pct(entry.spam_probability);
    item.append(main, verdictPill(band), risk);
    item.addEventListener("click", () => openSavedEntry(entry));
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openSavedEntry(entry);
      }
    });
    list.append(item);
  }
}

function setHistoryEnabled(enabled) {
  historyEnabled = Boolean(enabled);
  persistHistoryPreference(historyEnabled);
  if (!historyEnabled) {
    clearStoredHistory();
    announceHistory("History is off. Any saved checks were deleted from this browser.");
  } else {
    announceHistory("History is on. Checks are saved only in this browser, up to 50 entries.");
  }
  renderHistory();
  updateHistoryBadge();
}

function initHistory() {
  historyEnabled = readHistoryPreference();
  $("history-optin").checked = historyEnabled;
  if (!historyEnabled) clearStoredHistory(); /* Default is OFF: purge any legacy data. */
  $("history-optin").addEventListener("change", (event) => setHistoryEnabled(event.target.checked));
  $("btn-clear-history").addEventListener("click", () => {
    if (!loadHistory().length) return;
    if (window.confirm("Delete all checks saved in this browser?")) {
      clearStoredHistory();
      renderHistory();
      updateHistoryBadge();
      announceHistory("Saved history cleared from this browser.");
    }
  });
  renderHistory();
  updateHistoryBadge();
}

/* ---------- Single check flow ---------- */
function updateCharCount() {
  $("char-count").textContent = `${$("message-input").value.length} / ${MAX_MESSAGE_LENGTH}`;
}

async function runCheck({ save = true } = {}) {
  const input = $("message-input");
  const message = input.value.trim();
  const banner = $("error-banner");
  hideBanner(banner);
  if (!message) {
    showBanner(banner, "Type or paste an SMS message first.");
    input.focus();
    return;
  }
  if (message.length > MAX_MESSAGE_LENGTH) {
    showBanner(banner, `That message is ${message.length} characters — the limit is ${MAX_MESSAGE_LENGTH}.`);
    return;
  }
  const button = $("btn-check");
  setBusy(button, true, "Checking…");
  try {
    const analysis = await postJson(API.analyze, { message });
    renderAnalysis(analysis, { save });
  } catch (failure) {
    showBanner(banner, describeError(failure));
  } finally {
    setBusy(button, false, "Check message");
  }
}

/* ---------- Batch flow ---------- */
function parseBatchInput() {
  return $("batch-input").value.split("\n").map((line) => line.trim()).filter(Boolean);
}

function updateBatchCount() {
  const messages = parseBatchInput();
  const count = messages.length;
  const characters = messages.reduce((total, message) => total + message.length, 0);
  $("batch-count").textContent =
    `${count} message${count === 1 ? "" : "s"} · ${characters.toLocaleString()} characters`;
}

async function runBatch() {
  const messages = parseBatchInput();
  const banner = $("batch-error");
  hideBanner(banner);
  if (!messages.length) {
    showBanner(banner, "Paste at least one message (one per line).");
    return;
  }
  if (messages.length > BATCH_LIMIT) {
    showBanner(banner, `Batch is limited to ${BATCH_LIMIT} messages — remove some lines and try again.`);
    return;
  }
  const oversized = messages.findIndex((message) => message.length > MAX_MESSAGE_LENGTH);
  if (oversized !== -1) {
    showBanner(banner, `Message ${oversized + 1} is longer than ${MAX_MESSAGE_LENGTH} characters.`);
    return;
  }
  const button = $("btn-batch");
  setBusy(button, true, "Checking…");
  try {
    const data = await postJson(API.analyzeBatch, { messages });
    const results = Array.isArray(data.results) ? data.results : [];
    renderBatch(results);
    if (historyEnabled) {
      for (const analysis of results) addHistory(analysis, "batch", { render: false });
      renderHistory();
      updateHistoryBadge();
      announceHistory(`Saved in this browser: ${loadHistory().length} of ${HISTORY_LIMIT} checks.`);
    }
  } catch (failure) {
    showBanner(banner, describeError(failure));
  } finally {
    setBusy(button, false, "Check all");
  }
}

function openBatchResult(analysis) {
  $("message-input").value = analysis.message;
  updateCharCount();
  switchTab("check");
  renderAnalysis(analysis, { save: false });
}

function renderBatch(results) {
  const summary = $("batch-summary");
  const tbody = $("batch-tbody");
  summary.classList.remove("hidden");
  $("batch-results").classList.remove("hidden");
  tbody.replaceChildren();

  const stats = { likely_scam: 0, suspicious: 0, looks_safe: 0 };
  results.forEach((analysis, index) => {
    const band = bandOf(analysis);
    stats[band] += 1;

    const row = document.createElement("tr");
    row.tabIndex = 0;
    row.setAttribute("aria-label",
      `Message ${index + 1}: ${bandView(band).title}, ${pct(analysis.spam_probability)} scam probability. Press Enter to open the full analysis.`);
    const numberCell = document.createElement("td");
    numberCell.textContent = String(index + 1);
    const messageCell = document.createElement("td");
    messageCell.className = "batch-msg";
    messageCell.textContent = analysis.message;
    messageCell.title = analysis.message;
    const verdictCell = document.createElement("td");
    verdictCell.append(verdictPill(band));
    const riskCell = document.createElement("td");
    riskCell.className = "risk-cell";
    riskCell.append(miniMeter(analysis.spam_probability));
    const riskPct = document.createElement("span");
    riskPct.textContent = pct(analysis.spam_probability);
    riskCell.append(riskPct);
    const signalCell = document.createElement("td");
    const matches = Array.isArray(analysis.matches) ? analysis.matches : [];
    const types = [...new Set(matches.map((match) => match.type))];
    signalCell.textContent = types.map((type) => SIGNAL_SHORT[type] || type).join(" · ") || "—";

    row.append(numberCell, messageCell, verdictCell, riskCell, signalCell);
    row.addEventListener("click", () => openBatchResult(analysis));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openBatchResult(analysis);
      }
    });
    tbody.append(row);
  });

  $("stat-scam").textContent = String(stats.likely_scam);
  $("stat-suspicious").textContent = String(stats.suspicious);
  $("stat-safe").textContent = String(stats.looks_safe);
}

/* ---------- Wiring ---------- */
function initSingleCheck() {
  const input = $("message-input");
  input.addEventListener("input", updateCharCount);
  input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      runCheck();
    }
  });
  $("btn-check").addEventListener("click", () => runCheck());
  $("btn-clear").addEventListener("click", () => {
    input.value = "";
    updateCharCount();
    $("result").classList.add("hidden");
    hideBanner($("error-banner"));
    input.focus();
  });
  for (const chip of document.querySelectorAll(".example-chip")) {
    chip.addEventListener("click", () => {
      input.value = EXAMPLES[chip.dataset.example] || "";
      updateCharCount();
      runCheck();
    });
  }
  updateCharCount();
}

function initBatchCheck() {
  const input = $("batch-input");
  input.addEventListener("input", updateBatchCount);
  input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      runBatch();
    }
  });
  $("btn-batch").addEventListener("click", () => runBatch());
  updateBatchCount();
}

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initHistory();
  initSingleCheck();
  initBatchCheck();
  renderModelInfo();
  loadModelInfo();
});

/* Expose a tiny read-only hook for manual debugging in the console. */
window.phSmsd = { prefersReducedMotion, bandOf, modelInfo: () => modelInfo };
