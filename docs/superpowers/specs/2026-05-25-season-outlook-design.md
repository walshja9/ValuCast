# Season Outlook + Correctness Fixes Design Spec

**Date:** 2026-05-25
**Status:** Approved
**Scope:** Season outlook data pipeline, three correctness bug fixes

## Overview

Add a season outlook pipeline that combines 2026 actual YTD stats with rest-of-season projections to produce projected final 2026 stat lines for every player. Fix three confirmed correctness bugs: tier minimum size, AgeCurve pitcher pool matching, and pitcher H_ALLOWED normalization.

## Architecture Decision: Data Components vs Product Modes

### Three Stored Data Components

| Component | Definition | Source |
|---|---|---|
| `actuals_ytd` | Observed 2026 season stats through an as-of date, including derived QS | MLB Stats API season stats + game logs |
| `ros_projection` | Steamer rest-of-season projections (ZiPS ROS unavailable) | FanGraphs API (`steamerr`) |
| `season_outlook` | Combined projected 2026 final line: `actuals_ytd + ros_projection` | Computed during refresh |

These are data views, not product modes. The engine consumes `season_outlook` for redraft valuation.

### Product Modes (Current and Future)

| Mode | Data Source | Dynasty Adjustments | Status |
|---|---|---|---|
| Redraft | `season_outlook` | None | This session |
| DD 7x7 Dynasty | `season_outlook` + DD prospect feed | AgeCurve, prospect values, DD calibration | Later session |
| General Dynasty | `season_outlook` + generic prospect enrichment | AgeCurve, portable prospect inputs | Deferred design |

## Data Sources

### MLB Stats API — YTD Actuals

**Endpoint:** `https://statsapi.mlb.com/api/v1/stats`

**Hitters:** `?stats=season&group=hitting&season=2026&sportId=1&limit=5000&playerPool=ALL`
- Returns all hitters with 2026 MLB appearances (557 players as of spike)
- Fields: `plateAppearances`, `atBats`, `hits`, `baseOnBalls`, `hitByPitch`, `sacFlies`, `doubles`, `triples`, `homeRuns`, `runs`, `rbi`, `stolenBases`, `caughtStealing`, `strikeOuts`, `intentionalWalks`
- Singles derived: `1B = hits - doubles - triples - homeRuns`
- Player ID: `player.id` (MLBAM ID)

**Pitchers:** `?stats=season&group=pitching&season=2026&sportId=1&limit=5000&playerPool=ALL`
- Returns all pitchers with 2026 MLB appearances (638 players as of spike)
- Fields: `inningsPitched`, `earnedRuns`, `baseOnBalls`, `hits` (→ `H_ALLOWED`), `strikeOuts`, `wins`, `losses`, `saves`, `holds`, `gamesStarted`, `gamesPitched`
- `hits` in pitcher context is hits allowed — normalize to `H_ALLOWED` in adapter output
- `strikeOuts` normalized to `K` in adapter output
- Player ID: `player.id` (MLBAM ID)

**IP baseball notation normalization:** The MLB Stats API returns innings pitched in baseball notation where the decimal represents outs, not tenths: `4.2` means 4 innings + 2 outs = 4⅔ innings. The adapter must convert to true decimal before any arithmetic:

```
def normalize_ip(ip_baseball: float) -> float:
    """Convert baseball IP notation (4.2 = 4⅔) to true decimal (4.667)."""
    whole = int(ip_baseball)
    outs = round((ip_baseball - whole) * 10)
    return whole + outs / 3
```

This applies to both season stats and game log stats (for QS derivation: `normalize_ip(ip) >= 6.0`). FanGraphs projections already use true decimal notation and require no conversion.

**QS derivation:** Per-pitcher game logs at `https://statsapi.mlb.com/api/v1/people/{id}/stats?stats=gameLog&group=pitching&season=2026&gameType=R`
- Fetch game logs only for pitchers with `gamesStarted > 0` (257 pitchers as of spike)
- `QS = count of starts where inningsPitched >= 6.0 and earnedRuns <= 3`
- ~21 seconds total for full batch at current player count

### FanGraphs API — ROS Projections

**Endpoint:** `https://www.fangraphs.com/api/projections`

**CRITICAL: The existing code fetches full-season projections (`type=steamer`, `type=zips`), not rest-of-season. These include production already accrued in 2026. Adding actuals to full-season projections would double-count completed games.**

The pipeline must switch to explicit ROS endpoints:
- `type=steamerr` — Steamer Rest-of-Season (confirmed working: 4353 hitters, 5538 pitchers)
- `type=zipsr` — ZiPS Rest-of-Season (**currently returning 500 errors, unavailable**)

**Decision: Use Steamer ROS only (`steamerr`) for the ROS component.** ZiPS ROS is unavailable. Steamer ROS alone provides sufficient coverage (4353 hitters, 5538 pitchers) and updates throughout the season. If ZiPS ROS becomes available later, the blender can be re-enabled.

Spike verification (Judge, 2026):
- Steamer full-season: PA=633 (would double-count ~241 actual PA)
- Steamer ROS: PA=450 (correct — remaining games only)
- MLB actuals: PA=241
- Sum: 241 + 450 = 691 (plausible full-season projection)

**Modified files:** `scraper/fangraphs.py` must change `type=steamer` → `type=steamerr` for both hitter and pitcher endpoints, and remove ZiPS endpoints until `zipsr` is available. `scraper/blend.py` receives only Steamer ROS data (no blending needed with single source, but the pipeline structure is preserved for when ZiPS ROS returns).

- Player ID: `playerids` (FanGraphs ID), with `xMLBAMID`/`MLBAMID` for join
- Field names and schema are identical to the full-season endpoints

### Identity Join

- **Join key:** Composite `(mlbam_id, pool_family)` where pool_family is `"hitter"` or `"pitcher"`
- MLB Stats API provides `player.id` (MLBAM ID); pool_family determined by which endpoint returned the record (hitting vs pitching)
- FanGraphs projections store `mlbam_id` in player metadata; pool_family determined by `pool` field (`"hitter"` vs `"starter"`/`"reliever"`/`"pitcher"`)
- Spike confirmed 100% join coverage: 557/557 hitter actuals matched to FG hitter projections
- Pitcher join coverage should be reported separately during implementation
- **Two-way players (Ohtani):** appear as separate hitter and pitcher records in both sources. Joined independently by `(mlbam_id, pool_family)` — hitter actuals join hitter projection, pitcher actuals join pitcher projection. The resulting season-outlook records preserve the original FanGraphs `id` (used by web routes). Display-level merge happens later in `app.py`'s `_merge_two_way_players()`, unchanged.

## Season Outlook Calculation

### Counting Stats

Direct addition:

```
season_outlook.HR = actuals_ytd.HR + ros_projection.HR
season_outlook.R  = actuals_ytd.R  + ros_projection.R
season_outlook.K  = actuals_ytd.K  + ros_projection.K
season_outlook.QS = actuals_ytd.QS + ros_projection.QS
```

Full counting stat list:
- **Hitters:** PA, AB, H, HR, R, RBI, SB, CS, BB, SO, HBP, SF, 1B, 2B, 3B, G
- **Pitchers:** IP, ER, BB, H_ALLOWED, K, W, L, SV, HLD, GS, G, QS, SV_HLD (derived: SV + HLD)

### Rate Stats

Recalculated from combined components. Never averaged.

```
AVG  = (actual_H + ros_H) / (actual_AB + ros_AB)
OBP  = (actual_H + actual_BB + actual_HBP + ros_H + ros_BB + ros_HBP) /
       (actual_AB + actual_BB + actual_HBP + actual_SF + ros_AB + ros_BB + ros_HBP + ros_SF)
SLG  = (actual_TB + ros_TB) / (actual_AB + ros_AB)
OPS  = recalculated OBP + recalculated SLG
ERA  = 9 * (actual_ER + ros_ER) / (actual_IP + ros_IP)
WHIP = (actual_BB + actual_H_ALLOWED + ros_BB + ros_H_ALLOWED) / (actual_IP + ros_IP)
K_BB = (actual_K + ros_K) / (actual_BB + ros_BB)
K_9  = 9 * (actual_K + ros_K) / (actual_IP + ros_IP)
BB_9 = 9 * (actual_BB + ros_BB) / (actual_IP + ros_IP)
```

Total bases (TB) derived: `1B + 2*2B + 3*3B + 4*HR`

### Players Without Actuals

Players with ROS projections but no 2026 actuals (not yet debuted, injured, etc.): season outlook equals the ROS projection. Zero actuals, full projection.

### Players Without ROS Projections

Players with 2026 actuals but no ROS projection (call-ups, newly rostered relievers): included in season outlook as `actuals_ytd + zero ROS`. Their counting stats are their actuals to date; rate stats are calculated from actuals alone. These records are marked with `"has_ros": false` in metadata. **The web app must display a visible "No ROS projection" indicator** on these players (e.g., a badge or dimmed row) so users understand these are partial-season lines, not projected full-season values. This is required, not optional — without it, a call-up with 30 PA appears comparable to a projected 600 PA full-season line.

**ID contract for actuals-only players:** These players have no FanGraphs ID. To avoid collision with existing FanGraphs IDs (which are bare numeric strings like `"15640"`), actuals-only players use a namespaced record ID: `"mlbam_{mlbam_id}_H"` for hitters, `"mlbam_{mlbam_id}_P"` for pitchers. For example, MLBAM ID 123456 as a hitter becomes `"mlbam_123456_H"`. This prevents `ProjectionStore` from interpreting an unrelated player as a two-way duplicate.

**Display merge key:** All season-outlook records with an MLBAM ID set `metadata.base_id = "mlbam_{mlbam_id}"`, regardless of whether they matched ROS projections or not. This provides a universal grouping key for `_merge_two_way_players()` that handles all combinations: both roles matched to ROS, both actuals-only, or one matched and one actuals-only. Each record's routing `id` (FanGraphs ID for matched, `mlbam_{id}_H/P` for actuals-only) remains distinct for `ProjectionStore` indexing.

## Refresh Pipeline

### Current Flow

```
FanGraphs API → scraper/fangraphs.py → scraper/blend.py → data/projections/current.json
```

### New Flow

```
FanGraphs API → scraper/fangraphs.py → scraper/blend.py → data/projections/ros.json
MLB Stats API → scraper/mlb_actuals.py → data/actuals/current.json
               ↓
scraper/combine.py → data/projections/current.json (season outlook)
```

### File Layout

```
data/
  actuals/
    current.json          # YTD actuals normalized to engine schema
  projections/
    ros.json              # Steamer ROS projections (single source; ZiPS ROS unavailable)
    current.json          # Season outlook (actuals + ROS), consumed by web app
```

### Output Format

`data/projections/current.json` remains a **plain JSON array** of player records, exactly as the web app's `ProjectionStore` expects. This preserves backward compatibility — no envelope object, no breaking change to `projection_store.py`.

Dataset metadata is written to a **sidecar file** at `data/projections/metadata.json`:

```json
{
  "as_of": "2026-05-25",
  "actuals_source": "mlb_stats_api",
  "ros_source": "fangraphs_steamer_ros",
  "actuals_hitters": 557,
  "actuals_pitchers": 638,
  "ros_hitters": 4353,
  "ros_pitchers": 5538,
  "outlook_players": 9891,
  "players_without_ros": 0
}
```

`web/projection_store.py` is modified to load `metadata.json` if present and expose an `as_of` property. The web app displays this date in the footer. If the sidecar is missing (e.g., legacy data), `as_of` defaults to `None` and the footer shows no date.

### Error Handling

- If MLB Stats API season stats fetch fails: refresh aborts, retains last valid data files. Log the failure. Do not produce partial season outlook.
- If any QS game log fetch fails for a starting pitcher: the entire actuals refresh aborts and retains the last complete output. QS must be complete for all starters or not included at all — partial QS data would silently produce incorrect rankings for any league using QS categories.
- If FanGraphs fetch fails: refresh aborts, retains last valid `data/projections/ros.json`. Log the failure.
- If both actuals and ROS exist but combine step fails: retain last valid `current.json`. Log the failure.
- **Publish order:** Refresh validates all data in memory, then writes to `.tmp` files. It replaces `current.json` first, then `metadata.json`. If the second replace fails, `metadata.json` may be stale or missing on disk — but metadata is treated as **non-authoritative display information** (the `as_of` date in the footer). The app functions correctly with stale or missing metadata; only rankings data (`current.json`) is load-bearing. `ProjectionStore` already defaults `as_of` to `None` when the sidecar is absent.
- The web app always reads `current.json`. It does not know or care whether it contains outlook or projection-only data.

## New Files

| File | Responsibility |
|---|---|
| `scraper/mlb_actuals.py` | Fetch 2026 YTD actuals from MLB Stats API. Normalize to engine schema (field renaming, H→H_ALLOWED, SO→K, QS derivation). Output `data/actuals/current.json`. |
| `scraper/combine.py` | Join actuals to ROS projections by composite key `(mlbam_id, pool_family)`. Add counting stats, recalculate rate stats. Include actuals-only players as `actuals + zero ROS`. Output `data/projections/current.json` (player array) and `data/projections/metadata.json` (sidecar). Report hitter and pitcher join coverage separately. |

## Modified Files

| File | Change |
|---|---|
| `scraper/fangraphs.py` | Switch from full-season (`steamer`/`zips`) to ROS (`steamerr`) endpoints. Remove ZiPS until `zipsr` is available. |
| `scraper/blend.py` | Add `H_ALLOWED` normalization for pitchers (rename `H` → `H_ALLOWED` in `_finalize_pitcher_stats`). Handle single-source (Steamer-only) gracefully. |
| `scraper/refresh.py` | Update orchestration: fetch actuals, fetch ROS, combine, write output files and metadata sidecar with staged publish |
| `src/league_values/post_processors.py` | Fix `AgeCurve` to check `STARTER`/`RELIEVER` pools, not just `PITCHER` |
| `app.py` | Fix `_compute_tiers` to enforce minimum tier size invariant (no tier < 3 players) |
| `web/projection_store.py` | Load `metadata.json` sidecar if present, expose `as_of` property |
| `templates/base.html` | Display `as_of` date in footer when available |

## Correctness Bug Fixes

### 1. Tier Minimum Size

**Bug:** Gap-based tiering can create single-player tiers when one player's value is an outlier (e.g., Skubal alone in Tier 1).

**Fix:** After computing tier boundaries from gaps, enforce the invariant: **no tier may contain fewer than 3 players** (unless the entire result set has fewer than 3). Merge small tiers into their adjacent tier (downward for tier 1, upward for all others) and repeat until the invariant holds. This handles cascading merges where two neighboring small tiers combine into fewer than 3 players.

### 2. AgeCurve Pitcher Pool

**Bug:** `AgeCurve.process()` line 134 checks `r.player.pool is PlayerPool.PITCHER`, but live data uses `STARTER` and `RELIEVER`. All SP/RP fall through to the hitter curve.

**Fix:** Change the condition to `r.player.pool in (PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER)`.

### 3. Pitcher H_ALLOWED Normalization

**Bug:** `scraper/blend.py` stores pitcher hits allowed as `H` in the stats dict. `web/category_registry.py` defines WHIP with `numerator_stats=("BB", "H_ALLOWED")`. WHIP is calculated without hits allowed.

**Fix:** In `blend.py`'s `_finalize_pitcher_stats()`, rename `H` to `H_ALLOWED` (same pattern as the existing `SO` → `K` rename). This fix also applies to the new `mlb_actuals.py` adapter — pitcher hits must be output as `H_ALLOWED`.

## Adapter Schema

Both `mlb_actuals.py` and `blend.py` output player records in the same normalized schema consumed by the engine:

```json
{
  "id": "15640",
  "name": "Aaron Judge",
  "pool": "hitter",
  "positions": ["OF", "DH"],
  "team": "NYY",
  "stats": {
    "PA": 241, "AB": 198, "H": 50, "HR": 17, "R": 41, "RBI": 32,
    "SB": 5, "CS": 1, "BB": 39, "SO": 68, "HBP": 2, "SF": 0,
    "1B": 24, "2B": 9, "3B": 0, "G": 55,
    "AVG": 0.253, "OBP": 0.381, "SLG": 0.556, "OPS": 0.937,
    "TB": 110, "NSB": 4
  },
  "metadata": {
    "mlbam_id": "592450",
    "source": "mlb_stats_api",
    "as_of": "2026-05-25"
  }
}
```

Pitcher records use `H_ALLOWED` (not `H`), `K` (not `SO`/`strikeOuts`), and include `QS`, `SV_HLD`.

## What This Session Does NOT Include

- Dynasty mode (DD 7x7 or General)
- Prospect data ingestion
- Scheduled refresh (cron/Render job)
- Web app UI changes beyond: displaying `as_of` date in the footer, and "No ROS projection" indicator on actuals-only players
- ReplacementLevel or PositionScarcity post-processor activation
