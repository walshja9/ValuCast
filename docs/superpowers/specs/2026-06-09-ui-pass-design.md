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

**Type scale.** Establish a hard floor: any text carrying **meaningful content** (column
cells, badges, captions, control labels) is **≥ 0.8rem (~13px)** — bump the current
`0.65rem`/`0.7rem`/`0.75rem` content uses to the **0.8–0.85rem** band (amend-6: the floor is
0.8rem, not 0.78rem). Purely decorative micro-labels with no content may stay smaller.
Strengthen secondary-text contrast (`--c-muted` darker than `#6b7280`) to clear WCAG AA on
white. No layout/redesign — tokenize + legibility only.

## 2. Tab split (item 4) — treatment A (approved)

Primary tabs become **`Redraft | Dynasty | Prospects`** (horizon). The redraft scoring
format becomes a **secondary segmented pill row** (`H2H Categories | Roto | Points`) shown
on its own line **directly under the tabs, only when Redraft is active**. Dynasty and
Prospects show no scoring row.

**Tabs are navigation, not part of the `mode` radio group (amend-1).** The horizon tabs are
**links/buttons** that navigate to a new board; the scoring options remain `mode` **radios**
inside the form. They are different control types and must not share a radio group (a
horizon and a scoring format are not mutually-exclusive peers).
- Primary tabs render as `<a href>` (styled as tabs): Redraft → `/` (i.e. `mode=categories`),
  Dynasty → `/?mode=dd_dynasty`, Prospects → `/?mode=prospects`. The active tab is derived
  from `mode` (Redraft active when `mode ∈ {categories, roto, points}`).
- Scoring pills stay `name="mode"` radios (`categories`/`roto`/`points`) in the form, so
  changing scoring re-renders via the existing htmx `change` trigger and stays sticky.
- **Returning to Redraft (amend-1):** the Redraft tab defaults to **Categories**
  (`mode=categories`) — stateless and deterministic. Restoring the last-used scoring mode
  would require client-side memory (localStorage) and is an explicit **non-goal** for this
  pass; document the default behavior in the UI.

**htmx behavior for horizon vs in-horizon changes (amend-2).** `/rankings` replaces only
`#rankings-container` (+ existing OOB fragments), so a horizon change driven through the
form would leave the tabs, scoring row, and toolbar stale. Therefore:
- **Horizon change = full navigation** (the tab is a real `<a href>` → full page load),
  which re-renders tabs, scoring row, and the horizon-appropriate toolbar from scratch. No
  staleness.
- **In-horizon changes** (scoring, source, pool, position, search, view toggle) stay htmx
  partial swaps of `#rankings-container` + the established OOB fragments (caption, footer).
  These never change the tab/toolbar structure, so no staleness.
- Accessibility folds in from §4: the scoring/pool pills are focusable radio groups; the
  horizon tabs are focusable links with `aria-current="page"` on the active tab.

## 3. Sticky toolbar (item 5) — treatment A (approved)

Merge today's separate config-bar and filter-bar into **one toolbar** pinned (`position:
sticky`) under the tab/scoring header and above the already-sticky table header. Single row
on desktop, wraps on mobile. **"Customize"** (advanced category editing / `setup-panel`)
stays available behind its existing toggle button so the default toolbar stays uncluttered.

**Per-horizon toolbar contents (amend-8).** Consolidation must not drop horizon-specific
controls. Define the toolbar per horizon:
- **Redraft (categories / roto / points):** config summary · **Source (`Steamer |
  ValuCast`) — all three redraft modes, including Points (amend-4)** · pool (`All / Hitters
  / Pitchers`) · position select · search · **`Projections | Category value` toggle —
  categories & roto ONLY (amend-4)**, hidden in Points · Export · Customize button.
- **Dynasty:** the locked dynasty summary · pool (`All / MLB / Hitters / Pitchers /
  Prospects` — the dynasty-specific pool set) · position select · search · Export. No
  Source, no view toggle (DD feed is source-agnostic).
- **Prospects:** the prospect summary · position select · search · Export. No pool, no
  Source, no view toggle (matches today's prospects filter bar).

Source selection is preserved across **all** redraft modes (it already works in Points);
only the Projections/Category-value toggle is categories/roto-only.

**Sticky offset — dynamic, measured (amend-5).** The toolbar wraps on mobile, so its height
varies; a fixed `top` for the table header would overlap or gap. Use a **measured offset**:
publish the toolbar's height to a CSS custom property (`--toolbar-h`) via a small
`ResizeObserver` on the toolbar, and set the table header `top: var(--toolbar-h)` (toolbar
`top: 0`). Wrap toolbar + table in a positioning container so the toolbar pins first.
**Required verification:** scroll behavior with no overlap/gap at desktop **and** mobile
widths (including the wrapped multi-row toolbar state).

## 4. Accessibility pass (item 6)

Complete the pattern the source toggle established:
- **Radios** (mode/primary-tabs, scoring, pool) — replace `display:none` (unfocusable)
  with the clip-hidden-but-focusable technique (`position:absolute; width:1px; height:1px;
  clip-path:inset(50%)`) + a `:focus-visible` ring on the adjacent `<span>`. Wrap each
  group in a `<fieldset>` with a visually-hidden `<legend>` or `aria-label`.
- **Sort headers (amend-3)** — keep `aria-sort` on the `<th>` (reflecting state), but put a
  real `<button>` *inside* each sortable `<th>` that calls `sortTable`. Do not make the
  `<th>` itself the button. Buttons are focusable and Enter/Space-operable for free.
- **Compare `+`** — a real `<button>` with an `aria-label` ("Add <player> to compare");
  keep `event.stopPropagation()`.
- **Player rows (amend-3)** — do **NOT** put `role="button"`/`tabindex` on the `<tr>`: rows
  contain nested interactive controls (the compare button), so a button row is invalid
  ARIA. Instead add a **real detail-toggle `<button>` in the player-name cell**
  (`aria-expanded`, `aria-label` "Show <player> details") that calls `toggleDetail`. The
  whole-row click stays as a **mouse convenience only** (no row-level ARIA/keyboard role).
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
- **Validation details** — the evaluated statistics, **seasons used, eligibility floors,
  sample sizes, per-stat MAE ratios, and correlation-win rates** (all sourced from the
  validation artifact below, not prose-typed), and **why W/SV/QS are reported separately**
  (low-confidence, opportunity-driven categories).

### Held-out scorecard (numbers now PUBLIC, with per-stat honesty — amend-7)
Replace the vague "Track record" prose with a compact scorecard plus the required caveats:
| Step | Held-out result |
|---|---|
| Pitching vs persistence | **0.821 skill-stat MAE ratio (~17.9% lower error)** — covers `IP, K, ERA, WHIP, K/9, BB/9`. **IP and K were roughly neutral; the win was driven by the rate stats (ERA/WHIP/K9/BB9).** |
| Hitting vs classic Marcel | **0.979 aggregate rate-stat MAE ratio (~2.1% lower error)** — the **4–6% gains are concentrated in AVG/OBP/SLG/OPS**; counting stats roughly neutral. |
| Reliability-weighted regression | tie — not shipped |
| In-house expected-stat model (own xBA) | shortfall — not shipped (hitters use Savant xBA/xSLG) |

The page must also state the **seasons evaluated, eligibility floors (min PA / BF), sample
sizes, and correlation-win rates** — rendered from the artifact, never hand-typed.

### Validation artifact + drift-lock (amend-7)
Public numbers and the displayed model parameters must not silently diverge from the harness
or the source of truth.
- **Commit a structured artifact** `data/validation/methodology_scorecard.json` holding the
  scorecard rows, per-stat MAE ratios, seasons, eligibility floors, sample sizes, and
  correlation-win rates. It is **produced by the rolling-origin validation harness** (the
  source of truth) and committed; the methodology page **renders from it** (no numbers
  typed into the template).
- **Drift-lock tests:** (a) the methodology page renders exactly the artifact's numbers
  (page ↔ artifact lock); (b) the model-parameter values shown in "Model equations" match
  `marcel_params.py` / `pitcher_params.py` (page ↔ source lock) — assert against the params
  modules so a constant change fails the test until the page is updated.
- The exact season/eligibility/sample/win-rate values are filled **from the harness output
  at implementation time**, not invented in this spec.

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

1. **Tabs:** primary tabs are `Redraft | Dynasty | Prospects` **links** (horizon nav, full
   navigation, `aria-current` on active); the scoring pill row (`H2H | Roto | Points`) are
   `mode` radios shown only under Redraft and re-render via htmx; Redraft defaults to
   Categories. Mobile shows three primary tabs, not five crowded ones.
2. **Sticky toolbar:** config + filters are one bar pinned under the tabs while the table
   scrolls, **with no overlap/gap via the measured `--toolbar-h` offset**, verified at
   desktop and mobile (including the wrapped state); Customize is behind its button; the
   toolbar carries the correct horizon-specific controls (Redraft/Dynasty/Prospects sets).
3. **Accessibility:** keyboard-only — tabs (links), scoring/pool radios, position, search,
   per-`<th>` sort buttons, compare button, the name-cell detail button, view toggle, and a
   focusable export are all reachable with a visible focus ring and Enter/Space-operable
   (+ arrows in radio groups). No `display:none` on focusable radios; **no `role="button"`
   on `<tr>`** (rows keep mouse-only click).
4. **Tokens + type:** a `:root` token block exists and the high-frequency colors use it;
   no meaningful content text below **0.8rem**; secondary text meets AA contrast.
5. **Methodology:** page shows the back link, top "At a glance" table, the plain overview,
   the three expandable Under-the-hood/Equations/Validation sections (with a worked
   example), and the public held-out scorecard with per-stat caveats — **all numbers
   rendered from `methodology_scorecard.json`**, plus seasons/eligibility/sample/win-rates.
6. **Drift-lock:** tests assert the page's numbers equal the committed validation artifact,
   and the displayed model parameters equal `marcel_params.py`/`pitcher_params.py`; changing
   a constant or artifact value fails a test until the page is reconciled.
7. **Honesty reframe:** the page states ValuCast hasn't yet beaten Steamer/ZiPS (benchmark
   pending), and "comparison board; fair historical benchmark pending" replaces "external
   benchmark" on the page, the caption, and the footer.
8. **No regressions:** full suite green; default board values/columns unchanged; **source
   selection still works in all redraft modes incl. Points**; display toggle still
   categories/roto-only; filters/export still work.

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
- `app.py` — a `horizon` context helper for the active-tab derivation + per-horizon toolbar
  selection; `/methodology` reads `methodology_scorecard.json`; routing stays on `mode`.
- `data/validation/methodology_scorecard.json` — **NEW**, committed; produced by the
  validation harness; holds scorecard rows + per-stat MAE ratios + seasons + eligibility
  floors + sample sizes + correlation-win rates. The methodology page renders from it.
- `projections/backtest/` (harness) — emit/refresh the scorecard artifact (source of truth);
  the artifact is committed, the harness is the producer.
- `tests/` — tab-split rendering (links vs radios, Redraft-defaults-to-Categories,
  source-in-Points), sticky-toolbar presence + per-horizon contents, a11y markup assertions
  (focusable radios, per-`<th>` sort buttons + `aria-sort`, name-cell detail button, no
  `role=button` on `<tr>`, export href), methodology content (scorecard rendered from
  artifact, expandable sections, reframed Steamer wording), **drift-lock** (page↔artifact
  and page↔params), caption/footer reword.
