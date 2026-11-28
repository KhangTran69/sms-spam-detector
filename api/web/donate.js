/* Local, explicit donation form. It never retries or persists user text. */
export const PRIVACY_NOTICE_VERSION = "2026-11-01-v4";
const DONATION_REQUEST_TIMEOUT_MS = 15_000;

async function fetchBounded(fetchImpl, url, options, timeoutMs, { parseJson = false } = {}) {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetchImpl(url, { ...options, signal: controller.signal });
    let data = null;
    if (parseJson) {
      try {
        data = await response.json();
      } catch (error) {
        if (response.ok || timedOut) throw error;
      }
    }
    return { response, data };
  } catch (error) {
    if (timedOut) {
      const timeoutError = new Error("The local service request timed out.");
      timeoutError.timeout = true;
      throw timeoutError;
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export function buildDonationPayload({
  message,
  labelHint,
  language,
  consent,
  authorizedToShare,
  modelResearchConsent = false,
  noticeVersion = PRIVACY_NOTICE_VERSION,
}) {
  if (typeof message !== "string" || !message.trim()) throw new TypeError("Enter a message before submitting.");
  if (!consent) throw new TypeError("Consent is required before submitting.");
  if (!authorizedToShare) throw new TypeError("Confirm that you are authorized to share this message.");
  return {
    message,
    label_hint: labelHint || null,
    language: language || null,
    consent: true,
    authorized_to_share: true,
    model_research_consent: Boolean(modelResearchConsent),
    notice_version: noticeVersion,
  };
}

export function formatPiiFinding(span) {
  const category = typeof span?.category === "string" ? span.category : "personal detail";
  const value = typeof span?.value === "string" ? span.value : "";
  return `${category}: ${value}`;
}

export function renderPiiFindings(container, spans, documentRef = globalThis.document) {
  container.replaceChildren();
  for (const span of spans || []) {
    const item = documentRef.createElement("li");
    item.textContent = formatPiiFinding(span);
    container.append(item);
  }
  container.hidden = !(spans && spans.length);
}

export function createDonationForm({
  documentRef = globalThis.document,
  fetchImpl = globalThis.fetch,
  timeoutMs = DONATION_REQUEST_TIMEOUT_MS,
} = {}) {
  const form = documentRef.querySelector("#donation-form");
  if (!form) return;
  const message = documentRef.querySelector("#donation-message");
  const labelHint = documentRef.querySelector("#donation-label-hint");
  const language = documentRef.querySelector("#donation-language");
  const consent = documentRef.querySelector("#donation-consent");
  const authorizedToShare = documentRef.querySelector("#donation-authorized");
  const modelResearchConsent = documentRef.querySelector("#donation-research-consent");
  const submitButton = documentRef.querySelector("#donation-submit");
  const status = documentRef.querySelector("#donation-status");
  const findings = documentRef.querySelector("#donation-pii-findings");
  const withdrawalForm = documentRef.querySelector("#donation-withdrawal-form");
  const withdrawalId = documentRef.querySelector("#donation-withdrawal-id");
  const withdrawalButton = documentRef.querySelector("#donation-withdraw");

  // Pending choices and the opaque key live only in this page's memory.
  let pendingSubmission = null;

  const submissionFields = [message, labelHint, language, consent, authorizedToShare, modelResearchConsent];
  function setSubmitting(active) {
    for (const field of submissionFields) field.disabled = active;
    submitButton.disabled = active;
    withdrawalButton.disabled = active;
    withdrawalId.disabled = active;
  }

  function setStatus(text) {
    status.textContent = text;
  }

  function clearPiiFindings() {
    renderPiiFindings(findings, [], documentRef);
    message.removeAttribute("aria-invalid");
    message.setAttribute("aria-describedby", "donation-message-help");
  }

  message.addEventListener("input", clearPiiFindings);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitButton.disabled || withdrawalButton.disabled) return;
    clearPiiFindings();
    if (!form.reportValidity()) return;

    let payload;
    try {
      payload = buildDonationPayload({
        message: message.value,
        labelHint: labelHint.value,
        language: language.value,
        consent: consent.checked,
        authorizedToShare: authorizedToShare.checked,
        modelResearchConsent: modelResearchConsent.checked,
      });
    } catch (error) {
      setStatus(error.message);
      return;
    }

    const body = JSON.stringify(payload);
    if (pendingSubmission && pendingSubmission.body !== body) {
      setStatus("The previous submission outcome may be uncertain. Restore the previous choices to retry the same request, or contact the operator before starting another donation.");
      return;
    }
    if (!pendingSubmission) {
      if (!globalThis.crypto?.randomUUID) {
        setStatus("A secure submission key is unavailable. Open the local detector at its loopback address using a supported browser.");
        return;
      }
      pendingSubmission = { body, key: globalThis.crypto.randomUUID().replaceAll("-", ""), uncertain: false };
    }
    withdrawalId.value = "";
    setSubmitting(true);
    setStatus("Submitting once to this local detector service…");
    try {
      const { response, data } = await fetchBounded(fetchImpl, "/donate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, submission_key: pendingSubmission.key }),
        cache: "no-store",
      }, timeoutMs, { parseJson: true });
      const error = data?.error;
      if (!response.ok) {
        // A later rejection cannot settle an earlier ambiguous attempt.
        const definitiveRejection = [400, 415, 422].includes(response.status)
          || error?.code === "notice_version_mismatch";
        if (definitiveRejection && !pendingSubmission.uncertain) {
          pendingSubmission = null;
        } else {
          pendingSubmission.uncertain = true;
        }
        setSubmitting(false);
        if (error?.code === "pii_detected" && Array.isArray(error.details)) {
          renderPiiFindings(findings, error.details, documentRef);
          message.setAttribute("aria-invalid", "true");
          message.setAttribute("aria-describedby", "donation-message-help donation-pii-findings");
          message.focus();
        }
        const failure = error?.message || "Could not submit. Review the form and choose Submit again to retry manually.";
        setStatus(pendingSubmission?.uncertain
          ? failure + " The earlier submission outcome may still be uncertain. Keep the same form and check with the operator."
          : failure);
        return;
      }
      const recordId = typeof data?.record_id === "string" ? data.record_id : null;
      if (!recordId || !/^[a-f0-9]{32}$/.test(recordId)) {
        throw new Error("The service response did not include a valid withdrawal ID.");
      }
      pendingSubmission = null;
      withdrawalId.value = recordId;
      message.value = "";
      consent.checked = false;
      authorizedToShare.checked = false;
      modelResearchConsent.checked = false;
      const researchStatus = payload.model_research_consent
        ? " Your separate model-research choice was recorded; inclusion still requires independent review and approval."
        : " No model-research consent was given.";
      setStatus(`Received for local review. Stored for up to ${data?.retention_days || 90} days. It is not a verified label.${researchStatus}`);
    } catch (error) {
      if (pendingSubmission) pendingSubmission.uncertain = true;
      if (error.timeout) {
        setStatus("The local service timed out. The donation outcome may be uncertain; it was not automatically resent. To retry, submit the unchanged form on this page with the same key, or check with the operator.");
      } else {
        setStatus("Could not confirm whether the donation was stored. It was not automatically resent. To retry, submit the unchanged form on this page with the same key, or check with the local operator.");
      }
    } finally {
      setSubmitting(false);
    }
  });

  withdrawalForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitButton.disabled || withdrawalButton.disabled) return;
    if (!withdrawalForm.reportValidity()) return;
    const recordId = withdrawalId.value.trim();
    withdrawalButton.disabled = true;
    withdrawalId.disabled = true;
    submitButton.disabled = true;
    setStatus("Withdrawing the local donation…");
    try {
      const { response } = await fetchBounded(fetchImpl, "/donate", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: recordId }),
        cache: "no-store",
      }, timeoutMs);
      if (!response.ok) throw new Error("withdrawal failed");
      setStatus(
        "Withdrawal request received. The service cannot confirm a “Withdrawn” status or whether this ID matched a record. Keep this ID and contact the operator to confirm whether the message and label hint were erased.",
      );
    } catch (error) {
      if (error.timeout) {
        setStatus("The local service timed out. We could not confirm whether withdrawal completed; the request was not automatically retried. Keep the ID and contact the operator if unsure.");
      } else {
        setStatus("Could not confirm whether withdrawal completed. The request was not automatically retried; keep the ID and contact the operator if unsure.");
      }
    } finally {
      withdrawalButton.disabled = false;
      withdrawalId.disabled = false;
      submitButton.disabled = false;
    }
  });
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => createDonationForm());
}
