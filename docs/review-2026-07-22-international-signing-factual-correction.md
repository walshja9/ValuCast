# Review Packet: International Signing Factual Correction

**Date:** 2026-07-22
**Branch:** `codex/international-investment-evidence`
**Publication status:** Not published; no committed rank, public snapshot, workflow dispatch, or deployment.

## Review Status

- Claude approval: reported by the user on 2026-07-22.
- Final Codex review: approved after two additional fail-closed/honesty fixes.
- Publication still requires explicit user authorization.

The final Codex pass found and fixed two issues:

1. the production runner now raises immediately when its configured evidence
   file is missing instead of silently reverting to the uncorrected board; and
2. the coverage audit cannot claim corrected ranks were computed while a
   source-backed scoring gap remains unresolved.

## Review Question

Does this branch safely apply 13 source-backed international signing bonuses
only to Prospect Rank v1's existing factual-investment component while keeping
the v0.6 and universal prospect models unchanged?

## Intended Data Flow

`run_prospect_rank_v1` loads the evidence artifact and passes it explicitly to
`build_prospect_rank_v1`. The builder validates the evidence and overlays the
bonuses on a copied rank-local current-hitter input. The canonical prospect
input contract is not modified, and neither trained model builder receives the
overlay.

The overlay blocks invalid policy, duplicate MLBAM IDs, unsupported acquisition
types, non-positive bonuses, missing sources, unmatched IDs, and conflicts. An
identical existing bonus is an idempotent no-op.

## Exact Candidate Result

| MLBAM | Player | Current rank/value | Candidate rank/value |
|---:|---|---:|---:|
| 808265 | Franklin Arias | 9 / 53.89 | 7 / 55.95 |
| 800325 | Luis Lara | 10 / 51.78 | 8 / 54.50 |
| 800543 | Josue De Paula | 12 / 50.04 | 11 / 51.85 |
| 815908 | Jesús Made | 16 / 47.67 | 13 / 50.26 |
| 699013 | Esmerlyn Valdez | 19 / 46.96 | 17 / 47.76 |
| 694197 | Angel Genao | 28 / 42.92 | 21 / 45.70 |
| 815888 | Leo De Vries | 36 / 41.61 | 22 / 45.53 |
| 699302 | Héctor Rodríguez | 23 / 44.75 | 23 / 45.31 |
| 821181 | Juneiker Caceres | 27 / 43.45 | 24 / 45.00 |
| 703185 | Nelson Rada | 38 / 41.18 | 27 / 44.37 |
| 699393 | Pedro Ramírez | 32 / 42.39 | 32 / 42.70 |
| 703155 | Lazaro Montes | 50 / 38.26 | 38 / 41.72 |
| 699024 | Leo Bernal | 48 / 38.51 | 40 / 40.79 |

Additional invariants:

- 13 evidence rows applied; zero were idempotent in the current contract.
- No unrelated player's value changed.
- Top-50 membership remained unchanged.
- Top 25 remained 15 hitters and 10 pitchers.
- Top 50 remained 32 hitters and 18 pitchers.
- Prospect Rank v1 version changed from 0.2.8 to 0.2.9.

## Model Hashes

The candidate run read but did not write either trained model artifact:

```text
valucast_prospect_model.json
ed946bcd13ca92292fccf7623a983960caf120cc73a5e90bf34e1f1704b190a7

valucast_universal_prospect_model.json
9f887d5dacc27e3ef835ed37a03b544c5926ac01cdf6430a65d6f5f4f4ed14b2
```

`git diff --exit-code` reports no changes for either file.

## RED Evidence

The first focused run failed during collection because
`_with_verified_investment_facts` did not exist. After Task 1, the runner test
failed because `run_prospect_rank_v1` did not accept
`investment_evidence_path`, and the coverage test failed because the audit did
not expose `feeds_rank_score`.

## GREEN Evidence

```text
python -m pytest tests/test_prospect_rank_v1.py -k "verified_investment" -q
8 passed, 33 deselected

python -m pytest tests/test_prospect_rank_v1.py tests/test_prospect_coverage_audit.py -q
47 passed

python -m pytest tests/test_prospect_rank_v1.py tests/test_prospect_coverage_audit.py tests/test_valucast_quality_governor.py -q
93 passed

python -m pytest -q
2737 passed, 18 subtests passed in 421.96s

post-review exact candidate assertions
13 facts applied; exact preview true; zero unrelated value changes;
top-50 membership unchanged; model hashes unchanged
```

## Files to Attack

- `prospects/rank_v1.py`
- `prospects/coverage_audit.py`
- `scripts/validate_prospect_coverage_audit.py`
- `tests/test_prospect_rank_v1.py`
- `tests/test_prospect_coverage_audit.py`
- `data/prospects/raw/international_signing_facts.json`
- `docs/audit-2026-07-22-international-investment-evidence.md`

## Requested Adversarial Checks

1. Prove no evidence path reaches `prospects/model.py` or
   `prospects/universal.py`.
2. Try duplicate, invalid, unmatched, conflicting, and already-populated facts.
3. Confirm multiple current rows for one MLBAM ID receive the same correction.
4. Confirm exact MLBAM identity is used and names are irrelevant.
5. Confirm the canonical input contract is not mutated.
6. Confirm ordinary runner calls without an evidence file remain possible for
   isolated tests, while the production default loads the committed evidence.
7. Confirm provenance and coverage copy accurately admit rank/value effects.
8. Confirm no generated public artifact or deployment path was added.

## Governance Boundary

This is a factual input correction, not a predictive-model promotion. It does
not authorize universal-model use of international signing bonuses, a public
accuracy claim, a merge, a workflow dispatch, or a deployment. Publication
requires the requested Claude review, a subsequent independent Codex review,
and explicit user approval.
