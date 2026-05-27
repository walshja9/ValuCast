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
| `ros_projection` | Blended Steamer + ZiPS rest-of-season projections | FanGraphs API (existing) |
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

**QS derivation:** Per-pitcher game logs at `https://statsapi.mlb.com/api/v1/people/{id}/stats?stats=gameLog&group=pitching&season=2026&gameType=R`
- Fetch game logs only for pitchers with `gamesStarted > 0` (257 pitchers as of spike)
- `QS = count of starts where inningsPitched >= 6.0 and earnedRuns <= 3`
- ~21 seconds total for full batch at current player count

### FanGraphs API — ROS Projections (Existing)

**Endpoint:** `https://www.fangraphs.com/api/projections`
- Steamer + ZiPS, hitters and pitchers (4 endpoints)
- Player ID: `playerids` (FanGraphs ID), with `xMLBAMID`/`MLBAMID` for join

### Identity Join

- **Join key:** MLBAM ID
- MLB Stats API provides `player.id` (MLBAM ID)
- FanGraphs projections store `mlbam_id` in player metadata (populated by blender)
- Spike confirmed 100% join coverage: 557/557 hitter actuals matched to FG projections
- Two-way players (Ohtani): appear as separate hitter and pitcher records in both sources, joined independently before display-level merge

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

Players with 2026 actuals but no ROS projection (not in Steamer/ZiPS): included in `actuals_ytd` output but excluded from `season_outlook` for now. These are typically September call-ups or replacement-level players without projection coverage.

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
    ros.json              # Blended Steamer + ZiPS ROS projections
    current.json          # Season outlook (actuals + ROS), consumed by web app
```

### Output Metadata

Every `current.json` (season outlook) includes top-level metadata:

```json
{
  "as_of": "2026-05-25",
  "actuals_source": "mlb_stats_api",
  "ros_source": "fangraphs_steamer_zips",
  "actuals_players": 557,
  "ros_players": 9366,
  "outlook_players": 9366,
  "players": [...]
}
```

The web app can display the `as_of` date to communicate freshness.

### Error Handling

- If MLB Stats API fetch fails: refresh aborts, retains last valid `data/actuals/current.json`. Log the failure. Do not produce partial season outlook.
- If QS game log fetch fails for individual pitchers: set that pitcher's QS to `null` (not 0). Log the failure. Continue with other pitchers.
- If FanGraphs fetch fails: refresh aborts, retains last valid `data/projections/ros.json`. Log the failure.
- If both actuals and ROS exist but combine step fails: retain last valid `current.json`. Log the failure.
- The web app always reads `current.json`. It does not know or care whether it contains outlook or projection-only data.

## New Files

| File | Responsibility |
|---|---|
| `scraper/mlb_actuals.py` | Fetch 2026 YTD actuals from MLB Stats API. Normalize to engine schema (field renaming, H→H_ALLOWED, SO→K, QS derivation). Output `data/actuals/current.json`. |
| `scraper/combine.py` | Join actuals to ROS projections by MLBAM ID. Add counting stats, recalculate rate stats. Output `data/projections/current.json` with metadata. |

## Modified Files

| File | Change |
|---|---|
| `scraper/blend.py` | Add `H_ALLOWED` normalization for pitchers (rename `H` → `H_ALLOWED` in `_finalize_pitcher_stats`) |
| `scraper/refresh.py` | Update orchestration: fetch actuals, fetch ROS, combine, write output files |
| `src/league_values/post_processors.py` | Fix `AgeCurve` to check `STARTER`/`RELIEVER` pools, not just `PITCHER` |
| `app.py` | Fix `_compute_tiers` to enforce minimum tier size of 3 |

## Correctness Bug Fixes

### 1. Tier Minimum Size

**Bug:** Gap-based tiering can create single-player tiers when one player's value is an outlier (e.g., Skubal alone in Tier 1).

**Fix:** After computing tier boundaries from gaps, merge any tier with fewer than 3 players into its adjacent tier. Merge upward (small tier joins the tier above it) unless it's tier 1, in which case merge downward.

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
- Web app UI changes beyond displaying `as_of` date in the footer
- ReplacementLevel or PositionScarcity post-processor activation
