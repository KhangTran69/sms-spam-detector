/* ---------- Local-only privacy preview ---------- */
const PRIVACY_PLACEHOLDERS = {
  phone: "[PHONE]",
  email: "[EMAIL]",
  code: "[CODE]",
  reference: "[REFERENCE]",
};

export function detectSensitiveSpans(message) {
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

export function applyPrivacyMasks(message, spans) {
  const selected = normalizePrivacySpans(spans);
  let output = message;
  for (const span of selected.slice().reverse()) {
    output = output.slice(0, span.start) + PRIVACY_PLACEHOLDERS[span.type] + output.slice(span.end);
  }
  return output;
}

export function buildPrivacyReview(container, initialText, onConfirm, translate) {
  container.replaceChildren();
  container.classList.remove("hidden");
  const heading = document.createElement("h3");
  heading.textContent = translate("privacy.title");
  const help = document.createElement("p");
  help.className = "hint";
  help.textContent = translate("privacy.help");
  const editLabel = document.createElement("label");
  editLabel.textContent = translate("privacy.edit");
  const draft = document.createElement("textarea");
  draft.rows = 5;
  draft.value = initialText;
  draft.setAttribute("aria-label", translate("privacy.edit"));
  editLabel.append(draft);
  const suggestionHeading = document.createElement("h4");
  suggestionHeading.textContent = translate("privacy.detected");
  const suggestions = document.createElement("ul");
  suggestions.className = "privacy-suggestions";
  const none = document.createElement("p");
  none.className = "hint privacy-none";
  none.textContent = translate("privacy.none");
  const manualRow = document.createElement("div");
  manualRow.className = "privacy-manual-row";
  const manualTypeLabel = document.createElement("label");
  manualTypeLabel.textContent = translate("privacy.manualType");
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
  manualButton.textContent = translate("privacy.manual");
  const manualStatus = document.createElement("span");
  manualStatus.className = "hint";
  manualStatus.setAttribute("role", "status");
  manualRow.append(manualTypeLabel, manualButton, manualStatus);
  const outputLabel = document.createElement("label");
  outputLabel.textContent = translate("privacy.maskedPreview");
  const output = document.createElement("textarea");
  output.rows = 5;
  output.readOnly = true;
  outputLabel.append(output);
  const warning = document.createElement("p");
  warning.className = "privacy-warning";
  warning.textContent = translate("privacy.warning");
  const actions = document.createElement("div");
  actions.className = "buttons privacy-review-buttons";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "btn ghost";
  cancel.textContent = translate("privacy.cancel");
  const accept = document.createElement("button");
  accept.type = "button";
  accept.className = "btn primary";
  accept.textContent = translate("privacy.accept");
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
      text.textContent = `${translate(`privacy.${span.type}`)} → ${PRIVACY_PLACEHOLDERS[span.type]}`;
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
      manualStatus.textContent = translate("privacy.selectFirst");
      return;
    }
    manual.push({ start, end, type: manualType.value, manual: true });
    manualStatus.textContent = translate("privacy.selectionAdded");
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

export function clearPrivacyReview(container) {
  if (container) {
    container.replaceChildren();
    container.classList.add("hidden");
  }
}
