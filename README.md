# ValuCast

Player values tuned to your league.

ValuCast combines independent prospect intelligence with league-specific fantasy baseball values. It supports season outlook rankings, combined MLB/prospect dynasty boards, player comparisons, and trade decisions. Configure your scoring mode, categories, and weights to translate the available player evidence into your league's settings.

The public product and experimental research lineages have separate release gates. A research checkpoint or fitted model does not replace the public board. Product direction is recorded in the [positioning design](docs/superpowers/specs/2026-08-04-valucast-positioning-messaging-design.md); dated plans record their own scope and approval state.

**Live:** [valucast.app](https://valucast.app)

## What It Does

- **Season outlook:** 2026 YTD actuals (MLB Stats API) + Steamer ROS projections (FanGraphs) = projected full-season stat lines
- **Any format:** H2H Categories, Roto (SGP), or Points leagues
- **26 categories:** 13 hitting + 13 pitching, with custom weights
- **SP/RP split:** Separate baselines for starters and relievers
- **Instant results:** No uploads, no accounts — pick your format, see rankings
- **CSV export:** Download every matching dynasty/prospect asset, with source dates and prospect publication status
- **Dynasty and prospects:** League-aware rankings, player context, and trade analysis
- **Evidence:** Methodology, historical boards, and tracked calls with explicit readiness limits

## Quick Start

```bash
# Install
pip install -r requirements.txt
pip install -e .

# Run the web app with the committed data snapshot
python app.py
# → http://localhost:5001
```

The Prospects board combines hitters and pitchers into one list and keeps each two-way player once, using the best-ranked role. Use **Show all prospects** to view the full pool; **Export all matches CSV** includes every match regardless of the display limit. League filters and sorting apply to both. The stored prospect rank remains visible, so removing a duplicate role can leave a rank gap.

For a complete data refresh, use the existing `daily-public-data.yml` workflow. Running only `scraper.refresh` updates MLB projections, not the full prospect pipeline. Publication stays atomic after all validators pass. The site displays the snapshot date and overdue refresh warning; `/health/ready` reports serving readiness separately from data freshness and prospect qualification.

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
- **Daily publish:** GitHub Actions refreshes actuals, Steamer ROS, Statcast player-card data, DD factual prospect inputs, the ValuCast public dynasty snapshot, ValuCast-owned buy signals, and prospect forward-validation reports each morning, then deploys only after same-day freshness checks pass.
- **Dynasty migration:** `data/public/public_dynasty_snapshot.json` is ValuCast's canonical-publisher gate. Dynasty, Prospects, and Buys can consume ValuCast-owned artifacts once the quality governor and buy-review gates mark them ready for live consumers.

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
app.py                 Flask app (/, /rankings, /player, /compare, /export, /league-import, /methodology, /health/ready)
templates/             Jinja2 + htmx templates
static/                CSS
data/                  Projections, actuals, metadata
tests/                 unit and integration tests
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
- [x] Dynasty league customization (scoring format, prospect depth, trade window)
- [x] Render service configuration and gated deployment workflows
- [x] Canonical valuation and share-card caching
- [ ] Reuse cached canonical values throughout player detail and compare routes

## Deploy
Run `powershell -File scripts/deploy.ps1` from a clean `master` working tree.
Set `RENDER_DEPLOY_HOOK` to the Render deploy-hook URL to explicitly trigger the deployment.
Manual fallback: Render dashboard → `valucast` service → Manual Deploy → Deploy latest commit.
