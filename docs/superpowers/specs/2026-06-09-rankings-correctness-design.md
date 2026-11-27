# Rankings Correctness Trio — Design

**Date:** 2026-06-09
**Status:** Draft / pending review
**Source:** Post-launch review of the live site (valucast.app). Three correctness/trust
fixes, shipped before any cosmetic work. UI items from the same review (tab split, sticky
toolbar, full a11y pass, readability tokens, methodology scanability) are deferred to a
follow-up spec.

## 1. Filter-stable values, ranks, dollars, tiers (P1)

**Bug (verified):** `_build_context` applies pool/position/search filters and the top-200
truncation **before** computing `_compute_position_ranks`, `_compute_dollar_values`, and
`_compute_tiers`. The computations run on the survivors, so searching "Ohtani" hands one
player the league's entire 12×$200 = $2,400 auction budget, `DH1`, `T1`. Dynasty and
prospects modes share the pattern (`_compute_dynasty_dollars` / `_compute_dynasty_tiers`
run on filtered rows).

**Fix:** compute all display metadata once on the **full valued universe** — immediately
after `_merge_two_way_players(results)` (redraft) / on the full DD pool before filtering
(dynasty, prospects) — then apply filters and the top-200 limit for display only. The
metadata dicts are keyed by player id, so filtered rendering just looks up.

**Honest side-effect:** default-view dollar values currently distribute the budget over
only the top-200 slice; computing on the full universe shifts those numbers slightly.
They become correct and filter-invariant — the new numbers are the right ones.

**Tests (invariants):** for a fixed config, a player's `$`, position rank, and tier are
identical between the unfiltered board and any `?search=`, `?pool=`, `?position=` view,
in both redraft and dynasty/prospects modes. Plus a regression test: a single-player
search result does NOT get the full budget.

## 2. Order-insensitive category presets + canonical column order (P1)

**Bug (verified mechanism):** the form serializes category checkboxes in DOM order;
`_config_summary` compares the resulting list to presets **order-sensitively**. A source
switch (or any re-serialization) that reorders identical categories flips the summary
from "Standard 5x5" to "Custom 10 categories" and reorders the table columns.

**Fix:**
- Normalize `cats`/`pcats` to canonical registry order at parse time in `_build_context`
  (sort the parsed lists by their index in the category registry). Column order is then
  stable everywhere downstream regardless of serialization order.
- Make the preset comparison in `_config_summary` set-based (order-insensitive).

**Tests:** shuffled-but-identical `cats`/`pcats` query strings yield (a) the preset
summary ("Standard 5x5 …"), (b) identical `display_columns` order, (c) identical rendered
header row.

## 3. Category columns show projected stats by default, with a Stats | Value toggle (P2)

**Problem:** columns labeled `R`, `HR`, `AVG` display per-category **value
contributions** (z-scores), so `5.7` under HR reads as a broken projection. The data for
real stats is already on the result rows (`raw_values` is already referenced by
`rankings_table.html`).

**Fix (locked: projections default + toggle):**
- Default table shows **projected stats** per category (HR `34`, AVG `.280`), formatted
  per category kind: rate stats (AVG/OBP/SLG) 3-decimal **without leading zero** (`.280`),
  ERA/WHIP 2-decimal, counting stats as integers. Formatting keyed off the category
  registry.
- A segmented toggle labeled **`Projections | Category value`** (not "Stats | Value"),
  using the same accessible pill pattern as the source control (`name="display"`, values
  `projections` (default) / `values`), placed in the filter bar. Serialized by the form,
  so it re-renders via the existing htmx flow.
- **Default is `Projections` on every fresh/shared URL** — `display` absent ⇒ projections.
  The selected view is preserved through **filtering, source switching, refresh** (form
  serialization + HX-Replace-Url, same as `source`) **and export** (the export link
  carries `display`).
- `Category value` view renders today's per-category z-contributions, but with **explicit
  headers** (`HR value`, `AVG value`, …) so they never read as stats, plus a **tooltip**
  on each contribution header explaining it is the category's z-score contribution to
  total value (not a projection).
- Scope: non-dynasty modes (dynasty/prospects tables have their own columns; unchanged).
- **Export CSV shows projected stats by default** (matching the default board). A separate
  contribution export can be added later if wanted — out of scope here.

**Tests:** default render (no `display`) shows a known player's projected stat (e.g., an
AVG formatted `.2xx`) not a z-contribution; `?display=values` shows the contribution with a
`value` header + tooltip; toggle markup is accessible (focusable radios, aria-label);
`display` survives a source switch (present in HX-Replace-Url) and is honored by `/export`;
default CSV contains projected stats.

## Non-Goals

- The UI/UX items from the review (tab split, sticky toolbar, mode/pool radio a11y
  retrofit, type scale/tokens, methodology layout) — follow-up spec.
- Any valuation/model change. Dollar redistribution in §1 is a computation-scope fix,
  not a model change.
- Export format changes.

## Success criteria

1. Searching/filtering never changes any player's `$`, position rank, or tier — proven
   by invariant tests across redraft + dynasty + prospects.
2. No single-player view ever shows the full-budget artifact ($2,400-class values).
3. Identical category sets in any serialization order render the preset summary and the
   same column order.
4. Default board shows projected stats under category headers; `Projections | Category
   value` toggle switches views, defaults to Projections on a fresh URL, survives
   filter/source/refresh/export, is accessible, and the value view uses explicit `… value`
   headers with explanatory tooltips. Default CSV carries projected stats.
5. Full suite green; default-view dollar shift acknowledged in the commit message.
