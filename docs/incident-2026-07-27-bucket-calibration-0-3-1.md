# Incident: Undocumented Bucket-Calibration 0.3.1 (commit `0bfe5a0`, PR #15)

**Recorded:** 2026-07-27
**Status:** Scoring frozen at 0.3.1 pending formal evaluation. Veto restored. No rollback.

## What happened

Commit `0bfe5a0` ("fix: preserve prospect transition continuity", merged 2026-07-23 as
PR #15) changed prospect scoring math while presenting as continuity plumbing:

- swapped reliability precedence in `_sample_reliability_score` (model profile
  now wins over layer profile);
- rebased the thin-sample penalty in `_bucket_calibration_adjustment` from
  `current_reliability` to full-history `reliability` for v0.6 rows at/above
  `MIN_CURRENT_SAMPLE`;
- added a "continuity floor" capping the thin-sample penalty;
- bumped `BUCKET_CALIBRATION_VERSION` 0.3.0 → 0.3.1 with no design, plan, or
  audit document.

Measured effect (reproduced during the 2026-07-27 commit audit, see
`docs/review-2026-07-27-baseline-to-master-commit-audit.md` P0-1): on identical
2026-07-23 committed inputs, 0.3.1 vs 0.3.0 changed **348 of 2,856 scores and
2,770 of 2,856 ranks**; the 0.3.1 rebuild byte-matches the served 07-23 board.

The same commit weakened the transition-continuity publication veto
(`final_delta < 0` → `final_delta < -6.0`). Under 0.3.0 scoring the veto fires
on the 07-22→07-23 pair (1 incident, Ixan Henderson, final delta −11.35) and
would have halted the refresh for review; the commit's combined effect was to
publish through the gate instead of stopping at it.

## Decision (owner, 2026-07-27)

1. **No immediate revert.** Reverting 0.3.1 now would cause a second
   uncontrolled board-wide shift. Current scoring is **frozen as-served**.
2. **Veto restored immediately** to the spec condition (`final_delta < 0`) —
   done in this remediation branch; the strengthened confidence-bucket
   expansion from `0bfe5a0` is retained. Replayed against the 07-26→07-27
   served board pair and the 07-27 morning→afternoon-pulse pair: passed,
   0 incidents, so the restore does not block the next scheduled publication.
3. **Formal evaluation of 0.3.1 vs 0.3.0 before ratification.** Until that
   evaluation is recorded, 0.3.1 is *tolerated, not ratified*, and no further
   change to `BUCKET_CALIBRATION_VERSION`, `_sample_reliability_score`,
   `_bucket_calibration_adjustment`, or the continuity floor may ship without
   its own design doc and review.

## Evaluation gate for ratifying (or reverting) 0.3.1

The evaluation must be its own reviewed document
(`docs/audit-YYYY-MM-DD-bucket-calibration-0-3-1-evaluation.md`) covering:

- **Intent:** what continuity defect 0.3.1 was meant to fix (the level-
  transition penalty cliff), stated with the affected player set.
- **Side-effect inventory:** the full 348-player score delta and 2,770-row
  rank delta between 0.3.0 and 0.3.1 on a fixed input day, split into
  (a) intended transition-continuity corrections and (b) incidental
  full-history-reliability rebasing of non-transition thin-sample players.
- **Calibration check:** whether 0.3.1 improves or degrades the standing
  prospect calibration/backtest artifacts versus 0.3.0 on the committed
  evaluation data (no new data collection required).
- **Verdict:** ratify 0.3.1 (write the missing design doc, keep the version),
  or revert to 0.3.0 **as a scheduled, disclosed board re-baseline** (one
  public epoch bump per the standing re-baseline protocol) — never as a
  silent overnight shift in either direction.

## Control gap this exposed

A commit whose message and title claim one scope can ship frozen-surface
changes if no reviewer rebuilds the board from its parent. The daily-pair
continuity veto compares day N to day N−1 *outputs* and cannot see a same-day
code+output shift. Follow-up (tracked, not yet implemented): a CI check that
fails when `BUCKET_CALIBRATION_VERSION` (or other frozen-surface version
markers) changes in a commit that adds no matching design doc.
