# Data Pipeline Design

**Date:** 2026-05-18
**Status:** Approved

## Goal

Pull Steamer and ZiPS projections from FanGraphs, blend them into a single projection set, and output a JSON file that feeds directly into the league_values engine.

## Data Source

FanGraphs JSON API — no browser automation needed.

**Endpoint:** `https://www.fangraphs.com/api/projections`

**4 requests:**
| Type | Stats | URL Params |
|------|-------|------------|
| Steamer Hitters | bat | `?type=steamer&stats=bat&pos=all&team=0&players=0&lg=all` |
| Steamer Pitchers | pit | `?type=steamer&stats=pit&pos=all&team=0&players=0&lg=all` |
| ZiPS Hitters | bat | `?type=zips&stats=bat&pos=all&team=0&players=0&lg=all` |
| ZiPS Pitchers | pit | `?type=zips&stats=pit&pos=all&team=0&players=0&lg=all` |

Response: JSON array of player objects. ~300 hitters, ~400 pitchers per system.

## File Structure

```
scraper/
  fangraphs.py    # HTTP fetcher — 4 requests, save raw JSON
  blend.py        # Match players across sources, blend stats
  refresh.py      # Orchestrator: fetch → blend → write current.json
data/
  projections/
    raw/                         # Raw API responses (gitignored)
      steamer_hitters.json
      steamer_pitchers.json
      zips_hitters.json
      zips_pitchers.json
    current.json                 # Blended output (committed)
```

## Scraper (fangraphs.py)

```python
def fetch_projections(system: str, stats: str) -> list[dict]:
    """Fetch one projection set. system='steamer'|'zips', stats='bat'|'pit'."""

def fetch_all() -> dict[str, list[dict]]:
    """Fetch all 4 sets, return {"steamer_hitters": [...], ...}. 1s delay between requests."""

def save_raw(data: dict[str, list[dict]], output_dir: str) -> None:
    """Save raw JSON files to output_dir."""
```

Uses `urllib.request` with a User-Agent header. 1-second delay between requests. No external dependencies.

## Blender (blend.py)

### Matching

Players matched by `PlayerId` (FanGraphs ID) across Steamer and ZiPS. If a player appears in only one source, use that source alone.

### Blending Rules

- **Counting stats** (PA, AB, H, HR, R, RBI, SB, SO, BB, W, L, IP, K, SV, HLD, GS, QS, ER): simple average of both sources
- **Rate stats** (AVG, OBP, OPS, SLG, ERA, WHIP, K/BB, K/9, BB/9): volume-weighted average. For hitters, weight by PA. For pitchers, weight by IP.
- **Derived stats** computed after blending:
  - `SV_HLD = SV + HLD`
  - `K_BB = K / BB` (if BB > 0, else 0)
  - `AVG = H / AB` (if AB > 0, recomputed from blended counting stats for consistency)

### Pool Detection

- Hitters: `pool = "hitter"`
- Pitchers with `GS > 0` or `GS` missing but `SV == 0 and HLD == 0`: `pool = "starter"`
- Pitchers with `SV > 0 or HLD > 0` and `GS == 0`: `pool = "reliever"`
- Pitchers with both GS and SV/HLD: `pool = "starter"` (primary role)

### Position Detection

FanGraphs doesn't provide clean position strings. Use these heuristics:
- Hitters: map from FanGraphs `ShortName` or `Pos` field if available, else default to `["DH"]`
- Pitchers: `GS > 0` → `["SP"]`, `SV > 0 or HLD > 0` → `["RP"]`, both → `["SP", "RP"]`

### Age

FanGraphs doesn't include age in projection data. We'll compute from `MLBAMID` cross-reference or leave it to the web app to enrich later. For MVP, age is optional metadata.

## Output (current.json)

```json
[
  {
    "id": "12345",
    "name": "Bobby Witt Jr.",
    "pool": "hitter",
    "positions": ["SS"],
    "team": "KC",
    "stats": {
      "PA": 636, "AB": 570, "R": 95, "HR": 28, "RBI": 85,
      "SB": 35, "SO": 110, "H": 170, "BB": 60,
      "AVG": 0.298, "OBP": 0.355, "OPS": 0.880, "SLG": 0.525
    },
    "metadata": {"fangraphs_id": "12345", "mlbam_id": "67890"},
    "sources": ["steamer", "zips"]
  }
]
```

Directly usable as `PlayerProjection` dicts by `value_players()`.

## Refresh (refresh.py)

```python
def refresh(output_path: str = "data/projections/current.json") -> None:
    """Full pipeline: fetch all → blend → write output."""
```

Callable as `python -m scraper.refresh` or imported. Prints progress to stdout.

## Error Handling

- HTTP errors: retry once after 3s, then skip that source (blend from remaining)
- Missing fields: use 0.0 for missing numeric stats
- Empty responses: log warning, don't overwrite existing current.json

## Testing

- Unit tests for blending logic (mock data, not live API calls)
- Snapshot test: load a saved raw response, blend, verify output structure
- No live API tests in CI (flaky, rate-limited)

## Not Included

- In-season actual stats blending (future enhancement)
- Age lookup from external source
- Position data from roster sources (Fantrax, etc.)
- Automated cron setup (manual for MVP)
