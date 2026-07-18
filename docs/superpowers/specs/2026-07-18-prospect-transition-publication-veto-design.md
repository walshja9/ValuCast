# Prospect Transition Publication Veto Design

**Date:** 2026-07-18

**Status:** Proposed for implementation after written-spec review

## Decision

Add a transition-continuity check to the existing ValuCast quality governor and make that one check a hard daily-publication veto. The check observes consecutive Prospect Rank v1 archives. It does not alter Prospect Rank v1, availability, bucket calibration, public values, ranks, caps, Role Watch, or pitcher publication logic.

This is a safety gate, not a scoring fix. A separate registered challenger must justify any future change to the confidence-calibration formula.

## Problem and Evidence

Josue Briceno fell from 40.48 and prospect rank 37 on July 17 to 20.82 and rank 417 on July 18. His underlying `model_score` moved only from 45.17 to 45.08. The material changes were:

- level: A to AA;
- availability: `available` to `thin_current_sample`;
- availability adjustment: -2.02 points;
- newly activated `thin_current_sample_confidence` adjustment: -17.57 points.

The final 19.66-point fall was therefore a calibration transition, not a comparable deterioration in the underlying skill signal.

A replay of all 36 dated Prospect Rank v1 archives on `origin/master`, from June 13 through July 18, found:

- 617 matched level transitions;
- 15 hitter/pitcher continuity incidents under the proposed predicate;
- 12 pitcher incidents and 3 hitter incidents;
- Briceno was the largest final-score decline at -19.66.

The incidents include promotions and same-level pitcher workload/starter-status transitions. The failure class is broader than Briceno and broader than hitter promotions.

## Alternatives Considered

### 1. Hard publication veto - selected

Compare the current board with the latest earlier dated archive, report calibration-only transition cliffs in the quality governor, and fail the validation stage before the daily commit. This keeps the previous committed public build live while a human reviews the event.

Trade-off: because the daily data commit is atomic, a veto also delays otherwise-good actuals and MLB refresh data. That is preferable to knowingly publishing an unexplained 10-20 point prospect collapse.

### 2. Automatically carry forward the prior score - deferred

This would let the rest of the refresh ship, but it would create a second public scoring path, require rank recomputation, and risk disagreement among the prospect board, format ranks, movers, buys, and cards. It also mutates a public value without a registered model rule.

### 3. Cap or replace the thin-sample penalty now - rejected

This directly changes ranks and values before a registered replay or forward validation establishes a better calibration rule. It violates the model freeze and makes the guardrail inseparable from a model change.

## Continuity Check Contract

The check ID will be `prospect_transition_continuity`.

### Inputs

- the current `valucast_prospect_rank_v1` payload;
- the latest readable archive whose date is strictly earlier than the current payload date.

The current-day archive must never be selected as its own baseline, including on a same-day rerun. If no earlier archive exists on a true cold start, the check passes with `sample_ready: false`. A malformed selected baseline is a build error, not a silent skip.

Rows match on `(mlbam_id, role)`.

### Flag predicate

A row is a continuity incident only when every condition is true:

1. The row existed in both vintages.
2. At least one transition signal changed: displayed level, availability status, or factual `starter_role`.
3. The current bucket-calibration rules newly contain `thin_current_sample_confidence` and the prior rules did not.
4. The absolute change in `components.model_score` is at most 1.0 point.
5. The bucket-calibration adjustment worsened by more than 6.0 points. The 6.0 threshold reuses the existing `web.buy_score.STEP_THRESHOLD`; it does not introduce a second definition of a material score step.
6. The final public prospect score declined.

The gate intentionally evaluates the bucket-adjustment change, not only the final-score change, because the 0-point score floor can hide part of a large calibration step.

### Output

The quality-governor check records:

- baseline and current dates;
- evaluated matched-row count;
- incident count;
- hitter and pitcher counts;
- threshold values;
- a bounded sample containing identity, role, old/new level, old/new availability status, old/new starter-role state, model-score delta, bucket-adjustment delta, final-score delta, old/new rank, and active bucket rules.

No external ranking, consensus board, DD value, or market value participates in the check.

## Publication Enforcement

The check belongs to the Prospects surface inside `quality/valucast_governor.py`. A blocked result sets `surface_readiness.prospects` to false and exposes an honest blocker in the snapshot metadata.

The daily validator will additionally treat this exact check ID as fatal. Existing unrelated Prospects-only governor blockers remain advisory and retain their current behavior. This exception is necessary because the live Prospects route currently shows a preliminary banner but still renders the rows; a continuity veto must stop the atomic refresh before commit and push.

No workflow file or deployment behavior changes. The existing build-then-validate-then-commit order supplies the veto.

## Historical Audit and Current Incident

The 36-vintage replay is a required verification step and must use the same pure predicate as the governor check. The implementation must reproduce the 15 observed incidents and identify Briceno with:

- level A to AA;
- model-score delta -0.09;
- bucket-adjustment delta -17.57;
- final-score delta -19.66.

The initial gate does not retroactively rewrite Briceno's July 18 value. It prevents the same failure class from passing silently in a future refresh and provides the evidence needed for a separate calibration challenger. Any correction to Briceno or the other historical incidents requires an explicit, reviewed publication decision.

## Testing

Implementation follows test-first development.

Required positive cases:

- hitter promotion with stable `model_score` and a newly activated material thin-sample adjustment blocks;
- same-level pitcher starter/workload transition with the same pattern blocks;
- the Briceno July 17-to-18 archive replay blocks with the expected deltas;
- the daily validator fails when this check is blocked.

Required negative controls:

- a promotion without a new thin-sample rule passes;
- a real underlying model move greater than 1.0 point is not labeled calibration-only;
- a bucket-adjustment change of 6.0 points or less passes;
- a continuing thin-sample state does not create a new-transition incident;
- a score that does not decline passes;
- a cold start without an earlier archive passes with `sample_ready: false`;
- an unrelated Prospects-only quality blocker remains nonfatal to the atomic daily refresh.

Verification must include the focused tests, the existing quality-governor and public-snapshot suites, the daily build-step contract tests, the 36-archive replay, and the full automated suite.

## Operational Response

When the veto fires, its output must name the affected players and the exact score components that moved. Reviewers then choose one of three explicit actions outside this change:

1. confirm a genuine input correction and approve a narrowly documented override;
2. repair a data-contract error and rerun the build;
3. register and test a calibration challenger before changing the model.

There is no automatic waiver and no silent score substitution.

## Non-Goals and Frozen Constraints

- No change to `prospects/rank_v1.py` scoring or calibration.
- No change to `prospects/availability.py` thresholds.
- No change to public ranks, values, format ranks, pitcher caps, Role Watch, buys, movers, or pitcher publication decisions.
- No proprietary Hitter Skill+ or Pitcher Skill+ metric in this task.
- No change to the Steamer-based live forecast input.
- Preserve the registered model freeze and the failed pitcher-decay flag.
- Keep League Connect paused.
- No deployment or workflow dispatch from this branch.

## Expected Files During Implementation

- `quality/valucast_governor.py`: pure prior/current continuity check, prior-archive selection helper, and Prospects-surface registration.
- `scripts/build_public_dynasty_snapshot.py`: pass the earlier dated rank archive to the governor evaluation.
- `scripts/validate_valucast_quality_governor.py`: make only a blocked `prospect_transition_continuity` check fatal.
- `tests/test_valucast_quality_governor.py`: hitter, pitcher, threshold, and negative-control coverage.
- `tests/test_public_dynasty_snapshot.py`: snapshot integration and prior-date selection coverage if the builder boundary requires it.
- `tests/test_quality_governor_validation.py` or the existing validator test module: fatal-veto and unrelated-blocker behavior.

No new dependency, generated production artifact, route, template, or JavaScript component is planned.
