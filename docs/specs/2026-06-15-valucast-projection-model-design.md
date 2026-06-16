# ValuCast Projection Model — Design Doc (P2)

> 2026-06-15. Scope decision first, then the v1 spec. Read with
> `docs/valucast-methodology.md` (the engine reference) open.

> **STATUS UPDATE (2026-06-16).** The "v1 artifact" this doc proposed building
> ALREADY EXISTS and ships: `scripts/build_validation_scorecard.py` →
> `data/validation/methodology_scorecard.json`, rendered on `/methodology` (hitting
> vs classic Marcel, pitching vs persistence, per-stat MAE ratios, sample sizes,
> corr-win-rates, a `not_shipped` honesty block, and an explicit no-Steamer/ZiPS
> disclaimer). The premise below that "the MLB Marcel engine has no published
> accuracy artifact" was WRONG — I'd missed `build_validation_scorecard.py`.
> So we did NOT build a second artifact. This pass added only:
> (1) `scripts/validate_projection_scorecard.py` — an honesty validator that fails
> if the artifact swaps in an unsupported baseline or claims an external-model
> comparison win (tokens allowed only under `not_shipped`), or drops sample
> size / MAE ratio / corr-win-rate / `generated_at`;
> (2) `generated_at` emitted by the builder + backfilled into the committed artifact;
> (3) `tests/test_projection_scorecard.py`;
> (4) `/methodology` heading renamed to "MLB Projection Track Record".
> The rest of this doc is kept for the reasoning trail; treat the artifact spec as
> describing the already-shipped `methodology_scorecard.json`, not a new file.

## The decision: don't build a new model

The projection engine already exists and already validates. `projections/models/`
is a full Marcel hitter + pitcher engine (Statcast de-noise, reliability,
role-routing, tuning), and `projections/backtest/harness.py` runs a leakage-safe
rolling-origin backtest that scores it against persistence and classic-Marcel
baselines. The honesty audit passed — no external ranks, DD values, or market
values touch any scoring path.

So the gap is **not** modeling. It's that the MLB Marcel engine — our strongest
surface — has no *published, versioned* accuracy artifact. Its numbers (rate-stat
MAE ratio ~0.979 hitting, ~0.821 pitching skill) live only as prose in the
internal methodology doc. The prospect side, by contrast, ships
`data/models/valucast_prospect_outcome_backtest.json` and the app can render it.

v1 = close that asymmetry. Export the Marcel backtest as a versioned scorecard
artifact the same way the prospect outcome backtest is exported, so ValuCast can
*show* projection accuracy without anyone hand-copying numbers into a template.

No new model. No new inputs. No new claims.

<!-- ponytail: v1 is "publish what we already compute," not "compute something new." -->

## What v1 builds

One generator script + one JSON artifact + one read path. Mirror the existing
prospect pattern exactly (`scripts/validate_prospect_outcome_backtest.py` →
`data/models/valucast_prospect_outcome_backtest.json` → web reader).

### 1. Generator — `scripts/build_projection_scorecard.py`

Thin wrapper over what already runs:

- Call `projections.backtest.harness.rolling_origin(target_seasons, ...)` for
  hitting and `projections.backtest.pitching_harness` for pitching, over the same
  held-out target seasons the rung program already uses.
- Emit one JSON to `data/models/valucast_projection_scorecard.json`.
- No new metrics. The harness already returns per-stat `marcel_mae`,
  `persistence_mae`, `mae_ratio`, `marcel_corr`, `eval_n`, plus the rolled-up
  `mean_mae_ratio` / `corr_win_rate` / `beats_persistence` verdict. The script
  just serializes that.

### 2. Artifact contract — `valucast_projection_scorecard.json`

Reuse the prospect-artifact envelope so the web reader and tests are familiar:

```json
{
  "artifact": "valucast_projection_scorecard",
  "report_name": "ValuCast Projection Accuracy",
  "report_version": "0.1.0",
  "generated_at": "2026-06-15T00:00:00+00:00",
  "source_policy": {
    "external_projections_used": false,
    "dd_values_used": false,
    "market_values_used": false,
    "kind": "held_out_rolling_origin_backtest"
  },
  "target_seasons": [2018, 2019, 2021],
  "hitting": {
    "eval_n_by_season": { "2021": 312 },
    "headline": { "mean_mae_ratio": 0.979, "corr_win_rate": 0.83,
                  "beats_persistence": true },
    "per_stat": { "OPS": { "marcel_mae": 0.0, "persistence_mae": 0.0,
                           "mae_ratio": 0.0, "marcel_corr": 0.0 } }
  },
  "pitching": { "...": "same shape, skill-stat headline" }
}
```

Numbers above are placeholders — the generator fills them from the live harness.

**Honesty guardrails (load-bearing, not decoration):**
- `mae_ratio < 1.0` is the only "beats baseline" claim allowed. No "most
  accurate," no "beats Steamer." The archived-Steamer benchmark is still pending
  (methodology doc, "Validation discipline") — until it exists, the artifact
  compares to persistence and classic Marcel *only*, and labels say exactly that.
- Report rungs that **tied or lost** with the same prominence as wins (Reliability
  Rung 2 = tie, Barrel→HR Rung 4 = killed, own-xBA Phase A = shortfall). The
  scorecard's credibility is that it shows the misses.
- `source_policy` block asserts the no-external-input contract, same as the
  prospect artifact's. A test pins it.

### 3. Read path

Cheapest honest surface first: the artifact feeds the existing `/methodology`
page (a "Projection accuracy" section that reads the JSON instead of hardcoding
the ~0.979 figure). Player-card per-row accuracy badges are explicitly **out of
v1** — per-player projection error is noisier than the population MAE ratio and
invites false precision. Add later only if a real product need shows up.

### 4. One test — `tests/test_projection_scorecard.py`

Asserts: artifact validates against the envelope, `source_policy` external flags
are all `false`, every headline `beats_persistence` claim matches its
`mean_mae_ratio < 1.0`, and tie/loss rungs are present (not silently dropped).

## What v1 deliberately skips

- **A new projection model / new inputs.** YAGNI. The engine wins its gates today.
- **Steamer head-to-head.** Needs archived preseason Steamer; that's its own
  effort with its own spec (it's already on the methodology backlog). v1 must not
  imply it.
- **Per-player accuracy on cards.** False-precision risk; no product pull yet.
- **Unifying the prospect-peak and MLB value surfaces** (the memory's "candidate
  2"). Real, but it's a value-model refactor, not a projection-accuracy artifact —
  separate doc.

## Why this is the right v1

It ships projection *credibility* (the launch angle Alex wants — lead with
`/methodology` honesty, never "beats Steamer") for the cost of a wrapper script
and a JSON file, reusing a pattern that already passed review on the prospect
side. Everything bigger is a separate, spec'd effort.
