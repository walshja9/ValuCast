# League Values Engine — Design Spec

**Date:** 2026-05-18
**Status:** v0.1 shipped, v0.2 planned

## Problem

Fantasy baseball valuation tools hardcode one league format. A player's dynasty value depends entirely on what categories your league uses — OBP leagues value plate discipline, points leagues value counting stats, saves-only leagues discount holds relievers. Today, every tool either assumes standard 5x5 or requires users to build their own spreadsheet.

## Goal

A standalone, config-driven valuation engine where the league configuration owns the math. One projection set produces accurate values for any league format — H2H categories, roto, points — without rewriting valuation code. Eventually plugs into Diamond Dynasties as its core valuation layer.

## Architecture

### Core Package: `league_values`

```
src/league_values/
  __init__.py          # Public API surface
  models.py            # Frozen dataclasses: LeagueConfig, CategorySpec, PointRule,
                       #   PlayerProjection, ValuationResult, RosterSettings
  engine.py            # ValuationEngine: z-score valuation + points scoring
  presets.py           # Standard 5x5, default points, DD 7x7 configs
  config_loader.py     # JSON file -> LeagueConfig
  post_processors.py   # Composable adjustment pipeline (position scarcity,
                       #   age curves, replacement level, etc.)
```

### Data Flow

```
PlayerProjection[] + LeagueConfig
        |
        v
  ValuationEngine._value_categories()  or  _value_points()
        |
        | raw stat -> category impact -> z-score -> weighted sum
        v
  ValuationResult[] (raw z-score values)
        |
        v
  PostProcessorPipeline.run()
        |
        | position scarcity -> replacement level -> age curve -> ...
        v
  ValuationResult[] (final adjusted values)
```

### Scoring Modes

| Mode | Method | Output |
|------|--------|--------|
| H2H Categories | Z-score per category, weighted sum | Composite z-value |
| Roto | Standings Gain Points (SGP) per category | SGP-based value |
| Points | Rule-based stat * points multiplier | Total fantasy points |

## v0.1 (Shipped)

### What exists today

- **Config-driven categories**: `CategorySpec` with stat, direction, weight, pool, ratio handling
- **Volume-adjusted ratios**: ERA/AVG/WHIP valued by marginal impact (rate delta * volume), not raw rate
- **Points league scoring**: Rule-based stat multiplication with pool filtering
- **Fixed league baselines**: Optional `league_baselines` on `LeagueConfig` for stable z-scores
- **Min denominator floors**: Presets ship with sensible minimums (30 AB, 10 IP)
- **JSON config loading**: Any league format expressible as a JSON file
- **Presets**: Standard 5x5 categories, starter points league
- **Serialization**: `ValuationResult.to_dict()` for API/storage use
- **25 passing tests**: Rankings, volume adjustment, edge cases, baselines, presets, config loading

### Known limitations

- No position scarcity
- No replacement-level baseline
- No age/dynasty adjustments
- No roto mode (SGP)
- Pool-derived baselines shift with input set (mitigated by `league_baselines`)
- Hitter/pitcher z-scores not on a common scale
- `ValuationEngine` class is stateless — no extension points yet

## v0.2 (Next Phase)

### 1. Post-Processor Pipeline

The engine computes raw z-scores. Everything else layers on as composable post-processors.

```python
class PostProcessor(Protocol):
    def process(
        self,
        results: list[ValuationResult],
        league: LeagueConfig,
    ) -> list[ValuationResult]: ...

class ValuationEngine:
    def __init__(self, post_processors: list[PostProcessor] | None = None): ...
```

Each post-processor receives the full result list and league config, returns a new list of results (using `dataclasses.replace()` since `ValuationResult` is frozen). They compose in order:

1. **ReplacementLevel** — subtract replacement-level value so output measures surplus
2. **PositionScarcity** — multiply by position-based scarcity factor
3. **AgeCurve** — apply dynasty-horizon multiplier based on player age
4. **PerformancePenalty** — penalize extreme underperformers (ERA > 5.5, AVG < .200)
5. **AuctionDollar** — convert z-scores to auction dollar values

Post-processors are optional. The engine works without them (v0.1 behavior). DD will inject its own set when it plugs in.

### 2. Roster Settings & Replacement Level

```python
@dataclass(frozen=True)
class RosterSettings:
    teams: int = 12
    roster_size: int = 23
    positions: Mapping[str, int] = field(default_factory=dict)
    # e.g. {"C": 1, "1B": 1, "2B": 1, "SS": 1, "3B": 1, "OF": 3, "UTIL": 1, "SP": 5, "RP": 2}
    bench: int = 5
```

Replacement level = the Nth-best player at each position, where N = teams * slots. Players are valued by surplus above replacement at their best position.

### 3. Position Scarcity

Uses `RosterSettings` to compute how scarce each position is. Positions with fewer quality options (C, SS) get a premium. Multiplier derived from the gap between average starter and replacement at that position.

### 4. Roto / SGP Mode

Standings Gain Points: how many roto standings points does one unit of a stat buy?

- Compute league-wide standings from projections
- For each category, measure the average gap between adjacent standings positions
- SGP = (player stat - replacement) / gap_per_standings_point
- Sum across categories = total SGP value

This is the standard roto valuation method and slots in as a third scoring mode alongside categories and points.

### 5. DD Adapter

A thin integration layer that:
- Reads DD's `valuation_config.py` weights/baselines and converts to `LeagueConfig`
- Maps DD's `HITTING_CATS` / `PITCHING_CATS` to `CategorySpec` objects
- Wraps DD's age curves, market calibration, RP tiers as post-processors
- Lets DD call `value_players()` instead of its inline z-score logic

This does NOT require refactoring DD immediately. The adapter sits alongside DD's existing code, and individual components can migrate incrementally.

### 6. DD 7x7 Preset

AWal's actual league categories as a preset:

**Hitting:** R, HR, RBI, SB, AVG, OPS, SO (inverse)
**Pitching:** K, QS, SV+HLD, L (inverse), ERA (inverse), WHIP (inverse), K/BB

With DD's actual weights and league baselines baked in, so `value_players(projections, dd_7x7())` produces values comparable to DD's current engine.

## Non-Goals (Intentionally Out of Scope)

- **UI/web app** — this is a Python package, not a product yet
- **Projection generation** — this engine consumes projections, doesn't create them
- **Live scoring / matchup simulation** — DD handles this separately
- **Trade analysis** — depends on team context, not just player values
- **ML models** — these sit on top of valuations, not inside the engine

## File Conventions

- Pitcher hits allowed use `H_ALLOWED` to avoid collision with hitter `H` (hits)
- All models are frozen dataclasses with `from_dict()` factory methods
- Category direction: `higher` = higher is better, `lower` = lower is better
- Pool: `hitter`, `pitcher`, `all`
- Tests live in `tests/` and run via `python -m unittest discover -s tests`

## Success Criteria

- Same projection set → different league configs → meaningfully different player rankings
- Volume-adjusted ratios: workhorse with good ERA outranks short reliever with great ERA
- Min denominator floors prevent small-sample inflation
- Fixed baselines produce stable values across runs
- Post-processors compose cleanly — DD can inject its adjustments without forking
- DD adapter produces values within 5% of DD's current engine for the same inputs
