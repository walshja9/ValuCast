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
| ValuCast prospect board | Uses the ValuCast public snapshot when `VALUCAST_USE_PUBLIC_SNAPSHOT=1` and the quality governor approves it; otherwise falls back to the DD feed. | Independent ValuCast prospect board, fail-closed to legacy DD feed if the snapshot is not ready. |
| ValuCast dynasty board | Uses the ValuCast public snapshot when `VALUCAST_USE_PUBLIC_SNAPSHOT=1` and the quality governor approves it; otherwise falls back to the DD feed. | Independent ValuCast dynasty board, fail-closed to legacy DD feed if the snapshot is not ready. |
| ValuCast buys board | Uses the ValuCast-owned buy artifact when the public snapshot is active and the buy artifact passes its review/history gate; `VALUCAST_USE_VALUCAST_BUYS=0` is the rollback switch. | Independent ValuCast buy surface, fail-closed to the legacy DD-backed board if the artifact is not ready. |
| DD prospect board | DD ranks and values players for the Diamond Dynasties league. | DD league value. |
| DD Statistical Lens | DD compares its live prospect value against a ValuCast DD 7x7 adapter output. | Research-only disagreement lens; it does not change DD rank or value. |

The public surfaces now have separate gates. Dynasty and Prospects consume the
ValuCast public snapshot once the snapshot is same-day fresh and the quality
governor approves it. Buys consumes the ValuCast-owned buy artifact only after
its buy-review gate approves the launch; otherwise it fails closed to the
legacy DD-backed board.

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

The current system now has a ValuCast public snapshot that places MLB players
and prospects on one independent dynasty scale for Dynasty and Prospects. The
remaining pipeline work is to keep hardening that model, accumulate dated
ValuCast history, and promote league adapters and Buys only when their gates
pass.

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

## Current Public Snapshot Gate

ValuCast publishes a gate artifact at
`data/public/public_dynasty_snapshot.json`. That snapshot proves the public
schema, freshness, source-policy, duplicate-identity, field-validation, and
cross-universe calibration rails before Dynasty/Prospects can consume it.

The snapshot includes:

- `data/models/valucast_mlb_dynasty_layer.json`, a ValuCast-owned MLB
  projection-value layer built from the app's projection engine
- `data/models/valucast_mlb_track_record.json`, a ValuCast-owned MLB
  track-record contract built from official year-by-year MLB history and
  ValuCast current actuals
- `data/models/valucast_prospect_rank_v1.json`, a ValuCast-owned prospect
  candidate board built from the ValuCast prospect universe
- `data/models/valucast_prospect_buys.json`, a ValuCast-owned buy-signal
  artifact built from ValuCast Rank v1 rather than DD value history or public
  source-rank gaps
- `data/models/valucast_quality_governor.json`, a ValuCast-owned promotion
  gate that reviews the generated boards for baseball-sanity blockers before
  Dynasty/Prospects can treat them as official

It has two separate readiness concepts:

- `ready_for_live_consumers` means the snapshot can feed Dynasty/Prospects
  instead of the DD feed. This requires the quality governor to pass.
- `ready_for_all_public_surfaces` means Dynasty, Prospects, and Buys all have
  approved ValuCast-owned live artifacts.

The MLB layer now has a ValuCast-owned identity age source, a three-year
dynasty horizon, an annualized ROS true-talent prior, and a factual MLB
track-record contract. The prior scales rest-of-season projections back to
season-level context before comparing them to the current full-season line. The
track-record contract contributes career/prior/current/recent MLB volume,
experience bands, certainty, and bounded support floors from official
year-by-year history. These are projection-sanity rules, not name overrides,
and they do not use DD values, DD ranks, public ranks, or market lists. Track
record can support established players and discount limited-history spikes, but
it cannot bypass the pure-reliever dynasty cap. The cross-universe gate
certifies MLB and prospect rows on the shared `0_100_valucast_dynasty_score`
scale without mutating the underlying raw scores. The `/buys` switch remains
separately gated by `ValuCastBuyStore`, so a calibrated Dynasty/Prospects
snapshot cannot accidentally promote an unreviewed buy board.

The quality governor is not a scoring input. It does not train the model and it
does not use DD ranks, DD values, public ranks, or market values to change a
score. It is a publication brake. Current checks include:

- top-board MLB value spikes
- two-way identities split into separate hitter/pitcher public rows without a
  combined-value policy
- fallback-heavy top prospect rankings
- pedigree-only top prospect concentration
- top prospects leaning too heavily on neutral draft/signing context
- missing MLB-org display coverage near the top of the prospect board
- Prospect Rank v1 rows suppressed from the visible public prospect surface
- MLB projection rows with extreme current-over-ROS gaps near the top of the
  Dynasty board
- top-board MLB role shape, so pitcher or reliever runs cannot dominate the
  published Dynasty board
- exact pedigree-cap tie clusters near the top of the prospect board
- Buy promotion readiness, including review status and ValuCast score-history
  depth

The current Dynasty/Prospects gate can pass independently of Buys. That is
intentional: ValuCast's canonical public snapshot may be fit for board display
while the Buy board remains shadow-only until it has enough ValuCast score
history and explicit review approval.

Buy approval is an explicit release action, not a scheduled default. The daily
public-data workflow keeps `VALUCAST_BUYS_REVIEW_APPROVED=0`; a manual workflow
dispatch may set `approve_valucast_buys=true` to record human review approval
and regenerate the Buy artifact with the promotion gate open. The public route
still requires `VALUCAST_USE_VALUCAST_BUYS=1` and `ValuCastBuyStore` validation
before `/buys` can serve ValuCast-owned signals.

Two model-quality rules are now part of the public snapshot path:

- MLB two-way rows publish as one player with hitter/pitcher components instead
  of separate public Dynasty rows.
- MLB dynasty values use an internal ROS-stability adjustment so one extreme
  current-season line cannot define the whole top of the board by itself.
- Young hitters and limited-sample starters receive transparent volatility
  haircuts when current-season value is materially ahead of annualized ROS
  true talent.
- MLB track-record context can apply bounded established-player support floors
  and limited-history discounts, but cannot lift pure relievers above the
  reliever dynasty cap.
- Prospect pedigree fallback rows compress below their cap instead of tying at
  the same capped score, so high-investment low-minors prospects can surface
  without creating an arbitrary plateau.
- Prospect pedigree-only rows have a lower ceiling than model-backed rows, and
  the quality governor blocks the public snapshot if the top 50 leans too
  heavily on pedigree-only scoring.
- Prospect rows win publication conflicts against weak MLB projection rows
  until the prospect is explicitly marked as MLB-level or the MLB row is a
  material current-value promotion. A low present-day projection row should not
  erase a higher-confidence prospect future-value row, but a real current MLB
  contributor should not be demoted by stale prospect context.
- Quality-governor prospect checks run against the final visible public
  prospect surface, not only against the pre-merge Rank v1 artifact.

## Next Build

Promote ValuCast-owned Buys only after the buy gate passes and keep hardening
ValuCast Dynasty Value with dated forward evidence. The next model-calibration
inputs should be injury/playing-time context, role probability, position
scarcity, and forward validation against archived ValuCast outcomes. The MLB
track-record contract now separates projection upside from dynasty certainty at
the factual-history level; the next step is proving and tuning those weights
against future dated archives without borrowing DD values, public ranks, or
market lists.

The canonical model should keep combining:

- MLB projection value from ValuCast's season/projection engine
- prospect future value from the universal prospect profile and dynasty layer
- age, risk, playing-time confidence, role probability, and ceiling/bust shape
- position scarcity and replacement-level context
- a dynasty horizon that can compare current MLB value against future prospect
  value

The model should keep publishing:

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
