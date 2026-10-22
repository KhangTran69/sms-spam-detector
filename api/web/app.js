/* PH SMS Scam Detector — UI logic (no build step, vanilla JS). */
"use strict";

/* Endpoints served by api/main.py. Keep this list in sync with the API routes;
   tests/test_web_contract.py asserts every path here exists on the API. */
const API = {
  modelInfo: "/model-info",
  ready: "/ready",
  analyze: "/analyze",
  analyzeBatch: "/analyze/batch",
  feedback: "/feedback",
};

const HISTORY_KEY = "smsd_history_v1";
const HISTORY_PREF_KEY = "smsd_history_enabled_v1";
const API_TIMEOUT_MS = 20000;
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
const FALLBACK_BANDS = { likely_scam: 0.5, suspicious: 0.25, looks_safe: 0.0 };
const FALLBACK_MODEL_INFO = {
  model_version: "unknown",
  decision_threshold: 0.5,
  suspicious_threshold: 0.25,
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
    "service.apiLabel": "Detector API:",
    "service.browserLabel": "Browser reports:",
    "service.browserOnline": "Online",
    "service.browserOffline": "Offline",
    "service.modelLabel": "Model:",
    "service.checking": "Checking…",
    "service.apiAvailable": "Available",
    "service.apiUnavailable": "Could not reach API",
    "service.apiSlow": "Request timed out",
    "service.modelReady": "Ready",
    "service.modelUnavailable": "Unavailable",
    "service.modelUnknown": "Status unknown",
    "service.retry": "Retry connection",
    "tab.check": "Check a message",
    "tab.batch": "Batch check",
    "tab.compare": "Compare messages",
    "tab.history": "History",
    "value.unavailable": "Unavailable",
    "model.info": "Model information",
    "model.loading": "Loading…",
    "model.versionPrefix": "Model version: ",
    "model.thresholds.loading": "Decision threshold and risk bands are loading from the API.",
    "model.thresholds.line": "Decision threshold {threshold} · risk bands: likely spam ≥ {scam}, suspicious ≥ {suspicious}.",
    "model.fallbackSuffix": " Model information is unavailable; built-in fallback thresholds are shown.",
    "model.legacyWarning": "This is a legacy model with missing training metadata. Treat results as a demo only.",
    "model.provenance.unavailable": "Model provenance is unavailable for this result.",
    "check.label": "Paste the SMS you want to check",
    "check.placeholder": "e.g. Bank notice: Your account review is due. Visit bank-help.example to read more.",
    "check.help": "At most 10,000 characters. Messages are analysed in memory and are never stored on the server.",
    "check.clear": "Clear",
    "check.run": "Check message as written",
    "check.busy": "Checking…",
    "privacy.review": "Review sensitive details",
    "privacy.optional": "Optional: review and mask details before analysis.",
    "privacy.reviewA": "Review Message A",
    "privacy.reviewB": "Review Message B",
    "privacy.reviewBatch": "Review messages individually",
    "privacy.batchHelp": "Choose which entries to mask before submitting; unreviewed entries stay unchanged.",
    "privacy.title": "Local privacy preview",
    "privacy.help": "Suggestions are generated in this browser. They can miss personal details or flag harmless text. Review each one; this does not guarantee anonymization.",
    "privacy.edit": "Review or edit this text; select text below if you want to mask it manually",
    "privacy.detected": "Suggested details to mask",
    "privacy.none": "No likely phone numbers, email addresses, contextual codes, or reference numbers were detected. Names and other personal details may still be present.",
    "privacy.manual": "Mask selected text",
    "privacy.selectFirst": "Select some text in the preview first.",
    "privacy.selectionAdded": "Selected text will be masked in the preview.",
    "privacy.manualType": "Placeholder for selected text",
    "privacy.maskedPreview": "Exact text to submit",
    "privacy.warning": "Masking changes the text and may change the detector’s result. Review the exact text below.",
    "privacy.accept": "Analyze this reviewed text",
    "privacy.cancel": "Cancel review",
    "privacy.code": "Possible verification code",
    "privacy.phone": "Possible Philippine phone number",
    "privacy.email": "Possible email address",
    "privacy.reference": "Possible account or transaction reference",
    "privacy.maskedResult": "This result was produced from text with privacy masks. Masking can change the model’s assessment and does not guarantee anonymization.",
    "privacy.maskedBadge": "Masked before analysis",
    "privacy.batchEntry": "Message {n}",
    "privacy.reviewBatchEntry": "Review message {n}",
    "privacy.batchMasked": "Masked before analysis",
    "privacy.batchUnmasked": "Not masked",
    "privacy.batchApplied": "Reviewed text applied to message {n}.",
    "privacy.batchColumn": "Masked before analysis",
    "error.empty": "Type or paste an SMS message first.",
    "error.tooLong": "That message is {n} characters — the limit is 10,000.",
    "error.reach": "Could not reach the detector API. Check that the server is running and try again.",
    "error.http": "Request failed (HTTP {status}). Please try again.",
    "error.timeout": "The detector did not respond in time. Try again; the SMS was not sent again automatically.",
    "error.model503": "The model is not available on this server. If you run this project locally, train it with: python -m src.train",
    "error.trainHint": " If you run this project locally, train the model with: python -m src.train",
    "error.generic": "Something went wrong. Please try again.",
    "examples.aria": "Example messages",
    "examples.label": "Try an example:",
    "examples.scam": "Spam example",
    "examples.safe": "Legitimate example",
    "examples.note": "Fictional demo examples only. Click either button again to cycle through more messages.",
    "examples.status": "Loaded fictional {kind} message {index} of {total}; checking it now. Click again for another example.",
    "examples.scamKind": "spam",
    "examples.safeKind": "legitimate",
    "result.aria": "Analysis result",
    "band.likely_scam": "More spam signals",
    "band.suspicious": "Some spam signals",
    "band.looks_safe": "Few spam signals",
    "band.unavailable": "Unavailable",
    "verdict.score.uncalibrated": "uncalibrated spam model score",
    "verdict.score.calibrated": "calibrated spam score",
    "verdict.score.unavailable": "score interpretation unavailable",
    "verdict.modelVerdict": "model verdict",
    "verdict.decisionThreshold": "decision threshold",
    "meter.title": "Spam score",
    "meter.aria": "Uncalibrated spam model score",
    "meter.aria.calibrated": "Calibrated spam score",
    "meter.aria.unavailable": "Spam model score; interpretation unavailable",
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
    "summary.threshold": "Decision threshold",
    "summary.suspiciousThreshold": "Suspicious band threshold",
    "signals.title": "Message signals",
    "compare.title": "Compare two messages",
    "compare.help": "Compare each message's detector result and detected text patterns. These patterns do not explain why the model chose a verdict.",
    "compare.messageA": "Message A",
    "compare.messageB": "Message B",
    "compare.inputHelp": "Up to 10,000 characters. Text is sent to this detector's API for analysis and is not saved as comparison history.",
    "compare.swap": "Swap messages",
    "compare.clear": "Clear all",
    "compare.run": "Compare messages",
    "compare.busy": "Comparing…",
    "compare.empty": "Enter two messages and choose Compare messages to see results.",
    "compare.error.empty": "Enter both messages before comparing.",
    "compare.error.tooLong": "Message {n} has {count} characters; the limit is 10,000.",
    "compare.error.failed": "Could not complete both analyses. Please try again; no partial comparison is shown.",
    "compare.progress": "Analyzing both messages…",
    "compare.examplesLabel": "Fictional comparison examples",
    "compare.examples": "Fictional comparison examples:",
    "compare.exampleOtp": "OTP notices",
    "compare.exampleDelivery": "Delivery notices",
    "compare.exampleAccount": "Bank / e-wallet alerts",
    "compare.exampleNote": "Fictional UI examples only; they are not training or evaluation data.",
    "compare.exampleLoaded": "Loaded fictional {name} comparison pair.",
    "compare.resultsTitle": "Comparison results",
    "compare.resultFor": "Result for {name}",
    "compare.score": "Spam score",
    "compare.interpretation": "Score interpretation",
    "compare.modelVersion": "Model version",
    "compare.thresholds": "Decision / suspicious thresholds",
    "compare.provenance": "Model provenance",
    "compare.verdict": "Verdict",
    "compare.scoreDifference": "Score difference (Message A − Message B)",
    "compare.scoreDifferenceValue": "{points} percentage points",
    "compare.scoreNotComparable": "Scores cannot be compared directly because model version, score interpretation, or score data differ or are unavailable.",
    "compare.differencesTitle": "Detected text differences",
    "compare.differencesHelp": "These are patterns found in the text. They do not explain the model's decision.",
    "compare.common": "Detected in both",
    "compare.onlyA": "Detected only in Message A",
    "compare.onlyB": "Detected only in Message B",
    "compare.none": "No supported text patterns were detected in either message.",
    "compare.safetyNote": "A lower spam score does not guarantee that a message is safe. Verify requests through an official app or contact method.",
    "compare.copy": "Copy comparison summary",
    "compare.copyDone": "Comparison summary copied.",
    "compare.copyFail": "Could not copy automatically; please copy manually.",
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
    "guidance.title": "Message Safety Checklist (optional)",
    "guidance.intro": "Guidance based on your answers. It is separate from the model assessment and text patterns, and it does not change the score. Classification cannot establish who sent a message or guarantee it is safe.",
    "guidance.questions": "About this message",
    "guidance.expected": "Were you expecting this message?",
    "guidance.sensitive": "Does it ask you to share an OTP, password, PIN, or recovery code?",
    "guidance.payment": "Does it ask you to pay a fee, transfer money, or install an app?",
    "guidance.verifiedQuestion": "Have you independently verified the request through an official channel?",
    "guidance.yes": "Yes",
    "guidance.no": "No",
    "guidance.unsure": "Not sure",
    "guidance.nextHeading": "What should I do next?",
    "guidance.action.notInteracted": "I have not interacted with it",
    "guidance.action.openedLink": "I opened a link",
    "guidance.action.sharedSensitive": "I shared sensitive information",
    "guidance.action.sentMoney": "I sent money",
    "guidance.default": "Pause before acting. Do not reply, tap SMS links, or call numbers from an unexpected text. Verify requests in an official app you open yourself or through a contact method you already trust. For a delivery, check its tracking in the courier’s or retailer’s official app. Never share an OTP, PIN, password, or recovery code.",
    "guidance.unexpected": "You were not expecting it. Do not reply, use its links or numbers, or provide information. Check independently through the official app or a contact method you already trust.",
    "guidance.sensitiveRequest": "It asks for a secret code or password. Do not share it, even if the message looks familiar. A spam score cannot verify the sender or make this request safe.",
    "guidance.paymentRequest": "Do not pay, transfer money, or install an app because of this text. First confirm the request through an official channel you access independently.",
    "guidance.verified": "You say you verified the request independently. This does not authenticate the SMS sender. Continue only in that official app or channel, and never share codes or passwords by SMS.",
    "guidance.openedLink": "Close the page and do not enter or submit information. Opening a link alone does not prove your device or account was compromised. If you downloaded an app, do not open it; remove it and review your device security settings.",
    "guidance.sharedSensitive": "Act promptly: contact the relevant bank, e-wallet, or service through its official app or a contact method you already trust. Change affected credentials in the official app and ask the provider to secure the account. Never share another code during follow-up.",
    "guidance.sentMoney": "Contact your bank, e-wallet, or payment provider promptly through its official app or a trusted contact method. Keep transaction receipts and related messages for your records. Report through the provider’s official process; a refund or recovery is not guaranteed.",
    "guidance.copy": "Copy next-step guidance",
    "guidance.copyDone": "Guidance copied. Message text and your answers were not copied.",
    "guidance.copyFail": "Could not copy guidance automatically; please copy it manually.",
    "guidance.updated": "Next-step guidance updated based on your answers.",
    "feedback.title": "Help improve the detector",
    "feedback.help": "Optional anonymous report. It sends your selected correction, category, and model version only—never the SMS text. The operator must enable feedback collection.",
    "feedback.label": "What do you think the message is?",
    "feedback.ham": "Legitimate message",
    "feedback.spam": "Spam or unwanted advertising",
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
    "batch.col.risk": "Spam score",
    "batch.col.scoreDescription": "Score description",
    "batch.col.signals": "Signals",
    "batch.csv": "Download CSV",
    "batch.csv.done": "Downloaded {file}",
    "batch.csv.fail": "No results to download yet.",
    "batch.rowAria": "Message {n}: {band}, {pct} {score}. Detected text patterns: {signals}. {privacy} Press Enter to open the full analysis.",
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
    "history.reopenAria": "Reopen saved check from {time} — {band}, {pct} {score}",
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
    "service.apiLabel": "Detector API:",
    "service.browserLabel": "Sabi ng browser:",
    "service.browserOnline": "May koneksyon",
    "service.browserOffline": "Walang koneksyon",
    "service.modelLabel": "Modelo:",
    "service.checking": "Sinusuri…",
    "service.apiAvailable": "Available",
    "service.apiUnavailable": "Hindi maabot ang API",
    "service.apiSlow": "Nag-time out ang request",
    "service.modelReady": "Handa",
    "service.modelUnavailable": "Hindi available",
    "service.modelUnknown": "Hindi alam ang status",
    "service.retry": "Subukang kumonekta ulit",
    "tab.check": "Tingnan ang mensahe",
    "tab.batch": "Maramihang check",
    "tab.compare": "Ikumpara ang mga mensahe",
    "tab.history": "History",
    "value.unavailable": "Hindi available",
    "model.info": "Impormasyon ng modelo",
    "model.loading": "Naglo-load…",
    "model.versionPrefix": "Bersyon ng modelo: ",
    "model.thresholds.loading": "Niloload mula sa API ang decision threshold at risk bands.",
    "model.thresholds.line": "Decision threshold {threshold} · risk bands: malamang spam ≥ {scam}, kahina-hinala ≥ {suspicious}.",
    "model.fallbackSuffix": " Hindi available ang impormasyon ng modelo; built-in na fallback thresholds ang ipinapakita.",
    "model.legacyWarning": "Lumang modelo ito na walang kumpletong training metadata. Demo lamang ang resulta.",
    "model.provenance.unavailable": "Hindi available ang pinagmulan ng modelo para sa resultang ito.",
    "check.label": "I-paste ang SMS na gusto mong i-check",
    "check.placeholder": "Hal. May notice sa account mo. Tingnan sa bank-help.example kung kailangan ng action.",
    "check.help": "Hanggang 10,000 karakter. Sinusuri sa memory ang mga mensahe at hindi kailanman iniimbak sa server.",
    "check.clear": "Burahin",
    "check.run": "I-check ang mensahe ayon sa pagkakasulat",
    "check.busy": "Sinusuri…",
    "privacy.review": "Suriin ang sensitibong detalye",
    "privacy.optional": "Opsyonal: suriin at takpan ang detalye bago magpa-analyze.",
    "privacy.reviewA": "Suriin ang Mensahe A",
    "privacy.reviewB": "Suriin ang Mensahe B",
    "privacy.reviewBatch": "Suriin nang paisa-isa ang mga mensahe",
    "privacy.batchHelp": "Piliin kung aling entries ang tatakpan bago ipadala; hindi mababago ang hindi sinuri.",
    "privacy.title": "Privacy preview sa browser na ito",
    "privacy.help": "Sa browser na ito lang hinahanap ang mga mungkahi. Maaaring may hindi makita o mapagkamalang sensitibo ang karaniwang text. Suriin ang bawat isa; hindi nito ginagarantiya ang anonymization.",
    "privacy.edit": "Suriin o baguhin ang text; pumili ng bahagi sa ibaba kung mano-manong tatakpan",
    "privacy.detected": "Mga mungkahing takpan",
    "privacy.none": "Walang nakitang posibleng phone number, email, code ayon sa konteksto, o reference number. Maaaring may pangalan at iba pang personal na detalye pa rin.",
    "privacy.manual": "Takpan ang napiling text",
    "privacy.selectFirst": "Pumili muna ng text sa preview.",
    "privacy.selectionAdded": "Tatanggalin sa isusumiteng preview ang napiling text.",
    "privacy.manualType": "Placeholder para sa napiling text",
    "privacy.maskedPreview": "Eksaktong text na ipapadala",
    "privacy.warning": "Binabago ng masking ang text at maaaring magbago ang resulta ng detector. Suriin sa ibaba ang eksaktong text.",
    "privacy.accept": "I-analyze ang sinuring text",
    "privacy.cancel": "Kanselahin ang pagsusuri",
    "privacy.code": "Posibleng verification code",
    "privacy.phone": "Posibleng numero ng telepono sa Pilipinas",
    "privacy.email": "Posibleng email address",
    "privacy.reference": "Posibleng account o transaction reference",
    "privacy.maskedResult": "Resulta ito mula sa text na may privacy masks. Maaaring baguhin ng masking ang assessment ng modelo at hindi nito ginagarantiya ang anonymization.",
    "privacy.maskedBadge": "Tinakpan bago i-analyze",
    "privacy.batchEntry": "Mensahe {n}",
    "privacy.reviewBatchEntry": "Suriin ang mensahe {n}",
    "privacy.batchMasked": "Tinakpan bago i-analyze",
    "privacy.batchUnmasked": "Hindi tinakpan",
    "privacy.batchApplied": "Na-update ang sinuring text para sa mensahe {n}.",
    "privacy.batchColumn": "Tinakpan bago i-analyze",
    "error.empty": "Mag-type o mag-paste muna ng mensahe.",
    "error.tooLong": "{n} karakter ang mensahe — ang limit ay 10,000.",
    "error.reach": "Hindi makausap ang detector API. Siguraduhing naka-run ang server at subukan ulit.",
    "error.http": "Nabigo ang request (HTTP {status}). Subukan ulit.",
    "error.timeout": "Hindi agad sumagot ang detector. Subukan ulit; hindi awtomatikong ipinadala muli ang SMS.",
    "error.model503": "Hindi available ang modelo sa server na ito. Kung local ang pag-run mo, i-train ito gamit ang: python -m src.train",
    "error.trainHint": " Kung local ang pag-run mo, i-train ang modelo gamit ang: python -m src.train",
    "error.generic": "May naganap na mali. Subukan ulit.",
    "examples.aria": "Mga halimbawang mensahe",
    "examples.label": "Subukan ang halimbawa:",
    "examples.scam": "Halimbawa ng spam",
    "examples.safe": "Lehitimong halimbawa",
    "examples.note": "Gawa-gawa lamang na demo na mga halimbawa. I-click muli ang alinmang button para umikot sa ibang mensahe.",
    "examples.status": "Na-load ang gawa-gawang {kind} na mensahe ({index} ng {total}); sinusuri na. I-click muli para sa isa pa.",
    "examples.scamKind": "spam",
    "examples.safeKind": "lehitimo",
    "result.aria": "Resulta ng pagsusuri",
    "band.likely_scam": "Mas maraming spam signal",
    "band.suspicious": "May ilang spam signal",
    "band.looks_safe": "Kaunti ang spam signal",
    "band.unavailable": "Hindi available",
    "verdict.score.uncalibrated": "uncalibrated na spam model score",
    "verdict.score.calibrated": "calibrated na spam score",
    "verdict.score.unavailable": "hindi available ang interpretasyon ng score",
    "verdict.modelVerdict": "hatol ng modelo",
    "verdict.decisionThreshold": "decision threshold",
    "meter.title": "Spam score",
    "meter.aria": "Uncalibrated na spam model score",
    "meter.aria.calibrated": "Calibrated na spam score",
    "meter.aria.unavailable": "Spam model score; hindi available ang interpretasyon",
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
    "summary.threshold": "Threshold ng desisyon",
    "summary.suspiciousThreshold": "Threshold ng suspicious band",
    "signals.title": "Mga signal sa mensahe",
    "compare.title": "Ikumpara ang dalawang mensahe",
    "compare.help": "Ihambing ang resulta ng detector at mga natukoy na pattern sa bawat mensahe. Hindi ipinapaliwanag ng mga pattern na ito kung bakit iyon ang hatol ng modelo.",
    "compare.messageA": "Mensahe A",
    "compare.messageB": "Mensahe B",
    "compare.inputHelp": "Hanggang 10,000 karakter. Ipinapadala ang text sa API ng detector para suriin at hindi ise-save bilang comparison history.",
    "compare.swap": "Pagpalitin ang mga mensahe",
    "compare.clear": "Burahin lahat",
    "compare.run": "Ikumpara ang mga mensahe",
    "compare.busy": "Ikinukumpara…",
    "compare.empty": "Maglagay ng dalawang mensahe at pindutin ang Ikumpara ang mga mensahe para makita ang resulta.",
    "compare.error.empty": "Ilagay ang dalawang mensahe bago ikumpara.",
    "compare.error.tooLong": "May {count} karakter ang Mensahe {n}; 10,000 ang limit.",
    "compare.error.failed": "Hindi nakumpleto ang pagsusuri sa dalawang mensahe. Subukan ulit; walang bahagyang resulta ang ipapakita.",
    "compare.progress": "Sinusuri ang dalawang mensahe…",
    "compare.examplesLabel": "Mga gawa-gawang halimbawa ng paghahambing",
    "compare.examples": "Mga gawa-gawang halimbawa:",
    "compare.exampleOtp": "Mga OTP notice",
    "compare.exampleDelivery": "Mga delivery notice",
    "compare.exampleAccount": "Mga alerto ng bangko / e-wallet",
    "compare.exampleNote": "Mga gawa-gawang halimbawa lang sa UI; hindi ito training o evaluation data.",
    "compare.exampleLoaded": "Na-load ang gawa-gawang pares tungkol sa {name}.",
    "compare.resultsTitle": "Mga resulta ng paghahambing",
    "compare.resultFor": "Resulta para sa {name}",
    "compare.score": "Spam score",
    "compare.interpretation": "Interpretasyon ng score",
    "compare.modelVersion": "Bersyon ng modelo",
    "compare.thresholds": "Decision / suspicious thresholds",
    "compare.provenance": "Pinagmulan ng modelo",
    "compare.verdict": "Hatol",
    "compare.scoreDifference": "Pagkakaiba ng score (Mensahe A − Mensahe B)",
    "compare.scoreDifferenceValue": "{points} percentage point",
    "compare.scoreNotComparable": "Hindi direktang maihahambing ang mga score dahil magkaiba o hindi available ang bersyon ng modelo, interpretasyon ng score, o score data.",
    "compare.differencesTitle": "Mga natukoy na pagkakaiba sa text",
    "compare.differencesHelp": "Mga pattern ito na nakita sa text. Hindi nito ipinapaliwanag ang pasya ng modelo.",
    "compare.common": "Natukoy sa pareho",
    "compare.onlyA": "Natukoy lang sa Mensahe A",
    "compare.onlyB": "Natukoy lang sa Mensahe B",
    "compare.none": "Walang kilalang pattern sa text na natukoy sa alinmang mensahe.",
    "compare.safetyNote": "Hindi garantiya ng kaligtasan ang mas mababang spam score. Beripikahin ang mga kahilingan sa opisyal na app o contact method.",
    "compare.copy": "Kopyahin ang buod ng paghahambing",
    "compare.copyDone": "Nakopya ang buod ng paghahambing.",
    "compare.copyFail": "Hindi awtomatikong nakopya; kopyahin nang manual.",
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
    "guidance.title": "Checklist ng kaligtasan sa mensahe (opsyonal)",
    "guidance.intro": "Gabay ito batay sa mga sagot mo. Hiwalay ito sa assessment ng modelo at mga pattern sa text, at hindi nito binabago ang score. Hindi matutukoy ng classification kung sino ang nagpadala o magagarantiya na ligtas ang mensahe.",
    "guidance.questions": "Tungkol sa mensaheng ito",
    "guidance.expected": "Inaasahan mo ba ang mensaheng ito?",
    "guidance.sensitive": "Pinapabahagi ba nito ang OTP, password, PIN, o recovery code mo?",
    "guidance.payment": "Pinagbabayad ka ba ng fee, pinaglilipat ng pera, o pinapakabit ng app?",
    "guidance.verifiedQuestion": "Na-verify mo ba nang hiwalay ang request sa opisyal na channel?",
    "guidance.yes": "Oo",
    "guidance.no": "Hindi",
    "guidance.unsure": "Hindi sigurado",
    "guidance.nextHeading": "Ano ang susunod kong gagawin?",
    "guidance.action.notInteracted": "Wala pa akong ginawa rito",
    "guidance.action.openedLink": "Nagbukas ako ng link",
    "guidance.action.sharedSensitive": "Nagbahagi ako ng sensitibong impormasyon",
    "guidance.action.sentMoney": "Nagpadala ako ng pera",
    "guidance.default": "Mag-pause muna bago kumilos. Huwag mag-reply, mag-tap ng SMS link, o tumawag sa numerong nasa hindi inaasahang text. I-verify ang request sa opisyal na app na ikaw mismo ang magbubukas o sa trusted contact method. Para sa delivery, i-check ang tracking sa official app ng courier o retailer. Huwag kailanman ibahagi ang OTP, PIN, password, o recovery code.",
    "guidance.unexpected": "Hindi mo ito inaasahan. Huwag mag-reply, gumamit ng link o numero rito, o magbigay ng impormasyon. Mag-check nang hiwalay sa opisyal na app o trusted contact method.",
    "guidance.sensitiveRequest": "Humihingi ito ng secret code o password. Huwag itong ibahagi kahit mukhang pamilyar ang mensahe. Hindi nave-verify ng spam score kung sino ang sender o kung ligtas ang request.",
    "guidance.paymentRequest": "Huwag magbayad, mag-transfer ng pera, o mag-install ng app dahil lang sa text na ito. Kumpirmahin muna sa opisyal na channel na ikaw mismo ang bubukas.",
    "guidance.verified": "Sinabi mong na-verify mo nang hiwalay ang request. Hindi nito ina-authenticate ang SMS sender. Magpatuloy lang sa opisyal na app o channel at huwag magbahagi ng code o password sa SMS.",
    "guidance.openedLink": "Isara ang page at huwag maglagay o magsumite ng impormasyon. Hindi ibig sabihin na na-compromise ang device o account dahil lang nagbukas ka ng link. Kung may na-download na app, huwag itong buksan; alisin ito at tingnan ang security settings ng device.",
    "guidance.sharedSensitive": "Kumilos agad: kontakin ang bangko, e-wallet, o serbisyo sa opisyal na app o trusted contact method. Palitan ang apektadong credentials sa opisyal na app at hilinging i-secure ang account. Huwag magbahagi ng panibagong code sa follow-up.",
    "guidance.sentMoney": "Kontakin agad ang bangko, e-wallet, o payment provider sa opisyal na app o trusted contact method. Itago ang transaction receipt at kaugnay na mensahe bilang record. Mag-report sa opisyal na proseso ng provider; walang garantiya ng refund o recovery.",
    "guidance.copy": "Kopyahin ang gabay sa susunod na hakbang",
    "guidance.copyDone": "Nakopya ang gabay. Hindi kinopya ang text ng mensahe at mga sagot mo.",
    "guidance.copyFail": "Hindi awtomatikong nakopya ang gabay; kopyahin ito nang manual.",
    "guidance.updated": "Na-update ang susunod na gabay batay sa mga sagot mo.",
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
    "batch.col.risk": "Spam score",
    "batch.col.scoreDescription": "Paglalarawan ng score",
    "batch.col.signals": "Mga signal",
    "batch.csv": "I-download ang CSV",
    "batch.csv.done": "Nai-download: {file}",
    "batch.csv.fail": "Wala pang resultang ma-download.",
    "batch.rowAria": "Mensahe {n}: {band}, {pct} {score}. Mga natuklasang pattern: {signals}. {privacy} Pindutin ang Enter para buksan ang buong analysis.",
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
    "history.reopenAria": "Buksan muli ang check mula {time} — {band}, {pct} {score}",
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
  renderConnectionStatus();
  renderActiveModelInfo();
  renderHistory();
  updateHistoryBadge();
  updateCharCount();
  updateBatchCount();
  clearPrivacyReview("single-privacy-review");
  clearPrivacyReview("compare-review-a");
  clearPrivacyReview("compare-review-b");
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

/* ---------- Offline banner ---------- */
function showOfflineBanner() {
  $("offline-banner").classList.remove("hidden");
}

function hideOfflineBanner() {
  $("offline-banner").classList.add("hidden");
}

function renderConnectionStatus() {
  const api = $("api-status");
  const model = $("readiness-status");
  const browser = $("browser-status");
  const reportsOnline = window.navigator.onLine;
  browser.textContent = typeof reportsOnline === "boolean"
    ? t(reportsOnline ? "service.browserOnline" : "service.browserOffline") : t("service.modelUnknown");
  api.textContent = apiAvailable === null ? t("service.checking")
    : apiAvailable === true ? t("service.apiAvailable")
      : apiAvailable === "timeout" ? t("service.apiSlow") : t("service.apiUnavailable");
  model.textContent = modelReady === null ? t("service.checking")
    : modelReady === true ? t("service.modelReady")
      : modelReady === false ? t("service.modelUnavailable") : t("service.modelUnknown");
  api.dataset.state = apiAvailable === true ? "ready"
    : apiAvailable === false ? "error" : apiAvailable === "timeout" ? "warning" : "checking";
  model.dataset.state = modelReady === true ? "ready" : modelReady === false ? "error" : "checking";
}

function setApiAvailability(value, requestSequence) {
  if (requestSequence < apiStatusSequence) return false;
  apiStatusSequence = requestSequence;
  apiAvailable = value;
  renderConnectionStatus();
  return true;
}

function setModelReadiness(value, requestSequence) {
  if (requestSequence < modelStatusSequence) return false;
  modelStatusSequence = requestSequence;
  modelReady = value;
  renderConnectionStatus();
  return true;
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
let modelInfoLoaded = false;
let modelInfoError = null;
let apiAvailable = null;
let modelReady = null;
let apiRequestSequence = 0;
let apiStatusSequence = 0;
let modelStatusSequence = 0;
let modelInfoRequestSequence = 0;
let historyEnabled = false;
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

function normalizeModelInfo(info) {
  const safe = info && typeof info === "object" ? info : {};
  const bands = safe.bands && typeof safe.bands === "object" ? safe.bands : {};
  const decisionThreshold = validFraction(safe.decision_threshold);
  const likelyThreshold = validFraction(bands.likely_scam) ?? decisionThreshold;
  const suspiciousThreshold = validFraction(bands.suspicious) ?? validFraction(safe.suspicious_threshold);
  const normalizedBands = likelyThreshold !== null && suspiciousThreshold !== null
    && suspiciousThreshold < likelyThreshold
    ? { likely_scam: likelyThreshold, suspicious: suspiciousThreshold, looks_safe: 0 }
    : null;
  return {
    raw: safe,
    model_version: typeof safe.model_version === "string" && safe.model_version
      ? safe.model_version
      : null,
    decision_threshold: decisionThreshold,
    suspicious_threshold: suspiciousThreshold,
    bands: normalizedBands,
    data_note: typeof safe.data_note === "string" && safe.data_note.trim() ? safe.data_note.trim() : null,
    legacy_artifact: safe.legacy_artifact === true,
    feedback_enabled: safe.feedback_enabled === true,
    probability_calibrated: typeof safe.probability_calibrated === "boolean" ? safe.probability_calibrated : null,
    warnings: Array.isArray(safe.warnings) ? safe.warnings.filter((item) => typeof item === "string") : [],
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
  } catch (error) {
    if (error && error.name === "AbortError") throw error;
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

async function requestJson(path, options = {}) {
  const requestSequence = ++apiRequestSequence;
  const controller = new AbortController();
  const externalSignal = options.signal;
  let callerAborted = false;
  let timedOut = false;
  const abortFromCaller = () => {
    callerAborted = true;
    controller.abort();
  };
  if (externalSignal) {
    if (externalSignal.aborted) abortFromCaller();
    else externalSignal.addEventListener("abort", abortFromCaller, { once: true });
  }
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, API_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(path, { ...options, signal: controller.signal });
  } catch (throwable) {
    clearTimeout(timeoutId);
    if (externalSignal) externalSignal.removeEventListener("abort", abortFromCaller);
    if (callerAborted || (throwable && throwable.name === "AbortError" && !timedOut)) {
      const aborted = new Error("Request aborted");
      aborted.aborted = true;
      throw aborted;
    }
    if (timedOut) {
      const failure = new Error(t("error.timeout"));
      failure.timeout = true;
      if (setApiAvailability("timeout", requestSequence)) {
        setModelReadiness("unknown", requestSequence);
      }
      throw failure;
    }
    const failure = new Error(t("error.reach"));
    failure.apiUnavailable = true;
    if (setApiAvailability(false, requestSequence)) {
      setModelReadiness("unknown", requestSequence);
      if (window.navigator.onLine === false) showOfflineBanner();
    }
    throw failure;
  }
  if (setApiAvailability(true, requestSequence)) {
    // A reachable local or remote API is enough for this app to work even if
    // the browser reports that general internet access is unavailable.
    hideOfflineBanner();
  }
  try {
    const data = await parseResponse(response);
    if (path === API.ready) setModelReadiness(true, requestSequence);
    return data;
  } catch (failure) {
    if (callerAborted || (failure && failure.name === "AbortError" && !timedOut)) {
      const aborted = new Error("Request aborted");
      aborted.aborted = true;
      throw aborted;
    }
    if (timedOut) {
      const timeoutFailure = new Error(t("error.timeout"));
      timeoutFailure.timeout = true;
      if (setApiAvailability("timeout", requestSequence)) setModelReadiness("unknown", requestSequence);
      throw timeoutFailure;
    }
    if (failure && (failure.status === 503 || failure.code === "model_unavailable")) {
      setModelReadiness(false, requestSequence);
    }
    throw failure;
  } finally {
    clearTimeout(timeoutId);
    if (externalSignal) externalSignal.removeEventListener("abort", abortFromCaller);
  }
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
  clearPrivacyReview("single-privacy-review");
  clearPrivacyReview("compare-review-a");
  clearPrivacyReview("compare-review-b");
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

function bandsForAnalysis(analysis) {
  if (!analysis || typeof analysis !== "object") return modelInfo.bands;
  const useLoaded = resultMatchesLoadedModel(analysis);
  const likely = validFraction(analysis.decision_threshold)
    ?? (useLoaded ? validFraction(modelInfo.bands.likely_scam) : null);
  const suspicious = validFraction(analysis.suspicious_threshold)
    ?? (useLoaded ? validFraction(modelInfo.bands.suspicious) : null);
  if (likely === null || suspicious === null || suspicious >= likely) return null;
  return { likely_scam: likely, suspicious, looks_safe: 0 };
}

async function loadModelInfo() {
  const requestSequence = ++modelInfoRequestSequence;
  const warning = $("model-warning");
  try {
    const info = await requestJson(API.modelInfo);
    if (requestSequence !== modelInfoRequestSequence) return;
    modelInfo = normalizeModelInfo(info);
    modelInfoLoaded = true;
    modelInfoError = null;
    warning.textContent = "";
    warning.classList.add("hidden");
  } catch (failure) {
    if (requestSequence !== modelInfoRequestSequence) return;
    if (failure && failure.aborted) return;
    modelInfo = normalizeModelInfo(FALLBACK_MODEL_INFO);
    modelInfoLoaded = false;
    modelInfoError = failure;
  }
  renderActiveModelInfo();
  if (currentComparison) renderComparison(currentComparison.results);
}

async function refreshServiceStatus() {
  apiAvailable = null;
  modelReady = null;
  renderConnectionStatus();
  try {
    await requestJson(API.ready);
  } catch {
    // requestJson records reachability and readiness without resending SMS.
  }
  renderConnectionStatus();
}

/* ---------- Banding ---------- */
function bandFromProbability(probability, analysis = null) {
  const value = validFraction(probability);
  const bands = bandsForAnalysis(analysis);
  if (value === null || !bands) return "unavailable";
  if (value >= bands.likely_scam) return "likely_scam";
  if (value >= bands.suspicious) return "suspicious";
  return "looks_safe";
}

/* Prefer the API's own verdict band and fall back to the thresholds. */
function bandOf(analysis) {
  if (analysis && typeof analysis.risk_band === "string" && BAND_VIEW[analysis.risk_band]) {
    return analysis.risk_band;
  }
  return bandFromProbability(analysis ? analysis.spam_probability : null, analysis);
}

function bandView(band) {
  return BAND_VIEW[band] || { css: "unknown", icon: "ℹ️", key: "band.unavailable" };
}

function scoreLabel(analysis) {
  if (!analysis || typeof analysis.probability_calibrated !== "boolean") return t("verdict.score.unavailable");
  return analysis.probability_calibrated ? t("verdict.score.calibrated") : t("verdict.score.uncalibrated");
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
    const band = BAND_VIEW[entry.risk_band]
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

/* ---------- Local-only privacy preview ---------- */
const PRIVACY_PLACEHOLDERS = {
  phone: "[PHONE]",
  email: "[EMAIL]",
  code: "[CODE]",
  reference: "[REFERENCE]",
};

function detectSensitiveSpans(message) {
  const found = [];
  const collect = (regex, type, capture = 0) => {
    regex.lastIndex = 0;
    let match;
    while ((match = regex.exec(message)) !== null) {
      const value = match[capture];
      if (!value) continue;
      const offset = capture ? match[0].indexOf(value) : 0;
      found.push({ start: match.index + offset, end: match.index + offset + value.length, type, manual: false });
      if (!match[0].length) regex.lastIndex += 1;
    }
  };
  collect(/(?<!\d)(?:\+?63[\s().-]?9\d{2}|09\d{2})[\s().-]?\d{3}[\s.-]?\d{4}(?!\d)/g, "phone");
  collect(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "email");
  collect(/\b(?:otp(?:\s+code)?|one[\s-]?time(?:\s+(?:password|code|pin))?|verification\s+code|security\s+code|kodigo\s+sa\s+beripikasyon)\b\s*(?:is|:|=|-|mo\s+ay|ay|mo)?\s*([A-Z0-9]{4,8})\b/gi, "code", 1);
  collect(/\b(?:account|acct)\s*(?:number|no\.?|#)\s*[:=#-]?\s*((?=[A-Z0-9-]{5,24}\b)(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{4,23})\b/gi, "reference", 1);
  collect(/\b(?:reference|ref|transaction|txn)\s*(?:number|no\.?|id|#)\s*[:=#-]?\s*((?=[A-Z0-9-]{5,24}\b)(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{4,23})\b/gi, "reference", 1);
  const priority = { phone: 0, email: 1, code: 2, reference: 3 };
  found.sort((a, b) => priority[a.type] - priority[b.type] || a.start - b.start || b.end - a.end);
  const accepted = [];
  for (const span of found) {
    if (!accepted.some((other) => span.start < other.end && other.start < span.end)) accepted.push(span);
  }
  return accepted.sort((a, b) => a.start - b.start || a.end - b.end);
}

function normalizePrivacySpans(spans) {
  const valid = spans.filter((span) => Number.isInteger(span.start) && Number.isInteger(span.end)
    && span.start >= 0 && span.end > span.start && PRIVACY_PLACEHOLDERS[span.type])
    .sort((a, b) => a.start - b.start || Number(Boolean(b.manual)) - Number(Boolean(a.manual)));
  const merged = [];
  for (const span of valid) {
    const previous = merged[merged.length - 1];
    if (previous && span.start < previous.end) {
      previous.end = Math.max(previous.end, span.end);
      if (span.manual && !previous.manual) {
        previous.type = span.type;
        previous.manual = true;
      }
    } else {
      merged.push({ ...span });
    }
  }
  return merged;
}

function applyPrivacyMasks(message, spans) {
  const selected = normalizePrivacySpans(spans);
  let output = message;
  for (const span of selected.slice().reverse()) {
    output = output.slice(0, span.start) + PRIVACY_PLACEHOLDERS[span.type] + output.slice(span.end);
  }
  return output;
}

function buildPrivacyReview(container, initialText, onConfirm) {
  container.replaceChildren();
  container.classList.remove("hidden");
  const heading = document.createElement("h3");
  heading.textContent = t("privacy.title");
  const help = document.createElement("p");
  help.className = "hint";
  help.textContent = t("privacy.help");
  const editLabel = document.createElement("label");
  editLabel.textContent = t("privacy.edit");
  const draft = document.createElement("textarea");
  draft.rows = 5;
  draft.value = initialText;
  draft.setAttribute("aria-label", t("privacy.edit"));
  editLabel.append(draft);
  const suggestionHeading = document.createElement("h4");
  suggestionHeading.textContent = t("privacy.detected");
  const suggestions = document.createElement("ul");
  suggestions.className = "privacy-suggestions";
  const none = document.createElement("p");
  none.className = "hint privacy-none";
  none.textContent = t("privacy.none");
  const manualRow = document.createElement("div");
  manualRow.className = "privacy-manual-row";
  const manualTypeLabel = document.createElement("label");
  manualTypeLabel.textContent = t("privacy.manualType");
  const manualType = document.createElement("select");
  for (const type of Object.keys(PRIVACY_PLACEHOLDERS)) {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = PRIVACY_PLACEHOLDERS[type];
    manualType.append(option);
  }
  manualTypeLabel.append(manualType);
  const manualButton = document.createElement("button");
  manualButton.type = "button";
  manualButton.className = "btn ghost";
  manualButton.textContent = t("privacy.manual");
  const manualStatus = document.createElement("span");
  manualStatus.className = "hint";
  manualStatus.setAttribute("role", "status");
  manualRow.append(manualTypeLabel, manualButton, manualStatus);
  const outputLabel = document.createElement("label");
  outputLabel.textContent = t("privacy.maskedPreview");
  const output = document.createElement("textarea");
  output.rows = 5;
  output.readOnly = true;
  outputLabel.append(output);
  const warning = document.createElement("p");
  warning.className = "privacy-warning";
  warning.textContent = t("privacy.warning");
  const actions = document.createElement("div");
  actions.className = "buttons privacy-review-buttons";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "btn ghost";
  cancel.textContent = t("privacy.cancel");
  const accept = document.createElement("button");
  accept.type = "button";
  accept.className = "btn primary";
  accept.textContent = t("privacy.accept");
  actions.append(cancel, accept);
  container.append(heading, help, editLabel, suggestionHeading, suggestions, none, manualRow, outputLabel, warning, actions);

  let detected = detectSensitiveSpans(draft.value);
  let selected = new Set(detected.map((_, index) => index));
  let manual = [];
  const chosenSpans = () => [...detected.filter((_, index) => selected.has(index)), ...manual];
  const render = () => {
    suggestions.replaceChildren();
    none.classList.toggle("hidden", detected.length > 0);
    suggestionHeading.classList.toggle("hidden", detected.length === 0);
    detected.forEach((span, index) => {
      const item = document.createElement("li");
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selected.has(index);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) selected.add(index);
        else selected.delete(index);
        updateOutput();
      });
      const text = document.createElement("span");
      text.textContent = `${t(`privacy.${span.type}`)} → ${PRIVACY_PLACEHOLDERS[span.type]}`;
      label.append(checkbox, text);
      item.append(label);
      suggestions.append(item);
    });
    updateOutput();
  };
  const updateOutput = () => {
    output.value = applyPrivacyMasks(draft.value, chosenSpans()).trim();
  };
  draft.addEventListener("input", () => {
    detected = detectSensitiveSpans(draft.value);
    selected = new Set(detected.map((_, index) => index));
    manual = [];
    manualStatus.textContent = "";
    render();
  });
  manualButton.addEventListener("click", () => {
    const start = draft.selectionStart;
    const end = draft.selectionEnd;
    if (!Number.isInteger(start) || !Number.isInteger(end) || start === end) {
      manualStatus.textContent = t("privacy.selectFirst");
      return;
    }
    manual.push({ start, end, type: manualType.value, manual: true });
    manualStatus.textContent = t("privacy.selectionAdded");
    updateOutput();
  });
  const dispose = () => {
    container.replaceChildren();
    container.classList.add("hidden");
  };
  cancel.addEventListener("click", dispose);
  accept.addEventListener("click", () => {
    const spans = normalizePrivacySpans(chosenSpans());
    const text = applyPrivacyMasks(draft.value, spans).trim();
    dispose();
    onConfirm({ text, masked: spans.length > 0 });
  });
  render();
  draft.focus();
}

function clearPrivacyReview(containerId) {
  const container = $(containerId);
  if (container) {
    container.replaceChildren();
    container.classList.add("hidden");
  }
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
  clearPrivacyReview("single-privacy-review");
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
    const analysis = await postJson(API.analyze, { message }, { signal: controller.signal });
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
      });
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
      const data = await postJson(API.analyzeBatch, { messages: chunk }, { signal: controller.signal });
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
  clearPrivacyReview("compare-review-a");
  clearPrivacyReview("compare-review-b");
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
    const data = await postJson(API.analyzeBatch, { messages }, { signal: controller.signal });
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
      clearPrivacyReview(`compare-review-${side}`);
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
      });
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
    clearPrivacyReview("compare-review-a");
    clearPrivacyReview("compare-review-b");
    updateCompareCount("a");
    updateCompareCount("b");
  });
  $("btn-compare-clear").addEventListener("click", () => {
    invalidateComparison();
    $("compare-message-a").value = "";
    $("compare-message-b").value = "";
    compareMaskedInputs = [false, false];
    clearPrivacyReview("compare-review-a");
    clearPrivacyReview("compare-review-b");
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
      clearPrivacyReview("compare-review-a");
      clearPrivacyReview("compare-review-b");
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
    });
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
    renderConnectionStatus();
    refreshServiceStatus();
  });
  window.addEventListener("online", () => {
    renderConnectionStatus();
    hideOfflineBanner();
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
  renderConnectionStatus();
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
