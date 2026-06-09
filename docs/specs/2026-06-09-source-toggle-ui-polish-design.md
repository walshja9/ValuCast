# Source Toggle UI Polish — Design

**Date:** 2026-06-09
**Status:** Draft / pending review
**Builds on:** the ValuCast H+P source ship (`?source=valucast`, shipped 2026-06-05). This polishes the plain `<select name="source">` into a proper segmented control + honest provenance caption.

## Goal

Replace the plain source dropdown with a segmented control matching the app's existing `.mode-btn` idiom, and surface honest provenance when ValuCast is active — so users understand they're viewing our projection (hitters Savant-de-noised, pitchers in-house) vs the Steamer benchmark. Pure front-end polish; no projection/data changes.

## 1. The control (segmented radios)

Replace the `<select name="source">` in the non-dynasty config-bar with a **segmented control of two radio pills** — `Steamer` and `ValuCast H+P` — using `name="source"` (same radio pattern as the mode selector, so the form serializes it and stickiness is unchanged; the form's `change` trigger re-renders).

- **Equal visual weight (locked):** the *selected* pill is styled identically regardless of which source it is — neither Steamer nor ValuCast looks "preferred." Reuse the mode selector's active treatment (the established blue `#2563eb`) for whichever is checked; the unselected pill is the neutral default. No special color/badge for ValuCast.
- **Accessibility (locked):** wrap the control in a `<fieldset>` with a visually-hidden `<legend>` (or `aria-label="Projection source"`), and give the pills a **visible keyboard focus** indicator (`:focus-visible` outline) — radios are keyboard-navigable, focus must show.
- **Mobile (locked):** the segmented control wraps cleanly on narrow screens (the config-bar already stacks to a column on mobile; the control stays full-width and legible, no overflow).

## 2. Provenance caption

A one-line caption rendered directly under the config-bar, shown **only when `source=valucast` is active**. Exact text (locked):

> **ValuCast H+P** — full-season projections: hitters use Savant xBA/xSLG de-noising; pitchers are fully in-house. Steamer remains the default external benchmark.

This is the honesty surface: it does **not** imply the hitter inputs are our own (they use Savant's expected stats), and it names Steamer as the default benchmark.

## 3. Scope

Non-dynasty modes only (categories / roto / points) — the control and caption live in the existing non-dynasty config-bar branch. **Dynasty and Prospects** use the DD feed (source-agnostic): no toggle, no caption there. Scope is enforced by template placement (the control sits inside the non-dynasty `{% else %}` block).

## 4. Missing-team rendering

Blank teams (~26%, the source ceiling from `current.json`) render as **`—` in the HTML UI only**. Exports (CSV) and the underlying data keep the team **blank** — the dash is a display affordance, never written into data/exports. (Implemented at the table-template render site, not in the run or the export path.)

## Non-Goals

- Any projection/data/run change (pure presentation).
- A team-coverage improvement (the ~26% blank is the accepted source ceiling; a future pull could fill it).
- Source toggle in Dynasty/Prospects modes.
- Re-styling the broader page; only the source control + caption + the team-cell dash.

## Success criteria

1. **Segmented control:** the source control renders as two pills (not a `<select>`); the selected pill reflects the active source; selecting either re-renders that board (stickiness intact — existing source tests stay green).
2. **Equal weight:** Steamer-selected and ValuCast-selected use the *same* active styling (assert both states produce the same active class/markup, no ValuCast-only badge/color).
3. **Accessibility:** the control has `aria-label="Projection source"` (or fieldset/legend) and a `:focus-visible` style; assert the aria-label/fieldset is present in the markup.
4. **Caption gating:** the provenance caption is present for `source=valucast`, and **absent** for Steamer (default), Dynasty, and Prospects.
5. **Team dash:** the rankings HTML shows `—` for a blank-team player; `/export?source=valucast` CSV keeps that team blank (not `—`).
6. **No regressions:** full suite green; the default board unchanged.

## Files touched

- `templates/index.html` — replace the source `<select>` with the segmented `fieldset`; add the gated provenance caption.
- `static/style.css` — `.source-seg` segmented-control styles (reusing mode-btn active treatment), `:focus-visible`, mobile wrap.
- `templates/partials/rankings_table.html` (or wherever the team cell renders) — `team or '—'` in HTML only.
- `tests/test_app_source.py` — update selected-reflection assertion to the segmented control; add caption-gating (valucast yes; steamer/dynasty/prospects no), equal-weight, aria-label, and team-dash-vs-blank-export tests.
