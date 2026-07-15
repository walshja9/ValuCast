# Pitcher Cross-Role Shadow Design

## Goal

Replace the retired Diamond Dynasties prospect-adapter evidence with a ValuCast-owned, observe-only cross-role diagnostic that explains the live pitcher-heavy advisory without changing any score or rank.

## Decisions

### 1. Retire the DD prospect adapter completely

Remove the DD-only prospect preset, adapter backtest, adapter artifact, DD lens export, dated DD adapter archive, builders, tests, and workflow pathspecs. Remove DD adapter comparisons from the forward-shadow tracker and replace DD adapter evidence in the unified outcome report with the new cross-role shadow.

The public `ops_7x7` and `roto_5x5` within-role adapters remain. Core historical league configuration code outside the prospect adapter is out of scope.

### 2. Build one daily, observe-only cross-role shadow artifact

Create `data/models/valucast_prospect_cross_role_shadow.json` from existing committed artifacts only:

- `valucast_rank_backtest.json`: the frozen C0 historical rank-core cross-role concordance.
- `rank_gate_power_check.json`: the registered power result for detecting a cross-role scoring change.
- `valucast_prospect_rank_v1.json`: current top-25/top-50 hitter-pitcher shape and source-rank sensitivity.
- `valucast_aaa_statcast_features.json`: measured AAA pitch-level evidence where available.

The artifact must declare `feeds_model_score=false`, `feeds_public_rank=false`, and `score_changes_authorized=false`.

### 3. Separate four questions that the old language mixed together

1. **Historical absolute competence:** C0 weighted cross-role concordance must be at least `0.60`. This is an absolute care floor, replacing the old DD adapter's relative-only gate. Because the current folds were already viewed, the current result is descriptive; the threshold becomes confirmatory only on a new outcome vintage.
2. **Power to approve a scoring change:** maximum registered power across the tested plausible cross-role effects must be at least `0.70`. The current maximum is `0.015`, so no cross-role score lever can ship from this evidence.
3. **Current board shape:** retain the existing governor limits of at most 7 pitchers in the top 25 and at most 30% in the top 50. These are distribution guardrails, not accuracy claims.
4. **Independent pitcher evidence coverage:** measured AAA Statcast must cover at least 60% of current top-25 pitchers who are actually at AAA. Report total top-25 evidence breadth separately; lower-level pitchers are ineligible, not missing. Coverage is a readiness check, not a performance score.

Overall status is `review_ready` only when the first three checks pass; AAA
coverage remains disclosure-only because its denominator changed after the first
look. Otherwise status is `collecting`. Even `review_ready` never authorizes a
live change without a new registered review.

### 4. Do not invent a pitch-shape score

For covered pitchers, emit measured pitch counts, overall whiff/CSW/chase/zone/ground-ball rates, their empirical AAA percentiles, and raw pitch-type shape rows. Do not collapse these into a model coefficient or rank adjustment. Current coverage is too sparse and no historical AAA pitch-shape outcome panel exists.

### 5. Make the public advisory precise

Use the blocked-state message `Pitcher representation exceeds the publication range. Rankings remain visible, but the current evidence cannot justify either a cross-role score adjustment or relaxing the publication gate.` Keep the board visible and preserve the display-only advisory. The message must not cite DD adapter concordance or imply that the shape threshold measures predictive accuracy.

## Data-quality rules

- Require unique `(mlbam_id, role)` board identities and contiguous current ranks.
- Treat a missing/malformed required artifact as `blocked`, not zero evidence.
- Calculate consensus sensitivity at 1 through 5 source boards using the same current universe and median source rank; keep it diagnostic-only.
- Gate AAA coverage against the current top-25 AAA-eligible pitcher denominator and report total top-25 pitcher coverage separately.
- Preserve source dates and sample sizes in the artifact.

## Registered amendment record — 2026-07-15

Plan 028 Amendment 3 is authoritative for changes made after the first coverage
look. The original all-top-25-pitcher denominator produced 3/10 = 0.30 against
the 0.60 floor and failed. The later AAA-eligible denominator produced 3/3 =
1.00, but is post-look feed-completeness evidence only. It cannot confirm
cross-role calibration, and it cannot pass with fewer than 3 eligible pitchers.
The artifact retains both population and eligible rates.
It does not participate in the `review_ready` conjunction.

The model-to-served role-shape description is now computed in the committed
artifact rather than asserted in prose. On this snapshot,
`checks.current_board_shape.model_component_top25_pitcher_count` is 13 from
2,833 rows with numeric `components.model_score`; the served top 25 contains 10
pitchers; the publication cap is 7. This 13 → 10 → 7 sequence shows that later
rank construction reduces the model component's pitcher lean without clearing
the public shape guard. It describes scale mixing and board construction, not
predictive accuracy.

The alternative role-conditional outcome instrument is registered in Plan 028
before implementation. It must use the same fold-trained out-of-fold scores,
pass both registered simulation scenarios at power >= 0.70, and commit that
power artifact before the single historical role-coefficient look. No result
from that instrument directly authorizes a scoring lever.

## Verification

- Focused RED/GREEN tests for DD removal, shadow gate semantics, AAA coverage, outcome-report replacement, workflow wiring, and advisory copy.
- Rebuild and validate the new shadow and unified outcome artifacts.
- Rebuild the public league-adapter artifact and verify only `ops_7x7` and `roto_5x5` remain.
- Run the focused suites, then the full suite and compare against the baseline of 2 known failures and 2,121 passes.
- Confirm `prospects/model.py` and `prospects/rank_v1.py` scoring logic are unchanged and `PITCHER_STALE_PEDIGREE_DECAY_ENABLED` remains `False`.

