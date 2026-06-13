# ValuCast and Diamond Dynasties Boundary

## Short Version

ValuCast should be the independent baseball and dynasty opinion. Diamond
Dynasties should be a league product that can consume, compare, and adapt that
opinion for one specific 12-team 7x7 dynasty league.

DD can help collect factual inputs and can display ValuCast disagreements. DD
should not define ValuCast's model targets, rankings, or values.

## Why This Exists

The two products are related, but they should not collapse into the same thing:

- ValuCast answers: "What does our independent model think this player or
  prospect is worth?"
- Diamond Dynasties answers: "What is this player worth in our league, with our
  scoring, rosters, owners, market behavior, and trade context?"

That distinction matters because ValuCast is meant to become portable. One
ValuCast player profile should eventually support 5x5, DD 7x7, points, OBP, and
custom-league rankings through adapters. DD is one adapter and one product
surface, not the source of truth for the universal model.

## Current Live State

As of June 13, 2026:

| Surface | Current behavior | Product meaning |
| --- | --- | --- |
| ValuCast season rankings | ValuCast combines MLB actuals and rest-of-season projections into configurable redraft-style rankings. | Independent ValuCast season outlook. |
| ValuCast prospect board | Still uses the legacy DD prospect feed value/order after the Universal Index live trial was reverted. | Beta/legacy bridge, not the final independent ValuCast prospect model. |
| ValuCast dynasty board | Still uses the legacy DD dynasty feed value/order. | Beta/legacy bridge, not the final independent ValuCast dynasty model. |
| DD prospect board | DD ranks and values players for the Diamond Dynasties league. | DD league value. |
| DD Statistical Lens | DD compares its live prospect value against a ValuCast DD 7x7 adapter output. | Research-only disagreement lens; it does not change DD rank or value. |

The important gap is the ValuCast-owned public snapshot. Dynasty, Prospects,
and Buys still depend on DD-generated public rows in production. ValuCast now
has shadow prospect model pieces and a DD adapter, but those artifacts are not
publication-grade replacements for the public boards yet.

## Allowed Boundaries

DD may provide:

- sanitized factual exports for ValuCast training
- MLBAM identity and role matching
- display context, such as player cards, MiLB stat snippets, team, level, and
  source-rank context
- DD rank/value as clearly labeled comparison context

ValuCast may provide:

- universal player and prospect profiles
- dynasty values on a ValuCast-owned scale
- league adapters that translate a universal profile into 5x5, DD 7x7, points,
  OBP, or custom settings
- disagreement feeds that DD can inspect without mutating DD values

## Prohibited Boundaries

ValuCast models should not train on or target:

- DD dynasty ranks or values
- DD trade-market behavior
- public prospect rankings such as STS, CFR, Pipeline, or HKB
- external projections as prospect-model truth
- any adapter output as if it were the universal model

Public rankings and DD values can be shown as context, comparison, or market
signals. They should not occupy the seat where ValuCast's own model belongs.

## Intended Pipeline

The intended long-term flow is:

```text
factual player data
  -> ValuCast universal player/prospect profiles
  -> ValuCast dynasty value
  -> league adapters
  -> DD 7x7, 5x5, points, OBP, and custom-league rankings
```

The current system has pieces of this pipeline, but it is not complete. The
missing center piece is a ValuCast Dynasty Value model that puts MLB players
and prospects on one independent dynasty scale.

## Prospect Rank v1 Candidate

`prospects/rank_v1.py` builds `data/models/valucast_prospect_rank_v1.json`.
This is a candidate shadow artifact, not a live-board switch.

The rank score may use:

- ValuCast's shadow prospect model scores
- ValuCast's universal dynasty ceiling/risk layer
- factual sample reliability
- factual Rule 4 draft-pick and signing-bonus context

It may not use:

- DD dynasty ranks or values
- DD prospect ranks
- DD value history
- public prospect source ranks
- DD 7x7 adapter score or rank

`prospects/universe.py` builds the ValuCast-owned candidate universe from
ValuCast prospect model artifacts. DD feed rows may add optional
display/comparison context by MLBAM ID plus role, but DD no longer defines
Rank v1 membership. The artifact reports coverage gaps and migration blockers
so it cannot quietly replace the production feed.

```powershell
python scripts/build_prospect_universe.py
python scripts/build_prospect_rank_v1.py
```

## Current Shadow Build

ValuCast now publishes a shadow gate artifact at
`data/public/public_dynasty_snapshot.json`. That snapshot proves the public
schema, freshness, source-policy, duplicate-identity, and field-validation
rails before any live switch.

The snapshot includes:

- `data/models/valucast_mlb_dynasty_layer.json`, a ValuCast-owned MLB
  projection-value layer built from the app's projection engine
- `data/models/valucast_prospect_rank_v1.json`, a ValuCast-owned prospect
  candidate board built from the ValuCast prospect universe

It is intentionally not ready for public consumers yet because:

- current projection artifacts do not include an owned age source, so the MLB
  layer cannot apply a dynasty age curve
- the MLB layer is still one-season projection value, not a multi-year dynasty
  horizon
- MLB and prospect scores are not yet calibrated onto one cross-universe
  dynasty scale
- ValuCast-owned buy inputs are still missing

## Next Build

Build ValuCast Dynasty Value v1.

It should combine:

- MLB projection value from ValuCast's season/projection engine
- prospect future value from the universal prospect profile and dynasty layer
- age, risk, playing-time confidence, role probability, and ceiling/bust shape
- position scarcity and replacement-level context
- a dynasty horizon that can compare current MLB value against future prospect
  value

That model should publish:

- a ValuCast dynasty score
- a ValuCast dynasty rank
- clear provenance explaining whether a player's value is coming mostly from
  current MLB production, future projection, prospect upside, or risk-adjusted
  dynasty profile

After that, league adapters can translate the ValuCast profile into:

- DD 7x7 value
- standard 5x5 value
- points value
- custom-league value

The DD adapter should adapt ValuCast to DD. It should not become ValuCast.

## Product Labeling Rule

If a ValuCast screen is using DD value/order, label it as DD context or legacy
beta. Do not present it as an independent ValuCast value.

If a DD screen is using ValuCast output, label it as a ValuCast model,
ValuCast adapter, or research lens. Do not imply that it changes DD value unless
the DD model intentionally consumes it.

This keeps both products honest:

- ValuCast becomes the independent model company.
- DD becomes the sharpest implementation of that thinking for one real dynasty
  league.
