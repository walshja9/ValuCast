# ValuCast

Player values tuned to your league.

ValuCast is a fantasy baseball valuation tool that combines 2026 actual stats with rest-of-season projections to produce season outlook rankings for any league format. Configure your scoring mode, categories, and weights — ValuCast handles the math.

**Live:** [valucast.onrender.com](https://valucast.onrender.com) (deployment pending)

## What It Does

- **Season outlook:** 2026 YTD actuals (MLB Stats API) + Steamer ROS projections (FanGraphs) = projected full-season stat lines
- **Any format:** H2H Categories, Roto (SGP), or Points leagues
- **26 categories:** 13 hitting + 13 pitching, with custom weights
- **SP/RP split:** Separate baselines for starters and relievers
- **Instant results:** No uploads, no accounts — pick your format, see rankings
- **CSV export:** Download filtered rankings

## Quick Start

```bash
# Install
pip install -r requirements.txt
pip install -e .

# Refresh data (fetches latest actuals + projections)
python -c "from scraper.refresh import refresh; refresh()"

# Run the web app
python app.py
# → http://localhost:5001
```

## Data Pipeline

```
MLB Stats API  →  scraper/mlb_actuals.py  →  data/actuals/current.json
                                                     ↓
FanGraphs API  →  scraper/fangraphs.py    →  scraper/combine.py  →  data/projections/current.json
               →  scraper/blend.py        →  data/projections/ros.json
```

- **Actuals:** MLB Stats API season stats + game logs (for QS derivation)
- **ROS:** Steamer Rest-of-Season projections via FanGraphs (`steamerr`)
- **Combine:** Counting stats add directly. Rate stats (AVG, ERA, WHIP, etc.) recalculated from combined components — never averaged.
- **IP normalization:** MLB API innings are in baseball notation (4.2 = 4⅔); adapter converts to decimal before arithmetic.

## Engine

The valuation engine is format-agnostic. A league config declares scoring mode, categories, weights, and roster settings. The engine produces z-scores (or SGP/points) against the player pool.

Post-processors adjust raw scores:

- **VolumeMultiplier** — discounts part-time players
- **ReplacementLevel** — anchors replacement-level players at zero
- **PositionScarcity** — premiums for scarce positions (C, SS)
- **AgeCurve** — dynasty age adjustments (hitter and pitcher curves)

### Presets

| Preset | Mode | Categories |
|---|---|---|
| `standard_5x5` | Categories | R, HR, RBI, SB, AVG / W, K, ERA, WHIP, SV |
| `default_points` | Points | Standard scoring coefficients |
| `dd_7x7` | Categories | 7 hitting / 6 SP / 6 RP with custom weights (internal) |

## Project Structure

```
src/league_values/     Engine: models, scoring, post-processors, presets
scraper/               Data pipeline: FanGraphs, MLB Stats API, combiner, refresh
web/                   Web layer: projection store, category registry, config builder
app.py                 Flask app (5 routes: /, /rankings, /player, /compare, /export)
templates/             Jinja2 + htmx templates
static/                CSS
data/                  Projections, actuals, metadata
tests/                 282 unit tests
```

## Tests

```bash
python -m pytest
```

## Roadmap

- [x] Valuation engine with z-score, roto, and points modes
- [x] FanGraphs data pipeline (Steamer ROS)
- [x] Web app with category setup, rankings, player detail, compare, CSV export
- [x] Season outlook: 2026 actuals + ROS projections
- [x] Tier visualization, position ranks, auction dollars
- [x] Dynasty mode (Beta) with combined MLB + prospect rankings
- [x] Prospect board with source ranks, breakout indicators, MiLB stats
- [ ] Dynasty league customization (scoring format, prospect depth, trade window)
- [ ] Render deployment
- [ ] Engine result caching for faster player detail loads
