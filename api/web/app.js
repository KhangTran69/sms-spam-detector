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
const LANG_KEY = "smsd_lang_v1";
const THEME_KEY = "smsd_theme_v1";

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
  probability_calibrated: false,
};

/* ---------- Lightweight i18n (English / Taglish) ----------
   Static text is translated through data-i18n attributes in index.html;
   dynamic strings call t("key"). Missing keys fall back to English, and
   English falls back to the key itself, so a missing entry can never blank
   the UI. */
const I18N = {
  en: {
    "skip": "Skip to main content",
    "nav.views": "Views",
    "lang.aria": "Switch language between English and Taglish",
    "theme.aria": "Switch between light and dark mode",
    "theme.light": "Switch to light mode",
    "theme.dark": "Switch to dark mode",
    "offline.banner": "You appear to be offline. The page still works, but new checks need a connection.",
    "tab.check": "Check a message",
    "tab.batch": "Batch check",
    "tab.history": "History",
    "model.info": "Model information",
    "model.loading": "Loading…",
    "model.versionPrefix": "Model version: ",
    "model.thresholds.loading": "Decision threshold and risk bands are loading from the API.",
    "model.thresholds.line": "Decision threshold {threshold} · risk bands: likely scam ≥ {scam}, suspicious ≥ {suspicious}.",
    "model.fallbackSuffix": " Using built-in fallback thresholds until model information is available.",
    "model.legacyWarning": "This is a legacy model with missing training metadata. Treat results as a demo only.",
    "check.label": "Paste the SMS you want to check",
    "check.placeholder": "e.g. Bank notice: Your account review is due. Visit bank-help.example to read more.",
    "check.help": "At most 10,000 characters. Messages are analysed in memory and are never stored on the server.",
    "check.clear": "Clear",
    "check.run": "Check message",
    "check.busy": "Checking…",
    "error.empty": "Type or paste an SMS message first.",
    "error.tooLong": "That message is {n} characters — the limit is 10,000.",
    "error.reach": "Could not reach the detector API. Check that the server is running and try again.",
    "error.http": "Request failed (HTTP {status}). Please try again.",
    "error.model503": "The model is not available on this server. If you run this project locally, train it with: python -m src.train",
    "error.trainHint": " If you run this project locally, train the model with: python -m src.train",
    "error.generic": "Something went wrong. Please try again.",
    "examples.aria": "Example messages",
    "examples.label": "Try an example:",
    "examples.scam": "Scam example",
    "examples.safe": "Safe example",
    "examples.note": "Fictional demo examples only. Click either button again to cycle through more messages.",
    "examples.status": "Loaded fictional {kind} message {index} of {total}; checking it now. Click again for another example.",
    "examples.scamKind": "scam",
    "examples.safeKind": "safe",
    "result.aria": "Analysis result",
    "band.likely_scam": "Likely scam",
    "band.suspicious": "Suspicious",
    "band.looks_safe": "Looks safe",
    "verdict.score.uncalibrated": "uncalibrated model score",
    "verdict.score.calibrated": "estimated scam probability",
    "verdict.modelVerdict": "model verdict",
    "verdict.decisionThreshold": "decision threshold",
    "meter.title": "Estimated scam score",
    "meter.aria": "Uncalibrated model score",
    "meter.aria.calibrated": "Estimated scam probability",
    "copy.summary": "Copy summary",
    "copy.done": "Copied!",
    "copy.fail": "Could not copy automatically; please copy manually.",
    "summary.header": "PH SMS Scam Detector — result",
    "summary.verdict": "Verdict",
    "summary.score": "Score",
    "summary.signals": "Signals",
    "summary.message": "Message",
    "summary.tips": "Tips",
    "summary.model": "Model version",
    "signals.title": "Message signals",
    "signals.guidance": "These highlights mark text patterns the detector recognizes. They do not show which features influenced the model’s verdict. Links, numbers, amounts, urgency, and brand names can appear in legitimate messages too.",
    "signals.group": "Message text with detected text patterns",
    "signals.empty": "No supported text patterns were detected. That alone does not mean the message is safe.",
    "signals.noneSummary": "No supported text patterns",
    "signal.url.label": "Link",
    "signal.url.plural": "links",
    "signal.url.explanation": "Link-like text appears here. It may still be legitimate; check destinations independently.",
    "signal.phone.label": "Phone number",
    "signal.phone.plural": "phone numbers",
    "signal.phone.explanation": "A phone number appears. This does not identify who sent the message.",
    "signal.money.label": "Money amount",
    "signal.money.plural": "money amounts",
    "signal.money.explanation": "An amount appears. Legitimate bills and transaction alerts can include amounts.",
    "signal.urgency.label": "Urgency wording",
    "signal.urgency.plural": "urgency phrases",
    "signal.urgency.explanation": "These words can add time pressure, but urgency alone does not prove a scam.",
    "signal.brand.label": "Brand name",
    "signal.brand.plural": "brand names",
    "signal.brand.explanation": "A brand is mentioned. This does not verify the sender or prove impersonation.",
    "tips.title": "Safety tips",
    "tips.noReply": "Do not reply, tap links, or call the number in this message.",
    "tips.brandMentions": "This message mentions {brands}; that does not verify who sent it. Confirm account claims in the official app or through a trusted contact channel.",
    "tips.url": "Don't open links from unexpected texts. Open the official app or type the address yourself.",
    "tips.money": "Real prizes or refunds are never released in exchange for a fee, gift cards, or account details.",
    "tips.phone": "Replying or calling back confirms your number is active and invites more scam texts.",
    "tips.urgency": "Pressure to act right now is a classic scam tactic — slow down and double-check first.",
    "tips.otp": "Never share OTPs, PINs, or passwords — banks and e-wallets will never ask for them.",
    "tips.safeSpoof": "Even safe-looking senders can be spoofed; confirm money or account changes through the official channel.",
    "feedback.title": "Help improve the detector",
    "feedback.help": "Optional anonymous report. It sends your selected correction, category, and model version only—never the SMS text. The operator must enable feedback collection.",
    "feedback.label": "What do you think the message is?",
    "feedback.ham": "Legitimate message",
    "feedback.spam": "Spam or scam",
    "feedback.category": "Message category",
    "feedback.cat.other": "Not sure / other",
    "feedback.cat.otp": "OTP or verification code",
    "feedback.cat.bank": "Bank or e-wallet alert",
    "feedback.cat.delivery": "Delivery or parcel notice",
    "feedback.cat.personal": "Personal message",
    "feedback.cat.prize": "Prize or giveaway",
    "feedback.cat.phishing": "Link or account phishing",
    "feedback.submit": "Send anonymous correction",
    "feedback.busy": "Sending…",
    "feedback.chooseDifferent": "Choose the label you think the model got wrong.",
    "feedback.receipt": "Receipt: {id}",
    "batch.label": "Paste messages — one per line (up to 50)",
    "batch.placeholder": "One message per line…\nClaim a [AMOUNT] prize at prizes.example today.\nYour OTP is [CODE]. Do not share it.",
    "batch.help": "One message per line. At most 50 messages and 200,000 characters in total; blank lines are ignored. Nothing is stored on the server.",
    "batch.run": "Check all",
    "batch.busy": "Checking…",
    "batch.progress": "Analyzing {done} of {total} messages…",
    "batch.empty": "Add messages above, then choose Check all to see their results here.",
    "batch.error.empty": "Paste at least one message (one per line).",
    "batch.error.limit": "Batch is limited to {n} messages — remove some lines and try again.",
    "batch.error.chars": "Batch is limited to 200,000 total characters. Remove some text and try again.",
    "batch.error.itemTooLong": "Message {n} is longer than 10,000 characters.",
    "batch.caption": "Batch analysis results — one row per message. Select a row (or press Enter or Space) to open its full analysis.",
    "batch.col.num": "#",
    "batch.col.message": "Message",
    "batch.col.verdict": "Verdict",
    "batch.col.risk": "Scam risk",
    "batch.col.signals": "Signals",
    "batch.csv": "Download CSV",
    "batch.csv.done": "Downloaded {file}",
    "batch.csv.fail": "No results to download yet.",
    "batch.rowAria": "Message {n}: {band}, {pct} model score. Detected text patterns: {signals}. Press Enter to open the full analysis.",
    "batch.count.one": "1 message · {chars} characters",
    "batch.count.many": "{n} messages · {chars} characters",
    "history.title": "Recent checks",
    "history.clear": "Clear history",
    "history.list": "Saved checks",
    "history.optin": "Save my checks in this browser",
    "history.privacy": "Off by default. When on, the last 50 checks are stored only in this browser's localStorage — message text is never sent to or stored on the server. Turn it off to delete saved history from this browser.",
    "history.offnote": "History is off. Turn it on to keep the last 50 checks in this browser.",
    "history.empty": "No saved checks yet. Check a message and it will appear here.",
    "history.on": "History is on. Checks are saved only in this browser, up to 50 entries.",
    "history.off": "History is off. Any saved checks were deleted from this browser.",
    "history.cleared": "Saved history cleared from this browser.",
    "history.savedCount": "Saved in this browser: {n} of {limit} checks.",
    "history.confirmClear": "Delete all checks saved in this browser?",
    "history.reopenAria": "Reopen saved check from {time} — {band}, {pct} model score",
    "footer.disclaimer": "Heuristic aid, not a guarantee. Verify money or account messages through the official app or hotline — and never share OTPs or PINs.",
    "footer.synthetic": "Checks using synthetic Philippine data are not proof of real-world accuracy.",
  },
  taglish: {
    "skip": "Laktawan ang pangunahing nilalaman",
    "nav.views": "Mga view",
    "lang.aria": "Palitan ang wika: English o Taglish",
    "theme.aria": "Magpalit sa pagitan ng maliwanag at madilim na mode",
    "theme.light": "Lumipat sa maliwanag na mode",
    "theme.dark": "Lumipat sa madilim na mode",
    "offline.banner": "Mukhang offline ka. Gumagana pa rin ang pahina, pero kailangan ng connection ang mga bagong check.",
    "tab.check": "Tingnan ang mensahe",
    "tab.batch": "Maramihang check",
    "tab.history": "History",
    "model.info": "Impormasyon ng modelo",
    "model.loading": "Naglo-load…",
    "model.versionPrefix": "Bersyon ng modelo: ",
    "model.thresholds.loading": "Niloload mula sa API ang decision threshold at risk bands.",
    "model.thresholds.line": "Decision threshold {threshold} · risk bands: malamang scam ≥ {scam}, kahina-hinala ≥ {suspicious}.",
    "model.fallbackSuffix": " Ginagamit muna ang built-in na fallback thresholds hanggang makuha ang impormasyon ng modelo.",
    "model.legacyWarning": "Lumang modelo ito na walang kumpletong training metadata. Demo lamang ang resulta.",
    "check.label": "I-paste ang SMS na gusto mong i-check",
    "check.placeholder": "Hal. May notice sa account mo. Tingnan sa bank-help.example kung kailangan ng action.",
    "check.help": "Hanggang 10,000 karakter. Sinusuri sa memory ang mga mensahe at hindi kailanman iniimbak sa server.",
    "check.clear": "Burahin",
    "check.run": "I-check ang mensahe",
    "check.busy": "Sinusuri…",
    "error.empty": "Mag-type o mag-paste muna ng mensahe.",
    "error.tooLong": "{n} karakter ang mensahe — ang limit ay 10,000.",
    "error.reach": "Hindi makausap ang detector API. Siguraduhing naka-run ang server at subukan ulit.",
    "error.http": "Nabigo ang request (HTTP {status}). Subukan ulit.",
    "error.model503": "Hindi available ang modelo sa server na ito. Kung local ang pag-run mo, i-train ito gamit ang: python -m src.train",
    "error.trainHint": " Kung local ang pag-run mo, i-train ang modelo gamit ang: python -m src.train",
    "error.generic": "May naganap na mali. Subukan ulit.",
    "examples.aria": "Mga halimbawang mensahe",
    "examples.label": "Subukan ang halimbawa:",
    "examples.scam": "Halimbawa ng scam",
    "examples.safe": "Halimbawang ligtas",
    "examples.note": "Gawa-gawa lamang na demo na mga halimbawa. I-click muli ang alinmang button para umikot sa ibang mensahe.",
    "examples.status": "Na-load ang gawa-gawang {kind} na mensahe ({index} ng {total}); sinusuri na. I-click muli para sa isa pa.",
    "examples.scamKind": "scam",
    "examples.safeKind": "ligtas",
    "result.aria": "Resulta ng pagsusuri",
    "band.likely_scam": "Malamang scam",
    "band.suspicious": "Kahina-hinala",
    "band.looks_safe": "Mukhang ligtas",
    "verdict.score.uncalibrated": "model score (hindi pa-calibrate)",
    "verdict.score.calibrated": "tinatayang posibilidad ng scam",
    "verdict.modelVerdict": "hatol ng modelo",
    "verdict.decisionThreshold": "decision threshold",
    "meter.title": "Tinatayang scam score",
    "meter.aria": "Model score (hindi pa-calibrate)",
    "meter.aria.calibrated": "Tinatayang posibilidad ng scam",
    "copy.summary": "Kopyahin ang buod",
    "copy.done": "Nakopya na!",
    "copy.fail": "Hindi awtomatikong nakopya; kopyahin nang manual.",
    "summary.header": "PH SMS Scam Detector — resulta",
    "summary.verdict": "Hatol",
    "summary.score": "Score",
    "summary.signals": "Mga signal",
    "summary.message": "Mensahe",
    "summary.tips": "Mga tip",
    "summary.model": "Bersyon ng modelo",
    "signals.title": "Mga signal sa mensahe",
    "signals.guidance": "Inilalagyan ng highlight ang mga pattern sa text na kilala ng detector. Hindi ito pinapakita kung aling features ang naka-impluwensya sa hatol ng modelo. Ang mga link, numero, halaga, salitang may pagmamadali, at brand ay maaari ring lumabas sa lehitimong mensahe.",
    "signals.group": "Text ng mensahe kasama ang mga natuklasang pattern",
    "signals.empty": "Walang natuklasang kilalang pattern sa text. Iyon lamang ay hindi nangangahulugang ligtas ang mensahe.",
    "signals.noneSummary": "Walang kilalang pattern sa text",
    "signal.url.label": "Link",
    "signal.url.plural": "mga link",
    "signal.url.explanation": "May lumilitaw na text na parang link. Maaari pa rin itong lehitimo; i-check ang destinasyon nang hiwalay.",
    "signal.phone.label": "Numero ng telepono",
    "signal.phone.plural": "mga numero ng telepono",
    "signal.phone.explanation": "May lumilitaw na numero ng telepono. Hindi nito sinasabi kung sino ang nagpadala ng mensahe.",
    "signal.money.label": "Halaga",
    "signal.money.plural": "mga halaga",
    "signal.money.explanation": "May lumilitaw na halaga. Ang lehitimong bayarin at transaction alert ay maaaring maglaman ng halaga.",
    "signal.urgency.label": "Salitang pagmamadali",
    "signal.urgency.plural": "mga salitang pagmamadali",
    "signal.urgency.explanation": "Ang mga salitang ito ay maaaring magdagdag ng pressure ng oras, pero ang pagmamadali lamang ay hindi patunay ng scam.",
    "signal.brand.label": "Pangalan ng brand",
    "signal.brand.plural": "mga pangalan ng brand",
    "signal.brand.explanation": "May binanggit na brand. Hindi nito beripikado ang nagpadala ni napatunayang nagpanggap ang mensahe.",
    "tips.title": "Mga safety tip",
    "tips.noReply": "Huwag sasagot, huwag i-click ang mga link, at huwag tatawag sa numero sa mensaheng ito.",
    "tips.brandMentions": "Binabanggit ng mensahe ang {brands}; hindi nito beripikado kung sino ang nagpadala. Kumpirmahin ang mga claim sa opisyal na app o sa pinagkakatiwalaang contact channel.",
    "tips.url": "Huwag magbubukas ng link mula sa hindi inaasahang text. Buksan ang opisyal na app o i-type mo mismo ang address.",
    "tips.money": "Ang totoong premyo o refund ay hindi kailanman ipinagpapalit sa fee, gift card, o account details.",
    "tips.phone": "Ang pagsagot o pagtawag muli ay kumpirmang aktibo ang numero mo at nag-aanyaya ng mas maraming scam text.",
    "tips.urgency": "Ang pagpilit na kumilos ngayon na ay klasikong tactic ng scam — huminahon muna at i-double-check.",
    "tips.otp": "Huwag kailanman ibabahagi ang OTP, PIN, o password — hindi ito hihingin ng bangko o e-wallet.",
    "tips.safeSpoof": "Kahit mukhang lehitimong nagpadala ay maaaring peke; kumpirmahin ang pera o account changes sa opisyal na channel.",
    "feedback.title": "Tulungang pabutihin ang detector",
    "feedback.help": "Opsyonal at anonymous na report. Ipapadala lang ang napili mong correction, category, at bersyon ng modelo — hindi kailanman ang text ng SMS. Kailangang i-enable ng operator ang feedback collection.",
    "feedback.label": "Ano sa palagay mo ang mensahe?",
    "feedback.ham": "Lehitimong mensahe",
    "feedback.spam": "Spam o scam",
    "feedback.category": "Kategorya ng mensahe",
    "feedback.cat.other": "Hindi sigurado / iba pa",
    "feedback.cat.otp": "OTP o verification code",
    "feedback.cat.bank": "Alerto ng bangko o e-wallet",
    "feedback.cat.delivery": "Delivery o parcel notice",
    "feedback.cat.personal": "Personal na mensahe",
    "feedback.cat.prize": "Premyo o giveaway",
    "feedback.cat.phishing": "Link o account phishing",
    "feedback.submit": "Ipadala ang anonymous na correction",
    "feedback.busy": "Ipinapadala…",
    "feedback.chooseDifferent": "Piliin ang label na sa palagay mo ay mali ang modelo.",
    "feedback.receipt": "Resibo: {id}",
    "batch.label": "I-paste ang mga mensahe — isa kada linya (hanggang 50)",
    "batch.placeholder": "Isa kada linya…\nClaim ng [AMOUNT] prize sa prizes.example ngayon.\nAng OTP mo ay [CODE]. Huwag itong i-share.",
    "batch.help": "Isa kada linya. Hanggang 50 mensahe at 200,000 karakter lahat; hindi pinapansin ang blankong linya. Walang iniimbak sa server.",
    "batch.run": "I-check lahat",
    "batch.busy": "Sinusuri…",
    "batch.progress": "Sinusuri na ang {done} sa {total} na messages…",
    "batch.empty": "Maglagay ng messages sa taas, tapos pindutin ang I-check lahat para makita rito ang results.",
    "batch.error.empty": "Mag-paste muna ng kahit isang mensahe (isa kada linya).",
    "batch.error.limit": "Hanggang {n} mensahe lang ang batch — alisin ang ilang linya at subukan ulit.",
    "batch.error.chars": "Hanggang 200,000 karakter lahat ang batch. Alisin ang ilang text at subukan ulit.",
    "batch.error.itemTooLong": "Mas mahaba sa 10,000 karakter ang mensahe {n}.",
    "batch.caption": "Resulta ng batch analysis — isang row kada mensahe. Piliin ang row (o pindutin ang Enter o Space) para buksan ang buong analysis.",
    "batch.col.num": "#",
    "batch.col.message": "Mensahe",
    "batch.col.verdict": "Hatol",
    "batch.col.risk": "Scam risk",
    "batch.col.signals": "Mga signal",
    "batch.csv": "I-download ang CSV",
    "batch.csv.done": "Nai-download: {file}",
    "batch.csv.fail": "Wala pang resultang ma-download.",
    "batch.rowAria": "Mensahe {n}: {band}, {pct} model score. Mga natuklasang pattern: {signals}. Pindutin ang Enter para buksan ang buong analysis.",
    "batch.count.one": "1 mensahe · {chars} karakter",
    "batch.count.many": "{n} mensahe · {chars} karakter",
    "history.title": "Mga kamakailang check",
    "history.clear": "Burahin ang history",
    "history.list": "Mga naka-save na check",
    "history.optin": "I-save ang mga check ko sa browser na ito",
    "history.privacy": "Naka-off bilang default. Kapag naka-on, ang huling 50 check ay naka-imbak lang sa localStorage ng browser na ito — ang text ng mensahe ay hindi kailanman ipinapadala o iniimbak sa server. I-off ito para burahin ang naka-save na history.",
    "history.offnote": "Naka-off ang history. I-on ito para i-keep ang huling 50 check sa browser na ito.",
    "history.empty": "Wala pang naka-save na check. Mag-check ng mensahe at lalabas ito rito.",
    "history.on": "Naka-on ang history. Naka-imbak lang sa browser na ito ang mga check, hanggang 50.",
    "history.off": "Naka-off ang history. Nabura na ang anumang naka-save na check sa browser na ito.",
    "history.cleared": "Nabura na ang naka-save na history sa browser na ito.",
    "history.savedCount": "Naka-save sa browser na ito: {n} sa {limit} check.",
    "history.confirmClear": "Burahin lahat ng naka-save na check sa browser na ito?",
    "history.reopenAria": "Buksan muli ang check mula {time} — {band}, {pct} model score",
    "footer.disclaimer": "Gabay lamang ito, hindi garantiya. I-verify ang mga mensahe tungkol sa pera o account sa opisyal na app o hotline — at huwag kailanman ibahagi ang OTP o PIN.",
    "footer.synthetic": "Ang mga check na gumagamit ng synthetic Philippine data ay hindi patunay ng totoong kakayahan.",
  },
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
  renderModelInfo();
  renderHistory();
  updateHistoryBadge();
  updateCharCount();
  updateBatchCount();
  $("example-status").textContent = t("examples.note");
  $("copy-status").textContent = "";
  $("feedback-status").textContent = "";
  $("csv-status").textContent = "";
  $("history-status").textContent = "";
  if (batchAbortController && batchProgress) updateBatchProgress(batchProgress.done, batchProgress.total);
  if (window.currentAnalysis) renderAnalysis(window.currentAnalysis, { save: false });
  if (lastBatchResults) renderBatch(lastBatchResults);
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

/* ---------- Offline banner ---------- */
function showOfflineBanner() {
  $("offline-banner").classList.remove("hidden");
}

function hideOfflineBanner() {
  $("offline-banner").classList.add("hidden");
}

/* ---------- Banding ---------- */
/* API risk_band -> presentation. Titles/icons live here so every view is
   consistent; cutoffs always come from modelInfo.bands. */
const BAND_VIEW = {
  likely_scam: { css: "spam", icon: "🚨", key: "band.likely_scam" },
  suspicious: { css: "suspicious", icon: "⚠️", key: "band.suspicious" },
  looks_safe: { css: "safe", icon: "✅", key: "band.looks_safe" },
};

function bandTitle(band) {
  const view = BAND_VIEW[band] || BAND_VIEW.looks_safe;
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

const $ = (id) => document.getElementById(id);

let modelInfo = normalizeModelInfo(FALLBACK_MODEL_INFO);
let historyEnabled = false;
let lastBatchResults = null;

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
    legacy_artifact: safe.legacy_artifact === true,
    feedback_enabled: safe.feedback_enabled === true,
    probability_calibrated: safe.probability_calibrated === true,
  };
}

/* ---------- API access ----------
   Every POST flows through postJson with an AbortSignal. When a new check
   starts (or the input changes), the previous request is aborted so a slow,
   stale response can never overwrite a newer result. */
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
    return t("error.model503");
  }
  return t("error.http", { status: response.status });
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
  } catch (throwable) {
    if (throwable && throwable.name === "AbortError") {
      const aborted = new Error("Request aborted");
      aborted.aborted = true;
      throw aborted;
    }
    const failure = new Error(t("error.reach"));
    failure.offline = true;
    throw failure;
  }
  const data = await parseResponse(response);
  hideOfflineBanner();
  return data;
}

function postJson(path, body, { signal } = {}) {
  return requestJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

function describeError(failure) {
  if (!failure) return t("error.generic");
  let message = failure.message || t("error.generic");
  const modelUnavailable = failure.status === 503 || failure.code === "model_unavailable";
  if (modelUnavailable && !message.includes("src.train")) {
    message += t("error.trainHint");
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
  // A request belongs to the view where it was started. Leaving that view
  // cancels it so a late response cannot replace a result after navigation.
  if (name !== "check" && singleAbortController) invalidateSingle();
  if (name !== "batch" && batchAbortController) invalidateBatch();
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
  $("model-version").textContent = `${t("model.versionPrefix")}${modelInfo.model_version}`;
  $("model-note").textContent = modelInfo.data_note;
  const warning = $("model-warning");
  if (modelInfo.legacy_artifact) {
    warning.textContent = t("model.legacyWarning");
    warning.classList.remove("hidden");
  } else if (warning.textContent === t("model.legacyWarning")) {
    warning.textContent = "";
    warning.classList.add("hidden");
  }
  $("model-thresholds").textContent = t("model.thresholds.line", {
    threshold: pct(modelInfo.decision_threshold),
    scam: pct(modelInfo.bands.likely_scam),
    suspicious: pct(modelInfo.bands.suspicious),
  });
  $("risk-meter").setAttribute(
    "aria-label",
    modelInfo.probability_calibrated ? t("meter.aria.calibrated") : t("meter.aria"),
  );
}

async function loadModelInfo() {
  const warning = $("model-warning");
  try {
    const info = await requestJson(API.modelInfo);
    modelInfo = normalizeModelInfo(info);
    warning.textContent = "";
    warning.classList.add("hidden");
  } catch (failure) {
    if (failure && failure.aborted) return;
    modelInfo = normalizeModelInfo(FALLBACK_MODEL_INFO);
    warning.textContent = `${describeError(failure)}${t("model.fallbackSuffix")}`;
    warning.classList.remove("hidden");
    if (failure && failure.offline) showOfflineBanner();
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

function scoreLabel(analysis) {
  return analysis && analysis.probability_calibrated === true
    ? t("verdict.score.calibrated")
    : t("verdict.score.uncalibrated");
}

/* ---------- Single-check rendering ---------- */
function renderVerdict(analysis) {
  const band = bandOf(analysis);
  const view = bandView(band);
  $("verdict-card").className = `card verdict ${view.css}`;
  $("verdict-icon").textContent = view.icon;
  $("verdict-title").textContent = bandTitle(band);
  const decisionThreshold = numberOr(analysis.decision_threshold, modelInfo.decision_threshold);
  $("verdict-sub").textContent =
    `${pct(analysis.spam_probability)} ${scoreLabel(analysis)} · ${t("verdict.modelVerdict")}: ${analysis.prediction} · ` +
    `${t("verdict.decisionThreshold")} ${pct(decisionThreshold)}`;
}

function renderMeter(analysis) {
  const probability = numberOr(analysis.spam_probability, 0);
  const value = Math.round(probability * 100);
  const band = bandOf(analysis);
  const meter = $("risk-meter");
  meter.style.setProperty("--suspect", `${Math.round(modelInfo.bands.suspicious * 100)}%`);
  meter.style.setProperty("--scam", `${Math.round(modelInfo.bands.likely_scam * 100)}%`);
  meter.setAttribute("aria-valuenow", String(value));
  meter.setAttribute(
    "aria-label",
    analysis && analysis.probability_calibrated === true ? t("meter.aria.calibrated") : t("meter.aria"),
  );
  meter.setAttribute("aria-valuetext", `${value}% ${scoreLabel(analysis)} — ${bandTitle(band)}`);
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
    empty.textContent = t("signals.empty");
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

function buildSummaryText(analysis) {
  const lines = [
    t("summary.header"),
    `${t("summary.verdict")}: ${bandTitle(bandOf(analysis))} (${analysis.prediction})`,
    `${t("summary.score")}: ${pct(analysis.spam_probability)} (${scoreLabel(analysis)})`,
    `${t("summary.signals")}: ${signalSummary(analysis)}`,
    `${t("summary.message")}: ${typeof analysis.message === "string" ? analysis.message : ""}`,
  ];
  lines.push(`${t("summary.tips")}:`);
  for (const tip of buildTips(analysis)) lines.push(`- ${tip}`);
  lines.push(`${t("summary.model")}: ${modelInfo.model_version}`);
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
  $("copy-status").textContent = "";
  window.currentAnalysis = analysis;
  const feedbackForm = $("feedback-form");
  feedbackForm.classList.toggle("hidden", !modelInfo.feedback_enabled);
  $("feedback-status").textContent = "";
  setBusy($("btn-feedback"), false, t("feedback.submit"));
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
    status.textContent = t("feedback.chooseDifferent");
    return;
  }
  setBusy(button, true, t("feedback.busy"));
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
    status.textContent = `${result.message} ${t("feedback.receipt", { id: result.report_id })}`;
    sent = true;
  } catch (failure) {
    if (failure && failure.offline) showOfflineBanner();
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
  empty.textContent = historyEnabled ? t("history.empty") : t("history.offnote");
  $("btn-clear-history").disabled = entries.length === 0;
  for (const entry of entries) {
    const band = BAND_VIEW[entry.risk_band] ? entry.risk_band : bandFromProbability(entry.spam_probability);
    const timestamp = new Date(numberOr(entry.t, Date.now())).toLocaleString();
    const item = document.createElement("li");
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.setAttribute("aria-label",
      t("history.reopenAria", { time: timestamp, band: bandTitle(band), pct: pct(entry.spam_probability) }));
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

function invalidateSingle() {
  singleRevision += 1;
  if (singleAbortController) {
    singleAbortController.abort();
    singleAbortController = null;
  }
  window.currentAnalysis = null;
  $("result").classList.add("hidden");
  $("highlighted").replaceChildren();
  $("signals").replaceChildren();
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
  hideBanner($("batch-error"));
  setBusy($("btn-batch"), false, t("batch.run"));
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
    const analysis = await postJson(API.analyze, { message }, { signal: controller.signal });
    if (revision !== singleRevision) return;
    renderAnalysis(analysis, { save });
  } catch (failure) {
    if (failure && failure.offline) showOfflineBanner();
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
      const data = await postJson(API.analyzeBatch, { messages: chunk }, { signal: controller.signal });
      if (revision !== batchRevision) return;
      results.push(...(Array.isArray(data.results) ? data.results : []));
      updateBatchProgress(results.length, messages.length);
    }
    if (revision !== batchRevision) return;
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
    if (failure && failure.offline) showOfflineBanner();
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
    const verdictCell = document.createElement("td");
    verdictCell.dataset.label = t("batch.col.verdict");
    verdictCell.append(verdictPill(band));
    const riskCell = document.createElement("td");
    riskCell.className = "risk-cell";
    riskCell.dataset.label = t("batch.col.risk");
    riskCell.append(miniMeter(analysis.spam_probability, band));
    const riskPct = document.createElement("span");
    riskPct.textContent = pct(analysis.spam_probability);
    riskCell.append(riskPct);
    const signalCell = document.createElement("td");
    signalCell.dataset.label = t("batch.col.signals");
    const patterns = signalSummary(analysis);
    signalCell.textContent = patterns;
    row.setAttribute("aria-label",
      t("batch.rowAria", { n: index + 1, band: bandTitle(band), pct: pct(analysis.spam_probability), signals: patterns }));

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

/* ---------- CSV export (client-side only; nothing is uploaded) ---------- */
function csvCell(value) {
  const text = value === null || value === undefined ? "" : String(value);
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
    t("batch.col.signals"),
    t("summary.model"),
  ];
  const rows = [header];
  lastBatchResults.forEach((analysis, index) => {
    rows.push([
      String(index + 1),
      typeof analysis.message === "string" ? analysis.message : "",
      bandTitle(bandOf(analysis)),
      String(analysis.prediction || ""),
      pct(analysis.spam_probability),
      signalSummary(analysis),
      String(analysis.model_version || modelInfo.model_version),
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
  input.addEventListener("input", () => { invalidateBatch(); updateBatchCount(); });
  input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      runBatch();
    }
  });
  $("btn-batch").addEventListener("click", () => runBatch());
  $("btn-csv").addEventListener("click", downloadBatchCsv);
  updateBatchCount();
  $("batch-empty").textContent = t("batch.empty");
}

function initOfflineDetection() {
  if (!window.navigator.onLine) showOfflineBanner();
  window.addEventListener("offline", showOfflineBanner);
  window.addEventListener("online", hideOfflineBanner);
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
  renderModelInfo();
  loadModelInfo();
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
