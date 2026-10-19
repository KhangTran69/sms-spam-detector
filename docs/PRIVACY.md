# Privacy

This service classifies SMS text for spam/scam signals. SMS messages routinely
contain OTPs, account numbers, names, addresses, and links to financial
accounts, so privacy is a first-class design constraint.

## 1. What the server does with a message

- The message is sent to the API, transformed **in memory** into features, and
  classified. The response returns the verdict and derived signals.
- **No server-side message persistence.** The application does not write message
  text to a database, file, cache, feedback queue, or analytics system. A
  separate, operator-enabled feedback action stores only the user's selected
  expected label, broad category, and model version; it has no message-text
  field.
- The model artifact is static; it does not learn from or retain requests.
- Restarting the process is sufficient to erase all in-memory state.

## 2. Logging

- Application logs must **not contain message bodies**, message prefixes,
  matched spans, or raw request bodies. Log only operational metadata: request
  path, status code, latency, and (if needed) a coarse size bucket.
- Do not add "debug logging" of requests in production. If a logging framework
  captures request bodies by default, disable it.
- Reverse proxies (nginx, Caddy, cloud load balancers) must also be configured
  not to log request bodies. Access logs containing URLs are acceptable, but
  `/predict` and `/analyze` carry data in the body — do not switch them to GET.
- Never send production messages to third-party error trackers/APMs. If you must
  use one, scrub bodies and headers centrally.
- Batch endpoint: do not log the batch either. Error payloads are generic and do
  not echo message text (validation errors are 422 with field-level messages;
  detail never includes the submitted text).

## 3. Browser history (opt-in only)

The bundled web UI (`web/`) can keep recent checks in the browser's
`localStorage`. Rules:

- **Opt-in.** History is disabled unless the user explicitly enables it; the
  toggle state and the stored entries live only in the user's browser. With the
  feature off, no check is written to `localStorage`.
- **Client-side only.** Nothing in browser history is sent to the server, and
  the server has no endpoint to read it.
- **Bounded.** A small fixed limit of recent entries is kept (the UI trims the
  list; older entries are dropped), and "Clear history" deletes them.
- **Shared devices.** The UI cannot detect a shared browser profile, so an
  operator deploying it for multiple users should say so in their own privacy
  notice and tell users to clear history or use a private window on shared
  devices.
- **Incognito/private windows** do not persist `localStorage` beyond the session.

If the deployed UI does not show the opt-in toggle (older revision), assume
history is being stored in the browser and clear it; see the UI's history panel.

## 4. Anonymous correction reports (off by default)

- Feedback is disabled unless the operator sets `SMSD_FEEDBACK_ENABLED=true`.
- When enabled, a user must explicitly submit a correction. The browser sends
  only the selected expected label, the displayed prediction, a broad message
  category, and model version. The API request schema rejects extra fields,
  including `message` or `text`.
- The server writes those fields, a timestamp, and a random receipt ID to
  `data/feedback/reports.jsonl` (or `SMSD_FEEDBACK_PATH`). The local queue is
  ignored by Git; Compose uses the named `smsd_feedback` volume. It is capped at
  10 MiB and does not store IP addresses or SMS text.
- Reports are unverified review signals, never training labels. A reviewer must
  verify any separately donated/redacted example through the consent workflow
  in [DATA_COLLECTION.md](DATA_COLLECTION.md); reports never trigger training.
- Enabling the endpoint on a public service requires authentication or
  deployment-level abuse controls and a retention policy. The sample service
  is intended for local use by default.

## 5. Data minimization and PII

- Do not send live OTPs, full card numbers, or account credentials through any
  online tool, including this one. The API has no use for them and they increase
  exposure if the client, proxy, or network is compromised.
- The project does not require names, phone numbers, account numbers, or
  location. The API accepts a single text field and a bounded batch of texts.
- Any **collected** dataset for retraining must be masked before storage; see
  [DATA_COLLECTION.md](DATA_COLLECTION.md). Real message data must never be
  committed to Git — only the synthetic Philippine CSVs are tracked.
- Do not enable request-body logging, tracing of payloads, or crash-dump capture
  of request contents.

## 6. Data-subject requests and retention

Because the server does not store messages, it holds no per-user message data to
export or delete. The residual copies are:

| Location | What | How to handle a deletion request |
|---|---|---|
| Server memory | in-flight request only | nothing to delete once the response is sent |
| Server/proxy logs | must be message-free by policy | verify; if a body leaked, rotate/delete the log and record an incident |
| User's browser `localStorage` | opt-in history, user-controlled | "Clear history" button; it never leaves the browser |
| Feedback queue | labels/category/model version only | archive or delete `data/feedback/reports.jsonl` under the operator's retention policy |
| Retraining datasets (if any) | masked real data held locally | delete matching donor rows using the consent-log pseudonym, record deletion, retrain artifacts if required |

Retention:

- API traffic: no stored messages → no retention clock.
- Logs: keep the minimum (e.g. 30 days) and never include message bodies.
- Consented datasets: keep only while needed for the current model; revisit at
  least annually, delete stale/withdrawn data, and document the decision in the
  audit trail.

## 7. Security posture relevant to privacy

- Container runs as a **non-root** user (uid 10001) with a read-only model mount;
  no secrets are baked into the image or committed to the repository.
- CORS is a restrictive allowlist (`SMSD_CORS_ORIGINS`, defaults to local
  origins); wildcard origins are ignored. CORS is not an authentication or
  access-control mechanism — put the service behind a TLS reverse proxy and
  network controls if it is exposed beyond localhost.
- Security headers on responses: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.
- Request bodies are capped (1 MB) and messages are length-bounded (1–10,000
  characters; batches 1–50 messages, 200,000 characters total) to limit
  accidental data volume and abuse.
- The UI sends messages same-origin to the API; there are no third-party
  scripts, fonts, or analytics in the bundled page.
- TLS can be terminated by a reverse proxy (see
  [DEPLOYMENT.md](DEPLOYMENT.md)); the app itself speaks plain HTTP on the
  container network.

## 8. Operator checklist

- [ ] Request bodies are not logged anywhere (app, proxy, APM)
- [ ] No message data is persisted by the service
- [ ] Browser history is opt-in and clearable; users on shared devices are warned
- [ ] Model and data artifacts are git-ignored; repository contains no personal
      messages or secrets
- [ ] No third-party analytics/scripts in `web/`
- [ ] If anonymous feedback is enabled, queue retention and abuse controls are configured; summaries contain aggregate counts only
- [ ] Exposure is behind TLS + access controls if not localhost-only
- [ ] Incident path for accidental PII in logs/artifacts is documented
      ([RETRAINING.md](RETRAINING.md) incident response)
