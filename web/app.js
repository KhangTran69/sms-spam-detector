/* PH SMS Scam Detector — UI logic (no build step, vanilla JS). */
"use strict";

const API = { analyze: "/analyze", analyzeBatch: "/analyze/batch" };
const HISTORY_KEY = "smsd_history_v1";
const HISTORY_LIMIT = 50;

/* Verdict bands over the model's spam probability. The 0.70 cutoff mirrors the
   project's precision-first guidance (legit OTPs must not read as "scam"). */
const BANDS = {
  spam: { min: 0.70, title: "Likely scam", icon: "🚨" },
  suspicious: { min: 0.40, title: "Suspicious", icon: "⚠️" },
  safe: { min: 0.00, title: "Looks safe", icon: "✅" },
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

function bandOf(spamProbability) {
  if (spamProbability >= BANDS.spam.min) return "spam";
  if (spamProbability >= BANDS.suspicious.min) return "suspicious";
  return "safe";
}

async function api(path, body) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Could not reach the API — is the server running?");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
        : `Request failed (HTTP ${response.status})`;
    throw new Error(message);
  }
  return data;
}

/* ---------- Tabs ---------- */
function switchTab(name) {
  for (const tab of document.querySelectorAll(".tab")) {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  for (const panel of document.querySelectorAll(".panel")) {
    panel.classList.toggle("active", panel.id === `panel-${name}`);
  }
}

/* ---------- Single check rendering ---------- */
function renderVerdict(analysis) {
  const band = bandOf(analysis.spam_probability);
  const card = $("verdict-card");
  card.className = `card verdict ${band}`;
  $("verdict-icon").textContent = BANDS[band].icon;
  $("verdict-title").textContent = BANDS[band].title;
  const pct = Math.round(analysis.spam_probability * 100);
  $("verdict-sub").textContent =
    `${pct}% scam probability · model verdict: ${analysis.prediction} · confidence ${(analysis.probability * 100).toFixed(1)}%`;
}

function renderMeter(spamProbability) {
  const pct = Math.round(spamProbability * 100);
  $("meter-marker").style.left = `${pct}%`;
  const value = $("meter-value");
  value.textContent = `${pct}%`;
  value.style.color = { spam: "var(--red)", suspicious: "var(--amber)", safe: "var(--green)" }[bandOf(spamProbability)];
}

function renderHighlighted(message, matches) {
  const container = $("highlighted");
  container.replaceChildren();
  let pos = 0;
  for (const match of matches) {
    if (match.start > pos) container.append(document.createTextNode(message.slice(pos, match.start)));
    const mark = document.createElement("mark");
    mark.className = `sig sig-${match.type}`;
    mark.textContent = match.text;
    mark.title = `${SIGNALS[match.type]?.label || match.type} signal`;
    container.append(mark);
    pos = match.end;
  }
  if (pos < message.length) container.append(document.createTextNode(message.slice(pos)));
  if (!matches.length) container.append(document.createTextNode(message));
}

function renderSignals(analysis) {
  const container = $("signals");
  container.replaceChildren();
  const counts = {};
  for (const match of analysis.matches) counts[match.type] = (counts[match.type] || 0) + 1;
  const dotColor = { url: "#2563eb", phone: "#7c3aed", money: "#d97706", urgency: "#dc2626", brand: "#db2777" };
  for (const [type, count] of Object.entries(counts)) {
    const chip = document.createElement("span");
    chip.className = `chip chip-${type}`;
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = dotColor[type] || "#94a3b8";
    chip.append(dot, document.createTextNode(`${SIGNALS[type]?.label || type}${count > 1 ? ` ×${count}` : ""}`));
    container.append(chip);
  }
  if (analysis.brands.length) {
    const names = analysis.brands.map((b) => BRANDS[b] || b.toUpperCase()).join(", ");
    const brandChip = document.createElement("span");
    const risky = analysis.spam_probability >= BANDS.suspicious.min;
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
  const flags = new Set(analysis.flags);
  const risky = analysis.spam_probability >= BANDS.suspicious.min;
  const brandNames = analysis.brands.map((b) => BRANDS[b] || b.toUpperCase());
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
  list.className = `tips${analysis.spam_probability >= BANDS.suspicious.min ? " warn" : ""}`;
  for (const tip of buildTips(analysis)) {
    const li = document.createElement("li");
    li.textContent = tip;
    list.append(li);
  }
}

function renderAnalysis(analysis, { save = true } = {}) {
  $("result").classList.remove("hidden");
  renderVerdict(analysis);
  renderMeter(analysis.spam_probability);
  renderHighlighted(analysis.message, analysis.matches);
  renderSignals(analysis);
  renderTips(analysis);
  if (save) addHistory(analysis);
}

/* ---------- History (localStorage) ---------- */
function loadHistory() {
  try {
    const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveHistory(entries) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, HISTORY_LIMIT)));
  updateHistoryBadge();
}

function addHistory(analysis, source = "single") {
  const entries = loadHistory();
  const newest = entries[0];
  const duplicate = newest && newest.message === analysis.message &&
    newest.prediction === analysis.prediction && Math.abs(newest.spam_probability - analysis.spam_probability) < 0.005;
  if (!duplicate) {
    entries.unshift({
      t: Date.now(),
      message: analysis.message,
      prediction: analysis.prediction,
      spam_probability: analysis.spam_probability,
      probability: analysis.probability,
      flags: analysis.flags,
      matches: analysis.matches,
      brands: analysis.brands,
      source,
    });
  }
  saveHistory(entries);
  renderHistory();
}

function updateHistoryBadge() {
  const count = loadHistory().length;
  const badge = $("history-count");
  badge.textContent = String(count);
  badge.classList.toggle("hidden", count === 0);
}

function verdictPill(band) {
  const pill = document.createElement("span");
  pill.className = `verdict-pill ${band}`;
  pill.textContent = BANDS[band].title;
  return pill;
}

function miniMeter(spamProbability) {
  const wrap = document.createElement("div");
  wrap.className = "mini-meter";
  const fill = document.createElement("div");
  fill.style.width = `${Math.round(spamProbability * 100)}%`;
  fill.style.background = { spam: "var(--red)", suspicious: "var(--amber)", safe: "var(--green)" }[bandOf(spamProbability)];
  wrap.append(fill);
  return wrap;
}

function renderHistory() {
  const entries = loadHistory();
  const list = $("history-list");
  list.replaceChildren();
  $("history-empty").classList.toggle("hidden", entries.length > 0);
  for (const entry of entries) {
    const li = document.createElement("li");
    const band = bandOf(entry.spam_probability);
    const main = document.createElement("div");
    main.className = "history-item-main";
    const msg = document.createElement("div");
    msg.className = "history-msg";
    msg.textContent = entry.message;
    const meta = document.createElement("div");
    meta.className = "history-meta";
    meta.textContent = `${new Date(entry.t).toLocaleString()}${entry.source === "batch" ? " · batch" : ""}`;
    main.append(msg, meta);
    const risk = document.createElement("span");
    risk.className = `history-risk ${band}`;
    risk.textContent = `${Math.round(entry.spam_probability * 100)}%`;
    li.append(main, verdictPill(band), risk);
    li.addEventListener("click", () => {
      $("message-input").value = entry.message;
      updateCharCount();
      switchTab("check");
      renderAnalysis(entry, { save: false });
    });
    list.append(li);
  }
}

/* ---------- Single check flow ---------- */
function updateCharCount() {
  $("char-count").textContent = `${$("message-input").value.length} / 10000`;
}

async function runCheck() {
  const message = $("message-input").value.trim();
  const banner = $("error-banner");
  banner.classList.add("hidden");
  if (!message) {
    banner.textContent = "Type or paste a message first.";
    banner.classList.remove("hidden");
    return;
  }
  const button = $("btn-check");
  button.disabled = true;
  button.textContent = "Checking…";
  try {
    const analysis = await api(API.analyze, { message });
    renderAnalysis(analysis);
  } catch (err) {
    banner.textContent = err.message;
    banner.classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = "Check message";
  }
}

/* ---------- Batch flow ---------- */
function parseBatchInput() {
  return $("batch-input").value.split("\n").map((line) => line.trim()).filter(Boolean);
}

function updateBatchCount() {
  const n = parseBatchInput().length;
  $("batch-count").textContent = `${n} message${n === 1 ? "" : "s"}`;
}

async function runBatch() {
  const messages = parseBatchInput();
  const banner = $("batch-error");
  banner.classList.add("hidden");
  if (!messages.length) {
    banner.textContent = "Paste at least one message (one per line).";
    banner.classList.remove("hidden");
    return;
  }
  if (messages.length > 50) {
    banner.textContent = "Batch is limited to 50 messages — remove some lines and try again.";
    banner.classList.remove("hidden");
    return;
  }
  const button = $("btn-batch");
  button.disabled = true;
  button.textContent = "Checking…";
  try {
    const data = await api(API.analyzeBatch, { messages });
    renderBatch(data.results);
    for (const analysis of data.results) addHistory(analysis, "batch");
  } catch (err) {
    banner.textContent = err.message;
    banner.classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = "Check all";
  }
}

function renderBatch(results) {
  const summary = $("batch-summary");
  const tbody = $("batch-tbody");
  summary.classList.remove("hidden");
  $("batch-results").classList.remove("hidden");
  tbody.replaceChildren();

  const stats = { spam: 0, suspicious: 0, safe: 0 };
  results.forEach((analysis, index) => {
    const band = bandOf(analysis.spam_probability);
    stats[band] += 1;

    const row = document.createElement("tr");
    const num = document.createElement("td");
    num.textContent = String(index + 1);
    const msgCell = document.createElement("td");
    msgCell.className = "batch-msg";
    msgCell.textContent = analysis.message;
    msgCell.title = analysis.message;
    const verdictCell = document.createElement("td");
    verdictCell.append(verdictPill(band));
    const riskCell = document.createElement("td");
    riskCell.className = "risk-cell";
    riskCell.append(miniMeter(analysis.spam_probability));
    const riskPct = document.createElement("span");
    riskPct.textContent = `${Math.round(analysis.spam_probability * 100)}%`;
    riskCell.append(riskPct);
    const sigCell = document.createElement("td");
    const types = [...new Set(analysis.matches.map((m) => m.type))];
    sigCell.textContent = types.map((t) => SIGNAL_SHORT[t] || t).join(" · ") || "—";

    row.append(num, msgCell, verdictCell, riskCell, sigCell);
    row.addEventListener("click", () => {
      $("message-input").value = analysis.message;
      updateCharCount();
      switchTab("check");
      renderAnalysis(analysis, { save: false });
    });
    tbody.append(row);
  });

  $("stat-scam").textContent = String(stats.spam);
  $("stat-suspicious").textContent = String(stats.suspicious);
  $("stat-safe").textContent = String(stats.safe);
}

/* ---------- Wiring ---------- */
document.addEventListener("DOMContentLoaded", () => {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  }

  const input = $("message-input");
  input.addEventListener("input", updateCharCount);
  input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") runCheck();
  });
  $("btn-check").addEventListener("click", runCheck);
  $("btn-clear").addEventListener("click", () => {
    input.value = "";
    updateCharCount();
    $("result").classList.add("hidden");
    $("error-banner").classList.add("hidden");
    input.focus();
  });

  for (const chip of document.querySelectorAll(".example-chip")) {
    chip.addEventListener("click", () => {
      input.value = EXAMPLES[chip.dataset.example];
      updateCharCount();
      runCheck();
    });
  }

  const batchInput = $("batch-input");
  batchInput.addEventListener("input", updateBatchCount);
  batchInput.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") runBatch();
  });
  $("btn-batch").addEventListener("click", runBatch);

  $("btn-clear-history").addEventListener("click", () => {
    if (loadHistory().length && confirm("Clear all saved checks from this browser?")) {
      saveHistory([]);
      renderHistory();
    }
  });

  updateCharCount();
  updateBatchCount();
  updateHistoryBadge();
  renderHistory();
});
