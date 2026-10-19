"""Static contract checks between the bundled web UI and the FastAPI app.

These tests read ``api/main.py``, ``web/index.html``, ``web/app.js`` and
``web/styles.css`` as text: they are deterministic, fast, and catch drift such
as an endpoint renamed on the server but not in the client, a referenced DOM id
that no longer exists, or accessibility/privacy regressions.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_MAIN = ROOT / "api" / "main.py"
INDEX_HTML = ROOT / "web" / "index.html"
APP_JS = ROOT / "web" / "app.js"
STYLES_CSS = ROOT / "web" / "styles.css"


@pytest.fixture(scope="module")
def api_source() -> str:
    return API_MAIN.read_text(encoding="utf-8")


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
    return set(re.findall(r'@app\.(?:get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']', api_source))


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
    assert not missing, f"app.js calls endpoints missing from api/main.py: {sorted(missing)}"


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
    assert "<caption>" in html, "batch table needs a caption"
    assert 'scope="col"' in html, "table headers need scope=col"

    buttons = re.findall(r"<button\b[^>]*>", html)
    assert buttons
    for button in buttons:
        assert 'type="button"' in button, button

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


def test_styles_have_visible_focus_and_responsive_layout(css):
    assert ":focus-visible" in css
    assert ".skip-link" in css
    assert "prefers-reduced-motion" in css
    assert "@media (max-width: 640px)" in css
    assert "--suspect" in css and "--scam" in css  # meter zones from API thresholds
