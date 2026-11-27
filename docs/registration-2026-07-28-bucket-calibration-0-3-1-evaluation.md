# Registered Study: Bucket Calibration 0.3.1 vs 0.3.0

**Registered:** 2026-07-28 (this document is committed and pushed BEFORE any
study result is computed or viewed; the push timestamp and commit hash are the
registration record).
**Study type:** Offline, read-only. No repo tree, artifact, board, or
publication is touched. All computation happens in disposable worktrees under
the session scratchpad. No scoring change of any kind ships from this study —
every verdict below still requires explicit owner sign-off before any action.
**Fulfils:** the evaluation gate in
`docs/incident-2026-07-27-bucket-calibration-0-3-1.md`.

## Prior knowledge (disclosed)

The following facts were already observed during the 2026-07-27 commit audit
and are NOT study results: on 2026-07-23 inputs, 0.3.1 changed 348/2,856
scores and 2,770/2,856 ranks vs 0.3.0; three example deltas (Kudrna
14.53→31.20, Henderson 19.16→30.73, Arroyo 15.12→29.37); under 0.3.0 the
restored veto fires once on the 07-22→07-23 pair (Henderson, −11.35). All
thresholds below are set on quantities not yet computed: the multi-day
incident counts, the intended/unintended classification and its magnitude
distribution, and the calibration comparison.

## Frozen design

### Arms

- **A (0.3.0):** code tree at `20e2511` (range baseline; last pre-PR-#15 code).
- **B (0.3.1):** code tree at `3c847df` (PR #15 merge; isolates the
  calibration change from later, parity-proven changes such as Stage 1).

### Cohorts (input days)

Committed daily inputs, applied identically to both arms via
`git checkout <sha> -- data` in each worktree:
`5e8959d` (07-23), `1d63585` (07-24), `d4ae26f` (07-25), `b8cd8a9` (07-26),
`d83a9a7` (07-27), `3e044b1` (07-28). Day-pair analyses also use the served
07-22 board from `20e2511` as the first prior day. If either arm fails to
build a day, that day is excluded from BOTH arms and the exclusion reported.

### Determinism / seeds

The rank pipeline has no random number generation; there are no seeds to fix.
The one known nondeterministic leaf (`context_only.source_ranks`, documented
in `docs/audit-2026-07-22-stage1-contract-parity.md` and the 07-27 audit) is
context-only and is EXCLUDED from every metric. Any other run-to-run
nondeterminism discovered must be reported and that metric flagged.

### Metrics and pass thresholds

**Q1 — Intent (does 0.3.1 remove transition-continuity cliffs?)**
For each adjacent day pair (07-22→23 … 07-27→28), run the current
(spec-restored, `final_delta < 0`) `_prospect_transition_continuity` veto over
each arm's rebuilt boards. Metric: incident count per pair per arm.
**R1 passes iff** arm B has zero incidents on every pair AND arm A has at
least one incident on at least one pair (otherwise the change fixes nothing
the veto would have caught).

**Q2 — Scope (is the blast radius the intended one?)**
Same-day A-vs-B comparison per day. *Affected* = |Δscore| ≥ 0.01.
*Intended class* = affected player with, in arm B components for that day:
`continuity_floor_applied: true`, OR a bucket-calibration rule in
`{thin_current_sample_confidence, moderate_thin_sample_confidence}` together
with a current-season level transition per the governor's transition
definition evaluated on that day's row vs the prior day's row.
*Unintended class* = affected, not intended. Metrics, pooled across days and
reported per day: class counts; sum-|Δscore| share by class; unintended
median and P95 |Δscore|; unintended top-100 entries/exits (by rank).
**R2 passes iff** (a) intended class carries ≥ 50% of pooled sum-|Δscore|,
(b) unintended P95 |Δscore| ≤ 6.0 (the repo's own STEP_THRESHOLD materiality
line), and (c) no unintended player enters or leaves the top 100 between arms
on any day.

**Q3 — Calibration (does 0.3.1 degrade standing calibration?)**
Recompute the prospect calibration report and the peak-projection calibration
under each arm on the same committed inputs, where those builders run offline
(no network) from committed data. Metric: each artifact's headline error
statistic (as named in the artifact itself). **R3 passes iff** arm B is not
worse than arm A by more than 2% relative on any headline statistic (2%
mirrors the repo's own `MIN_GATE_IMPROVEMENT_PCT`). If a builder cannot run
offline from committed inputs, that artifact is recorded N/A and excluded
from the verdict — this exclusion rule is set now, before knowing which
builders run.

### Subgroup checks (report-only, no thresholds)

Breakdowns of Q2 deltas by: role (hitter/pitcher), level (A/A+/AA/AAA),
bucket membership, `continuity_floor_applied`, and top-100 vs 101-500 vs
rest. These inform remediation design; they do not move the verdict.

### Verdict rules (mechanical)

- **RATIFY** iff R1, R2, R3 all pass → write the missing 0.3.1 design doc,
  keep the version, close the incident.
- **REVERT** iff R1 fails or R3 fails → return to 0.3.0 as ONE scheduled,
  disclosed public re-baseline (never a silent overnight shift).
- **SPLIT-REMEDIATE** iff R1 and R3 pass but R2 fails → design a 0.3.2 that
  keeps the transition-continuity floor and reverts the unintended
  reliability rebasing, shipped as one disclosed re-baseline with its own
  design doc and review.

Ties/edge cases: a metric that cannot be computed for a reason not covered
above voids the verdict for owner adjudication rather than defaulting to
pass. The study executor reports raw measured quantities; verdict application
is mechanical from this table. Owner sign-off is required before ANY
follow-on action, including RATIFY.
