# League Values

League Values is a standalone fantasy baseball valuation engine built around one idea:
the league configuration owns the math.

Instead of hardcoding one set of categories, every league declares:

- scoring mode: `categories`, `roto`, or `points`
- player pools: hitters, pitchers, or all players
- category direction: higher is better or lower is better
- category weight
- ratio-stat numerator, denominator, multiplier, and optional baseline
- points rules for points leagues

That lets one projection set produce different values for a 5x5 roto league, OBP/QS
league, saves-plus-holds league, or points league without rewriting the valuation code.
Post-processors (replacement level, position scarcity, age curve) apply on top of raw
scores to reflect real roster construction constraints.

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

## Scoring Modes

**Categories (z-score)** — each stat is z-scored against the player pool; weights scale
the contribution. This is the standard mode for head-to-head category leagues.

**Roto (SGP)** — standings gain points replaces z-scores. Pass `scoring_mode=ScoringMode.ROTO`
and set `sgp_denominator` on each `CategorySpec`. SGP measures how much one unit of a stat
moves a team up the standings, so a 1-HR improvement in a tight HR race is worth more than
the same HR in a blowout category.

**Points** — define `PointRule` entries on the league config. Each stat is multiplied by
its coefficient and summed. No pooling or z-scoring; raw point totals drive value.

## Post-Processors

Post-processors run after raw scores are computed and adjust values to reflect scarcity,
roster construction, and career trajectory.

```python
from league_values import ValuationEngine
from league_values.post_processors import AgeCurve, PositionScarcity, ReplacementLevel

engine = ValuationEngine(post_processors=[
    ReplacementLevel(),
    PositionScarcity(multipliers={"C": 1.00, "SS": 1.05, "OF": 0.97, "SP": 1.00, "RP": 0.55}),
    AgeCurve(
        hitter_curve={22: 1.65, 27: 1.25, 32: 0.87},
        pitcher_curve={22: 1.50, 27: 1.15, 32: 0.78},
    ),
])
results = engine.value_players(players, league)
```

- **ReplacementLevel** — shifts the value distribution so replacement-level players anchor
  at zero. Players below replacement go negative; stars read as surplus above zero.
- **PositionScarcity** — multiplies each player's value by a position coefficient. Scarce
  positions (catcher, shortstop) get a premium; deep positions (OF) get a slight discount.
  RP are heavily discounted by default since their counting-stat volume is low.
- **AgeCurve** — applies a multiplier based on player age and pool (hitter vs pitcher).
  Values between curve breakpoints are linearly interpolated; values outside the range
  clamp to the nearest endpoint.

## Presets

Three built-in presets cover the most common league formats:

| Preset | Mode | Categories |
|---|---|---|
| `standard_5x5` | Categories | R, HR, RBI, SB, AVG / W, K, ERA, WHIP, SV |
| `default_points` | Points | Standard ESPN/Yahoo scoring coefficients |
| `dd_7x7` | Categories | R, HR, RBI, SB, AVG, OBP, XBH / W, K, ERA, WHIP, SV, HLD, QS |

```python
from league_values.presets import standard_5x5, dd_7x7

league = standard_5x5()
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

- `src/league_values/models.py` — league config, category specs, points rules, player projections, roster settings
- `src/league_values/engine.py` — category z-score, roto SGP, and points league scoring
- `src/league_values/post_processors.py` — ReplacementLevel, PositionScarcity, AgeCurve
- `src/league_values/presets.py` — standard_5x5, default_points, dd_7x7
- `src/league_values/config_loader.py` — JSON/dict config deserialization
- `examples/` — sample league configs and demo input
- `tests/` — behavior tests for all scoring modes and post-processors

## Next Useful Milestones

1. Add auction dollar conversion (translate surplus value to $ budget).
2. Add keeper/dynasty modifiers (contract years, keeper cost discount).
3. Add DD adapter (wire DD projection exports directly into this engine).
4. Wrap with an API or app UI for league setup.
