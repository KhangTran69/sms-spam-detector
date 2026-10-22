import { API, createApiClient } from "./api-client.js?v=ui15-history-store-20261022";
import { I18N } from "./i18n.js?v=ui15-history-store-20261022";
import { applyPrivacyMasks, buildPrivacyReview, clearPrivacyReview, detectSensitiveSpans } from "./privacy-preview.js?v=ui15-history-store-20261022";
import { createHistoryStore } from "./history-store.js?v=ui15-history-store-20261022";
import { createConnectionStatus } from "./connection-status.js?v=ui15-history-store-20261022";
import { createResultFormatting, normalizeModelInfo } from "./result-format.js?v=ui15-history-store-20261022";

/* PH SMS Scam Detector — UI logic (no build step, vanilla JS). */
"use strict";

const HISTORY_LIMIT = 50;
const BATCH_LIMIT = 50;
const MAX_BATCH_CHARACTERS = 200000;
const MAX_MESSAGE_LENGTH = 10000;
const LANG_KEY = "smsd_lang_v1";
const THEME_KEY = "smsd_theme_v1";

const SYNTHETIC_DATA_NOTE =
  "Checks using synthetic Philippine data are not proof of real-world accuracy. Treat every verdict as a hint, not a fact.";
const HISTORY_OFF_NOTE =
  "History is off. Turn it on to keep the last 50 checks in this browser.";

function $(id) {
  return document.getElementById(id);
}

/* Fallback thresholds mirror the API default; the authoritative values are
   fetched from GET /model-info on load (decision_threshold, suspicious_threshold
   and the risk `bands`). These constants only cover a metadata fetch failure. */
const FALLBACK_BANDS = { likely_scam: 0.5, suspicious: 0.25, looks_safe: 0.0 };
const FALLBACK_MODEL_INFO = {
  model_version: "unknown",
  decision_threshold: 0.5,
  suspicious_threshold: 0.25,
  bands: { ...FALLBACK_BANDS },
  data_note: SYNTHETIC_DATA_NOTE,
  probability_calibrated: false,
};

let lang = "en";

function t(key, params) {
  let text = Object.prototype.hasOwnProperty.call(I18N.taglish, key) && lang === "taglish"
    ? I18N.taglish[key]
    : I18N.en[key];
  if (typeof text !== "string") text = I18N.en[key];
  if (typeof text !== "string") return key;
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

function readLanguage() {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    return saved === "taglish" || saved === "fil" ? "taglish" : "en";
  } catch {
    return "en";
  }
}

function applyStaticI18n() {
  document.documentElement.lang = lang === "taglish" ? "en-PH" : "en";
  for (const element of document.querySelectorAll("[data-i18n]")) {
    element.textContent = t(element.dataset.i18n);
  }
  for (const element of document.querySelectorAll("[data-i18n-aria-label]")) {
    element.setAttribute("aria-label", t(element.dataset.i18nAriaLabel));
  }
  for (const element of document.querySelectorAll("[data-i18n-placeholder]")) {
    element.setAttribute("placeholder", t(element.dataset.i18nPlaceholder));
  }
}

/* Busy buttons cache their idle label; a language switch must drop those
   caches so the translated label is used on the next cycle. */
function resetIdleLabels() {
  for (const button of document.querySelectorAll("button[data-idle-label]")) {
    const labels = {
      "btn-check": ["check.run", "check.busy"],
      "btn-batch": ["batch.run", "batch.busy"],
      "btn-feedback": ["feedback.submit", "feedback.busy"],
      "btn-compare-run": ["compare.run", "compare.busy"],
    }[button.id];
    if (button.getAttribute("aria-busy") === "true" && labels) {
      button.dataset.idleLabel = t(labels[0]);
      button.textContent = t(labels[1]);
    } else {
      delete button.dataset.idleLabel;
    }
  }
}

function setLanguage(nextLang) {
  lang = nextLang === "taglish" || nextLang === "fil" ? "taglish" : "en";
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    /* preference stays for this page load only */
  }
  applyStaticI18n();
  resetIdleLabels();
  $("btn-lang").textContent = lang === "taglish" ? "EN" : "Taglish";
  updateThemeButton();
  connectionStatus.render();
  renderActiveModelInfo();
  renderHistory();
  updateHistoryBadge();
  updateCharCount();
  updateBatchCount();
  clearPrivacyReview($("single-privacy-review"));
  clearPrivacyReview($("compare-review-a"));
  clearPrivacyReview($("compare-review-b"));
  clearBatchPrivacyReview();
  $("batch-review-status").textContent = "";
  $("example-status").textContent = t("examples.note");
  $("copy-status").textContent = "";
  $("feedback-status").textContent = "";
  $("csv-status").textContent = "";
  $("history-status").textContent = "";
  if (batchAbortController && batchProgress) updateBatchProgress(batchProgress.done, batchProgress.total);
  if (window.currentAnalysis) renderAnalysis(window.currentAnalysis, { save: false });
  if (lastBatchResults) renderBatch(lastBatchResults);
  if (currentComparison) renderComparison(currentComparison.results);
}

/* ---------- Theme (light ↔ dark, persisted) ---------- */
const THEME_STATES = ["light", "dark"];
const THEME_ICONS = { light: "🌙", dark: "☀️" };

function readTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    return saved === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

function updateThemeButton() {
  const button = $("btn-theme");
  button.textContent = THEME_ICONS[currentTheme];
  const nextTheme = currentTheme === "dark" ? "light" : "dark";
  button.setAttribute("aria-label", t(`theme.${nextTheme}`));
  button.title = t(`theme.${nextTheme}`);
}

let currentTheme = "light";

function toggleTheme() {
  currentTheme = currentTheme === "dark" ? "light" : "dark";
  try {
    localStorage.setItem(THEME_KEY, currentTheme);
  } catch {
    /* theme stays for this page load only */
  }
  applyTheme(currentTheme);
  updateThemeButton();
}

/* ---------- Connection status ---------- */
const connectionStatus = createConnectionStatus({
  element: $, translate: t, browserOnline: () => window.navigator.onLine, offlineBanner: $("offline-banner"),
});

const apiClient = createApiClient({
  translate: t,
  setApiAvailability: connectionStatus.setApiAvailability,
  setModelReadiness: connectionStatus.setModelReadiness,
  hideOfflineBanner: connectionStatus.hideOfflineBanner,
  showOfflineBanner: connectionStatus.showOfflineBanner,
});

/* ---------- Banding ---------- */
/* API risk_band -> presentation. Titles/icons live here so every view is
   consistent; cutoffs always come from modelInfo.bands. */
function bandTitle(band) {
  const view = resultFormatting.bandView(band);
  return t(view.key);
}

const SIGNALS = {
  url: { labelKey: "signal.url.label", pluralKey: "signal.url.plural", explanationKey: "signal.url.explanation" },
  phone: { labelKey: "signal.phone.label", pluralKey: "signal.phone.plural", explanationKey: "signal.phone.explanation" },
  money: { labelKey: "signal.money.label", pluralKey: "signal.money.plural", explanationKey: "signal.money.explanation" },
  urgency: { labelKey: "signal.urgency.label", pluralKey: "signal.urgency.plural", explanationKey: "signal.urgency.explanation" },
  brand: { labelKey: "signal.brand.label", pluralKey: "signal.brand.plural", explanationKey: "signal.brand.explanation" },
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
    "Nanalo ka ng [AMOUNT]! I-claim agad sa prize-claim.example bago mag-expire ang promo.",
    "Delivery notice: May kulang na [AMOUNT] fee. Bayaran ngayon sa parcel-pay.example para ma-release ang package.",
    "GCash security check: May unusual activity. I-verify ang wallet mo sa gcash-review.example ngayon.",
    "Work from home! Earn [AMOUNT] kada araw. Send [ID] and a registration fee today to reserve your slot.",
    "SIM registration failed. I-update ang details mo sa sim-update.example within 2 hours para hindi ma-disable ang number.",
    "Maya: May pending reward ka. Confirm your wallet at maya-bonus.example before midnight.",
    "Pre-approved loan offer! Pay a [AMOUNT] processing fee at mabilis-loan.example to release funds today.",
    "Guaranteed daily investment returns daw! Register at kita-now.example habang may slots pa.",
    "May ayuda ka raw na naghihintay. Submit your account details at ayuda-claim.example ngayong araw.",
    "Final warning: Your online account will close tonight. Restore access at secure-login.example.",
    "GCash payment failed. Re-enter your MPIN at gcash-fix.example para ma-refund ang [AMOUNT].",
    "Customs notice: Pay the missing parcel tax at release-package.example or your delivery will be returned.",
    "Your [AMOUNT] refund is ready. Add your card number at refund-center.example to receive it.",
    "Lucky winner ka! Send [CODE] to prize-desk.example to claim your mystery gift.",
    "Hiring urgent: No experience needed. Deposit [AMOUNT] at work-slot.example to secure the job.",
    "May suspicious charge daw sa account mo. Verify agad sa account-check.example para ma-block ito.",
    "UnionBank notice: Your profile needs updating. Continue at ub-profile.example within 30 minutes.",
    "Your e-wallet will be deactivated. I-confirm ang PIN mo sa wallet-restore.example ngayon.",
    "Subscription payment declined. Update billing details at renew-now.example to avoid losing access.",
  ],
  safe: [
    "Your one-time code is [CODE]. Never share it with anyone, even someone claiming to be from your bank.",
    "BDO: Your transfer was completed. If you don't recognize it, check your account using the official app.",
    "Your parcel is out for delivery today. Track it in the official courier app. No payment is due by SMS.",
    "Meralco reminder: Your bill is ready. Please check the amount and due date in the official app.",
    "Reminder: Parent meeting is on Friday at 3 PM in the school library. Salamat po!",
    "Uy, kita tayo after class? I can bring the notes from yesterday. Message me when you're nearby.",
    "BPI: A purchase was approved for [AMOUNT]. Review recent activity in the official app if needed.",
    "GCash: You received [AMOUNT]. Open the app directly to review your balance and transaction history.",
    "Maya: Your cash-in is complete. Please check the transaction in your Maya app.",
    "J&T Express: Your parcel is out for delivery. No extra payment is needed for this shipment.",
    "Maynilad: Your latest bill is available. Check the due date through the official customer portal.",
    "Class is moved to Room 204 tomorrow. Pakisabi na rin sa group. Salamat!",
    "Team reminder: Our weekly check-in starts at 10 AM. Please bring your project updates.",
    "Your salary has been credited to your payroll account. Check your bank's official app for details.",
    "Nasa sakayan na ako. Dadaan ako sa tindahan, may kailangan ka ba?",
    "Doctor appointment reminder: Your visit is scheduled for Thursday afternoon. Call the clinic using its saved contact if you need to reschedule.",
    "Your subscription renewal was successful. Manage your plan in the service's official app.",
    "Card payment approved for [AMOUNT]. If this wasn't you, contact your bank using the number on your card.",
    "Your package was delivered to the pickup counter. Bring your claim slip when you collect it.",
    "This week's member promo is available in the official store app. No need to reply to this message.",
  ],
};
const EXAMPLE_INDEX = { scam: -1, safe: -1 };

let modelInfo = normalizeModelInfo(FALLBACK_MODEL_INFO, validFraction);
let modelInfoLoaded = false;
let modelInfoError = null;
let modelInfoRequestSequence = 0;
let historyEnabled = false;
const historyStore = createHistoryStore(() => window.localStorage, { limit: HISTORY_LIMIT });
const resultFormatting = createResultFormatting({
  translate: t,
  validFraction,
  getModelInfo: () => modelInfo,
  matchesLoadedModel: resultMatchesLoadedModel,
});
const { bandsForAnalysis, bandFromProbability, bandOf, bandView, scoreLabel } = resultFormatting;
let lastBatchResults = null;

/* ---------- Small helpers ---------- */
function numberOr(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function validFraction(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
}

function pct(value) {
  const fraction = validFraction(value);
  return fraction === null ? t("value.unavailable") : `${Math.round(fraction * 100)}%`;
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

function describeError(failure) {
  if (!failure) return t("error.generic");
  let message = failure.message || t("error.generic");
  const modelUnavailable = failure.status === 503 || failure.code === "model_unavailable";
  if (modelUnavailable && !message.includes("src.train")) message += t("error.trainHint");
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
  clearPrivacyReview($("single-privacy-review"));
  clearPrivacyReview($("compare-review-a"));
  clearPrivacyReview($("compare-review-b"));
  clearBatchPrivacyReview();
  // A request belongs to the view where it was started. Leaving that view
  // cancels it so a late response cannot replace a result after navigation.
  if (name !== "check" && singleAbortController) invalidateSingle();
  if (name !== "batch" && batchAbortController) invalidateBatch();
  if (name !== "compare" && compareAbortController) invalidateComparison();
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
  renderModelInfo(name === "check" ? window.currentAnalysis : null);
}

function renderActiveModelInfo() {
  const activeTab = tabElements().find((tab) => tab.getAttribute("aria-selected") === "true");
  renderModelInfo(activeTab && activeTab.dataset.tab === "check" ? window.currentAnalysis || null : null);
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
function resultMatchesLoadedModel(analysis) {
  return Boolean(modelInfoLoaded && analysis && typeof analysis.model_version === "string"
    && analysis.model_version && analysis.model_version !== "unknown"
    && analysis.model_version === modelInfo.model_version);
}

function renderModelInfo(analysis = null) {
  const resultContext = Boolean(analysis && typeof analysis === "object");
  const matchedInfo = resultContext && resultMatchesLoadedModel(analysis);
  const modelVersion = resultContext
    ? (typeof analysis.model_version === "string" && analysis.model_version ? analysis.model_version : t("value.unavailable"))
    : (modelInfoLoaded && modelInfo.model_version ? modelInfo.model_version : t("value.unavailable"));
  const bands = bandsForAnalysis(analysis);
  $("model-version").textContent = `${t("model.versionPrefix")}${modelVersion}`;
  $("model-note").textContent = resultContext
    ? (matchedInfo && modelInfo.data_note ? modelInfo.data_note : t("model.provenance.unavailable"))
    : (modelInfoLoaded && modelInfo.data_note ? modelInfo.data_note : t("model.provenance.unavailable"));
  const warning = $("model-warning");
  if (resultContext && matchedInfo && modelInfo.warnings.length) {
    warning.textContent = modelInfo.warnings.join(" ");
    warning.classList.remove("hidden");
  } else if (resultContext && matchedInfo && modelInfo.legacy_artifact) {
    warning.textContent = t("model.legacyWarning");
    warning.classList.remove("hidden");
  } else if (modelInfoError && (!resultContext || !matchedInfo)) {
    warning.textContent = `${describeError(modelInfoError)}${t("model.fallbackSuffix")}`;
    warning.classList.remove("hidden");
  } else if (resultContext || (!modelInfoError && !modelInfo.legacy_artifact)) {
    warning.textContent = "";
    warning.classList.add("hidden");
  } else if (!resultContext && modelInfo.legacy_artifact) {
    warning.textContent = t("model.legacyWarning");
    warning.classList.remove("hidden");
  }
  $("model-thresholds").textContent = bands
    ? t("model.thresholds.line", {
      threshold: pct(resultContext ? validFraction(analysis.decision_threshold)
        ?? (matchedInfo ? validFraction(modelInfo.decision_threshold) : null) : validFraction(modelInfo.decision_threshold)),
      scam: pct(bands.likely_scam),
      suspicious: pct(bands.suspicious),
    })
    : `${t("model.thresholds.loading")} ${t("value.unavailable")}`;
  const displayedCalibration = resultContext
    ? (typeof analysis.probability_calibrated === "boolean" ? analysis.probability_calibrated : null)
    : (modelInfoLoaded ? modelInfo.probability_calibrated : null);
  $("risk-meter").setAttribute(
    "aria-label",
    displayedCalibration === true ? t("meter.aria.calibrated")
      : displayedCalibration === false ? t("meter.aria") : t("meter.aria.unavailable"),
  );
}

async function loadModelInfo() {
  const requestSequence = ++modelInfoRequestSequence;
  const warning = $("model-warning");
  try {
    const info = await apiClient.requestJson(API.modelInfo);
    if (requestSequence !== modelInfoRequestSequence) return;
    modelInfo = normalizeModelInfo(info, validFraction);
    modelInfoLoaded = true;
    modelInfoError = null;
    warning.textContent = "";
    warning.classList.add("hidden");
  } catch (failure) {
    if (requestSequence !== modelInfoRequestSequence) return;
    if (failure && failure.aborted) return;
    modelInfo = normalizeModelInfo(FALLBACK_MODEL_INFO, validFraction);
    modelInfoLoaded = false;
    modelInfoError = failure;
  }
  renderActiveModelInfo();
  if (currentComparison) renderComparison(currentComparison.results);
}

async function refreshServiceStatus() {
  connectionStatus.reset();
  try {
    await apiClient.requestJson(API.ready);
  } catch {
    // requestJson records reachability and readiness without resending SMS.
  }
  connectionStatus.render();
}

/* ---------- Single-check rendering ---------- */
function renderVerdict(analysis) {
  const band = bandOf(analysis);
  const view = bandView(band);
  $("verdict-card").className = `card verdict ${view.css}`;
  $("verdict-icon").textContent = view.icon;
  $("verdict-title").textContent = bandTitle(band);
  const decisionThreshold = validFraction(analysis.decision_threshold)
    ?? (resultMatchesLoadedModel(analysis) ? validFraction(modelInfo.decision_threshold) : null);
  $("verdict-sub").textContent =
    `${pct(analysis.spam_probability)} ${scoreLabel(analysis)} · ${t("verdict.modelVerdict")}: ${analysis.prediction || t("value.unavailable")} · ` +
    `${t("verdict.decisionThreshold")} ${pct(decisionThreshold)}`;
}

function renderMeter(analysis) {
  const probability = validFraction(analysis.spam_probability);
  const value = probability === null ? null : Math.round(probability * 100);
  const band = bandOf(analysis);
  const meter = $("risk-meter");
  const bands = bandsForAnalysis(analysis);
  meter.classList.toggle("meter-no-thresholds", !bands || value === null);
  if (bands) {
    meter.style.setProperty("--suspect", `${Math.round(bands.suspicious * 100)}%`);
    meter.style.setProperty("--scam", `${Math.round(bands.likely_scam * 100)}%`);
  }
  if (value === null) meter.removeAttribute("aria-valuenow");
  else meter.setAttribute("aria-valuenow", String(value));
  const calibration = analysis && typeof analysis.probability_calibrated === "boolean"
    ? analysis.probability_calibrated : null;
  meter.setAttribute("aria-label", calibration === true ? t("meter.aria.calibrated")
    : calibration === false ? t("meter.aria") : t("meter.aria.unavailable"));
  meter.setAttribute("aria-valuetext", value === null ? t("value.unavailable")
    : `${value}% ${scoreLabel(analysis)} — ${bandTitle(band)}`);
  $("meter-marker").style.left = value === null ? "0%" : `${value}%`;
  const output = $("meter-value");
  output.textContent = value === null ? t("value.unavailable") : `${value}%`;
  output.style.color = { spam: "var(--red)", suspicious: "var(--amber)", safe: "var(--green)" }[bandView(band).css] || "var(--muted)";
}

function renderHighlighted(analysis, container = $("highlighted"), idPrefix = "signal") {
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
    mark.setAttribute("aria-describedby", active.map((match) => `${idPrefix}-${match.id}`).join(" "));
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

function renderSignals(analysis, container = $("signals"), idPrefix = "signal") {
  container.replaceChildren();
  const message = typeof analysis.message === "string" ? analysis.message : "";
  const matches = signalMatches(analysis, Array.from(message));
  if (!matches.length) {
    const empty = document.createElement("li");
    empty.className = "signal-empty";
    empty.textContent = t("signals.empty");
    container.append(empty);
    return;
  }
  for (const match of matches) {
    const item = document.createElement("li");
    item.id = `${idPrefix}-${match.id}`;
    item.className = `signal-item signal-item-${match.type}`;
    const reference = document.createElement("span");
    reference.className = "signal-reference";
    reference.setAttribute("aria-label", `Signal ${match.id}`);
    reference.textContent = String(match.id);
    const label = document.createElement("strong");
    label.textContent = t(SIGNALS[match.type].labelKey);
    const explanation = document.createElement("span");
    explanation.className = "signal-explanation";
    explanation.textContent = t(SIGNALS[match.type].explanationKey);
    const example = document.createElement("q");
    example.className = "signal-match-text";
    example.textContent = match.text;
    item.append(reference, label, explanation, example);
    container.append(item);
  }
}

function signalSummary(analysis) {
  const matches = signalMatches(analysis);
  if (!matches.length) return t("signals.noneSummary");
  const counts = new Map();
  for (const match of matches) counts.set(match.type, (counts.get(match.type) || 0) + 1);
  return [...counts.entries()]
    .map(([type, count]) => `${t(SIGNALS[type].labelKey)}${count > 1 ? ` ×${count}` : ""}`)
    .join(" · ");
}

function buildTips(analysis) {
  const tips = [];
  const flags = new Set(Array.isArray(analysis.flags) ? analysis.flags : []);
  const risky = bandOf(analysis) !== "looks_safe";
  const brands = Array.isArray(analysis.brands) ? analysis.brands : [];
  const brandNames = brands.map((brand) => BRANDS[brand] || String(brand).toUpperCase());
  if (risky) {
    tips.push(t("tips.noReply"));
    if (brandNames.length) {
      tips.push(t("tips.brandMentions", { brands: brandNames.join(", ") }));
    }
  }
  if (flags.has("has_url")) tips.push(t("tips.url"));
  if (flags.has("has_money")) tips.push(t("tips.money"));
  if (flags.has("has_phone")) tips.push(t("tips.phone"));
  if (flags.has("has_urgency")) tips.push(t("tips.urgency"));
  tips.push(t("tips.otp"));
  if (!risky) tips.push(t("tips.safeSpoof"));
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

/* Optional user-provided context is page-memory only. A WeakMap ties answers
   to the exact result object so each batch/comparison result stays independent;
   no answer becomes part of an API payload, history record, or export. */
const safetyGuidanceState = new WeakMap();
let safetyGuidanceId = 0;

function guidanceStateFor(analysis) {
  let state = safetyGuidanceState.get(analysis);
  if (!state) {
    state = { expected: null, sensitive: null, payment: null, verified: null, actions: [], open: false };
    safetyGuidanceState.set(analysis, state);
  }
  return state;
}

function guidanceRecommendations(state) {
  const recommendations = [];
  const add = (key) => {
    const text = t(key);
    if (!recommendations.includes(text)) recommendations.push(text);
  };
  const selectedActions = Array.isArray(state.actions) ? state.actions : [];
  add("guidance.default");
  if (selectedActions.includes("openedLink")) add("guidance.openedLink");
  if (selectedActions.includes("sharedSensitive")) add("guidance.sharedSensitive");
  if (selectedActions.includes("sentMoney")) add("guidance.sentMoney");
  if (state.expected === "no") add("guidance.unexpected");
  if (state.sensitive === "yes") add("guidance.sensitiveRequest");
  if (state.payment === "yes") add("guidance.paymentRequest");
  if (state.verified === "yes") add("guidance.verified");
  return recommendations;
}

function renderGuidanceAdvice(advice, state) {
  advice.replaceChildren();
  for (const recommendation of guidanceRecommendations(state)) {
    const item = document.createElement("li");
    item.textContent = recommendation;
    advice.append(item);
  }
}

function guidanceQuestion(fieldset, questionKey, stateKey, name, state) {
  const legend = document.createElement("legend");
  legend.textContent = t(questionKey);
  fieldset.append(legend);
  for (const value of ["yes", "no", "unsure"]) {
    const label = document.createElement("label");
    label.className = "guidance-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = name;
    input.value = value;
    input.dataset.guidanceField = stateKey;
    input.dataset.guidanceValue = value;
    input.checked = state[stateKey] === value;
    label.append(input, document.createTextNode(t(`guidance.${value}`)));
    fieldset.append(label);
  }
}

function renderSafetyGuidance(container, analysis, idPrefix = "single") {
  const state = guidanceStateFor(analysis);
  const details = document.createElement("details");
  details.className = "card safety-guidance";
  details.setAttribute("aria-live", "off");
  details.open = state.open;
  const summary = document.createElement("summary");
  summary.textContent = t("guidance.title");
  details.append(summary);

  const intro = document.createElement("p");
  intro.className = "muted guidance-intro";
  intro.textContent = t("guidance.intro");
  details.append(intro);

  const questions = document.createElement("fieldset");
  questions.className = "guidance-group guidance-questions";
  const questionsLegend = document.createElement("legend");
  questionsLegend.textContent = t("guidance.questions");
  questions.append(questionsLegend);
  const id = `${idPrefix}-${++safetyGuidanceId}`;
  for (const [questionKey, stateKey] of [
    ["guidance.expected", "expected"],
    ["guidance.sensitive", "sensitive"],
    ["guidance.payment", "payment"],
    ["guidance.verifiedQuestion", "verified"],
  ]) {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "guidance-question";
    guidanceQuestion(fieldset, questionKey, stateKey, `${id}-${stateKey}`, state);
    questions.append(fieldset);
  }
  details.append(questions);

  const nextSteps = document.createElement("fieldset");
  nextSteps.className = "guidance-group guidance-actions";
  const nextLegend = document.createElement("legend");
  nextLegend.textContent = t("guidance.nextHeading");
  nextSteps.append(nextLegend);
  const actionInputs = [];
  for (const [value, key] of [
    ["notInteracted", "guidance.action.notInteracted"],
    ["openedLink", "guidance.action.openedLink"],
    ["sharedSensitive", "guidance.action.sharedSensitive"],
    ["sentMoney", "guidance.action.sentMoney"],
  ]) {
    const label = document.createElement("label");
    label.className = "guidance-option guidance-action-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = `${id}-action`;
    input.value = value;
    input.dataset.guidanceField = "action";
    input.dataset.guidanceValue = value;
    input.checked = state.actions.includes(value);
    actionInputs.push(input);
    label.append(input, document.createTextNode(t(key)));
    nextSteps.append(label);
  }
  details.append(nextSteps);

  const advice = document.createElement("ul");
  advice.className = "tips guidance-advice";
  renderGuidanceAdvice(advice, state);
  details.append(advice);
  const announcement = document.createElement("p");
  announcement.className = "sr-only";
  announcement.setAttribute("role", "status");
  announcement.setAttribute("aria-live", "polite");
  announcement.setAttribute("aria-atomic", "true");
  details.append(announcement);

  const actions = document.createElement("div");
  actions.className = "guidance-copy-row";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "btn ghost small";
  copy.textContent = t("guidance.copy");
  const copyStatus = document.createElement("span");
  copyStatus.className = "hint";
  copyStatus.setAttribute("role", "status");
  copyStatus.setAttribute("aria-live", "polite");
  copy.addEventListener("click", async () => {
    let copied = false;
    try {
      await navigator.clipboard.writeText(guidanceRecommendations(state).join("\n"));
      copied = true;
    } catch {
      try {
        const helper = document.createElement("textarea");
        helper.value = guidanceRecommendations(state).join("\n");
        helper.setAttribute("readonly", "");
        helper.style.position = "fixed";
        helper.style.left = "-9999px";
        document.body.append(helper);
        helper.select();
        copied = document.execCommand("copy");
        helper.remove();
      } catch {
        copied = false;
      }
    }
    copyStatus.textContent = copied ? t("guidance.copyDone") : t("guidance.copyFail");
  });
  actions.append(copy, copyStatus);
  details.append(actions);

  details.addEventListener("toggle", () => { state.open = details.open; });
  details.addEventListener("change", (event) => {
    const target = event.target;
    if (!target || !target.dataset || !target.dataset.guidanceField) return;
    if (target.dataset.guidanceField === "action") {
      const selected = new Set(state.actions);
      if (target.dataset.guidanceValue === "notInteracted") {
        state.actions = target.checked ? ["notInteracted"] : [];
      } else {
        selected.delete("notInteracted");
        if (target.checked) selected.add(target.dataset.guidanceValue);
        else selected.delete(target.dataset.guidanceValue);
        state.actions = [...selected];
      }
      for (const control of actionInputs) {
        control.checked = state.actions.includes(control.dataset.guidanceValue);
      }
    } else {
      state[target.dataset.guidanceField] = target.dataset.guidanceValue;
    }
    renderGuidanceAdvice(advice, state);
    announcement.textContent = t("guidance.updated");
    copyStatus.textContent = "";
  });
  container.replaceChildren(details);
}

function buildSummaryText(analysis) {
  const modelVersion = typeof analysis.model_version === "string" && analysis.model_version
    ? analysis.model_version : t("value.unavailable");
  const lines = [
    t("summary.header"),
    `${t("summary.verdict")}: ${bandTitle(bandOf(analysis))} (${analysis.prediction || t("value.unavailable")})`,
    `${t("summary.score")}: ${pct(analysis.spam_probability)} (${scoreLabel(analysis)})`,
    `${t("summary.threshold")}: ${pct(analysis.decision_threshold)}`,
    `${t("summary.suspiciousThreshold")}: ${pct(analysis.suspicious_threshold)}`,
    `${t("summary.signals")}: ${signalSummary(analysis)}`,
    `${t("summary.message")}: ${typeof analysis.message === "string" ? analysis.message : ""}`,
  ];
  if (analysis.masked_input === true) lines.push(t("privacy.maskedResult"));
  lines.push(`${t("summary.tips")}:`);
  for (const tip of buildTips(analysis)) lines.push(`- ${tip}`);
  lines.push(`${t("summary.model")}: ${modelVersion}`);
  lines.push(t("footer.synthetic"));
  return lines.join("\n");
}

async function copySummary() {
  const analysis = window.currentAnalysis;
  const status = $("copy-status");
  if (!analysis) return;
  const text = buildSummaryText(analysis);
  let copied = false;
  try {
    await navigator.clipboard.writeText(text);
    copied = true;
  } catch {
    // Clipboard API unavailable (older browsers / insecure context): fall back
    // to a temporary textarea selection + execCommand copy.
    try {
      const helper = document.createElement("textarea");
      helper.value = text;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.left = "-9999px";
      document.body.append(helper);
      helper.select();
      copied = document.execCommand("copy");
      helper.remove();
    } catch {
      copied = false;
    }
  }
  status.textContent = copied ? t("copy.done") : t("copy.fail");
}

function renderAnalysis(analysis, { save = true } = {}) {
  $("result").classList.remove("hidden");
  renderVerdict(analysis);
  renderMeter(analysis);
  renderHighlighted(analysis);
  renderSignals(analysis);
  renderTips(analysis);
  renderSafetyGuidance($("safety-guidance"), analysis);
  $("privacy-result-note").classList.toggle("hidden", analysis.masked_input !== true);
  $("privacy-result-note").textContent = analysis.masked_input === true ? t("privacy.maskedResult") : "";
  $("copy-status").textContent = "";
  window.currentAnalysis = analysis;
  renderModelInfo(analysis);
  const feedbackForm = $("feedback-form");
  const feedbackEnabled = resultMatchesLoadedModel(analysis) && modelInfo.feedback_enabled;
  feedbackForm.classList.toggle("hidden", !feedbackEnabled);
  $("feedback-status").textContent = "";
  setBusy($("btn-feedback"), false, t("feedback.submit"));
  if (feedbackEnabled) {
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
  if (!analysis || !resultMatchesLoadedModel(analysis) || !modelInfo.feedback_enabled) return;
  if (expectedLabel === analysis.prediction) {
    status.textContent = t("feedback.chooseDifferent");
    return;
  }
  setBusy(button, true, t("feedback.busy"));
  let sent = false;
  try {
    // Send only the user's selected label, category, and model version.
    // Never include the analyzed SMS or a saved history entry.
    const result = await apiClient.postJson(API.feedback, {
      model_version: analysis.model_version,
      predicted_label: analysis.prediction,
      expected_label: expectedLabel,
      category: $("feedback-category").value,
    });
    if (window.currentAnalysis !== analysis) return;
    status.textContent = `${result.message} ${t("feedback.receipt", { id: result.report_id })}`;
    sent = true;
  } catch (failure) {
    if (window.currentAnalysis === analysis) status.textContent = describeError(failure);
  } finally {
    if (window.currentAnalysis === analysis) {
      setBusy(button, false, t("feedback.submit"));
      if (sent) button.disabled = true;
    }
  }
}

/* ---------- History (browser-only, opt-in) ---------- */
function readHistoryPreference() {
  return historyStore.isEnabled();
}

function persistHistoryPreference(enabled) {
  return historyStore.setEnabled(enabled);
}

function clearStoredHistory() {
  historyStore.clear();
}

function loadHistory() {
  if (!historyEnabled) return [];
  return historyStore.load();
}

function saveHistory(entries) {
  return historyEnabled ? historyStore.save(entries) : historyStore.save([]);
}

function addHistory(analysis, source = "single", { render = true } = {}) {
  if (!historyEnabled) return;
  const entries = loadHistory();
  const newest = entries[0];
  const duplicate = newest &&
    newest.message === analysis.message &&
    newest.source === source &&
      newest.masked_input === (analysis.masked_input === true) &&
      newest.model_version === (typeof analysis.model_version === "string" ? analysis.model_version : null) &&
      newest.probability_calibrated === (typeof analysis.probability_calibrated === "boolean" ? analysis.probability_calibrated : null) &&
    Math.abs(numberOr(newest.spam_probability, -1) - numberOr(analysis.spam_probability, -2)) < 0.005;
  if (!duplicate) {
    entries.unshift({
      t: Date.now(),
      message: analysis.message,
      prediction: analysis.prediction,
      spam_probability: validFraction(analysis.spam_probability),
      probability_calibrated: typeof analysis.probability_calibrated === "boolean" ? analysis.probability_calibrated : null,
      model_version: typeof analysis.model_version === "string" ? analysis.model_version : null,
      risk_band: bandOf(analysis),
      decision_threshold: validFraction(analysis.decision_threshold),
      suspicious_threshold: validFraction(analysis.suspicious_threshold),
      flags: Array.isArray(analysis.flags) ? analysis.flags : [],
      masked_input: analysis.masked_input === true,
      source,
    });
    saveHistory(entries);
  }
  if (render) {
    renderHistory();
    updateHistoryBadge();
    announceHistory(t("history.savedCount", { n: loadHistory().length, limit: HISTORY_LIMIT }));
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
  pill.textContent = bandTitle(band);
  return pill;
}

function miniMeter(probability, band = bandFromProbability(probability)) {
  const wrap = document.createElement("div");
  wrap.className = "mini-meter";
  const fill = document.createElement("div");
  const score = validFraction(probability);
  fill.style.width = score === null ? "0%" : `${Math.round(score * 100)}%`;
  fill.style.background = score === null ? "var(--muted)"
    : ({ spam: "var(--red)", suspicious: "var(--amber)", safe: "var(--green)" }[bandView(band).css] || "var(--muted)");
  if (score === null) wrap.classList.add("mini-meter-unavailable");
  wrap.append(fill);
  return wrap;
}

function openSavedEntry(entry) {
  $("message-input").value = entry.message;
  updateCharCount();
  switchTab("check");
  runCheck({ save: false, masked: entry.masked_input === true });
}

function renderHistory() {
  const entries = historyEnabled ? loadHistory() : [];
  const list = $("history-list");
  list.replaceChildren();
  const empty = $("history-empty");
  empty.classList.toggle("hidden", entries.length > 0);
  empty.textContent = historyEnabled ? t("history.empty") : t("history.offnote");
  $("btn-clear-history").disabled = entries.length === 0;
  for (const entry of entries) {
    const band = resultFormatting.isKnownBand(entry.risk_band)
      ? entry.risk_band
      : bandFromProbability(entry.spam_probability, entry);
    const timestamp = new Date(numberOr(entry.t, Date.now())).toLocaleString();
    const item = document.createElement("li");
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.setAttribute("aria-label",
      t("history.reopenAria", {
        time: timestamp,
        band: bandTitle(band),
        pct: pct(entry.spam_probability),
        score: scoreLabel(entry),
      }) + (entry.masked_input === true ? ` · ${t("privacy.maskedBadge")}` : ""));
    const main = document.createElement("div");
    main.className = "history-item-main";
    const message = document.createElement("div");
    message.className = "history-msg";
    message.textContent = entry.message;
    const meta = document.createElement("div");
    meta.className = "history-meta";
    meta.textContent = `${timestamp}${entry.source === "batch" ? " · batch" : ""}`;
    if (entry.masked_input === true) meta.textContent += ` · ${t("privacy.maskedBadge")}`;
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
  const requested = Boolean(enabled);
  historyEnabled = requested ? persistHistoryPreference(true) : false;
  if (!requested) persistHistoryPreference(false);
  $("history-optin").checked = historyEnabled;
  if (!historyEnabled) {
    clearStoredHistory();
    announceHistory(t("history.off"));
  } else {
    announceHistory(t("history.on"));
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
    if (window.confirm(t("history.confirmClear"))) {
      clearStoredHistory();
      renderHistory();
      updateHistoryBadge();
      announceHistory(t("history.cleared"));
    }
  });
  renderHistory();
  updateHistoryBadge();
}

/* ---------- Single check flow ---------- */
let singleRevision = 0;
let batchRevision = 0;
let singleAbortController = null;
let batchAbortController = null;
let batchProgress = null;
let batchMaskedIndices = new Set();

function invalidateSingle() {
  singleRevision += 1;
  if (singleAbortController) {
    singleAbortController.abort();
    singleAbortController = null;
  }
  if (window.currentAnalysis && typeof window.currentAnalysis === "object") {
    safetyGuidanceState.delete(window.currentAnalysis);
  }
  window.currentAnalysis = null;
  $("result").classList.add("hidden");
  $("highlighted").replaceChildren();
  $("signals").replaceChildren();
  $("tips").replaceChildren();
  $("safety-guidance").replaceChildren();
  $("privacy-result-note").classList.add("hidden");
  $("privacy-result-note").textContent = "";
  clearPrivacyReview($("single-privacy-review"));
  $("copy-status").textContent = "";
  $("feedback-status").textContent = "";
  $("feedback-form").classList.add("hidden");
  renderModelInfo(null);
  hideBanner($("error-banner"));
  setBusy($("btn-check"), false, t("check.run"));
}

function invalidateBatch() {
  batchRevision += 1;
  if (batchAbortController) {
    batchAbortController.abort();
    batchAbortController = null;
  }
  batchProgress = null;
  lastBatchResults = null;
  $("batch-summary").classList.add("hidden");
  $("batch-results").classList.add("hidden");
  $("batch-progress").classList.add("hidden");
  $("batch-empty").classList.remove("hidden");
  $("batch-tbody").replaceChildren();
  $("csv-status").textContent = "";
  hideBanner($("batch-error"));
  setBusy($("btn-batch"), false, t("batch.run"));
}

function updateCharCount() {
  $("char-count").textContent = `${Array.from($("message-input").value).length} / ${MAX_MESSAGE_LENGTH}`;
}

async function runCheck({ save = true, masked = false } = {}) {
  invalidateSingle();
  const revision = singleRevision;
  const input = $("message-input");
  const message = input.value.trim();
  const banner = $("error-banner");
  hideBanner(banner);
  if (!message) {
    showBanner(banner, t("error.empty"));
    input.focus();
    return;
  }
  if (Array.from(message).length > MAX_MESSAGE_LENGTH) {
    showBanner(banner, t("error.tooLong", { n: Array.from(message).length }));
    return;
  }
  const controller = new AbortController();
  singleAbortController = controller;
  const button = $("btn-check");
  setBusy(button, true, t("check.busy"));
  try {
    const analysis = await apiClient.postJson(API.analyze, { message }, { signal: controller.signal });
    if (revision !== singleRevision) return;
    analysis.masked_input = masked;
    renderAnalysis(analysis, { save });
  } catch (failure) {
    if (revision === singleRevision && !(failure && failure.aborted)) {
      showBanner(banner, describeError(failure));
    }
  } finally {
    if (revision === singleRevision) {
      singleAbortController = null;
      setBusy(button, false, t("check.run"));
    }
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
  $("batch-count").textContent = count === 1
    ? t("batch.count.one", { chars: characters.toLocaleString() })
    : t("batch.count.many", { n: count, chars: characters.toLocaleString() });
}

function clearBatchPrivacyReview() {
  const container = $("batch-privacy-review");
  container.replaceChildren();
  container.classList.add("hidden");
}

function renderBatchPrivacyReview() {
  const container = $("batch-privacy-review");
  const messages = parseBatchInput();
  container.replaceChildren();
  container.classList.toggle("hidden", messages.length === 0);
  messages.forEach((message, index) => {
    const entry = document.createElement("section");
    entry.className = "batch-review-entry";
    const heading = document.createElement("h3");
    heading.textContent = t("privacy.batchEntry", { n: index + 1 });
    const status = document.createElement("p");
    status.className = "hint";
    status.textContent = batchMaskedIndices.has(index) ? t("privacy.batchMasked") : t("privacy.batchUnmasked");
    const review = document.createElement("div");
    review.className = "privacy-review hidden";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn secondary";
    button.textContent = t("privacy.reviewBatchEntry", { n: index + 1 });
    button.addEventListener("click", () => {
      buildPrivacyReview(review, message, ({ text, masked }) => {
        const updated = parseBatchInput();
        if (index >= updated.length) return;
        updated[index] = text;
        $("batch-input").value = updated.join("\n");
        invalidateBatch();
        updateBatchCount();
        if (masked) batchMaskedIndices.add(index);
        else batchMaskedIndices.delete(index);
        renderBatchPrivacyReview();
        const announcement = $("batch-review-status");
        announcement.textContent = t("privacy.batchApplied", { n: index + 1 });
      }, t);
    });
    entry.append(heading, status, button, review);
    container.append(entry);
  });
}

function showBatchProgress(done, total) {
  batchProgress = { done, total };
  $("batch-progress").textContent = t("batch.progress", { done, total });
  $("batch-progress").classList.remove("hidden");
  $("batch-results").classList.remove("hidden");
  $("batch-empty").classList.add("hidden");
  const tbody = $("batch-tbody");
  tbody.replaceChildren();
  for (let index = 0; index < 3; index += 1) {
    const row = document.createElement("tr");
    row.className = "skeleton-row";
    row.setAttribute("aria-hidden", "true");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    const skeleton = document.createElement("div");
    skeleton.className = "skeleton";
    cell.append(skeleton);
    row.append(cell);
    tbody.append(row);
  }
}

function updateBatchProgress(done, total) {
  batchProgress = { done, total };
  $("batch-progress").textContent = t("batch.progress", { done, total });
}

async function runBatch() {
  invalidateBatch();
  const revision = batchRevision;
  const messages = parseBatchInput();
  clearBatchPrivacyReview();
  const banner = $("batch-error");
  hideBanner(banner);
  if (!messages.length) {
    showBanner(banner, t("batch.error.empty"));
    return;
  }
  if (messages.length > BATCH_LIMIT) {
    showBanner(banner, t("batch.error.limit", { n: BATCH_LIMIT }));
    return;
  }
  if (messages.reduce((total, message) => total + Array.from(message).length, 0) > MAX_BATCH_CHARACTERS) {
    showBanner(banner, t("batch.error.chars"));
    return;
  }
  const oversized = messages.findIndex((message) => Array.from(message).length > MAX_MESSAGE_LENGTH);
  if (oversized !== -1) {
    showBanner(banner, t("batch.error.itemTooLong", { n: oversized + 1 }));
    return;
  }
  const button = $("btn-batch");
  setBusy(button, true, t("batch.busy"));
  showBatchProgress(0, messages.length);
  const controller = new AbortController();
  batchAbortController = controller;
  try {
    const results = [];
    // Small sequential requests allow honest per-message progress without
    // changing the API contract or exposing partial results as final.
    const chunkSize = 10;
    for (let offset = 0; offset < messages.length; offset += chunkSize) {
      const chunk = messages.slice(offset, offset + chunkSize);
      const data = await apiClient.postJson(API.analyzeBatch, { messages: chunk }, { signal: controller.signal });
      if (revision !== batchRevision) return;
      results.push(...(Array.isArray(data.results) ? data.results : []));
      updateBatchProgress(results.length, messages.length);
    }
    if (revision !== batchRevision) return;
    results.forEach((analysis, index) => { analysis.masked_input = batchMaskedIndices.has(index); });
    lastBatchResults = results;
    renderBatch(results);
    $("batch-empty").classList.add("hidden");
    if (historyEnabled) {
      for (const analysis of results) addHistory(analysis, "batch", { render: false });
      renderHistory();
      updateHistoryBadge();
      announceHistory(t("history.savedCount", { n: loadHistory().length, limit: HISTORY_LIMIT }));
    }
  } catch (failure) {
    if (revision === batchRevision && !(failure && failure.aborted)) {
      showBanner(banner, describeError(failure));
      $("batch-results").classList.add("hidden");
      $("batch-empty").classList.remove("hidden");
    }
  } finally {
    if (revision === batchRevision) {
      batchAbortController = null;
      $("batch-progress").classList.add("hidden");
      setBusy(button, false, t("batch.run"));
    }
  }
}

function openBatchResult(analysis) {
  invalidateSingle();
  safetyGuidanceState.delete(analysis);
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
    messageCell.dataset.label = t("batch.col.message");
    messageCell.textContent = analysis.message;
    messageCell.title = analysis.message;
    if (analysis.masked_input === true) {
      const badge = document.createElement("span");
      badge.className = "privacy-masked-badge";
      badge.textContent = t("privacy.maskedBadge");
      messageCell.append(badge);
    }
    const verdictCell = document.createElement("td");
    verdictCell.dataset.label = t("batch.col.verdict");
    verdictCell.append(verdictPill(band));
    const riskCell = document.createElement("td");
    riskCell.className = "risk-cell";
    riskCell.dataset.label = t("batch.col.risk");
    riskCell.append(miniMeter(analysis.spam_probability, band));
    const riskPct = document.createElement("span");
    riskPct.textContent = pct(analysis.spam_probability);
    riskPct.setAttribute("aria-label", `${pct(analysis.spam_probability)} ${scoreLabel(analysis)}`);
    riskCell.append(riskPct);
    const signalCell = document.createElement("td");
    signalCell.dataset.label = t("batch.col.signals");
    const patterns = signalSummary(analysis);
    signalCell.textContent = patterns;
    row.setAttribute("aria-label",
      t("batch.rowAria", {
        n: index + 1,
        band: bandTitle(band),
        pct: pct(analysis.spam_probability),
        score: scoreLabel(analysis),
        signals: patterns,
        privacy: analysis.masked_input === true ? t("privacy.maskedBadge") : "",
      }));

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

/* ---------- Message comparison (UI-only examples; never saved to history) ---------- */
const COMPARE_EXAMPLES = {
  otp: [
    "Your one-time code is [CODE]. Never share it. Open the official app if you did not request it.",
    "Your [CODE] OTP expires in 5 minutes. Confirm it now at verify-account.example to prevent a block.",
  ],
  delivery: [
    "Your parcel is out for delivery today. Check the official courier app; no extra payment is due.",
    "May parcel ka! Pay [AMOUNT] at parcel-release.example today or ibabalik ang delivery.",
  ],
  account: [
    "Your e-wallet transfer of [AMOUNT] is complete. Review it in the official app; never share your PIN.",
    "Wallet alert: account access will stop today. I-confirm ang PIN mo sa wallet-check.example para ma-restore.",
  ],
};
const COMPARE_EXAMPLE_NAMES = { otp: "OTP", delivery: "delivery", account: "bank / e-wallet" };
let compareRevision = 0;
let compareAbortController = null;
let currentComparison = null;
let compareMaskedInputs = [false, false];

function updateCompareCount(side) {
  const value = $(side === "a" ? "compare-message-a" : "compare-message-b").value;
  $(`compare-count-${side}`).textContent = `${Array.from(value).length} / ${MAX_MESSAGE_LENGTH}`;
}

function invalidateComparison({ preserveError = false } = {}) {
  compareRevision += 1;
  if (compareAbortController) {
    compareAbortController.abort();
    compareAbortController = null;
  }
  currentComparison = null;
  $("compare-results").classList.add("hidden");
  $("compare-empty").classList.remove("hidden");
  $("compare-summary").textContent = "";
  $("compare-result-cards").replaceChildren();
  $("compare-signal-differences").replaceChildren();
  $("compare-copy-status").textContent = "";
  $("compare-progress").classList.add("hidden");
  $("compare-example-note").textContent = t("compare.exampleNote");
  if (!preserveError) hideBanner($("compare-error"));
  setBusy($("btn-compare-run"), false, t("compare.run"));
}

function comparisonScoreText(result) {
  const score = validFraction(result && result.spam_probability);
  return score === null ? t("value.unavailable") : pct(score);
}

function modelContextText(result) {
  return typeof result.model_version === "string" && result.model_version
    ? result.model_version : t("value.unavailable");
}

function renderComparisonCard(result, name, index) {
  const card = document.createElement("article");
  card.className = "card compare-result-card";
  const heading = document.createElement("h3");
  heading.textContent = t("compare.resultFor", { name });
  const verdict = document.createElement("p");
  verdict.className = `compare-verdict ${bandView(bandOf(result)).css}`;
  verdict.textContent = `${t("compare.verdict")}: ${bandTitle(bandOf(result))} (${result.prediction || t("value.unavailable")})`;
  const privacyNote = document.createElement("p");
  privacyNote.className = "privacy-result-note";
  privacyNote.textContent = result.masked_input === true ? t("privacy.maskedResult") : "";
  privacyNote.classList.toggle("hidden", result.masked_input !== true);
  const details = document.createElement("dl");
  details.className = "compare-metadata";
  const rows = [
    [t("compare.score"), comparisonScoreText(result)],
    [t("compare.interpretation"), scoreLabel(result)],
    [t("compare.modelVersion"), modelContextText(result)],
    [t("compare.thresholds"), `${pct(validFraction(result.decision_threshold))} / ${pct(validFraction(result.suspicious_threshold))}`],
  ];
  for (const [labelText, valueText] of rows) {
    const term = document.createElement("dt");
    term.textContent = labelText;
    const definition = document.createElement("dd");
    definition.textContent = valueText;
    details.append(term, definition);
  }
  const provenance = document.createElement("p");
  provenance.className = "muted compare-provenance";
  provenance.textContent = resultMatchesLoadedModel(result)
    ? `${t("compare.provenance")}: ${modelInfo.data_note}${modelInfo.warnings.length ? ` ${modelInfo.warnings.join(" ")}` : ""}`
    : `${t("compare.provenance")}: ${t("model.provenance.unavailable")}`;
  const signalHeading = document.createElement("h4");
  signalHeading.textContent = t("signals.title");
  const highlighted = document.createElement("div");
  highlighted.className = "highlighted compare-highlighted";
  highlighted.setAttribute("role", "group");
  highlighted.setAttribute("aria-label", t("signals.group"));
  renderHighlighted(result, highlighted, `compare-${index}-signal`);
  const signalList = document.createElement("ul");
  signalList.className = "signals compare-signals";
  renderSignals(result, signalList, `compare-${index}-signal`);
  const tipsHeading = document.createElement("h4");
  tipsHeading.textContent = t("tips.title");
  const tips = document.createElement("ul");
  tips.className = `tips${bandOf(result) !== "looks_safe" ? " warn" : ""}`;
  for (const text of buildTips(result)) {
    const item = document.createElement("li");
    item.textContent = text;
    tips.append(item);
  }
  const guidance = document.createElement("div");
  guidance.className = "compare-guidance";
  renderSafetyGuidance(guidance, result, `compare-${index}`);
  card.append(heading, verdict, privacyNote, details, provenance, signalHeading, highlighted, signalList, tipsHeading, tips, guidance);
  return card;
}

function compareScoreInterpretation(left, right) {
  const leftScore = validFraction(left && left.spam_probability);
  const rightScore = validFraction(right && right.spam_probability);
  return Boolean(leftScore !== null && rightScore !== null
    && typeof left.model_version === "string" && left.model_version
    && left.model_version !== "unknown"
    && left.model_version === right.model_version
    && typeof left.probability_calibrated === "boolean"
    && left.probability_calibrated === right.probability_calibrated);
}

function detectedSignalTypes(result) {
  return new Set(signalMatches(result).map((match) => match.type));
}

function renderSignalDifferences(left, right, list = $("compare-signal-differences")) {
  list.replaceChildren();
  const typesA = detectedSignalTypes(left);
  const typesB = detectedSignalTypes(right);
  const common = [...typesA].filter((type) => typesB.has(type));
  const onlyA = [...typesA].filter((type) => !typesB.has(type));
  const onlyB = [...typesB].filter((type) => !typesA.has(type));
  const entries = [
    [t("compare.common"), common],
    [t("compare.onlyA"), onlyA],
    [t("compare.onlyB"), onlyB],
  ].filter(([, types]) => types.length);
  if (!entries.length) {
    const empty = document.createElement("li");
    empty.textContent = t("compare.none");
    list.append(empty);
    return { common, onlyA, onlyB };
  }
  for (const [label, types] of entries) {
    const item = document.createElement("li");
    const strong = document.createElement("strong");
    strong.textContent = `${label}: `;
    const names = document.createElement("span");
    names.textContent = types.map((type) => t(SIGNALS[type].labelKey)).join(", ");
    item.append(strong, names);
    list.append(item);
  }
  return { common, onlyA, onlyB };
}

function comparisonSummaryText(comparison) {
  const [left, right] = comparison.results;
  const lines = [t("compare.resultsTitle")];
  for (const [name, result] of [["A", left], ["B", right]]) {
    lines.push(`${t("compare.resultFor", { name: `Message ${name}` })}: ${bandTitle(bandOf(result))} (${result.prediction || t("value.unavailable")})`);
    lines.push(`${t("compare.score")}: ${comparisonScoreText(result)}`);
    lines.push(`${t("compare.interpretation")}: ${scoreLabel(result)}`);
    lines.push(`${t("compare.modelVersion")}: ${modelContextText(result)}`);
    lines.push(`${t("compare.thresholds")}: ${pct(validFraction(result.decision_threshold))} / ${pct(validFraction(result.suspicious_threshold))}`);
    if (result.masked_input === true) lines.push(t("privacy.maskedResult"));
    const provenance = resultMatchesLoadedModel(result) && modelInfo.data_note
      ? `${modelInfo.data_note}${modelInfo.warnings.length ? ` ${modelInfo.warnings.join(" ")}` : ""}`
      : t("model.provenance.unavailable");
    lines.push(`${t("compare.provenance")}: ${provenance}`);
  }
  lines.push(compareScoreInterpretation(left, right)
    ? `${t("compare.scoreDifference")}: ${t("compare.scoreDifferenceValue", { points: ((left.spam_probability - right.spam_probability) * 100).toFixed(1) })}`
    : t("compare.scoreNotComparable"));
  const differences = renderSignalDifferences(left, right, document.createElement("ul"));
  for (const [key, values] of [["compare.common", differences.common], ["compare.onlyA", differences.onlyA], ["compare.onlyB", differences.onlyB]]) {
    lines.push(`${t(key)}: ${values.length ? values.map((type) => t(SIGNALS[type].labelKey)).join(", ") : t("signals.noneSummary")}`);
  }
  lines.push(t("compare.differencesHelp"), t("compare.safetyNote"), t("footer.synthetic"));
  return lines.join("\n");
}

function renderComparison(results) {
  const [left, right] = results;
  currentComparison = { results };
  $("compare-result-cards").replaceChildren(
    renderComparisonCard(left, "Message A", 0),
    renderComparisonCard(right, "Message B", 1),
  );
  renderSignalDifferences(left, right);
  const comparable = compareScoreInterpretation(left, right);
  $("compare-summary").textContent = comparable
    ? `${t("compare.scoreDifference")}: ${t("compare.scoreDifferenceValue", { points: ((left.spam_probability - right.spam_probability) * 100).toFixed(1) })}`
    : t("compare.scoreNotComparable");
  $("compare-results").classList.remove("hidden");
  $("compare-empty").classList.add("hidden");
}

async function runComparison() {
  invalidateComparison();
  const revision = compareRevision;
  const leftInput = $("compare-message-a");
  const rightInput = $("compare-message-b");
  const messages = [leftInput.value.trim(), rightInput.value.trim()];
  clearPrivacyReview($("compare-review-a"));
  clearPrivacyReview($("compare-review-b"));
  const banner = $("compare-error");
  if (messages.some((message) => !message)) {
    showBanner(banner, t("compare.error.empty"));
    (messages[0] ? rightInput : leftInput).focus();
    return;
  }
  const oversized = messages.findIndex((message) => Array.from(message).length > MAX_MESSAGE_LENGTH);
  if (oversized !== -1) {
    showBanner(banner, t("compare.error.tooLong", { n: oversized ? "B" : "A", count: Array.from(messages[oversized]).length }));
    return;
  }
  const controller = new AbortController();
  compareAbortController = controller;
  setBusy($("btn-compare-run"), true, t("compare.busy"));
  $("compare-empty").classList.add("hidden");
  $("compare-progress").textContent = t("compare.progress");
  $("compare-progress").classList.remove("hidden");
  try {
    const data = await apiClient.postJson(API.analyzeBatch, { messages }, { signal: controller.signal });
    if (revision !== compareRevision) return;
    if (!data || !Array.isArray(data.results) || data.results.length !== 2
      || data.results.some((result, index) => !result || result.message !== messages[index])) {
      throw new Error(t("compare.error.failed"));
    }
    data.results.forEach((result, index) => { result.masked_input = compareMaskedInputs[index]; });
    renderComparison(data.results);
  } catch (failure) {
    if (revision === compareRevision && !(failure && failure.aborted)) {
      showBanner(banner, failure && failure.message === t("compare.error.failed")
        ? t("compare.error.failed") : describeError(failure));
      $("compare-empty").classList.remove("hidden");
    }
  } finally {
    if (revision === compareRevision) {
      compareAbortController = null;
      $("compare-progress").classList.add("hidden");
      setBusy($("btn-compare-run"), false, t("compare.run"));
    }
  }
}

async function copyComparisonSummary() {
  if (!currentComparison) return;
  const status = $("compare-copy-status");
  try {
    await navigator.clipboard.writeText(comparisonSummaryText(currentComparison));
    status.textContent = t("compare.copyDone");
  } catch {
    status.textContent = t("compare.copyFail");
  }
}

function initComparison() {
  for (const side of ["a", "b"]) {
    $(`compare-message-${side}`).addEventListener("input", () => {
      invalidateComparison();
      compareMaskedInputs[side === "a" ? 0 : 1] = false;
      clearPrivacyReview($(`compare-review-${side}`));
      updateCompareCount(side);
    });
    $(`btn-compare-review-${side}`).addEventListener("click", () => {
      const input = $(`compare-message-${side}`);
      const message = input.value.trim();
      if (!message) {
        showBanner($("compare-error"), t("compare.error.empty"));
        input.focus();
        return;
      }
      if (Array.from(message).length > MAX_MESSAGE_LENGTH) {
        showBanner($("compare-error"), t("compare.error.tooLong", {
          n: side.toUpperCase(), count: Array.from(message).length,
        }));
        return;
      }
      invalidateComparison();
      buildPrivacyReview($(`compare-review-${side}`), message, ({ text, masked }) => {
        input.value = text;
        compareMaskedInputs[side === "a" ? 0 : 1] = masked;
        updateCompareCount(side);
      }, t);
    });
    updateCompareCount(side);
  }
  $("btn-compare-run").addEventListener("click", runComparison);
  $("btn-compare-swap").addEventListener("click", () => {
    invalidateComparison();
    const left = $("compare-message-a");
    const right = $("compare-message-b");
    [left.value, right.value] = [right.value, left.value];
    compareMaskedInputs.reverse();
    clearPrivacyReview($("compare-review-a"));
    clearPrivacyReview($("compare-review-b"));
    updateCompareCount("a");
    updateCompareCount("b");
  });
  $("btn-compare-clear").addEventListener("click", () => {
    invalidateComparison();
    $("compare-message-a").value = "";
    $("compare-message-b").value = "";
    compareMaskedInputs = [false, false];
    clearPrivacyReview($("compare-review-a"));
    clearPrivacyReview($("compare-review-b"));
    updateCompareCount("a");
    updateCompareCount("b");
    $("compare-message-a").focus();
  });
  $("btn-compare-copy").addEventListener("click", copyComparisonSummary);
  for (const button of document.querySelectorAll("[data-compare-example]")) {
    button.addEventListener("click", () => {
      const pair = COMPARE_EXAMPLES[button.dataset.compareExample];
      if (!pair) return;
      invalidateComparison();
      $("compare-message-a").value = pair[0];
      $("compare-message-b").value = pair[1];
      compareMaskedInputs = [false, false];
      clearPrivacyReview($("compare-review-a"));
      clearPrivacyReview($("compare-review-b"));
      updateCompareCount("a");
      updateCompareCount("b");
      $("compare-example-note").textContent = t("compare.exampleLoaded", {
        name: COMPARE_EXAMPLE_NAMES[button.dataset.compareExample],
      });
    });
  }
}

/* ---------- CSV export (client-side only; nothing is uploaded) ---------- */
function csvCell(value) {
  let text = value === null || value === undefined ? "" : String(value);
  // Keep spreadsheet programs from evaluating SMS content as a formula.
  if (/^[\s\uFEFF]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

function downloadBatchCsv() {
  const status = $("csv-status");
  if (!Array.isArray(lastBatchResults) || !lastBatchResults.length) {
    status.textContent = t("batch.csv.fail");
    return;
  }
  const header = [
    t("batch.col.num"),
    t("batch.col.message"),
    t("batch.col.verdict"),
    "Model prediction",
    t("batch.col.risk"),
    t("batch.col.scoreDescription"),
    t("summary.threshold"),
    t("summary.suspiciousThreshold"),
    t("batch.col.signals"),
    t("summary.model"),
    t("privacy.batchColumn"),
  ];
  const rows = [header];
  lastBatchResults.forEach((analysis, index) => {
    rows.push([
      String(index + 1),
      typeof analysis.message === "string" ? analysis.message : "",
      bandTitle(bandOf(analysis)),
      String(analysis.prediction || ""),
      pct(analysis.spam_probability),
      scoreLabel(analysis),
      pct(analysis.decision_threshold),
      pct(analysis.suspicious_threshold),
      signalSummary(analysis),
      modelContextText(analysis),
      analysis.masked_input === true ? t("privacy.batchMasked") : t("privacy.batchUnmasked"),
    ]);
  });
  // BOM so Excel opens UTF-8 (₱, Filipino text) correctly.
  const blob = new Blob(["\uFEFF" + rows.map((row) => row.map(csvCell).join(",")).join("\r\n")], {
    type: "text/csv;charset=utf-8",
  });
  const filename = `sms-scam-checks-${new Date().toISOString().slice(0, 10)}.csv`;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  status.textContent = t("batch.csv.done", { file: filename });
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
  $("btn-privacy-review").addEventListener("click", () => {
    const message = input.value.trim();
    if (!message) {
      showBanner($("error-banner"), t("error.empty"));
      input.focus();
      return;
    }
    if (Array.from(message).length > MAX_MESSAGE_LENGTH) {
      showBanner($("error-banner"), t("error.tooLong", { n: Array.from(message).length }));
      return;
    }
    invalidateSingle();
    buildPrivacyReview($("single-privacy-review"), message, ({ text, masked }) => {
      input.value = text;
      updateCharCount();
      runCheck({ masked });
    }, t);
  });
  $("btn-copy-summary").addEventListener("click", copySummary);
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
      $("example-status").textContent = t("examples.status", {
        kind: chip.dataset.example === "scam" ? t("examples.scamKind") : t("examples.safeKind"),
        index: example.index,
        total: example.total,
      });
      runCheck();
    });
  }
  updateCharCount();
}

function initBatchCheck() {
  const input = $("batch-input");
  input.addEventListener("input", () => {
    invalidateBatch();
    batchMaskedIndices.clear();
    clearBatchPrivacyReview();
    $("batch-review-status").textContent = "";
    updateBatchCount();
  });
  input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      runBatch();
    }
  });
  $("btn-batch").addEventListener("click", () => runBatch());
  $("btn-batch-review").addEventListener("click", () => {
    invalidateBatch();
    renderBatchPrivacyReview();
  });
  $("btn-csv").addEventListener("click", downloadBatchCsv);
  updateBatchCount();
  $("batch-empty").textContent = t("batch.empty");
}

function initOfflineDetection() {
  window.addEventListener("offline", () => {
    connectionStatus.render();
    refreshServiceStatus();
  });
  window.addEventListener("online", () => {
    connectionStatus.render();
    connectionStatus.hideOfflineBanner();
    refreshServiceStatus();
    loadModelInfo();
  });
}

function initServiceWorker() {
  // Cache the static shell only. POST /analyze requests and other API calls
  // are never intercepted, so no message content is ever cached or synced.
  if (!("serviceWorker" in navigator)) return;
  const host = location.hostname;
  if (location.protocol !== "https:" && host !== "localhost" && host !== "127.0.0.1") return;
  navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" }).then((registration) => {
    // Check the release on normal visits so updated shell assets arrive without
    // asking users to perform a hard refresh.
    return registration.update();
  }).catch(() => {
    /* Offline shell support is a bonus; ignore registration failures. */
  });
}

document.addEventListener("DOMContentLoaded", () => {
  lang = readLanguage();
  currentTheme = readTheme();
  applyTheme(currentTheme);
  applyStaticI18n();
  $("btn-lang").textContent = lang === "taglish" ? "EN" : "Taglish";
  $("btn-lang").addEventListener("click", () => setLanguage(lang === "taglish" ? "en" : "taglish"));
  $("btn-theme").addEventListener("click", toggleTheme);
  updateThemeButton();
  initTabs();
  initHistory();
  initSingleCheck();
  initBatchCheck();
  initOfflineDetection();
  $("btn-retry-status").addEventListener("click", () => {
    refreshServiceStatus();
    loadModelInfo();
  });
  connectionStatus.render();
  renderModelInfo();
  refreshServiceStatus();
  loadModelInfo();
  initComparison();
  initServiceWorker();
});

/* Expose a tiny read-only hook for manual debugging in the console. */
window.phSmsd = {
  prefersReducedMotion,
  bandOf,
  modelInfo: () => modelInfo,
  language: () => lang,
  theme: () => currentTheme,
};
