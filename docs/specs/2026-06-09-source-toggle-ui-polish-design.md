# Source Toggle UI Polish + ValuCast Methodology (Doc + Page) — Design

**Date:** 2026-06-09
**Status:** Draft / pending review
**Builds on:** the ValuCast H+P source ship (`?source=valucast`, shipped 2026-06-05). This polishes the plain `<select name="source">` into a proper segmented control + honest provenance caption, and documents the in-house process behind ValuCast — both as a canonical internal reference and a distilled user-facing page.

## Goal

Two tied deliverables:
1. **UI polish** — replace the plain source dropdown with a segmented control matching the app's `.mode-btn` idiom + an honest provenance caption when ValuCast is active.
2. **Methodology documentation** — a canonical **internal** `docs/valucast-methodology.md` (the rung program, validation discipline, honesty rules, verdicts) and a distilled **user-facing** "How ValuCast works" page linked from the caption. The caption is the teaser; the page is the credibility; the internal doc is the source of truth for both.

The UI is pure front-end; the methodology page is a read-only route. No projection/data changes.

## 1. The control (segmented radios)

Replace the `<select name="source">` in the non-dynasty config-bar with a **segmented control of two radio pills** — `Steamer` and `ValuCast H+P` — using `name="source"` (same radio pattern as the mode selector, so the form serializes it and stickiness is unchanged; the form's `change` trigger re-renders).

- **Equal visual weight (locked):** the *selected* pill is styled identically regardless of which source it is — neither Steamer nor ValuCast looks "preferred." Reuse the mode selector's active treatment (the established blue `#2563eb`) for whichever is checked; the unselected pill is the neutral default. No special color/badge for ValuCast.
- **Accessibility (locked):** wrap the control in a `<fieldset>` with a visually-hidden `<legend>` (or `aria-label="Projection source"`). **Do NOT copy the mode selector's `display:none` on the radios** — `display:none` removes them from the tab order (unfocusable). Use a **visually-hidden-but-focusable** technique (the clip/`sr-only` pattern: `position:absolute; width:1px; height:1px; clip-path:inset(50%)` — NOT `display:none`), and render a visible focus ring on the label via `input:focus-visible + span`. Keyboard users must be able to tab to and see the focused pill.
- **Mobile (locked):** the segmented control wraps cleanly on narrow screens (the config-bar already stacks to a column on mobile; the control stays full-width and legible, no overflow).

## 2. Provenance caption

A one-line caption under the config-bar, shown **only when `source=valucast` is active**. Exact text (locked, refined):

> **ValuCast H+P** — full-season projections: hitters use Savant xBA/xSLG de-noising; the **pitching model is fully in-house**. Steamer remains the default external benchmark. **[How ValuCast works →]**

(Wording note: "the pitching model is fully in-house" — *model*, not raw data, so it doesn't imply proprietary Statcast.) The **"How ValuCast works →"** link points to the methodology page (§6).

**HTMX freshness (P1 — required):** the caption lives **outside** `#rankings-container`, but `/rankings` only re-renders that container — so a Jinja-only caption would go **stale** when the user switches the source radio (table updates, caption doesn't). Fix with an **out-of-band swap**: a stable placeholder `<div id="source-caption">` sits in the page; `partials/rankings_response.html` emits `<div id="source-caption" hx-swap-oob="true">…</div>` whose contents are the caption when `source=valucast` and **empty** otherwise. Every `/rankings` response (any filter or source change) thus refreshes the caption out-of-band — no full reload. This is server-rendered, so it's directly testable (the response carries the right caption per source).

## 3. Scope

Non-dynasty modes only (categories / roto / points) — the control and caption live in the existing non-dynasty config-bar branch. **Dynasty and Prospects** use the DD feed (source-agnostic): no toggle, no caption there. Scope is enforced by template placement (the control sits inside the non-dynasty `{% else %}` block).

## 4. Missing-team rendering

Blank teams (~26%, the source ceiling from `current.json`) render as **`—` in the HTML UI only**. Exports (CSV) and the underlying data keep the team **blank** — the dash is a display affordance, never written into data/exports. (Implemented at the table-template render site, not in the run or the export path.)

## 4b. Source-aware footer (P1)

`base.html` currently always states redraft values use "actuals + Steamer ROS" — which **contradicts** the new honesty surface on the ValuCast board and reads wrong on `/methodology`. Make the footer provenance line **source/page-aware**:
- Default board (`source` steamer / absent): unchanged — "actuals + Steamer ROS".
- ValuCast board (`source=valucast`): "ValuCast H+P projection — hitters Savant-de-noised, pitching model in-house."
- `/methodology` and Dynasty/Prospects: a neutral line (or omit the redraft-provenance clause) so it doesn't assert Steamer on pages where it's false.

`base.html` reads `source` from context (default steamer); routes already pass it (or it defaults). Add `base.html` to scope.

## 5. Internal methodology doc (`docs/valucast-methodology.md`)

The canonical engineering reference — consolidates what's currently scattered across specs/plans/memory into one source of truth. Sections:
- **The rung program** — hitting (Marcel foundation → reliability-weighting [TIE] → Statcast input de-noising [WIN]) and pitching (role-routed Marcel, per-batter-faced, continuous SP-probability [WIN]).
- **Validation discipline** — immutable historical backbone, leakage-safe rolling-origin backtest, beat-the-baseline gates (persistence → classic), the carryover guard, and the go/no-go gating that killed Rung 4 and the own-xBA Phase A.
- **Honesty rules** — what's ours vs borrowed: pitchers fully in-house; hitters consume **Savant** xBA/xSLG (the own-xBA grid was a measured **SHORTFALL** — corr 0.87, sprint speed needed); Steamer is the external benchmark/default.
- **Verdict ledger** — the per-rung results table (hitting 0.979 rate-stat MAE ratio; pitching 0.821 skill MAE ratio; Rung 2 / Rung 4 / own-xBA negatives).
- **The workflow** — brainstorm → spec → plan → execute → held-out verdict, recorded honestly either way.

This is internal (repo `docs/`), not linked from the app. It's the source the user page distills from.

## 6. User-facing methodology page (`/methodology`)

A read-only route + template, distilled from §5 for a league audience. Reachable from the caption's "How ValuCast works →" link (and acceptable to also add a footer/nav link). No data/auth; static render. Sections:
- *What ValuCast is.*
- **The two boards, distinguished (P1 — required):** state plainly that the **default board** = current-season actuals + Steamer ROS; the **ValuCast board** = a prior-year-driven full-season projection. The live source toggle is useful for **eyeball comparison, but is NOT an apples-to-apples formal backtest** (different kinds of number) — our real validation is the held-out backtest, described below.
- *How hitters are projected* — Marcel-style, then **Statcast input de-noising** toward Savant xBA/xSLG. **Public own-xBA disclosure (P2 wording — exact):** "We tested an in-house expected-stats model, but it did not clear our validation bar, so hitters continue to use Savant xBA/xSLG as inputs." (Keep the internal `corr 0.87`/sprint-speed detail in §5 only.)
- *How pitchers are projected* — **"the pitching model is fully in-house"** (per-batter-faced, role-routed). *Model*, not proprietary raw data.
- *How we validate* — leakage-safe held-out backtest; beat-the-benchmark gates.
- *What's ours vs borrowed* — the honesty table (pitching model in-house; hitter inputs from Savant; Steamer the benchmark/default).
- *Track record* — the verdicts in plain terms (no raw correlation numbers).
- **Version marker (P2):** a footer line "As of June 2026 · ValuCast H+P v1" to bound the claims and reduce methodology drift. Mirror the same marker at the top of the internal §5 doc.

## Non-Goals

- Any projection/data/run change (pure presentation + docs).
- A team-coverage improvement (the ~26% blank is the accepted source ceiling; a future pull could fill it).
- Source toggle in Dynasty/Prospects modes.
- Re-styling the broader page; only the source control + caption + the team-cell dash.

## Success criteria

1. **Segmented control:** the source control renders as two pills (not a `<select>`); the selected pill reflects the active source; selecting either re-renders that board (stickiness intact — existing source tests stay green).
2. **Equal weight:** Steamer-selected and ValuCast-selected use the *same* active styling (assert both states produce the same active class/markup, no ValuCast-only badge/color).
3. **Accessibility:** the control has `aria-label="Projection source"` (or fieldset/legend), the radios are **focusable** (visually-hidden via clip, NOT `display:none`), and there's a `input:focus-visible + span` style; assert the aria-label/fieldset + the non-`display:none` hiding in the markup/CSS.
4. **Caption gating + HTMX freshness:** the `/rankings?source=valucast` response carries the provenance caption (via `hx-swap-oob` `#source-caption`); the `/rankings` (steamer) response's OOB caption is **empty** — so switching the source radio updates the caption without a reload. Caption absent in Dynasty/Prospects.
5. **Source-aware footer:** the footer provenance line says Steamer-ROS on the default board, the ValuCast line on `source=valucast`, and does not assert Steamer on `/methodology`.
6. **Team dash:** the rankings HTML shows `—` for a blank-team player; `/export?source=valucast` CSV keeps that team blank (not `—`).
7. **Methodology page:** `/methodology` returns 200 and contains the key honest statements (pitching model in-house; hitters use Savant xBA/xSLG; Steamer benchmark; own-xBA shortfall disclosed in the public wording) + the two-boards distinction + the "As of June 2026 · ValuCast H+P v1" marker. The caption's "How ValuCast works →" link points to it.
8. **Internal doc:** `docs/valucast-methodology.md` exists with the rung program, validation discipline, honesty rules, verdict ledger, and the v1/date marker.
9. **No regressions:** full suite green; the default board unchanged.

## Files touched

- `templates/index.html` — replace the source `<select>` with the segmented `fieldset`; add the gated provenance caption with the methodology link.
- `static/style.css` — `.source-seg` segmented-control styles (reusing mode-btn active treatment), `:focus-visible`, mobile wrap; light methodology-page styling.
- `templates/partials/rankings_table.html` (or wherever the team cell renders) — `team or '—'` in HTML only.
- `templates/partials/rankings_response.html` — OOB `#source-caption` fragment (gated by source).
- `templates/base.html` — source/page-aware footer provenance line; `#source-caption` placeholder if it lives in the layout.
- `templates/methodology.html` — the user-facing methodology page.
- `app.py` — `/methodology` read-only route.
- `docs/valucast-methodology.md` — the canonical internal methodology doc.
- `tests/test_app_source.py` — selected-reflection (segmented control), caption-gating, equal-weight, aria-label, team-dash-vs-blank-export, and `/methodology` route + content tests.
