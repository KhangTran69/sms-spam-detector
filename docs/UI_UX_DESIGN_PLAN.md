# UI/UX Design Plan — Hallmark material adoption

Created: 2026-11-27 · Source of design method: [Nutlope/hallmark](https://github.com/Nutlope/hallmark) (MIT) · Roadmap link: [ROADMAP.md](ROADMAP.md) T4.

This plan adapts the Hallmark design method — "look made, not generated" — to
this project's constraints (no build step, vanilla JS, bilingual EN/Taglish,
light+dark, test-pinned safety copy, WCAG floor already enforced). It borrows
Hallmark's **rules and one design material**; it does not adopt its agent
packaging, its 51-theme machinery, or its photo library.

---

## 1. What Hallmark is and what we borrow

Hallmark is Together AI's anti-AI-slop design skill: a non-waivable **Floor**
of CSS/type/layout rules, overridable **Reflex gates**, a **sloplint** checker
for named "AI tells", and 51 self-contained **theme materials** (palette + type
voice + surface rules, ≤ 8 KB each). We borrow three things:

1. **The Floor** as an acceptance gate for every future UI change.
2. **One theme material** as the design language (not a theme roulette).
3. **A ported lint** of the tells that apply to a static, no-build app —
   wired into the existing test stack instead of adding puppeteer.

Explicitly **not** borrowed: theme dealing (`theme.mjs`), `puppeteer-core`,
the 755-photo library, the Claude/Codex plugin packaging.

## 2. Honest audit: our current UI against the Floor

Checked against `api/web/{index.html,styles.css,app.js}` at commit `1045ab3`:

| # | Hallmark rule | Our status |
|---|---|---|
| F2 | Never animate `width`/`left` | **Violate** — `.meter-marker { transition: left .5s }`, `.mini-meter > div { transition: width .4s }` |
| F9 | No eyebrow labels (tracked caps) | **Violate** — every card heading: `text-transform: uppercase; letter-spacing: .6px` ("MODEL INFORMATION", "MESSAGE SIGNALS", "SAFETY TIPS", …) |
| F10 | No meta-clutter (dot-joined status strings, decorative dots) | **Violate** — connection row: "Browser reports: **Online** · Detector API: **Available** · Model: **Ready**" with colored state dots and an always-visible Retry button |
| F11 | No purple-to-blue gradient | **Violate** — header: `linear-gradient(135deg, #312e81, #4f46e5, #6d28d9)` |
| F11 | No emoji icons | **Violate** — 🛡️ brand, 🚨/⚠️/✅ verdict icons, example chips |
| F11 | No card-in-card / uniform card monotony | **Violate** — every section is the same white rounded shadowed card; verdict card nests inside the result stack |
| F1 | Tokens only | **Partial** — tokens exist, but literal hexes survive in signal underline colors and the header gradient |
| F12 | Hero (headline + primary action) visible at 1280×800 | **Violate** — header + connection card + model card push the input below the fold; the job is off-screen |
| F13 | ≈ 80 words/screen | **Violate** — help + guidance + caveat + note stack ≈ 150+ words on the check screen |
| F6–F8 | Focus, reduced-motion, no-script | **Pass** (enforced by existing tests) |
| Honesty | No invented metrics | **Pass** (enforced by `check_headline_claims.py` and pinned disclaimers) |

The pattern is recognizable: the UI reads as generated. The fix is a material,
not more polish.

## 3. Chosen material: **Editorial** (with two stated adaptations)

Candidates considered:

- **Editorial** (magazine voice): warm-white uncoated stock, condensed display
  (Bricolage Grotesque 800) over a serif body (Source Serif 4), square corners,
  heavy ink rule + hairlines, one printer's green, "nothing is boxed, nothing
  casts a shadow", **contents as rows**.
- **Console** (instrument aesthetic): graphite panels, mono for measured
  values, amber = person / cool = instrument. Strong metaphor for
  "instrument measured the message", but dark-first is wrong for a phone-first
  Filipino audience, and its devtools flavor undersells the trust job.

**Recommendation: Editorial**, because the product's job is *reading a text
artifact and judging trust* — a serif reading voice for the message under
analysis is itself a trust signal (official notices, press), hairline rows
natively replace our uniform card grid, and the material's restraint leaves
nowhere for slop to hide. Two adaptations, recorded in the CSS stamp per
Hallmark's waiver culture:

- **Adaptation A — safety signal colors.** The material allows one accent
  (printer's green). A scam detector needs a tri-band verdict. Rule: verdict
  bands are carried by **words + weight + a 4px rule color** (deep green,
  ochre, brick red, all oklch-tokenized, desaturated to sit in the ink world);
  color is never the only carrier (already an a11y requirement), and signal
  colors never decorate non-verdict surfaces.
- **Adaptation B — dark colorway.** Editorial's material is light-paper only.
  Derive one dark dial (paper `oklch(16% 0.01 86)`, ink `oklch(94% 0.008 86)`,
  same hue family) validated ≥ WCAG AA, keeping the existing manual + system
  theme toggle.

Fonts are **self-hosted** in `api/web/fonts/` (OFL; Bricolage Grotesque
variable for the `wdth 75` display treatment, Source Serif 4 variable subset):
no third-party font CDN request, preserving the project's no-external-requests
privacy posture. New files go through the static allowlist (`_STATIC_ASSETS`,
`font/woff2` content type) and the SW shell list.

## 4. Phased work

### Phase 0 — Baseline and lint port (agent-executable)

1. Port the applicable tells as static checks in
   `tests/test_web_contract.py` (plus a new `check_ui_floor` grouping):
   no `text-transform: uppercase` on headings, no `linear-gradient` outside
   an explicit waiver list, no emoji in index.html or user-facing i18n
   strings, no `transition:` on `width`/`left`/`top`/`height`, no
   `transition: all`, no literal hex/rgb outside `:root` token blocks,
   one visible primary action per panel. These run in CI forever after —
   the anti-slop regression gate.
2. Refresh the screenshot inventory (`docs/images/`) at 360/800/1280 widths
   as the "before" record.

### Phase 1 — Material tokens (agent-executable)

1. New `api/web/tokens.css` (loaded first): Editorial oklch palette, type
   scale, `--radius-*: 0`, rule weights, focus token; dark dial via
   `[data-theme="dark"]` + system query. Hallmark stamp as the first CSS
   comment (material, adaptations, date, source revision).
2. Self-hosted fonts + `@font-face` in `tokens.css`; `font-display: swap`.
3. Replace literal colors in `styles.css` with tokens; delete the gradient
   header → ink band with paper type (≤ 2 bands/page per the material).
4. Bump shell generation (`smsd-shell-v26`, asset stamp `ui21-editorial-*`).

### Phase 2 — Job-driven layout ("a checker checks", agent-executable)

1. Check-first hero: label + textarea + primary action within the first
   800px of height at 1280×800; the page headline is a sentence, not a brand
   banner.
2. Demote meta: connection status becomes a single quiet line, restyled
   small and muted with no colored state dots. Deviation from the original
   "hidden when all-good" ambition, on the record: the browser smoke pins an
   always-reachable retry control (users may re-check status proactively),
   and hiding it would strand a user whose server died silently. Model
   information collapses into one line in the footer area; the details
   disclosure keeps thresholds/provenance.
3. Replace the card stack with hairline sections opened by a heavy ink rule;
   the analyzed message becomes the typographic centerpiece: serif, larger,
   set as a quotation with the existing signal underlines (patterns keep
   their per-type distinction via underline style, colors tokenized).

### Phase 3 — Component de-slop pass (agent-executable)

1. Verdict: words first ("Likely scam"), display face, 4px signal-color rule
   on the left edge only; score line in tabular figures; **no background
   wash, no emoji, no pill**.
2. Meter: zone colors muted to the ink world; marker animated with
   `transform: translateX()` + `clip-path` fills (Floor F2-compliant),
   reduced-motion honored.
3. Signals, tips, batch results, history, compare: hairline rows, sharp
   corners, body-face labels in sentence case; batch summary as a
   "contents as rows" block instead of three stat cards.
4. Example chips become text links with a rule underline (no pill chips).

### Phase 4 — Copy and bilingual pass (agent + native-speaker review)

1. Cut the check screen to the ≈ 80-word budget while preserving the
   test-pinned honesty strings ("synthetic Philippine data", "not proof of
   real-world accuracy", privacy lines) — where trimming conflicts with a
   pinned string, update the pin deliberately in the same PR with the
   reason recorded (Hallmark-style, on the record).
2. Mirror all new copy in the Taglish dictionary; verify Taglish line
   lengths in the new condensed-display hierarchy at 360px.

### Phase 5 — Gates and re-review (agent + human)

1. Full stack: pytest (including the new floor tests), `npm run
   test:modules`, browser smoke, `make doctor`, refresh `docs/images/`.
2. Keyboard-only + screen-reader spot pass on the new verdict/meter/
   disclosure components; contrast validation of both colorways (scripted
   oklch→WCAG check in the floor tests).
3. **Comprehension re-review** per `docs/HUMAN_REVIEW.md` — the redesign
   changes verdict presentation, which is exactly what the comprehension
   gates cover; no release of the redesign past a local pilot until the
   provisional criteria are re-run on the new copy.

## 5. Decision points for the owner

| Decision | Options | Default if unanswered |
|---|---|---|
| D-UI-1 Material | Editorial (recommended) / Console / custom brief | Editorial |
| D-UI-2 Self-hosted fonts | Ship ~120 KB woff2 (recommended) / system-stack adaptation | Ship fonts |
| D-UI-3 Verdict emoji | Remove entirely (recommended, Floor) / keep in batch table only | Remove |

## 6. Success criteria

- All new floor tests pass in CI; zero tells on the check screen by the
  audit table in §2.
- The check job (paste → verdict → next step) completes without scrolling
  at 1280×800 and 360×800.
- Both colorways ≥ WCAG AA; keyboard-only walkthrough unchanged; browser
  smoke + module tests green.
- Comprehension re-review: no participant reads a low score as a guarantee
  (per HUMAN_REVIEW criteria).
- A "made, not generated" review: no gradient, no emoji, no eyebrow caps,
  no uniform card grid, one material voice across light/dark and both
  languages.

## 7. Risks

- **Semantic dilution**: an intentionally quiet palette must not soften the
  verdict. Mitigation: verdict is always words + weight + rule color, tested
  to remain the highest-contrast element in the result.
- **Copy regression**: trimming words near pinned honesty strings. Mitigation:
  contract tests fail the build; any pin change ships with its justification.
- **Taglish typography**: condensed display at `wdth 75` may crowd longer
  Filipino words. Mitigation: 360px smoke assertions + native-speaker review.
- **Font payload**: ~120 KB woff2 against a lean shell. Mitigation: subset,
  `font-display: swap`, shell cache makes it a one-time cost.
