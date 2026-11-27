# DD 7x7 Dynasty Mode Design Spec

**Date:** 2026-05-27
**Status:** Approved
**Scope:** DD dynasty feed contract, ValuCast consumption, DD 7x7 Dynasty UI mode with interleaved MLB + prospect rankings

## Overview

Add a `DD 7x7 Dynasty` mode to ValuCast that consumes a combined dynasty rankings feed from Diamond Dynasties. In this mode, DD is the valuation authority — ValuCast is the presentation layer. MLB players and prospects are interleaved in a unified ranking table sorted by DD's calibrated 0-150 dynasty values.

## Mode Architecture

| Mode | Value Source | Stat Display | Customizable? |
|---|---|---|---|
| Redraft (H2H/Roto/Points) | ValuCast engine z-scores from season outlook | Actuals + ROS + Outlook | Yes |
| DD 7x7 Dynasty | DD feed `dynasty_value` (0-150 scale) | MLB: Actuals + ROS + Outlook. Prospects: MiLB stat line from feed | **No** — fixed preset |

- Redraft modes work exactly as today. ValuCast engine computes z-scores from season outlook stats.
- DD 7x7 Dynasty bypasses the engine for ranking. DD's feed provides `dynasty_value` and `dynasty_rank` for all players.
- ValuCast's season outlook data provides MLB stat display (actuals/ROS/outlook) alongside DD values.
- Prospect stat display comes from the feed's `stat_line` field.

## DD Feed Contract

### File Location

- **Env var:** `DD_DYNASTY_FEED_PATH`
- **Default:** `data/dd/dd_dynasty_feed.json`
- Path is configurable. Local development points to a DD repo export. Production uses a committed artifact.

### Envelope

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-05-27T08:00:00-04:00",
  "generated_by": "diamond_dynasties",
  "source": "diamond_dynasties",
  "league_preset": "DD_7x7",
  "scale": "0_150_dynasty_value",
  "value_semantics": "higher_is_better",
  "player_count": 1800,
  "prospect_count": 500,
  "players": [...]
}
```

### Shared Fields (all players)

**Required** (record skipped if missing):
- `id` — stable row key
- `player_type` — `"mlb"` or `"prospect"`
- `name` — display name
- `dynasty_rank` — overall rank (MLB + prospects combined, 1 = best)
- `dynasty_value` — numeric, 0-150 calibrated dynasty value

**Optional/nullable:**
- `mlbam_id` — for joining to season outlook. Some prospects may not have one.
- `positions` — list of position strings (e.g., `["SS", "3B"]`)
- `mlb_team` — org abbreviation
- `age` — integer
- `status` — `"mlb"`, `"minors"`, `"injured_mlb"`, etc.
- `last_updated` — per-record staleness indicator

### ID Contract

```text
MLB players:    dd_mlb_{mlbam_id}
Prospects:      dd_prospect_{mlbam_id}     (when MLBAM ID exists)
                dd_prospect_{dd_slug}      (fallback for no MLBAM ID)
```

### Prospect-Only Fields

- `level` — current MiLB level (e.g., "AAA", "AA", "A+")
- `eta` — expected MLB debut year
- `prospect_rank` — rank among prospects only (distinct from `dynasty_rank`)
- `source_ranks` — `{"pipeline": 17, "cfr": 4, "hkb": 4, "milb_perf": 21}`
- `breakout_label` — `"major_breakout"`, `"breakout"`, `"rising"`, `"steady"`, `"slipping"`, `"falling"`, `"major_fall"`
- `breakout_rank_change` — integer, positive = improving
- `stat_line` — loosely typed dict of MiLB stats. Hitter example:

```json
{"pa": 180, "hr": 8, "sb": 12, "avg": 0.285, "ops": 0.860, "iso": 0.175, "k_pct": 18.5, "bb_pct": 11.2}
```

Pitcher example:

```json
{"ip": 38.7, "era": 1.63, "k_per_9": 13.5, "bb_per_9": 1.6, "whip": 0.8, "k_bb_pct": 35.9}
```

### Validation Rules (ValuCast side)

- **Reject feed** if `schema_version != "1.0"`
- **Reject feed** if `players` is missing or empty
- **Reject feed** if duplicate `id` values exist
- **Skip + count** records missing `id`, `player_type`, `name`, non-numeric `dynasty_value`, or non-numeric `dynasty_rank`
- **Reject feed** if invalid record rate exceeds 5%
- **Warn** if `generated_at` is older than 48 hours
- **Warn** if any records were skipped (log count)
- **Sort** by `dynasty_rank` ascending (required field, no fallback — DD feed is the ranking authority)

### DD-Side Generator

New script in the DD repo that:
1. Calls `get_dynasty_value()` for all MLB players (existing function)
2. Reads `prospects_ranked.json` + applies `_calculate_prospect_value()` for prospect values
3. Assigns overall `dynasty_rank` (combined MLB + prospects sorted by value)
4. Normalizes both into the feed schema
5. Writes `dd_dynasty_feed.json`
6. Runs as part of DD's nightly pipeline

## ValuCast Consumption

### Feed Loader: `web/dd_feed_store.py`

New module that loads and validates the DD dynasty feed at app startup. Parallel to `web/projection_store.py`.

- Loads from `DD_DYNASTY_FEED_PATH` env var or default path
- Validates per the rules above
- Exposes: `get_all()`, `get_by_id()`, `filter()`, `generated_at`, `is_available`
- If feed is missing or invalid at startup: `is_available = False`, log warning, DD Dynasty mode hidden in UI

### View Model: `DynastyRankingRow`

DD feed records are NOT `ValuationResult` objects. They did not come from the engine. Use a dedicated view model:

```python
@dataclass
class DynastyRankingRow:
    id: str
    name: str
    player_type: str          # "mlb" or "prospect"
    positions: tuple[str, ...]
    team: str
    age: int | None
    dynasty_rank: int
    dynasty_value: float
    status: str | None
    # MLB-specific (from season outlook join)
    mlb_stats: dict | None          # season outlook stats
    mlb_stats_actual: dict | None   # YTD actuals
    mlb_stats_ros: dict | None      # ROS projection
    # Prospect-specific (from feed)
    prospect_rank: int | None
    level: str | None
    eta: int | None
    source_ranks: dict | None
    breakout_label: str | None
    breakout_rank_change: int | None
    stat_line: dict | None
    # Metadata
    mlbam_id: str | None
    metadata: dict
```

### Joining Feed to Season Outlook

- MLB players in the feed have `mlbam_id` — join to season outlook records for stat display
- Join by `mlbam_id` against `ProjectionStore` metadata
- Two-way players (Ohtani): DD feed has one row. Season outlook may have two records (hitter + pitcher). Collect all matching season-outlook records for that `mlbam_id` and merge stats for display.
- Prospects: no season outlook join. Stat display comes from feed `stat_line`.
- **The join is display-only. Ranking and value always come from the feed.**

### Changes to `app.py`

**Rankings route (`/` and `/rankings`):**

`_build_context` detects `mode=dd_dynasty` and branches:
- Loads rankings from `dd_feed_store` instead of engine results
- Builds `DynastyRankingRow` list instead of `ValuationResult` list
- Joins MLB rows to season outlook for stat display
- Applies filters (pool, position, search) to the DD list
- Computes auction dollars from `dynasty_value` distribution
- Does NOT run the engine, does NOT compute tiers/position ranks from z-scores
- Tiers can optionally be computed from `dynasty_value` gaps (same algorithm)

**Player detail route (`/player/<id>`):**

Must branch BEFORE `ProjectionStore` lookup. DD feed IDs (`dd_prospect_*`, `dd_mlb_*`) do not exist in `ProjectionStore` and would 404.

```text
if mode == dd_dynasty:
    row = dd_feed_store.get_by_id(player_id)
    if row is None: return 404
    if row.player_type == "prospect":
        render player_detail_dynasty.html (prospect view)
    else:
        join to season outlook by mlbam_id for stat display
        render player_detail_dynasty.html (MLB view)
else:
    existing ProjectionStore lookup + engine path
```

**Compare route (`/compare`):**

Compare is **disabled in DD Dynasty mode** for v1. The current compare modal assumes `ValuationResult` with `raw_values`, `z_scores`, and `category_values` — none of which exist for `DynastyRankingRow`. Compare checkboxes are hidden in the DD Dynasty rankings table. A dynasty-specific compare modal can be added in a future version.

**URL fallback when feed is unavailable:**

If `mode=dd_dynasty` is requested via URL but `dd_feed_store.is_available` is False:
- Redirect to `/?mode=categories` (default redraft)
- Flash a notice: "DD 7x7 Dynasty data is not available. Showing default rankings."
- This prevents broken shared URLs and direct navigation from crashing

### URL Behavior

- `mode=dd_dynasty` is the mode identifier
- Supported params: `mode`, `pool`, `position`, `search`
- **Ignored/stripped params:** `cats`, `pcats`, `w_*`, `split_rp`, `pt_*`, `rules`
- `HX-Replace-Url` preserves only supported params
- Shared URLs work: `/?mode=dd_dynasty&search=anderson`

## UI Changes

### Mode Selector

Fourth pill button, same row:

```
[H2H Categories] [Roto] [Points] [DD 7x7 Dynasty]
```

Hidden if `dd_feed_store.is_available` is False.

### Config Panel (DD Dynasty mode)

Replace collapsible Customize panel with a locked summary card:

```
DD 7x7 Dynasty uses Diamond Dynasties' fixed categories, weights, age curves,
market calibration, and prospect model. Custom category editing is disabled.
Updated 2026-05-27.
```

No Customize button. No category checkboxes.

### Pool Filter (DD Dynasty mode)

Extended filter options:

```
[All] [MLB] [Hitters] [Pitchers] [Prospects]
```

- "All" = everything
- "MLB" = `player_type == "mlb"` only
- "Hitters" / "Pitchers" = filter by position/pool, includes both MLB and prospects
- "Prospects" = `player_type == "prospect"` only

### Rankings Table (DD Dynasty mode)

| Column | Behavior |
|---|---|
| # | `dynasty_rank` |
| Player | Name + position rank badge (MLB) or prospect rank badge `P#2` (prospect) + type badge |
| Type | "Prospect" badge on prospect rows (amber pill, similar to no-ROS badge) |
| Pos | Positions from feed |
| Team | `mlb_team` from feed |
| Age | From feed |
| Dynasty Value | `dynasty_value` (renamed from "Value") |
| Dynasty $ | Auction dollars derived from `dynasty_value` distribution |
| Category columns | **Hidden** — DD values are pre-computed, no per-category z-scores to show |

### Player Detail — MLB Players

- Header: name, positions, team, **Dynasty Value: 88.2**
- "2026 Season Outlook" stat grid (from joined season outlook data)
- "2026 Actual Stats (through {date})" stat grid
- "ROS Projection (Steamer)" stat grid
- **No category breakdown table** (DD values are not decomposed into category contributions in the feed)

### Player Detail — Prospects

- Header: name, positions, team, **Dynasty Value: 71.3**, **Prospect Rank: #2**
- "Prospect Profile" section: level, ETA, age, breakout label + rank change
- "Source Rankings" section: Pipeline #17, CFR #4, HKB #4, MiLB Perf #21
- "MiLB Stats" section: stat_line rendered as stat grid (same CSS as MLB stats)
- No season outlook stats

### CSV Export (DD Dynasty mode)

Columns:

```
Overall Dynasty Rank, Player, Type, Positions, Team, Age, Dynasty Value, Dynasty $, Prospect Rank, Level, ETA
```

### Mobile

Same card layout pattern as redraft mode. Prospect badge and dynasty value visible in card view.

## New Files

| File | Responsibility |
|---|---|
| `web/dd_feed_store.py` | Load, validate, and serve DD dynasty feed at startup |
| `web/dynasty_models.py` | `DynastyRankingRow` dataclass |
| `templates/partials/rankings_table_dynasty.html` | Dynasty-specific rankings table (no category columns, prospect badges, dynasty value header) |
| `templates/partials/player_detail_dynasty.html` | Dynasty-specific player detail (branches MLB vs prospect internally) |
| DD repo: `generate_valucast_feed.py` | Generate `dd_dynasty_feed.json` from DD valuations |

## Modified Files

| File | Change |
|---|---|
| `app.py` | DD Dynasty branch in `_build_context`, `/player/<id>` routes to `dd_feed_store` first in DD mode, compare disabled in DD mode, URL fallback when feed unavailable, dynasty auction dollars |
| `templates/index.html` | DD Dynasty mode button (conditional on `dd_available`), locked config card, extended pool filter, compare bar hidden in DD mode |
| `templates/partials/rankings_response.html` | Include dynasty table partial when `mode == dd_dynasty` |
| `static/style.css` | Prospect badge, prospect-rank badge, locked config card, dynasty-specific styles |
| `web/config_builder.py` | `dd_dynasty` mode handling, URL param stripping for `cats`/`pcats`/`w_*`/`split_rp`/`pt_*` |

## What This Spec Does NOT Include

- General Dynasty mode (deferred — design depends on what DD components generalize)
- DD 7x7 Redraft (engine-computed values with DD categories but no dynasty adjustments)
- v1.1 feed fields: `risk_grade`, `risk_score`, `value_components`, `bats`, `throws`, `org_rank`
- Engine result caching
- IP/PA minimum filter for small-sample players
- Render deployment
- Scheduled feed refresh / CI pipeline for feed publishing
