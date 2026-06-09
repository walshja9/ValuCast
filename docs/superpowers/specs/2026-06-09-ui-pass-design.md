# ValuCast UI Pass — Design (review items 4–8)

**Date:** 2026-06-09
**Status:** Draft / pending review
**Source:** Post-launch UX review of valucast.app. One combined pass over the rankings
surface, sequenced foundation-first. Correctness is already shipped; this is presentation,
information architecture, accessibility, and a substantive methodology-page upgrade.

## Goal

Make the rankings surface clearer and more usable — split horizon from scoring, keep
controls in reach while scrolling, finish the accessibility pattern, tokenize + lift
legibility — and turn the methodology page into a credible, self-substantiating
explanation of how the model works and how well it validates.

## Sequence (one spec, staged execution)

1. Design tokens + type scale (foundation everything else uses)
2. Tab split (Redraft / Dynasty / Prospects + scoring sub-control)
3. Sticky toolbar
4. Accessibility pass
5. Methodology page (layout + model explainer + validation scorecard + honesty reframe)

## 1. Design tokens + type scale

**Tokens.** Add a `:root` block in `static/style.css` for the repeated values, then replace
hardcoded literals with `var(...)`. Minimum set (names illustrative):
- Color: `--c-blue #2563eb`, `--c-blue-strong #1d4ed8`, `--c-navy #1a1a2e`,
  `--c-text #1e293b`, `--c-muted` (a darker slate than today's `#6b7280` for contrast),
  `--c-border #e5e7eb`, `--c-border-strong #d1d5db`, `--c-dynasty #7c3aed`,
  `--c-prospect #059669`, `--c-pos #059669`, `--c-neg #dc2626`.
- Space: `--space-1 .25rem` … `--space-4 1rem`. Radius: `--radius-sm 6px`, `--radius 8px`,
  `--radius-lg 10px`.
- Replace the highest-frequency literals (the 24× `#2563eb`, 17× `#6b7280`, 15× `#d1d5db`,
  8× `#e5e7eb`) with tokens; lower-frequency one-offs may stay literal if tokenizing adds
  no clarity (YAGNI). Token coverage is a means, not a metric to maximize.

**Type scale.** Establish a floor: control/table text no smaller than **0.8rem (~13px)**.
Bump the current `0.65rem`/`0.7rem`/`0.75rem` uses that carry real content (column cells,
badges, captions) up to the 0.78–0.85rem band; purely decorative micro-labels may stay
small. Strengthen secondary-text contrast (`--c-muted` darker than `#6b7280`) to clear
WCAG AA on white. No layout/redesign — tokenize + legibility only.

## 2. Tab split (item 4) — treatment A (approved)

Primary tabs become **`Redraft | Dynasty | Prospects`** (horizon). The redraft scoring
format becomes a **secondary segmented pill row** (`H2H Categories | Roto | Points`) shown
on its own line **directly under the tabs, only when Redraft is active**. Dynasty and
Prospects show no scoring row.

- `mode` remains the single source of truth and the URL param. Map it as horizon × scoring:
  the three redraft scoring modes (`categories`, `roto`, `points`) render under the
  **Redraft** primary tab (Redraft is "active" when `mode` is one of those); `dd_dynasty`
  and `prospects` are the other two primary tabs. The primary tab and the scoring row are
  two coordinated controls that both write `mode` via the existing htmx form (`change`
  trigger), so stickiness/serialization are unchanged.
- Accessibility folds in from §4: both the primary tabs and the scoring pills are
  focusable radio groups.

## 3. Sticky toolbar (item 5) — treatment A (approved)

Merge today's separate config-bar and filter-bar into **one toolbar** pinned (`position:
sticky`) under the tab/scoring header and above the already-sticky table header. Single row
on desktop, wraps on mobile. Contents left→right: config summary · pool (`All/Hitters/
Pitchers`) · position select · search · `Projections | Category value` toggle · Export.
Source pills sit in the toolbar too (categories/roto only, as today). **"Customize"**
(advanced category editing / `setup-panel`) stays available behind its existing toggle
button so the default toolbar stays uncluttered.

- The toolbar and the table header must not overlap when both are sticky: stack their
  sticky offsets (toolbar `top: 0`; table header `top: <toolbar height>`), or wrap the
  toolbar + table in a container so the toolbar pins first. Verify no z-index/overlap on
  scroll at desktop and mobile widths.

## 4. Accessibility pass (item 6)

Complete the pattern the source toggle established:
- **Radios** (mode/primary-tabs, scoring, pool) — replace `display:none` (unfocusable)
  with the clip-hidden-but-focusable technique (`position:absolute; width:1px; height:1px;
  clip-path:inset(50%)`) + a `:focus-visible` ring on the adjacent `<span>`. Wrap each
  group in a `<fieldset>` with a visually-hidden `<legend>` or `aria-label`.
- **Sort headers** — make each `<th>` sortable control keyboard-operable: `tabindex="0"`,
  `role="button"`, `aria-sort` reflecting state, and an Enter/Space handler calling the
  existing `sortTable`.
- **Compare `+`** — a real `<button>` (or `role="button"` + `tabindex` + key handler) with
  an `aria-label` ("Add <player> to compare"); keep `event.stopPropagation()`.
- **Player rows** — the row's expand action is keyboard-reachable: add `tabindex="0"` +
  `role="button"` + `aria-expanded` + Enter/Space → `toggleDetail`. (Keep the row click.)
- **Export** — a focusable control (real `<a href>` to `/export?…` built from the form, or
  a `<button>`), not a bare `<a onclick>` with no href.
- Verify a keyboard-only pass: Tab reaches every control with a visible focus ring; Enter/
  Space activate; arrow keys move within radio groups.

## 5. Methodology page (item 8) — layout + model explainer + validation + honesty reframe

### Layout (approved mockup)
- A `← Back to rankings` link by the title; the `As of June 2026 · ValuCast H+P v1` marker
  beneath.
- **"At a glance"** provenance table moved to the top (Component | Provenance).
- Narrower reading column (~680px) and ~15px body text.

### Model explainer with progressive disclosure
Keep the existing plain-language overview, then add three `<details>`/expandable sections:
- **Under the hood** — prose naming the methods (Marcel-style weighting, regression to the
  mean, age adjustment, Statcast input de-noising for hitters, per-batter-faced rates with
  a continuous starter/reliever role blend for pitchers).
- **Model equations** — the central formulas with one worked example:
  - season weighting of a per-opportunity rate (weights `(5,4,3)`),
  - regression to league mean: `proj = (observed·N + league·n_reg) / (N + n_reg)`,
  - age adjustment,
  - hitter Statcast de-noising (blend actual toward Savant xBA/xSLG, mix-preserving
    redistribution into 1B/2B/3B/HR),
  - pitcher continuous role blend (role-shift `f[c]^(h_sp − p_sp)` with `p_sp` the
    starter probability),
  - **one worked example** carrying real-ish numbers through weighting → regression →
    age → output.
  - **Constants are sourced from `projections/models/marcel_params.py` and
    `pitcher_params.py` at authoring time** (do not hardcode drifting values in prose;
    cite the params as the source of truth).
- **Validation details** — evaluated statistics, seasons used, eligibility rules, sample
  sizes, the correlation/MAE results, and **why W/SV/QS are reported separately** (low-
  confidence, opportunity-driven categories).

### Held-out scorecard (numbers now PUBLIC)
Replace the vague "Track record" prose with a compact scorecard:
| Step | Held-out result |
|---|---|
| Pitching vs persistence | **0.821 skill-stat MAE ratio (~17.9% lower error)** |
| Hitting vs classic Marcel | **0.979 rate-stat MAE ratio (~2.1% lower error)** |
| Reliability-weighted regression | tie — not shipped |
| In-house expected-stat model (own xBA) | shortfall — not shipped |

### Honesty reframe (ripples beyond the page)
- State plainly: **ValuCast has not yet proven it beats Steamer/ZiPS** — we lack matching
  archived preseason projections for a fair, apples-to-apples historical backtest. Our
  validation is vs internal baselines (persistence, classic Marcel), not vs those systems.
- **Rename "external benchmark" → "external comparison board; fair historical benchmark
  pending"** everywhere it appears: the methodology page, the **source caption**
  (`_source_caption.html`), and the **footer** (`_footer_provenance.html`). The caption/
  footer currently say Steamer "remains the default external benchmark" / similar — update
  to the comparison-board wording.

### Stays internal
Exhaustive implementation parameters and the full per-experiment ledger remain in
`docs/valucast-methodology.md`. The public page carries enough math + validation to
substantiate the claims without becoming documentation soup.

## Non-Goals

- Any projection/valuation/data change (pure presentation + docs).
- Redesigning the table columns/rows beyond tokens + type scale.
- Dynasty/Prospects table internals.
- A real ValuCast-vs-Steamer backtest (blocked on archived preseason projections; the page
  states this honestly instead).

## Success criteria

1. **Tabs:** primary tabs are `Redraft | Dynasty | Prospects`; the scoring pill row
   (`H2H | Roto | Points`) shows only under Redraft; selecting any still drives `mode` and
   re-renders. Mobile shows three primary tabs, not five crowded ones.
2. **Sticky toolbar:** config + filters are one bar that stays pinned under the tabs while
   the table scrolls, without overlapping the table header; wraps cleanly on mobile;
   Customize is behind its button.
3. **Accessibility:** keyboard-only — every control (tabs, scoring, pool, position, search,
   sort headers, compare, rows, view toggle, export) is reachable with a visible focus
   ring and operable via Enter/Space (+ arrows in radio groups); no `display:none` on
   focusable radios.
4. **Tokens + type:** a `:root` token block exists and the high-frequency colors use it;
   no content text below ~0.8rem; secondary text meets AA contrast.
5. **Methodology:** page shows the back link, top "At a glance" table, the plain overview,
   the three expandable Under-the-hood/Equations/Validation sections (with a worked
   example), and the public held-out scorecard with the four results.
6. **Honesty reframe:** the page states ValuCast hasn't yet beaten Steamer/ZiPS (benchmark
   pending), and "comparison board; fair historical benchmark pending" replaces "external
   benchmark" on the page, the caption, and the footer.
7. **No regressions:** full suite green; default board values/columns unchanged; source/
   display toggles, filters, export still work.

## Files touched (anticipated)

- `static/style.css` — `:root` tokens, type-scale bumps, `.source-seg` reuse for new
  pill groups, sticky-toolbar layout, methodology styles (at-a-glance, ledger, `details`).
- `templates/index.html` — primary tabs + scoring row, consolidated sticky toolbar, a11y
  markup on tabs/pool/sort/compare/rows/export.
- `templates/partials/rankings_table.html` — sort-header + compare + row a11y attributes.
- `templates/partials/_source_caption.html`, `templates/partials/_footer_provenance.html`
  — Steamer "comparison board; benchmark pending" reword.
- `templates/methodology.html` — layout, model explainer (progressive disclosure),
  scorecard, honesty reframe.
- `app.py` — only if the tab/scoring split needs context flags (e.g. a `horizon` helper);
  routing stays on `mode`.
- `tests/` — tab-split rendering, sticky-toolbar presence, a11y markup assertions
  (focusable radios, aria-sort, export href), methodology content (scorecard numbers,
  expandable sections, reframed Steamer wording), caption/footer reword.
