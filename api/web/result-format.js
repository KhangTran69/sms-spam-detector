/* Shared score and threshold interpretation for single, batch, history, and compare views. */
const BAND_VIEW = Object.freeze({
  likely_scam: { css: "spam", icon: "🚨", key: "band.likely_scam" },
  suspicious: { css: "suspicious", icon: "⚠️", key: "band.suspicious" },
  looks_safe: { css: "safe", icon: "✅", key: "band.looks_safe" },
});

export function normalizeModelInfo(info, validFraction) {
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
    model_version: typeof safe.model_version === "string" && safe.model_version ? safe.model_version : null,
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

export function createResultFormatting({ translate, validFraction, getModelInfo, matchesLoadedModel }) {
  function bandsForAnalysis(analysis) {
    const modelInfo = getModelInfo();
    if (!analysis || typeof analysis !== "object") return modelInfo.bands;
    const useLoaded = matchesLoadedModel(analysis);
    const likely = validFraction(analysis.decision_threshold)
      ?? (useLoaded ? validFraction(modelInfo.bands && modelInfo.bands.likely_scam) : null);
    const suspicious = validFraction(analysis.suspicious_threshold)
      ?? (useLoaded ? validFraction(modelInfo.bands && modelInfo.bands.suspicious) : null);
    if (likely === null || suspicious === null || suspicious >= likely) return null;
    return { likely_scam: likely, suspicious, looks_safe: 0 };
  }

  function bandFromProbability(probability, analysis = null) {
    const value = validFraction(probability);
    const bands = bandsForAnalysis(analysis);
    if (value === null || !bands) return "unavailable";
    if (value >= bands.likely_scam) return "likely_scam";
    if (value >= bands.suspicious) return "suspicious";
    return "looks_safe";
  }

  function bandOf(analysis) {
    if (analysis && typeof analysis.risk_band === "string" && BAND_VIEW[analysis.risk_band]) {
      return analysis.risk_band;
    }
    return bandFromProbability(analysis ? analysis.spam_probability : null, analysis);
  }

  function bandView(band) {
    return BAND_VIEW[band] || { css: "unknown", icon: "ℹ️", key: "band.unavailable" };
  }

  function isKnownBand(band) {
    return Object.prototype.hasOwnProperty.call(BAND_VIEW, band);
  }

  function scoreLabel(analysis) {
    if (!analysis || typeof analysis.probability_calibrated !== "boolean") return translate("verdict.score.unavailable");
    return analysis.probability_calibrated
      ? translate("verdict.score.calibrated")
      : translate("verdict.score.uncalibrated");
  }

  return Object.freeze({ bandsForAnalysis, bandFromProbability, bandOf, bandView, isKnownBand, scoreLabel });
}
