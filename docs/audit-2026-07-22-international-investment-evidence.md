# International Investment-Evidence Repair

**Date:** 2026-07-22
**Decision:** Close the top-50 evidence gap without changing the frozen prospect model, ranks, values, or publication policy.

## Result

The live scoring input still has signing or draft context for 19 of 32 top-50 hitters (59.4%). MLB Pipeline provides source-backed international signing bonuses for all 13 missing hitters. With those records included as observational evidence, top-50 hitter coverage is 32 of 32 (100%).

The distinction is deliberate:

- **Scoring-input coverage** reports only what the current frozen model receives.
- **Verified evidence coverage** reports either existing scoring context or a source-backed signing bonus.
- Verified evidence is not merged into `prospect_model_inputs.json`, does not receive a model weight, and cannot change a rank or value.

## Current coverage

| Board band | Frozen scoring input | Verified evidence |
|---|---:|---:|
| Top 25, all | 19/25 (76.0%) | 25/25 (100%) |
| Top 25, hitters | 9/15 (60.0%) | 15/15 (100%) |
| Top 50, all | 37/50 (74.0%) | 50/50 (100%) |
| Top 50, hitters | 19/32 (59.4%) | 32/32 (100%) |
| Top 100, all | 77/100 (77.0%) | 90/100 (90.0%) |
| Top 200, all | 156/200 (78.0%) | 169/200 (84.5%) |

## Governance

The sourced records live in `data/prospects/raw/international_signing_facts.json`. Every row is keyed by MLBAM ID and includes the bonus, source name, source URL, and verification date. The coverage audit consumes the file only in its `verified_evidence` lane.

Moving these facts into scoring remains a future registered challenger decision. That later study must measure whether investment context improves forward outcomes; this repair does not assume that spending equals skill.

The model freeze, failed pedigree-decay flag, pitcher cap, governor, holds, and public-claim policy remain unchanged.
