# Prospect Investment-Context Coverage Audit

**Date:** 2026-07-21
**Decision:** Repair investment-data coverage before using draft or signing context in a public comparison surface. Do not change the model, ranks, values, or publication policy from this audit.

## Answer first

The current Prospect Rank v1 board passes its existing score-source coverage gate: all top-200 players have a non-raw score source, so the root coverage status remains `candidate_ready`. That verdict does **not** mean every contextual input is complete.

Draft/signing investment context is missing for 45 of the top 200 players, and the gap is concentrated among hitters. The new audit section reports that incompleteness separately as `investment_context.status = incomplete`; it is observational and explicitly cannot change the root readiness status.

## Current coverage

| Board band | All prospects | Hitters | Pitchers |
|---|---:|---:|---:|
| Top 25 | 19/25 (76.0%) | 9/15 (60.0%) | 10/10 (100.0%) |
| Top 50 | 38/50 (76.0%) | 20/32 (62.5%) | 18/18 (100.0%) |
| Top 100 | 77/100 (77.0%) | 42/61 (68.9%) | 35/39 (89.7%) |
| Top 200 | 155/200 (77.5%) | 80/114 (70.2%) | 75/86 (87.2%) |

“Covered” means `factual_investment_context` is present in the current rank artifact. “Missing” means the field is null; it does not prove that the player had no meaningful draft or signing investment.

## Four-player comparison case

The current board separates the four hitters even before any public side-by-side presentation:

| Player | VC rank | VC score | Investment context | MLB-translated K% | MLB-translated BB% | MLB-translated ISO |
|---|---:|---:|---:|---:|---:|---:|
| Eli Willits | 2 | 68.12 | 100 | 26.0% | 12.4% | .138 |
| Franklin Arias | 8 | 54.94 | missing | 18.4% | 9.4% | .183 |
| Jesús Made | 16 | 48.51 | missing | 18.7% | 8.9% | .136 |
| Leo De Vries | 35 | 41.64 | missing | 23.6% | 9.8% | .133 |

That is enough to support a transparent comparison of current skill and sample context. It is not enough to interpret the full rank separation as a clean test of draft/signing investment, because only one of the four has that field populated.

## What the sensitivity bound means

For a v0.6-scored prospect, the direct Rank v1 investment component has a 0.06 weight. A missing value is currently scored at 25. Replacing that configured missing score with the maximum possible context score of 100 would add at most:

`0.06 × (100 - 25) = 4.5 score points`

All 12 top-50 hitters with missing investment context have that same 4.5-point direct upper bound in the artifact. This is deliberately **not** a counterfactual rank:

- the upstream v0.6 `model_score` is held fixed;
- no player is assumed to deserve a score of 100;
- no board is reranked;
- any upstream effect of draft/signing inputs remains unmeasured here.

The bound answers only, “How much can the direct Rank v1 component move if every other input is frozen?” It cannot tell us where a player should rank after the missing data is repaired.

## Product and model recommendation

1. Repair and verify draft/signing coverage, starting with top-50 hitters and identity joins.
2. Keep the field labeled as context, not skill evidence and not a scouting grade.
3. Build the proposed four-player comparison from current skill, opportunity/sample, and ValuCast Value only after the inputs shown are definitionally consistent.
4. Re-run this audit after the data repair. Then measure whether investment context improves forward outcomes through the registered post-2026 challenger process in Plan 034.
5. Until that test exists, do not increase its weight, impute a neutral value, publish rank counterfactuals, or claim that it explains the current rank differences.

## Governance

- Model, ranking, value, pitcher cap, governor, hold, and publication behavior: unchanged.
- Root coverage decision: unchanged (`candidate_ready`).
- Investment-context decision: incomplete, observational, and non-blocking.
- Failed pedigree-decay flag and existing model freeze: preserved.
- Public superiority claim: not authorized by this audit.

## Evidence

- `data/models/valucast_prospect_rank_v1.json` — current board, score sources, translated rates, and investment fields.
- `data/models/valucast_prospect_coverage_audit.json` — version 0.2.0 coverage bands and direct-component sensitivity bounds.
- `prospects/rank_v1.py` — configured score-source weights and missing-investment score.
- `prospects/coverage_audit.py` — observational coverage and sensitivity calculation.
