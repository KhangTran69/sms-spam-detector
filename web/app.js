/* PH SMS Scam Detector — UI logic (no build step, vanilla JS). */
"use strict";

/* Endpoints served by api/main.py. Keep this list in sync with the API routes;
   tests/test_web_contract.py asserts every path here exists on the API. */
const API = {
  modelInfo: "/model-info",
  analyze: "/analyze",
  analyzeBatch: "/analyze/batch",
  feedback: "/feedback",
};

const HISTORY_KEY = "smsd_history_v1";
const HISTORY_PREF_KEY = "smsd_history_enabled_v1";
const HISTORY_LIMIT = 50;
const BATCH_LIMIT = 50;
const MAX_BATCH_CHARACTERS = 200000;
const MAX_MESSAGE_LENGTH = 10000;

const SYNTHETIC_DATA_NOTE =
  "Checks using synthetic Philippine data are not proof of real-world accuracy. Treat every verdict as a hint, not a fact.";
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
  url: { label: "Link", plural: "links", explanation: "Link-like text appears here. It may still be legitimate; check destinations independently." },
  phone: { label: "Phone number", plural: "phone numbers", explanation: "A phone number appears. This does not identify who sent the message." },
  money: { label: "Money amount", plural: "money amounts", explanation: "An amount appears. Legitimate bills and transaction alerts can include amounts." },
  urgency: { label: "Urgency wording", plural: "urgency phrases", explanation: "These words can add time pressure, but urgency alone does not prove a scam." },
  brand: { label: "Brand name", plural: "brand names", explanation: "A brand is mentioned. This does not verify the sender or prove impersonation." },
};
const isSignalType = (type) => Object.prototype.hasOwnProperty.call(SIGNALS, type);

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
  scam: [
    "BDO ALERT: Your account access will be suspended today. Confirm your details at bdo-verify.example to keep it active.",
    "Nanalo ka ng ₱50,000! I-claim agad sa prize-claim.example bago mag-expire ang promo.",
    "Delivery notice: May kulang na ₱35 fee. Bayaran ngayon sa parcel-pay.example para ma-release ang package.",
    "GCash security check: May unusual activity. I-verify ang wallet mo sa gcash-review.example ngayon.",
    "Work from home! Earn ₱8,000 kada araw. Send your ID and registration fee today to reserve your slot.",
    "SIM registration failed. I-update ang details mo sa sim-update.example within 2 hours para hindi ma-disable ang number.",
  ],
  safe: [
    "Your one-time code is [CODE]. Never share it with anyone, even someone claiming to be from your bank.",
    "BDO: Your transfer was completed. If you don't recognize it, check your account using the official app.",
    "Your parcel is out for delivery today. Track it in the official courier app. No payment is due by SMS.",
    "Meralco reminder: Your bill is ready. Please check the amount and due date in the official app.",
    "Reminder: Parent meeting is on Friday at 3 PM in the school library. Salamat po!",
    "Uy, kita tayo after class? I can bring the notes from yesterday. Message me when you're nearby.",
  ],
};
const EXAMPLE_INDEX = { scam: -1, safe: -1 };

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

function nextExample(kind) {
  const examples = EXAMPLES[kind];
  if (!examples) return null;
  const index = (EXAMPLE_INDEX[kind] + 1) % examples.length;
  EXAMPLE_INDEX[kind] = index;
  return { message: examples[index], index: index + 1, total: examples.length };
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
    feedback_enabled: safe.feedback_enabled === true,
    probability_calibrated: safe.probability_calibrated === true,
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
  const decisionThreshold = numberOr(analysis.decision_threshold, modelInfo.decision_threshold);
  const scoreLabel = analysis.probability_calibrated === true ? "estimated scam probability" : "uncalibrated model score";
  $("verdict-sub").textContent =
    `${pct(analysis.spam_probability)} ${scoreLabel} · model verdict: ${analysis.prediction} · ` +
    `decision threshold ${pct(decisionThreshold)}`;
}

function renderMeter(analysis) {
  const probability = numberOr(analysis.spam_probability, 0);
  const value = Math.round(probability * 100);
  const band = bandOf(analysis);
  const meter = $("risk-meter");
  meter.style.setProperty("--suspect", `${Math.round(modelInfo.bands.suspicious * 100)}%`);
  meter.style.setProperty("--scam", `${Math.round(modelInfo.bands.likely_scam * 100)}%`);
  meter.setAttribute("aria-valuenow", String(value));
  const scoreLabel = analysis.probability_calibrated === true ? "estimated scam probability" : "uncalibrated model score";
  meter.setAttribute("aria-valuetext", `${value}% ${scoreLabel} — ${bandView(band).title}`);
  $("meter-marker").style.left = `${value}%`;
  const output = $("meter-value");
  output.textContent = `${value}%`;
  output.style.color = { spam: "var(--red)", suspicious: "var(--amber)", safe: "var(--green)" }[bandView(band).css];
}

function renderHighlighted(analysis) {
  const container = $("highlighted");
  const message = typeof analysis.message === "string" ? analysis.message : "";
  const characters = Array.from(message); // API offsets count Unicode code points.
  container.replaceChildren();
  const matches = signalMatches(analysis, characters);
  const boundaries = [...new Set([0, characters.length, ...matches.flatMap(({ start, end }) => [start, end])])]
    .sort((left, right) => left - right);
  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const start = boundaries[index];
    const end = boundaries[index + 1];
    if (end <= start) continue;
    const text = characters.slice(start, end).join("");
    const active = matches.filter((match) => match.start <= start && match.end >= end);
    if (!active.length) {
      container.append(document.createTextNode(text));
      continue;
    }
    const types = [...new Set(active.map((match) => match.type))];
    const mark = document.createElement("mark");
    mark.className = `sig ${types.map((type) => `sig-${type}`).join(" ")}`;
    mark.setAttribute("aria-describedby", active.map((match) => `signal-${match.id}`).join(" "));
    // Keep the visual highlight free of numeric prefixes; the accessible
    // description still links it to the matching signal detail row.
    mark.append(document.createTextNode(text));
    container.append(mark);
  }
  if (!characters.length) container.append(document.createTextNode(""));
}

function signalMatches(analysis, characters) {
  const messageCharacters = characters || Array.from(
    analysis && typeof analysis.message === "string" ? analysis.message : "",
  );
  const matches = analysis && Array.isArray(analysis.matches) ? analysis.matches : [];
  return matches
    .filter((match) => match && isSignalType(match.type)
      && Number.isInteger(match.start) && Number.isInteger(match.end)
      && match.start >= 0 && match.end > match.start && match.end <= messageCharacters.length)
    .map((match) => ({
      type: match.type,
      start: match.start,
      end: match.end,
      text: messageCharacters.slice(match.start, match.end).join(""),
    }))
    .sort((left, right) => left.start - right.start || left.end - right.end)
    .map((match, index) => ({ ...match, id: index + 1 }));
}

function renderSignals(analysis) {
  const container = $("signals");
  container.replaceChildren();
  const message = typeof analysis.message === "string" ? analysis.message : "";
  const matches = signalMatches(analysis, Array.from(message));
  if (!matches.length) {
    const empty = document.createElement("li");
    empty.className = "signal-empty";
    empty.textContent = "No supported text patterns were detected. That alone does not mean the message is safe.";
    container.append(empty);
    return;
  }
  for (const match of matches) {
    const item = document.createElement("li");
    item.id = `signal-${match.id}`;
    item.className = `signal-item signal-item-${match.type}`;
    const reference = document.createElement("span");
    reference.className = "signal-reference";
    reference.setAttribute("aria-label", `Signal ${match.id}`);
    reference.textContent = String(match.id);
    const label = document.createElement("strong");
    label.textContent = SIGNALS[match.type].label;
    const explanation = document.createElement("span");
    explanation.className = "signal-explanation";
    explanation.textContent = SIGNALS[match.type].explanation;
    const example = document.createElement("q");
    example.className = "signal-match-text";
    example.textContent = match.text;
    item.append(reference, label, explanation, example);
    container.append(item);
  }
}

function signalSummary(analysis) {
  const matches = signalMatches(analysis);
  if (!matches.length) return "No supported text patterns";
  const counts = new Map();
  for (const match of matches) counts.set(match.type, (counts.get(match.type) || 0) + 1);
  return [...counts.entries()]
    .map(([type, count]) => `${SIGNALS[type].label}${count > 1 ? ` ×${count}` : ""}`)
    .join(" · ");
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
      tips.push(`This message mentions ${brandNames.join(", ")}; that does not verify who sent it. Confirm account claims in the official app or through a trusted contact channel.`);
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
  window.currentAnalysis = analysis;
  const feedbackForm = $("feedback-form");
  feedbackForm.classList.toggle("hidden", !modelInfo.feedback_enabled);
  $("feedback-status").textContent = "";
  setBusy($("btn-feedback"), false, "Send anonymous correction");
  if (modelInfo.feedback_enabled) {
    $("feedback-label").value = analysis.prediction === "spam" ? "ham" : "spam";
  }
  if (save) addHistory(analysis);
}

async function submitFeedback(event) {
  event.preventDefault();
  const status = $("feedback-status");
  const button = $("btn-feedback");
  const analysis = window.currentAnalysis;
  const expectedLabel = $("feedback-label").value;
  if (!analysis || !modelInfo.feedback_enabled) return;
  if (expectedLabel === analysis.prediction) {
    status.textContent = "Choose the label you think the model got wrong.";
    return;
  }
  setBusy(button, true, "Sending…");
  let sent = false;
  try {
    // Send only the user's selected label, category, and model version.
    // Never include the analyzed SMS or a saved history entry.
    const result = await postJson(API.feedback, {
      model_version: analysis.model_version,
      predicted_label: analysis.prediction,
      expected_label: expectedLabel,
      category: $("feedback-category").value,
    });
    if (window.currentAnalysis !== analysis) return;
    status.textContent = `${result.message} Receipt: ${result.report_id}`;
    sent = true;
  } catch (failure) {
    if (window.currentAnalysis === analysis) status.textContent = describeError(failure);
  } finally {
    if (window.currentAnalysis === analysis) {
      setBusy(button, false, "Send anonymous correction");
      if (sent) button.disabled = true;
    }
  }
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

function miniMeter(probability, band = bandFromProbability(probability)) {
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
      `Reopen saved check from ${timestamp} — ${bandView(band).title}, ${pct(entry.spam_probability)} model score`);
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
let singleRevision = 0;
let batchRevision = 0;

function invalidateSingle() {
  singleRevision += 1;
  window.currentAnalysis = null;
  $("result").classList.add("hidden");
  $("highlighted").replaceChildren();
  $("signals").replaceChildren();
  hideBanner($("error-banner"));
  setBusy($("btn-check"), false, "Check message");
}

function invalidateBatch() {
  batchRevision += 1;
  $("batch-summary").classList.add("hidden");
  $("batch-results").classList.add("hidden");
  $("batch-tbody").replaceChildren();
  hideBanner($("batch-error"));
  setBusy($("btn-batch"), false, "Check all");
}

function updateCharCount() {
  $("char-count").textContent = `${Array.from($("message-input").value).length} / ${MAX_MESSAGE_LENGTH}`;
}

async function runCheck({ save = true } = {}) {
  invalidateSingle();
  const revision = singleRevision;
  const input = $("message-input");
  const message = input.value.trim();
  const banner = $("error-banner");
  hideBanner(banner);
  if (!message) {
    showBanner(banner, "Type or paste an SMS message first.");
    input.focus();
    return;
  }
  if (Array.from(message).length > MAX_MESSAGE_LENGTH) {
    showBanner(banner, `That message is ${Array.from(message).length} characters — the limit is ${MAX_MESSAGE_LENGTH}.`);
    return;
  }
  const button = $("btn-check");
  setBusy(button, true, "Checking…");
  try {
    const analysis = await postJson(API.analyze, { message });
    if (revision !== singleRevision) return;
    renderAnalysis(analysis, { save });
  } catch (failure) {
    if (revision === singleRevision) showBanner(banner, describeError(failure));
  } finally {
    if (revision === singleRevision) setBusy(button, false, "Check message");
  }
}

/* ---------- Batch flow ---------- */
function parseBatchInput() {
  return $("batch-input").value.split("\n").map((line) => line.trim()).filter(Boolean);
}

function updateBatchCount() {
  const messages = parseBatchInput();
  const count = messages.length;
  const characters = messages.reduce((total, message) => total + Array.from(message).length, 0);
  $("batch-count").textContent =
    `${count} message${count === 1 ? "" : "s"} · ${characters.toLocaleString()} characters`;
}

async function runBatch() {
  invalidateBatch();
  const revision = batchRevision;
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
  if (messages.reduce((total, message) => total + Array.from(message).length, 0) > MAX_BATCH_CHARACTERS) {
    showBanner(banner, "Batch is limited to 200,000 total characters. Remove some text and try again.");
    return;
  }
  const oversized = messages.findIndex((message) => Array.from(message).length > MAX_MESSAGE_LENGTH);
  if (oversized !== -1) {
    showBanner(banner, `Message ${oversized + 1} is longer than ${MAX_MESSAGE_LENGTH} characters.`);
    return;
  }
  const button = $("btn-batch");
  setBusy(button, true, "Checking…");
  try {
    const data = await postJson(API.analyzeBatch, { messages });
    if (revision !== batchRevision) return;
    const results = Array.isArray(data.results) ? data.results : [];
    renderBatch(results);
    if (historyEnabled) {
      for (const analysis of results) addHistory(analysis, "batch", { render: false });
      renderHistory();
      updateHistoryBadge();
      announceHistory(`Saved in this browser: ${loadHistory().length} of ${HISTORY_LIMIT} checks.`);
    }
  } catch (failure) {
    if (revision === batchRevision) showBanner(banner, describeError(failure));
  } finally {
    if (revision === batchRevision) setBusy(button, false, "Check all");
  }
}

function openBatchResult(analysis) {
  invalidateSingle();
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
    riskCell.append(miniMeter(analysis.spam_probability, band));
    const riskPct = document.createElement("span");
    riskPct.textContent = pct(analysis.spam_probability);
    riskCell.append(riskPct);
    const signalCell = document.createElement("td");
    const patterns = signalSummary(analysis);
    signalCell.textContent = patterns;
    row.setAttribute("aria-label",
      `Message ${index + 1}: ${bandView(band).title}, ${pct(analysis.spam_probability)} model score. Detected text patterns: ${patterns}. Press Enter to open the full analysis.`);

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
  input.addEventListener("input", () => { invalidateSingle(); updateCharCount(); });
  input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      runCheck();
    }
  });
  $("btn-check").addEventListener("click", () => runCheck());
  $("feedback-form").addEventListener("submit", submitFeedback);
  $("btn-clear").addEventListener("click", () => {
    invalidateSingle();
    input.value = "";
    updateCharCount();
    $("result").classList.add("hidden");
    hideBanner($("error-banner"));
    input.focus();
  });
  for (const chip of document.querySelectorAll(".example-chip")) {
    chip.addEventListener("click", () => {
      const example = nextExample(chip.dataset.example);
      if (!example) return;
      invalidateSingle();
      input.value = example.message;
      updateCharCount();
      $("example-status").textContent =
        `Fictional ${chip.dataset.example} example ${example.index} of ${example.total}; checking it now. Click again for another example.`;
      runCheck();
    });
  }
  updateCharCount();
}

function initBatchCheck() {
  const input = $("batch-input");
  input.addEventListener("input", () => { invalidateBatch(); updateBatchCount(); });
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
