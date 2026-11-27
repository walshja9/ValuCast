# Prospect Evidence Improvement — Fable Review Packet

## Review range

- Base: `1d0650b939a4ef7472b5064a6e928f89064c6e94`
- Implementation head: `37bf9ab0e0d6a218dc16097edfe903992ae9c6fd`
- Branch: `codex/prospect-evidence-improvement`
- This packet is a later documentation-only commit and is intentionally outside the implementation range.

## Binding constraints

- The live prospect model, Rank v1, universal model, model freeze, failed-decay flag, pitcher publication veto, pitcher cap, and Role Watch must not change.
- Consensus, scouting/FV, competitor outputs, market values, and current ValuCast order are context or post-freeze evaluation only.
- Draft position, verified signing investment, position, availability, and factual playing-time evidence remain permitted.
- Plan 034, C1, C2, and the MLB pitcher challenger outer look remain unspent.
- Do not execute any registered outer look while reviewing this branch.

## Workstreams

### 1. Program design and governance

Files:

- `docs/superpowers/specs/2026-08-03-prospect-evidence-improvement-program-design.md`
- `docs/superpowers/plans/2026-08-03-prospect-evidence-coverage.md`
- `docs/superpowers/plans/2026-08-03-prospect-translation-readiness.md`
- `docs/superpowers/plans/2026-08-03-development-context-challengers.md`
- `docs/superpowers/plans/2026-08-03-pitcher-skill-challenger-integration.md`
- `docs/superpowers/plans/2026-08-03-prospect-model-independence-and-review.md`

The program separates factual coverage, translation readiness, registered context challengers, and pitcher-skill research from all serving decisions.

### 2. Investment and availability evidence coverage

Files:

- `prospects/coverage_audit.py`
- `prospects/availability.py`
- `scripts/validate_prospect_coverage_audit.py`
- `scripts/validate_prospect_availability.py`
- `tests/test_prospect_coverage_audit.py`
- `tests/test_prospect_availability.py`
- `data/models/valucast_prospect_coverage_audit.json`
- `data/models/valucast_prospect_availability.json`

Checks:

- The deterministic investment queue contains 1,497 unresolved identity-role rows.
- Every queue row carries `changes_ranks_or_values: false` and no invented amount.
- Availability contains 5,325 profiles: 3,701 known available, 1,538 known limited, and 86 known unavailable.
- Evidence provenance is additive; the existing availability scoring decisions are unchanged.

### 3. Translation readiness and registered C1/C2 definitions

Files:

- `prospects/challenger_readiness.py`
- `scripts/build_prospect_challenger_readiness.py`
- `tests/test_prospect_challenger_readiness.py`
- `data/validation/prospect_challenger_readiness.json`

Checks:

- Historical identity key is `cohort_year:mlbam_id:role`: 6,756 rows, 3,307 hitters, 3,449 pitchers, zero duplicates.
- AAA Statcast readiness covers 380 role-aware rows.
- Missing values remain null; `zero_filled_count` is zero.
- C1 development-density hash: `c12ba47c777962f1290e9b81395e571e3ef9334f34225a074a1d8495580afab7`.
- C2 position-by-youth hash: `837f4bdb9009e03ac2d96f1f967b92f1cb05d232d177fc0dbcf35c1c3c1d4c4c`.
- `confirmatory_scoring_authorized: false` and `registered_look_spent: false`.
- The readiness artifact is `waiting_for_vintage`; the not-before date remains 2027-01-01.

### 4. Registered MLB pitcher skill challenger integration

Files:

- `docs/superpowers/specs/2026-08-02-mlb-pitcher-skill-challenger-design.md`
- `docs/superpowers/plans/2026-08-02-mlb-pitcher-skill-challenger.md`
- `plans/035-mlb-pitcher-skill-challenger.md`
- `plans/README.md`
- `projections/data/pitching_statcast.py`
- `projections/models/pitcher_skill_challenger.py`
- `projections/backtest/pitcher_skill_challenger_harness.py`
- `scripts/fetch_mlb_pitcher_statcast.py`
- `scripts/run_mlb_pitcher_skill_challenger.py`
- `tests/test_pitching_statcast.py`
- `tests/test_pitcher_skill_challenger.py`
- `tests/test_mlb_pitcher_skill_registration.py`
- `tests/test_mlb_pitcher_skill_challenger_runner.py`

Chronology is preserved: design, plan, registration, acquisition/aggregation, model, harness, then hardening. Registration status is `registered_unspent`; seed 35021 is fresh. The one combined feature set and its descriptive in-look ablations remain research-only.

Boundary checks:

- `data/validation/mlb_pitcher_skill_challenger_result.json` does not exist.
- The runner was not executed.
- No serving or workflow path imports the challenger.
- `feeds_live_projection`, `feeds_rank_or_value`, and `feeds_pitcher_publication` are false.

### 5. Model-independence enforcement

Files:

- `prospects/input_contract.py`
- `prospects/challenger_readiness.py`
- `tests/test_prospect_research_independence.py`
- `tests/test_prospect_rank_v1.py`

The shared factual-contract boundary rejects exact keys for consensus, source ranks, FV/tool grades, competitor outputs, market/dynasty values, and current ValuCast rank. It deliberately does not use substring matching. A full Rank v1 mutation test changes every external source rank from 1 to 999 and confirms that displayed context changes while `(mlbam_id, score, rank)` remains identical.

## Serving invariance

Git blob hashes are identical at the base and implementation head:

| Artifact | Base | Implementation head |
|---|---|---|
| `data/models/valucast_prospect_model.json` | `c77e257fc7462758859a091cb47075cb80b6e768` | `c77e257fc7462758859a091cb47075cb80b6e768` |
| `data/models/valucast_prospect_rank_v1.json` | `e7daf3a514c70438026ce00e37c245983f1f340d` | `e7daf3a514c70438026ce00e37c245983f1f340d` |
| `data/models/valucast_universal_prospect_model.json` | `d05b2b79a2acbf25a7c8613fa097efa7ddbe9351` | `d05b2b79a2acbf25a7c8613fa097efa7ddbe9351` |

## Verification already run

Focused changed-path suite:

```text
python -m pytest tests/test_prospect_coverage_audit.py tests/test_prospect_availability.py tests/test_prospect_challenger_readiness.py tests/test_prospect_research_independence.py tests/test_prospect_rank_v1.py tests/test_pitching_statcast.py tests/test_pitcher_skill_challenger.py tests/test_mlb_pitcher_skill_challenger_runner.py tests/test_mlb_pitcher_skill_registration.py -q
258 passed in 14.82s
```

Additional contract/model suite:

```text
python -m pytest tests/test_stage1_contract.py tests/test_prospect_model.py tests/test_prospect_challenger_readiness.py -q
57 passed in 33.54s
```

Full repository suite:

```text
python -m pytest -q
3184 passed, 3 skipped, 18 subtests passed in 546.49s
```

Boundary commands:

```text
git diff --check 1d0650b9...37bf9ab0
Test-Path data/validation/mlb_pitcher_skill_challenger_result.json
rg -n "pitcher_skill_challenger|mlb_pitcher_skill_challenger" app.py prospects/rank_v1.py templates web .github
```

Expected after the documentation whitespace cleanup: clean diff; result path false; no serving or workflow importer.

## Known non-actions

- No live score, rank, value, cap, Role Watch, pitcher publication, or model-calibration change.
- No workflow file change or workflow dispatch.
- No pitcher outer-look execution or result artifact.
- No Plan 034, C1, or C2 outcome scoring.
- No consensus, scouting, competitor, market, or current ValuCast rank added to factual model rows.
- No missing AAA feature value replaced with zero.

## Fable prompt

```text
Review 1d0650b939a4ef7472b5064a6e928f89064c6e94..37bf9ab0e0d6a218dc16097edfe903992ae9c6fd as a senior sabermetrician, statistician, model-risk reviewer, and production engineer. Findings only; do not edit. Reproduce the investment queue and availability provenance, verify no score/rank/value change, attack Plan 034's no-outcome gate for any path that could score early, verify C1/C2 exactly match the frozen registration, and review the pitcher challenger chronology, provenance, pitch geometry, folds, fallback, target alignment, gate math, and absence of a serving importer or result artifact. Mutate consensus, scouting/FV, competitor, market, and current-ValuCast-rank fields to test score invariance. Treat any look-spending path, leakage, silent zero fill, identity collapse, or production reachability as P0. Report P1/P2 issues, unnecessary complexity, exact file:line evidence, commands run, and a checked-clean register. Do not run the registered pitcher outer look or any Plan 034/C1/C2 outcome scorer.
```
