# International Investment-Evidence Repair

**Date:** 2026-07-22
**Decision:** Apply the 13 verified bonuses only to Prospect Rank v1's factual-investment component after review; keep both trained prospect models frozen.

## Result

The currently published scoring input has signing or draft context for 19 of 32 top-50 hitters (59.4%). MLB Pipeline provides source-backed international signing bonuses for all 13 missing hitters. The candidate rank-local correction raises top-50 hitter scoring coverage to 32 of 32 (100%).

The distinction is deliberate:

- The bonuses feed only the existing factual-investment rank component.
- They are not merged into `prospect_model_inputs.json`.
- The v0.6 and universal models therefore remain unchanged.
- The candidate changes final ranks and values but is not published yet.

## Current coverage

| Board band | Currently published | Candidate correction |
|---|---:|---:|
| Top 25, all | 19/25 (76.0%) | 25/25 (100%) |
| Top 25, hitters | 9/15 (60.0%) | 15/15 (100%) |
| Top 50, all | 37/50 (74.0%) | 50/50 (100%) |
| Top 50, hitters | 19/32 (59.4%) | 32/32 (100%) |
| Top 100, all | 77/100 (77.0%) | 90/100 (90.0%) |
| Top 200, all | 156/200 (78.0%) | 169/200 (84.5%) |

## Governance

The sourced records live in `data/prospects/raw/international_signing_facts.json`. Every row is keyed by MLBAM ID and includes the bonus, source name, source URL, and verification date. Prospect Rank v1 validates and overlays them onto a rank-local copy of current hitter inputs. Invalid, duplicate, unmatched, or conflicting evidence blocks the build.

The evidence cannot feed the v0.6 or universal model. A later registered challenger must test whether international investment predicts future outcomes beyond the existing factual rank component; this correction does not assume that spending equals skill.

Publication remains gated on independent review, final Codex verification, and explicit user approval. The model freeze, failed pedigree-decay flag, pitcher cap, governor, holds, and public-claim policy remain unchanged.
