# Projections Foundation + Marcel Hitting Model — Design

**Date:** 2026-06-02
**Status:** Approved (design)
**Supersedes for projection roadmap:** the public-feed framing in `2026-05-18-data-pipeline-design.md` (Steamer + ZiPS 4-request blend). That pipeline now only fetches Steamer ROS; this spec defines our *own* projection layer alongside it.

## Goal

Make ValuCast generate its own projected stat lines instead of only consuming Steamer. This first spec delivers the **foundation** plus the **first model**:

1. An immutable historical-data backbone + model-run archive.
2. A Marcel-style hitter projector.
3. A rolling-origin backtest harness that scores held-out seasons.
4. Export of engine-native `PlayerProjection` rows so the existing valuation engine values our numbers with zero engine changes.
5. A projection-source seam so our model **coexists** with Steamer — Steamer is the benchmark/fallback, never deleted.

This is the first of a multi-spec program:

```
0+1. Foundation + hitting model   ← THIS SPEC
2.   Pitching model               (later spec)
3.   Prospect / MiLB translation  (later spec)
4.   DD unification + go public   (north star, deferred)
```

## Why

Four motivations, in priority order: own the whole stack, learn the craft, eventually beat the public systems, and ultimately unify with Diamond Dynasties. "Beat the public systems" is the one with teeth: it makes a **validation harness a first-class, day-one deliverable**, not an afterthought. Every future sophistication (peripherals, then Statcast) must prove itself on the harness or it doesn't ship.

The data-sophistication ceiling we are designing *toward* is THE BAT X tier (Statcast inputs). This spec deliberately stops at the **Marcel rung** — the canonical baseline every real system started from. We climb the ladder in later specs, measuring each rung.

## Non-Goals (explicitly out of this spec)

- Peripherals, Statcast, batted-ball inputs (later rungs).
- Pitching and prospect models (separate specs).
- Any source-selector **UI**. We build the seam; the toggle comes later.
- Actually beating **Steamer**. That is a secondary target gated on obtaining clean *archived preseason* Steamer projections (the Steamer we currently scrape is in-season ROS — the wrong vintage for a fair backtest). The v1 bar is beating naive baselines (below), not Steamer.
- Park factors, league/era normalization beyond the league-mean regression.
- Refactoring Flask. The source seam is minimal and additive.

## Two honesty rules locked into the design

- **Marcel is the permanent internal baseline.** We compute it ourselves for any past season, so "did we beat Marcel?" is always answerable for free. Beating Steamer is real but secondary.
- **Tuning never touches the season it is scored on.** See the rolling-origin harness (§5). My earlier "≥5 seasons" framing was too loose; rolling-origin is the anti-leakage fix.

---

## 1. Player Identity / Crosswalk (prerequisite contract)

Marcel joins seasons by a stable id and needs age. This contract defines what every historical snapshot and projection row is keyed on, so it comes *before* the archive section.

**Identity record (`projections/data/identity.json`, one per player):**

| Field | Required | Source | Notes |
|---|---|---|---|
| `mlbam_id` | yes | MLB Stats API | Stable join key. Matches the `mlbam_*` namespace already used in `scraper/combine.py`. |
| `name` | yes | MLB Stats API | Display only — never a join key. |
| `birth_date` | yes | MLB Stats API (`people` endpoint) | Drives age curve. Age computed as of a fixed projection-season reference date (April 1). |
| `bats` / `throws` | no | MLB Stats API | Carried for later models; unused in v1. |
| `debut` / `current_team` | no | MLB Stats API | Carried; unused in v1. |

Built once from the union of players appearing in the historical snapshots, refreshed on data pull. Missing `birth_date` → player still projectable but flagged `age_unknown=True` in metadata and given a neutral (1.0) age multiplier rather than dropped.

## 2. Normalized Historical Schema

Each historical season snapshot is a list of per-player hitting rows keyed by `mlbam_id`, holding raw counting stats only (rates derived at projection time, never stored pre-derived):

```
mlbam_id, season, PA, AB, H, 1B, 2B, 3B, HR, R, RBI, SB, CS, BB, SO, HBP, SF
```

`1B` is derived (`H - 2B - 3B - HR`) at ingest and stored, since it is a base component. `TB` and `NSB` (= `SB - CS`) are *not* stored — they are derived in export from the components above, keeping one source of truth.

## 3. Immutable Data Backbone + Run Archive (fixes P1 #1)

**Historical snapshots** — facts, append-only, never overwritten:

```
projections/data/
  identity.json
  historical/
    hitting_2010.json
    ...
    hitting_2025.json
  manifest.json        # per-season: source, pull timestamp, row count, schema version
```

Pull MLB Stats API season hitting stats (`sportId=1`) for **2010–2025**. That gives 3-season input windows for every target season 2013–2025 (13 backtestable seasons). A re-pull of an already-final season must be a no-op on disk (verified by content hash in the manifest) — if the API ever returns different numbers for a finalized season, fail loud rather than silently overwrite.

**Model-run archive** — every projection run is immutable and self-describing:

```
projections/runs/
  <run_id>/                       # run_id = <model>_<as_of_season>_<vN>, no wall-clock in id
    projections.json              # PlayerProjection rows
    run_manifest.json             # model version, config/constants used, input data version,
                                  #   as_of_season, eval population definition
```

This is what makes "what did we project before season X?" and "run A vs run B" answerable. `data/projections/current.json` is **not** touched by this layer.

## 4. Marcel Hitter Projector (`projections/models/marcel_hitter.py`)

Project at the **per-PA component-rate level** (rates are more stable than ratios), then scale by projected PA and reconstruct categories.

For target season `T`, using only seasons `≤ T-1`:

1. **Weight** the three prior seasons `T-1, T-2, T-3` by `5 / 4 / 3`. Weighted component totals and weighted PA.
2. **Regress to league mean** by adding `N_REG` PA of league-average component rates (classic Marcel ≈ 1200). League-average rates computed from that season's snapshot population (above the playing-time floor).
3. **Age-adjust** around peak age 29: `mult = 1 + k_young·(29 - age)` for age < 29, `1 + k_old·(29 - age)` for age > 29 (`k_old` makes it a decline). Defaults `k_young = 0.006`, `k_old = 0.003`.
4. **Project PA**: `PA_proj ≈ 0.5·PA[T-1] + 0.1·PA[T-2] + 200`.
5. **Compose**: `projected_count = regressed_rate · PA_proj · age_mult`; derive `AVG/OBP/SLG/OPS/TB/NSB` from components.

**The constants `N_REG`, `k_young`, `k_old`, and the PA-projection coefficients are knobs, not dogma.** Plain Marcel inherits Tango's fixed numbers; we tune ours on the harness (§5). That is the first place we beat textbook Marcel — and the tuning is leakage-safe by construction.

A new hitter with only 1–2 prior seasons is projected on whatever seasons exist (weights renormalized); zero prior seasons → not projectable (excluded, not zeroed).

## 5. Backtest Harness (`projections/backtest/`)

**Rolling-origin replay.** For each target season `T` in the evaluation range, project `T` using data `≤ T-1` *and* select any tuned parameters using only seasons `< T`. A season is never used to both tune the constants and score them. This replaces loose held-out splitting and is the core anti-leakage guarantee.

**Scorecard** (`projections/backtest/scorecard`): per-stat **MAE, RMSE, correlation** for `PA, HR, R, RBI, SB, AVG, OBP, SLG, OPS`, aggregated across target seasons and reported per-season.

**Baselines to beat, in order:**
1. **Persistence** — "season `T-1` = season `T`." The v1 pass bar.
2. **League-average** — everyone gets the mean.
3. **Untuned Marcel** — Tango's fixed constants. Beating this proves tuning helped.
4. **Steamer** — a stretch column, populated only if/when archived preseason Steamer is obtained. Absent in v1; its absence is logged, never silently skipped.

**Fair evaluation population** (documented in each run manifest): players with `≥ MIN_EVAL_PA` actual PA in season `T` **and** at least one projectable prior season. Both projection and actual restricted to the same population so comparisons are apples-to-apples.

## 6. Export → Engine-native PlayerProjection (`projections/export/`)

The engine consumes `PlayerProjection(id, name, pool, stats, positions, metadata)` and reads category ingredients directly out of `stats`. Export emits the **full component contract** (not just headline ratios) so the existing `category_registry` numerator/denominator math stays honest:

```
stats: { PA, AB, H, 1B, 2B, 3B, HR, R, RBI, SB, CS, BB, SO, HBP, SF, TB, NSB,
         AVG, OBP, SLG, OPS }
```

- `pool = HITTER`. `id = mlbam_{id}_H` (matches existing namespace).
- `metadata`: `{ source: "marcel", model: "valucast_marcel", model_version, as_of_season, age_unknown? }`.

Verified by feeding a run's `projections.json` through the existing engine and producing a ranked board — **no engine code changes**.

## 7. Projection-Source Seam (fixes P1 #2 + P2)

**`ProjectionCatalog`** — a named-path registry that instantiates `ProjectionStore(source="steamer" | "marcel")`. `data/projections/current.json` becomes the `steamer` entry; a published Marcel run becomes the `marcel` entry. The app's default stays `steamer`, so current behavior and all 428 tests are unchanged. No Flask refactor, no UI — the seam exists so the next spec can expose a toggle.

**Naming discipline:** the baseline run's source is `marcel`; metadata carries `model: "valucast_marcel"`. Bare **`valucast`** is reserved for the eventual tuned/blended proprietary model so provenance stays clean as the family grows.

**P2 provenance fix:** `scraper/combine.py` (matched-player paths) carries `sources` through so every row is attributable. Without this the harness cannot tell Steamer/Marcel/ValuCast rows apart.

---

## Success Criteria (the "done" checks)

1. **Backbone immutable:** 2010–2025 hitting snapshots + identity + manifest stored; re-running the pull does not mutate a finalized season's file (content-hash no-op verified).
2. **Model correct:** Marcel projector emits schema-valid `PlayerProjection` rows; the per-PA → counting math is verified against a hand-computed example in a unit test.
3. **Harness honest + winning:** rolling-origin scorecard over ≥10 target seasons; **tuned Marcel beats persistence** on aggregate MAE and correlation for the headline categories. Tuning seasons provably disjoint from scored seasons.
4. **Engine values it:** a published Marcel run produces a ranked board via `source="marcel"` end-to-end with no errors and no engine changes.
5. **Steamer intact:** `source="steamer"` reproduces today's behavior; existing **428 tests stay green**; `combine.py` rows now carry `sources`.

## Risks / Open Questions

- **Archived preseason Steamer** is the gate on the strongest accuracy claim. Tracked as a research task, not a v1 blocker.
- **R / RBI are lineup-context-dependent** and will be the noisiest categories under any rate-based model. Reported but not over-fit; a context layer is a later-rung concern.
- **Pre-2015 Statcast absence** doesn't affect this Marcel-tier spec, but the historical range (2010+) is chosen so the Statcast-era subset (2015+) is already present when later specs need it.
