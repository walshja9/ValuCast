# League Values

League Values is a standalone fantasy baseball valuation engine built around one idea:
the league configuration owns the math.

Instead of hardcoding one set of categories, every league declares:

- scoring mode: `categories` or `points`
- player pools: hitters, pitchers, or all players
- category direction: higher is better or lower is better
- category weight
- ratio-stat numerator, denominator, multiplier, and optional baseline
- points rules for points leagues

That lets one projection set produce different values for a 5x5 roto league, OBP/QS
league, saves-plus-holds league, or points league without rewriting the valuation code.

## Quick Start

```powershell
$env:PYTHONPATH = "src"
python examples/run_demo.py
```

```python
from league_values import CategorySpec, LeagueConfig, PlayerPool, ScoringMode, value_players

league = LeagueConfig(
    name="Power league",
    scoring_mode=ScoringMode.CATEGORIES,
    categories=(
        CategorySpec(id="HR", label="Home Runs", pool=PlayerPool.HITTER, stat="HR", weight=2),
        CategorySpec(id="RBI", label="RBI", pool=PlayerPool.HITTER, stat="RBI"),
    ),
)

players = [
    {"id": "1", "name": "Power Bat", "pool": "hitter", "stats": {"HR": 42, "RBI": 108}},
    {"id": "2", "name": "Speed Bat", "pool": "hitter", "stats": {"HR": 12, "RBI": 62}},
]

for result in value_players(players, league):
    print(result.name, round(result.total_value, 2))
```

## Ratio Categories

Ratio categories are volume-adjusted. A player hitting `.320` over `600 AB` can be more
valuable than a player hitting `.350` over `100 AB` because the engine values category
impact, not just the raw rate.

For example, batting average can be configured as:

```json
{
  "id": "AVG",
  "label": "Batting Average",
  "pool": "hitter",
  "numerator_stats": ["H"],
  "denominator_stats": ["AB"],
  "direction": "higher"
}
```

ERA can be configured as:

```json
{
  "id": "ERA",
  "label": "ERA",
  "pool": "pitcher",
  "numerator_stats": ["ER"],
  "denominator_stats": ["IP"],
  "ratio_multiplier": 9,
  "direction": "lower"
}
```

## Project Shape

- `src/league_values/models.py`: league config, category specs, points rules, player projections
- `src/league_values/engine.py`: category z-score valuation and points league scoring
- `src/league_values/presets.py`: standard 5x5 and starter points presets
- `examples/`: sample league configs and demo input
- `tests/`: behavior tests for config-driven scoring

## Next Useful Milestones

1. Add roster settings and replacement-level valuation by position.
2. Add auction dollar conversion.
3. Add keeper/dynasty modifiers.
4. Add import adapters for DD projections.
5. Wrap this package with an API or app UI for league setup.
