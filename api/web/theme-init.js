/* Apply a saved theme before first paint; no inline scripts required. */
"use strict";

try {
  const saved = localStorage.getItem("smsd_theme_v1");
  if (saved === "light" || saved === "dark") {
    document.documentElement.setAttribute("data-theme", saved);
  }
} catch {
  // Storage may be blocked; use the default theme.
}
