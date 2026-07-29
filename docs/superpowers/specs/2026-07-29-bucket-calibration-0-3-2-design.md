# Bucket Calibration 0.3.2 Design (Split-Remediation)

**Date:** 2026-07-29
**Commissioned by:** owner decision recorded in
`docs/audit-2026-07-29-bucket-calibration-0-3-1-evaluation.md` (accept
SPLIT-REMEDIATE; ratification and full reversion both rejected).
**Approval scope:** design and validation only. Publication requires the
owner's final approval after reviewing the current-board preview, and ships
as ONE scheduled, disclosed public re-baseline.

## Goal

Keep 0.3.1's validated transition-continuity floor; revert its unintended
reliability rebasing, returning every non-floor player exactly to 0.3.0
scoring. In study terms: preserve the 87 intended row-days, undo the 1,860
unintended ones (93.4% of 0.3.1's change magnitude, five unintended top-100
boundary crossings).

## The three parts of `0bfe5a0`, and their disposition

All in `prospects/rank_v1.py`:

1. **Reliability precedence swap** in `_sample_reliability_score` (~line
   1021): model-profile `sample_reliability` preferred over layer-profile.
   **REVERT** to layer-first (0.3.0 order). This value feeds bucket-rule
   eligibility and magnitudes board-wide; the study attributes the
   moderate-bucket and no-bucket unintended deltas to it.
2. **Thin-penalty rebasing** in `_bucket_calibration_adjustment` (~line
   1546): for `prospect_model_v0_6` rows with served sample ≥
   `MODEL_MIN_CURRENT_SAMPLE`, `thin_reliability` switched from
   `current_reliability` to full-history `reliability`, zeroing penalties of
   −11.5..−13.2 for rows that then leave the calibrated population entirely
   (the signature on all ten largest unintended deltas). **REVERT**: thinness
   and ramp always use `current_reliability` (0.3.0 behavior). The
   `served_sample`/`thin_reliability` scaffolding is removed.
3. **Continuity floor** (new in 0.3.1): for v0.6 rows with `sample <
   MODEL_MIN_CURRENT_SAMPLE` and a prior-season career row, the thin-sample
   penalty is floored at a prior-year-strength-scaled bound. **KEEP,
   unchanged.** This is the mechanism R1 validated (zero incidents in arm B;
   the one real Henderson cliff in arm A), and the study shows the
   floor-applied population is exactly the intended class.

Version: `BUCKET_CALIBRATION_VERSION` 0.3.1 → **0.3.2**. The
`MODEL_MIN_CURRENT_SAMPLE` import stays (the floor uses it).

### Why parts 1–2 cannot disturb the floor population

The rebasing branch requires served sample ≥ `MODEL_MIN_CURRENT_SAMPLE`; the
floor branch requires `sample < MODEL_MIN_CURRENT_SAMPLE` — disjoint by
construction, and under both versions the floor path's thinness/ramp already
used `current_reliability`. The precedence swap (part 1) does not enter the
floor value formula (prior-year strength, pedigree, activity penalty only).
This is the design expectation; ship-gate 1 and 2 verify it empirically
rather than trusting it.

## Non-goals

- No governor/veto change (the spec-restored `final_delta < 0` veto and the
  widened confidence-bucket set stay exactly as merged in PR #25).
- No threshold, weight, or model change of any other kind.
- No data/artifact edits: committed boards change only when the re-baseline
  ships through the normal daily build.

## Validation plan (owner ship-gates 1–7)

1. **Non-floor exactness:** rebuild all six frozen study days under 0.3.2;
   for every row without `continuity_floor_applied`, score must equal the
   0.3.0 (arm A) score exactly (2dp artifact precision), and full decision
   fields must match arm A except where floor rows reorder ranks.
2. **Floor retention:** every arm-B `continuity_floor_applied` row-day keeps
   its 0.3.1 score and floor annotations exactly.
3. **Veto clean:** the restored `_prospect_transition_continuity` reports
   zero incidents over all six 0.3.2 day pairs.
4. **Current-board preview:** rebuild the latest served board's inputs under
   0.3.2 and publish (to the owner, not the site) the complete list of score
   changes and every top-100 entry/exit vs the currently served artifact.
5. **Full checks:** entire pytest suite, governor validators, and the
   committed-artifact validate step pass with the 0.3.2 code.
6. **Study raw tables committed** (`docs/studies/2026-07-28-bucket-calibration-0-3-1/`).
7. **Scheduled, disclosed re-baseline:** merge and publication happen only
   after the owner approves the gate-4 preview; the board movement ships in
   one daily build with a disclosure note, never silently.

Expected gate-4 shape from the study: ~354 players move toward their 0.3.0
scores (median ~2.5, P95 ~10.9); Milbrandt, Pena, Fitz-Gerald, and Harlan
leave the top 100, King re-enters; the 16 floor-protected pitchers (incl.
Noble Meyer) keep their 0.3.1 scores. Gate 4 reports the actual list.

## Regression tests to add

- A non-floor thin-sample v0.6 row at/above `MODEL_MIN_CURRENT_SAMPLE`
  receives the identical penalty under 0.3.2 as under 0.3.0 code semantics
  (guards part 2's revert).
- `_sample_reliability_score` prefers the layer profile again (guards part 1).
- A sub-`MIN_CURRENT_SAMPLE` row with a prior season still receives the
  floored penalty with `continuity_floor_applied: true` (guards part 3).
