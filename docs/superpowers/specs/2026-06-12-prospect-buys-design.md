# Prospect Buys Board + Shareable Graphic — Design

**Date:** 2026-06-12
**Status:** Approved (Alex, 6/12)
**Reference:** Scout the Statline "40 Buys Now for Later" graphic (2-column ranked list, headshots, team logos, position/level tags, branded header/footer).

## Goal

A `/buys` page ranking the top-40 prospect "buys now for later" from ValuCast data, plus a one-click branded PNG export sized for X (1080×1350, 4:5). The list is the product feature; the graphic is the content-marketing engine — same niche Scout the Statline posts in, but powered by real valuation data and branded ValuCast Broadcast Dark.

## Data source

`data/dd/dd_dynasty_feed.json` (schema 1.1), already loaded via `dd_store` / `web/dynasty_models.py`. **No DD-producer changes — single-repo feature.** All scoring inputs exist per prospect record:

- `value_history` — ((date, value), ...) daily, ~30d. Producer denylists the 6/2 + 6/10 contaminated snapshots, but **real re-baseline steps remain in-series** (e.g. 82.0→64.3 on 5/25, 65.6→76.2 on 6/3). Any momentum math must not cross a step.
- `breakout_label` — major_breakout (14) / breakout (32) / rising (32) / steady (105) / slipping (19) / falling (6) / "" (284).
- `breakout_rank_change` — **do not use** (sign semantics ambiguous; observed range -37..+227).
- `source_ranks` — pipeline / cfr / hkb / milb_perf integer ranks, any may be missing.
- `age`, `level` (A / A+ / AA / AAA / MLB / ""), `eta`, `dynasty_value`, `dynasty_rank`, `prospect_rank`.
- `mlbam_id` — present on 469/492 prospects; drives headshots.
- `mlb_team` — abbreviation; drives team logos via static abbrev→MLB-team-id map.

## Buy score — `web/buy_score.py` (new, pure functions)

Follows the `value_spark.py` pattern: feed rows in, plain dicts out, no Flask imports.

`buy_score = 0.35·momentum + 0.30·breakout + 0.20·consensus_gap + 0.15·runway`, each term normalized to [0, 1] (breakout may dip mildly below 0). Score scaled ×100 for display.

**Momentum (35%).** Compute on the *clean tail* of `value_history`: walk backward from the latest point; a 1-day absolute jump > 6.0 points is an epoch step — stop there. Cap the tail at the last 14 calendar days. Momentum = (last − first) / max(first, 1) over that tail, clamped to [-0.08, +0.12], then min-max mapped to [0, 1] (so 0 raw Δ ≈ 0.4). Fewer than 2 clean points → 0.4 (neutral). Rationale: epoch steps are 10–17 pts vs ≤ ~1 pt real daily moves — endogenous detection is robust and survives future re-baselines without a date denylist.

**Breakout (30%).** `breakout_label` tier map: major_breakout 1.0, breakout 0.75, rising 0.5, steady 0.15, "" 0.10, slipping −0.15, falling −0.30.

**Consensus gap (20%).** perf_rank = min(hkb, milb_perf) (ignore missing); pipeline_rank missing → 150. gap = pipeline_rank − perf_rank. Map log-scaled: `max(0, log10(max(gap,1)) / log10(150))` when gap > 0, else 0. Both performance ranks missing → 0. Captures "performance outrunning public reputation" — the Bolte shape (Pipeline-unranked, strong hkb).

**Runway (15%).** `age_term`: ≤18 → 1.0, 19 → 0.9, 20 → 0.75, 21 → 0.6, 22 → 0.45, 23 → 0.3, ≥24 → 0.15 (missing age → 0.5). `level_term`: A → 1.0, A+ → 0.85, AA → 0.6, AAA → 0.35, "" → 0.5. runway = mean(age_term, level_term).

**Eligibility.** `player_type == "prospect"` AND `level != "MLB"` (call-ups' buy window closed at debut — keep as a module-level constant so it's flippable). Missing `mlbam_id` or short history do NOT exclude (silhouette fallback / neutral momentum).

**Ranking.** Sort by buy_score desc, tie-break `dynasty_value` desc, then name asc (determinism). Take top 40 (constant, overridable via `?n=` within [10, 60]). `n` affects the **interactive list only** — the graphic node always renders the top 40 (2×20 layout is fixed; fewer than 40 eligible → fill what exists, leave trailing cells empty).

**Tuning gate:** weights/thresholds above are v1 priors. Before ship, Fable sanity-checks the produced top-40 against known names and tunes one pass. Numbers in this spec may shift; structure may not.

## Route & page — `/buys`

- Standalone template `templates/buys.html` extending `base.html` (precedent: `value_map.html`). Nav link added next to Map.
- Page body: title row ("Buys Now for Later — Top 40 Prospect Buys" + date + methodology one-liner), the interactive list, and a "Download graphic" button.
- Interactive list: app-styled rows (rank, headshot thumb, name linking to `/player/<id>`, `TEAM · POS · LEVEL`, buy-score chip, breakout label chip, 30d spark via existing `_value_spark.html` where history exists). Mobile: single column, standard responsive table→card patterns already in `style.css`.
- Graceful degradation: `dd_store` unavailable → notice panel (same pattern as `/` dynasty fallback).
- No new query-param surface beyond optional `n`.

## Shareable graphic node

- A fixed-size 1080×1350 DOM node (`#buys-graphic`), rendered server-side into the same template, positioned off-canvas (not `display:none` — html2canvas needs layout), scaled-down visible preview via `transform: scale()` in a collapsible "Preview graphic" section.
- Layout mirrors the reference: branded header (ValuCast wordmark, "BUYS NOW FOR LATER — TOP 40 PROSPECT BUYS", date), 2 columns × 20 rows (rank badge, team logo, circular headshot, bold name, `TEAM · POS · LEVEL` tag), footer ("valucast.app").
- **Brand: Broadcast Dark** — `--surface` navy base, solid/gradient backgrounds only, prospect-green (`--c-prospect`) and blue (`--c-blue`) accents. **No `backdrop-filter` inside the graphic node** (html2canvas cannot rasterize it). Distinct from Scout the Statline's white/blue — no trade-dress cloning.
- Headshots: `https://img.mlbstatic.com/mlb-photos/image/upload/d_people:generic:headshot:67:current.png/w_120,q_auto:best/v1/people/{mlbam_id}/headshot/67/current` — the `d_` default serves a generic silhouette for missing/absent ids (no broken images). Missing `mlbam_id` → use id 0 (forces silhouette).
- Team logos: `https://www.mlbstatic.com/team-logos/{team_id}.svg`, via a static 30-entry abbrev→id dict in `web/buy_score.py` (or small `web/mlb_assets.py`). Unknown abbrev → omit logo, keep layout.

## PNG export

- Vendor `html2canvas.min.js` into `static/` (same vendoring pattern as `htmx.min.js`; pin version in a comment).
- Button handler: `html2canvas(node, {scale: 2, useCORS: true, backgroundColor: <surface>})` → canvas → `toBlob` → anchor download `valucast-buys-YYYY-MM-DD.png`. **Export targets the off-canvas unscaled `#buys-graphic` node** — never the transform-scaled preview (html2canvas misrenders under ancestor transforms).
- All `<img>` in the graphic node carry `crossorigin="anonymous"` (mlbstatic serves `Access-Control-Allow-Origin: *`).
- **CORS fallback (build only if needed):** if export produces a tainted canvas in verification, add `/img-proxy?u=<allowlisted-host-url>` Flask route (strict allowlist: img.mlbstatic.com, www.mlbstatic.com) and point the node's images at it. Not built preemptively.
- Export failure (JS error/taint) → inline notice "Export failed — screenshot the preview instead"; the preview node is always usable manually.

## Testing

- `tests/test_buy_score.py`: step detection (clean series, single step, step-at-edge, short history), tail capping, clamps, label tiers, consensus-gap math (missing ranks, unranked-pipeline case), runway table, eligibility (MLB excluded, prospect-only), determinism of sort, `n` bounds.
- Route tests in existing style: `/buys` 200 + contains list and graphic markup; dd-unavailable fallback; top-40 length; call-up exclusion asserted against committed feed.
- Existing suite stays green (810).

## Out of scope (v1)

- Sell list / "fades" variant, positional buy lists, weekly auto-generation or scheduling, server-side Pillow rendering, DD-producer changes, OG-image integration.

## Execution

Codex implements from Fable's brief (single repo, this spec). Fable reviews diff, runs pytest, sanity-checks the top-40 names with Alex, tunes weights, ships. Render auto-deploys from master push; verify live via /health/ready then /buys.
