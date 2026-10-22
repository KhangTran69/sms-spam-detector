/* Browser-local history persistence. This module has no network or DOM access. */
export function createHistoryStore(storage, { key = "smsd_history_v1", preferenceKey = "smsd_history_enabled_v1", limit = 50 } = {}) {
  function target() {
    return typeof storage === "function" ? storage() : storage;
  }

  function isEnabled() {
    try {
      return target().getItem(preferenceKey) === "1";
    } catch {
      return false;
    }
  }

  function setEnabled(enabled) {
    const value = Boolean(enabled);
    let stored = false;
    try {
      target().setItem(preferenceKey, value ? "1" : "0");
      stored = true;
    } catch {
      // Storage can be unavailable in private browsing; callers keep history off.
    }
    if (!value) clear();
    return stored;
  }

  function clear() {
    try {
      target().removeItem(key);
    } catch {
      // Storage may be disabled or full; the UI remains usable.
    }
  }

  function load() {
    if (!isEnabled()) return [];
    try {
      const parsed = JSON.parse(target().getItem(key) || "[]");
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((entry) => entry && typeof entry.message === "string").slice(0, limit);
    } catch {
      return [];
    }
  }

  function save(entries) {
    if (!isEnabled()) {
      clear();
      return [];
    }
    const trimmed = entries.slice(0, limit);
    try {
      target().setItem(key, JSON.stringify(trimmed));
    } catch {
      // Do not turn a local storage quota failure into an analysis failure.
    }
    return trimmed;
  }

  return Object.freeze({ isEnabled, setEnabled, clear, load, save });
}
