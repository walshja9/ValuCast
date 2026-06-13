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
| ValuCast prospect board | Prospects are ordered by the ValuCast Universal Prospect Index and joined to DD feed rows for identity, cards, source-rank context, and MiLB details. | Independent ValuCast prospect opinion, not DD order. |
| ValuCast dynasty board | Still uses the legacy DD dynasty feed value/order. | Beta/legacy bridge, not the final independent ValuCast dynasty model. |
| DD prospect board | DD ranks and values players for the Diamond Dynasties league. | DD league value. |
| DD Statistical Lens | DD compares its live prospect value against a ValuCast DD 7x7 adapter output. | Research-only disagreement lens; it does not change DD rank or value. |

The important gap is the ValuCast dynasty board. Prospects are no longer simply
mirroring DD, but the combined dynasty view still needs its own ValuCast-owned
value model.

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
