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
- **Accessibility (locked):** wrap the control in a `<fieldset>` with a visually-hidden `<legend>` (or `aria-label="Projection source"`), and give the pills a **visible keyboard focus** indicator (`:focus-visible` outline) — radios are keyboard-navigable, focus must show.
- **Mobile (locked):** the segmented control wraps cleanly on narrow screens (the config-bar already stacks to a column on mobile; the control stays full-width and legible, no overflow).

## 2. Provenance caption

A one-line caption rendered directly under the config-bar, shown **only when `source=valucast` is active**. Exact text (locked):

> **ValuCast H+P** — full-season projections: hitters use Savant xBA/xSLG de-noising; pitchers are fully in-house. Steamer remains the default external benchmark. **[How ValuCast works →]**

This is the honesty surface: it does **not** imply the hitter inputs are our own (they use Savant's expected stats), and it names Steamer as the default benchmark. The **"How ValuCast works →"** link points to the methodology page (§7).

## 3. Scope

Non-dynasty modes only (categories / roto / points) — the control and caption live in the existing non-dynasty config-bar branch. **Dynasty and Prospects** use the DD feed (source-agnostic): no toggle, no caption there. Scope is enforced by template placement (the control sits inside the non-dynasty `{% else %}` block).

## 4. Missing-team rendering

Blank teams (~26%, the source ceiling from `current.json`) render as **`—` in the HTML UI only**. Exports (CSV) and the underlying data keep the team **blank** — the dash is a display affordance, never written into data/exports. (Implemented at the table-template render site, not in the run or the export path.)

## 5. Internal methodology doc (`docs/valucast-methodology.md`)

The canonical engineering reference — consolidates what's currently scattered across specs/plans/memory into one source of truth. Sections:
- **The rung program** — hitting (Marcel foundation → reliability-weighting [TIE] → Statcast input de-noising [WIN]) and pitching (role-routed Marcel, per-batter-faced, continuous SP-probability [WIN]).
- **Validation discipline** — immutable historical backbone, leakage-safe rolling-origin backtest, beat-the-baseline gates (persistence → classic), the carryover guard, and the go/no-go gating that killed Rung 4 and the own-xBA Phase A.
- **Honesty rules** — what's ours vs borrowed: pitchers fully in-house; hitters consume **Savant** xBA/xSLG (the own-xBA grid was a measured **SHORTFALL** — corr 0.87, sprint speed needed); Steamer is the external benchmark/default.
- **Verdict ledger** — the per-rung results table (hitting 0.979 rate-stat MAE ratio; pitching 0.821 skill MAE ratio; Rung 2 / Rung 4 / own-xBA negatives).
- **The workflow** — brainstorm → spec → plan → execute → held-out verdict, recorded honestly either way.

This is internal (repo `docs/`), not linked from the app. It's the source the user page distills from.

## 6. User-facing methodology page (`/methodology`)

A read-only route + template, distilled from §5 for a league audience. Sections: *What ValuCast is* · *How hitters are projected* (incl. the honest Savant note) · *How pitchers are projected (in-house)* · *How we validate* (held-out, beat-the-benchmark) · *What's ours vs borrowed* (the honesty table) · *Track record* (the verdicts in plain terms). Reachable from the provenance caption's "How ValuCast works →" link (and acceptable to also add a footer/nav link). No data/auth; static render of the methodology content.

## Non-Goals

- Any projection/data/run change (pure presentation + docs).
- A team-coverage improvement (the ~26% blank is the accepted source ceiling; a future pull could fill it).
- Source toggle in Dynasty/Prospects modes.
- Re-styling the broader page; only the source control + caption + the team-cell dash.

## Success criteria

1. **Segmented control:** the source control renders as two pills (not a `<select>`); the selected pill reflects the active source; selecting either re-renders that board (stickiness intact — existing source tests stay green).
2. **Equal weight:** Steamer-selected and ValuCast-selected use the *same* active styling (assert both states produce the same active class/markup, no ValuCast-only badge/color).
3. **Accessibility:** the control has `aria-label="Projection source"` (or fieldset/legend) and a `:focus-visible` style; assert the aria-label/fieldset is present in the markup.
4. **Caption gating:** the provenance caption is present for `source=valucast`, and **absent** for Steamer (default), Dynasty, and Prospects.
5. **Team dash:** the rankings HTML shows `—` for a blank-team player; `/export?source=valucast` CSV keeps that team blank (not `—`).
6. **Methodology page:** `/methodology` returns 200 and contains the key honest statements (pitchers in-house; hitters use Savant xBA/xSLG; Steamer benchmark; own-xBA shortfall noted). The caption's "How ValuCast works →" link points to it.
7. **Internal doc:** `docs/valucast-methodology.md` exists with the rung program, validation discipline, honesty rules, and verdict ledger.
8. **No regressions:** full suite green; the default board unchanged.

## Files touched

- `templates/index.html` — replace the source `<select>` with the segmented `fieldset`; add the gated provenance caption with the methodology link.
- `static/style.css` — `.source-seg` segmented-control styles (reusing mode-btn active treatment), `:focus-visible`, mobile wrap; light methodology-page styling.
- `templates/partials/rankings_table.html` (or wherever the team cell renders) — `team or '—'` in HTML only.
- `templates/methodology.html` — the user-facing methodology page.
- `app.py` — `/methodology` read-only route.
- `docs/valucast-methodology.md` — the canonical internal methodology doc.
- `tests/test_app_source.py` — selected-reflection (segmented control), caption-gating, equal-weight, aria-label, team-dash-vs-blank-export, and `/methodology` route + content tests.
