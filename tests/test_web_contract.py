"""Static contract checks between the bundled web UI and the FastAPI app.

These tests read ``api/main.py``, ``api/web/index.html``, ``api/web/app.js`` and
``api/web/styles.css`` as text: they are deterministic, fast, and catch drift such
as an endpoint renamed on the server but not in the client, a referenced DOM id
that no longer exists, or accessibility/privacy regressions.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_MAIN = ROOT / "api" / "main.py"
API_ROUTES = ROOT / "api" / "routes.py"
API_SCHEMAS = ROOT / "api" / "schemas.py"
INDEX_HTML = ROOT / "api" / "web" / "index.html"
APP_JS = ROOT / "api" / "web" / "app.js"
STYLES_CSS = ROOT / "api" / "web" / "styles.css"


@pytest.fixture(scope="module")
def api_source() -> str:
    return "".join(path.read_text(encoding="utf-8") for path in (API_MAIN, API_ROUTES, API_SCHEMAS))


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return STYLES_CSS.read_text(encoding="utf-8")


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def html_ids(html: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', html))


def api_routes(api_source: str) -> set[str]:
    return set(re.findall(r'@(?:app|router)\.(?:get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']', api_source))


def js_endpoint_paths(js: str) -> set[str]:
    """String literals in app.js that look like API paths (e.g. "/analyze")."""
    candidates = set(re.findall(r'["\'](/[a-z][a-z0-9/_-]*)["\']', js))
    # Static assets are served by the mount, not declared as routes.
    return {path for path in candidates if not path.startswith("/static")}


def test_web_assets_exist():
    for path in (INDEX_HTML, APP_JS, STYLES_CSS):
        assert path.is_file(), f"missing web asset: {path}"
        assert path.stat().st_size > 0


def test_every_endpoint_referenced_by_app_js_exists_on_the_api(api_source, js):
    referenced = js_endpoint_paths(js)
    routes = api_routes(api_source)
    assert {"/model-info", "/analyze", "/analyze/batch"} <= referenced, referenced
    missing = referenced - routes
    assert not missing, f"app.js calls endpoints missing from api/main.py + api/routes.py: {sorted(missing)}"


def test_app_js_uses_model_info_thresholds_and_risk_band(js):
    assert "/model-info" in js
    for token in (
        "modelInfo",
        "risk_band",
        "decision_threshold",
        "suspicious_threshold",
        "bands",
        "data_note",
        "model_version",
        "probability_calibrated",
    ):
        assert token in js, f"app.js must consume {token!r} from the API"
    # Thresholds come from the API; a fallback exists but must be clearly a fallback.
    assert "FALLBACK_BANDS" in js
    assert "modelInfo.bands.likely_scam" in js
    assert "modelInfo.bands.suspicious" in js
    assert "const BANDS" not in js, "risk bands must not be a single hardcoded table"


def test_model_info_is_fetched_on_load(js):
    assert "loadModelInfo" in js
    assert "DOMContentLoaded" in js
    # The fetch result must drive the note, version and thresholds rendered in the UI.
    assert "info.data_note" in js or "safe.data_note" in js
    assert "model-version" in js and "model-note" in js and "model-thresholds" in js


def test_history_is_opt_in_and_privacy_preserving(js, html):
    assert "HISTORY_PREF_KEY" in js
    assert 'localStorage.getItem(HISTORY_PREF_KEY) === "1"' in js, "history must default to OFF"
    assert "HISTORY_KEY" in js
    assert "removeItem(HISTORY_KEY)" in js, "turning history off must delete stored messages"
    assert js.count("if (!historyEnabled)") >= 2, "history reads/writes must be guarded when off"
    assert "localStorage" in js
    assert "localStorage" in html
    # The opt-in control ships unchecked (default OFF).
    assert re.search(r'id="history-optin"[^>]*\bchecked\b', html) is None
    assert "history-optin" in html and "history-optin" in js
    normalized = collapse_whitespace(html)
    assert "Off by default" in normalized
    assert "never sent to or stored on the server" in normalized or "never stored on the server" in normalized


def test_all_dom_ids_used_by_app_js_exist_in_index_html(js, html):
    referenced = set(re.findall(r'\$\("([^"]+)"\)', js))
    ids = html_ids(html)
    assert referenced, "expected app.js to use the $() id helper"
    missing = referenced - ids
    assert not missing, f"app.js references missing DOM ids: {sorted(missing)}"


def test_index_html_has_accessible_tabs(html):
    assert 'role="tablist"' in html
    tabs = re.findall(r"<button\b[^>]*\brole=\"tab\"[^>]*>", html)
    assert len(tabs) == 3, tabs
    for tab in tabs:
        assert "aria-selected=" in tab
        assert "aria-controls=" in tab
        assert "tabindex=" in tab
    ids = html_ids(html)
    controls = set(re.findall(r'aria-controls="([^"]+)"', html))
    assert controls and controls <= ids
    labelled_by = set(re.findall(r'aria-labelledby="([^"]+)"', html))
    assert labelled_by and labelled_by <= ids
    assert html.count('role="tabpanel"') == 3


def test_index_html_has_live_regions_meter_and_labels(html):
    assert html.count("aria-live=") >= 3, "result, error and status regions need aria-live"
    assert 'id="result"' in html and 'aria-live="polite"' in html
    assert 'role="alert"' in html

    assert 'role="meter"' in html
    assert "aria-valuenow=" in html
    assert "aria-valuemin=" in html and "aria-valuemax=" in html
    assert 'aria-valuemax="100"' in html

    ids = html_ids(html)
    labels = set(re.findall(r'<label\b[^>]*\bfor="([^"]+)"', html))
    assert {"message-input", "batch-input", "history-optin"} <= labels
    assert labels <= ids
    assert "<textarea" in html and 'id="message-input"' in html


def test_index_html_has_skip_link_table_semantics_and_button_types(html, css):
    assert 'class="skip-link"' in html and 'href="#main-content"' in html
    assert 'id="main-content"' in html
    assert re.search(r"<caption\b", html), "batch table needs a caption"
    assert 'scope="col"' in html, "table headers need scope=col"

    buttons = re.findall(r"<button\b[^>]*>", html)
    assert buttons
    for button in buttons:
        assert 'type="button"' in button or ('type="submit"' in button and 'id="btn-feedback"' in button), button

    assert "prefers-reduced-motion" in css


def test_app_js_has_keyboard_navigation(js):
    for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
        assert key in js, f"tabs must support {key}"
    assert "aria-selected" in js
    assert "tabIndex" in js
    assert 'event.key === "Enter"' in js
    assert 'event.key === " "' in js, "rows need Space activation"
    assert "role" in js and "tab" in js


def test_app_js_renders_text_without_innerhtml(js):
    for pattern in ("innerHTML", "insertAdjacentHTML", "document.write", "outerHTML"):
        assert pattern not in js, f"message content must not be injected via {pattern}"
    assert "textContent" in js
    assert "createTextNode" in js or "createElement" in js


def test_synthetic_data_and_privacy_disclaimers_are_present(js, html):
    js_normalized = collapse_whitespace(js)
    html_normalized = collapse_whitespace(html)
    for text in (js_normalized, html_normalized):
        assert "synthetic Philippine data" in text
        assert "not proof of real-world accuracy" in text
    assert "data_note" in js, "the disclaimer should come from /model-info data_note"
    assert "browser" in html_normalized and "server" in html_normalized
    assert "last 50 checks" in html_normalized


def test_feedback_is_operator_opt_in_and_never_sends_message_text(api_source, js, html):
    assert '"/feedback"' in js
    assert "SMSD_FEEDBACK_ENABLED" in api_source
    assert 'ConfigDict(extra="forbid")' in api_source
    assert "SMS text" in html and "never the SMS text" in html
    feedback_handler = js.split("async function submitFeedback(event)", 1)[1].split("/* ---------- History", 1)[0]
    assert "analysis.message" not in feedback_handler
    assert "message:" not in feedback_handler


def test_uncalibrated_scores_are_not_presented_as_probability(js, html):
    assert "uncalibrated spam model score" in js
    assert "calibrated spam score" in js
    assert "estimated scam probability" not in js.lower()
    assert "Likely spam" in js
    assert "Spam or unwanted advertising" in js
    assert "calibration status follows the loaded model" in html
    assert 'displayedCalibration ? t("meter.aria.calibrated") : t("meter.aria")' in js
    assert 'analysis && analysis.probability_calibrated === true ? t("meter.aria.calibrated") : t("meter.aria")' in js
    assert "probability_calibrated" in js
    assert "} scam probability" not in js
    assert 't("batch.col.scoreDescription")' in js
    assert "probability_calibrated: analysis.probability_calibrated === true" in js
    assert "displayedCalibration" in js


def test_service_worker_installs_complete_static_shell_and_never_caches_api():
    sw = (ROOT / "api" / "web" / "sw.js").read_text(encoding="utf-8")
    assert '"/manifest.webmanifest"' in sw
    assert "await Promise.all(SHELL_ASSETS.map((asset) => cache.add(asset)))" in sw
    assert "await caches.delete(CACHE_NAME)" in sw
    assert "const SHELL_PATHS" in sw, "only exact shell paths should be intercepted"
    assert "if (!SHELL_PATHS.has(url.pathname)) return" in sw
    for path in ("/analyze", "/analyze/batch", "/predict", "/feedback", "/model-info"):
        assert f'"{path}"' in sw
    assert "smsd-shell-v7" in sw


def test_app_js_handles_network_and_api_error_states(js):
    assert "Could not reach the detector API" in js
    assert "data.error" in js, "the stable error schema must be parsed"
    assert "error.message" in js
    assert "detail" in js, "fallback to FastAPI detail payloads"
    assert "503" in js and "model_unavailable" in js
    assert "src.train" in js, "missing-model errors should be actionable"
    assert "disabled = true" in js and "aria-busy" in js, "buttons must be disabled while loading"


def test_index_html_has_model_status_region(html):
    for element_id in ("model-status", "model-version", "model-note", "model-thresholds"):
        assert f'id="{element_id}"' in html
    assert 'id="model-status"' in html
    assert re.search(r'id="model-status"[^>]*aria-live', html) or re.search(r'aria-live[^>]*id="model-status"', html)


def test_message_signals_are_described_as_text_patterns(html, js, css):
    normalized = collapse_whitespace(html)
    versioned_assets = re.findall(r"/static/(?:styles\.css|app\.js)\?v=([a-z0-9-]+)", html)
    assert versioned_assets and len(versioned_assets) == 2, "signal CSS/JS updates must bypass stale browser caches"
    assert versioned_assets[0] == versioned_assets[1], "CSS and JS cache-bust versions must match"
    sw = (ROOT / "api" / "web" / "sw.js").read_text(encoding="utf-8")
    sw_asset_versions = re.findall(r"/static/(?:styles\.css|app\.js)\?v=([a-z0-9-]+)", sw)
    assert sw_asset_versions == versioned_assets, "service-worker shell must fetch the current UI asset versions"
    assert 'id="signals-guidance"' in html
    assert "do not show which features influenced the model’s verdict" in normalized
    assert "can appear in legitimate messages too" in normalized
    assert 'id="highlighted"' in html and 'role="group"' in html
    assert 'id="signals"' in html and 'aria-labelledby="signals-heading"' in html
    assert ".signal-reference" in css and "vertical-align: super" in css
    assert "Loaded fictional {kind} message" in js
    assert "Fictional {kind} example {index}" not in js
    assert 'register("/sw.js", { updateViaCache: "none" })' in js
    for explanation in (
        "Link-like text appears here.",
        "A phone number appears.",
        "An amount appears.",
        "These words can add time pressure",
        "This does not verify the sender or prove impersonation.",
    ):
        assert explanation in js
    assert "signalSummary(analysis)" in js, "batch and single views should share signal labels"


def test_styles_have_visible_focus_and_responsive_layout(css):
    assert ":focus-visible" in css
    assert ".skip-link" in css
    assert "prefers-reduced-motion" in css
    assert "@media (max-width: 640px)" in css
    assert "--suspect" in css and "--scam" in css  # meter zones from API thresholds


# ----------------------------- fetch correctness -----------------------------


def test_in_flight_requests_are_aborted_not_just_ignored(js):
    assert "AbortController" in js, "each check must run under an AbortController"
    assert "singleAbortController" in js and "batchAbortController" in js
    assert ".abort()" in js, "starting a new check must cancel the in-flight request"
    assert "signal: controller.signal" in js, "the abort signal must reach fetch"
    assert "revision !== singleRevision" in js and "revision !== batchRevision" in js
    assert 'failure.name === "AbortError"' in js or "aborted" in js


# ----------------------------- i18n -----------------------------


def test_language_toggle_is_en_taglish_and_persisted(js, html):
    assert 'id="btn-lang"' in html
    assert "data-i18n" in html, "static strings must be translatable via data-i18n"
    assert "data-i18n-aria-label" in html
    assert 'data-i18n-placeholder="check.placeholder"' in html
    assert 'data-i18n-placeholder="batch.placeholder"' in html
    assert "LANG_KEY" in js
    assert "localStorage.setItem(LANG_KEY, lang)" in js, "language preference must persist"
    assert '"taglish"' in js and '"en"' in js
    # Both dictionaries carry the core strings.
    for key in (
        "band.likely_scam",
        "band.suspicious",
        "band.looks_safe",
        "check.run",
        "batch.run",
        "history.optin",
        "footer.synthetic",
        "signals.guidance",
        "tips.otp",
    ):
        assert f'"{key}"' in js
    assert "I18N.taglish" in js and "I18N.en" in js


def test_i18n_dictionaries_have_identical_keys(js):
    match = re.search(r"const I18N = \{(.*?)\n\};", js, re.DOTALL)
    assert match, "I18N dictionary must exist"
    dictionary_source = match.group(1)
    blocks = re.findall(r"(en|taglish): \{(.*?)\n  \},", dictionary_source, re.DOTALL)
    assert len(blocks) == 2, f"expected en+fil dictionaries, found {[name for name, _ in blocks]}"
    keys = {}
    for name, body in blocks:
        keys[name] = set(re.findall(r'"([a-z][a-z0-9._]+)":', body))
    assert keys["en"], "english dictionary must not be empty"
    assert keys["en"] == keys["taglish"], (
        f"dictionary key drift: en-only={sorted(keys['en'] - keys['taglish'])[:5]} "
        f"taglish-only={sorted(keys['taglish'] - keys['en'])[:5]}"
    )


def test_signal_terminology_is_consistent_across_languages(js):
    for signal in ("url", "phone", "money", "urgency", "brand"):
        assert f'"signal.{signal}.label"' in js


# ----------------------------- dark mode -----------------------------


def test_dark_mode_variables_and_toggle(css, js, html):
    assert 'id="btn-theme"' in html
    assert 'data-i18n-aria-label="theme.aria"' in html
    assert 'id="offline-banner"' in html
    assert ':root[data-theme="dark"]' in css, "manual dark theme must define its own variables"
    assert "prefers-color-scheme: dark" not in css, "theme must have only the explicit light/dark modes"
    assert "color-scheme: light" in css and "color-scheme: dark" in css
    assert "THEME_KEY" in js and "localStorage.setItem(THEME_KEY" in js, "theme choice must persist"
    assert 'const THEME_STATES = ["light", "dark"]' in js
    assert "readTheme" in js and "applyTheme" in js and "toggleTheme" in js
    assert "cycleTheme" not in js and '"theme.auto"' not in js
    for state in ("light", "dark"):
        assert f'"{state}"' in js
    # Both themes must define the core palette variables (WCAG baseline).
    for variable in (
        "--bg",
        "--card",
        "--ink",
        "--muted",
        "--line",
        "--primary",
        "--focus",
        "--red",
        "--amber",
        "--green",
    ):
        light_section = css.split(':root[data-theme="dark"]', 1)[0]
        dark_section = css.split(':root[data-theme="dark"]', 1)[1]
        assert light_section.count(variable) >= 1 and dark_section.count(variable) >= 1, variable


# ----------------------------- sharing & export -----------------------------


def test_copy_summary_is_client_side_only(js, html):
    assert 'id="btn-copy-summary"' in html
    assert "navigator.clipboard.writeText" in js
    assert "execCommand" in js, "clipboard fallback for older browsers/insecure contexts"
    assert 'id="copy-status"' in html


def test_csv_export_escapes_and_is_client_side_only(js, html):
    assert 'id="btn-csv"' in html
    assert '""' in js, "CSV cells must escape double quotes"
    assert "text/csv;charset=utf-8" in js
    assert "\\uFEFF" in js, "CSV needs a BOM so Excel reads UTF-8 peso signs correctly"
    assert "URL.createObjectURL" in js and "revokeObjectURL" in js
    assert "XMLHttpRequest" not in js and "fetch(" in js  # no upload anywhere


# ----------------------------- loading & empty states -----------------------------


def test_batch_shows_progress_and_skeleton(js, html, css):
    assert 'id="batch-progress"' in html
    assert 'aria-live="polite"' in html.split('id="batch-progress"')[1][:200]
    assert "showBatchProgress" in js
    assert "updateBatchProgress" in js and "chunkSize = 10" in js
    assert '"skeleton"' in js
    assert ".skeleton" in css and "skeleton-shimmer" in css


def test_model_info_failure_is_surfaced(js):
    assert "model.fallbackSuffix" in js or "fallback thresholds" in js
    assert "showOfflineBanner" in js


# ----------------------------- offline / PWA -----------------------------


def test_offline_banner_exists_and_is_wired(js, html):
    assert 'id="offline-banner"' in html
    assert 'role="alert"' in html.split('id="offline-banner"')[1][:300]
    assert "initOfflineDetection" in js
    assert 'addEventListener("offline"' in js and 'addEventListener("online"' in js
    assert "navigator.onLine" in js


def test_service_worker_never_caches_messages(js, html, api_source):
    assert 'rel="manifest"' in html and "/manifest.webmanifest" in html
    assert '"/sw.js"' in js and "serviceWorker" in js
    # The SW must exist, only cache GETs, and never intercept analysis endpoints.
    sw = (ROOT / "api" / "web" / "sw.js").read_text(encoding="utf-8")
    assert 'request.method !== "GET"' in sw
    for endpoint in ("/analyze", "/predict", "/feedback", "/model-info"):
        assert endpoint in sw, f"service worker must explicitly exclude {endpoint}"
    assert "caches" in sw
    # Manifest and SW must be served by the app.
    assert '"/manifest.webmanifest"' in api_source and '"/sw.js"' in api_source
    manifest = (ROOT / "api" / "web" / "manifest.webmanifest").read_text(encoding="utf-8")
    assert '"start_url": "/"' in manifest
    assert "icons" in manifest


def test_mobile_batch_cards_use_data_labels(css, js):
    assert "data-label" in css, "mobile card layout labels cells via ::before content"
    assert "messageCell.dataset.label" in js and "verdictCell.dataset.label" in js
    assert "@media (max-width: 640px)" in css
    assert ".batch-table thead { display: none; }" in css
    assert "pointer: coarse" in css and "min-height: 44px" in css
