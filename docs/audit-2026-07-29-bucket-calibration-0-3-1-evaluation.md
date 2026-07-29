# Evaluation: Bucket Calibration 0.3.1 vs 0.3.0 — Registered Study Results

**Date:** 2026-07-29
**Registration:** `docs/registration-2026-07-28-bucket-calibration-0-3-1-evaluation.md`
(commit `3688f83`, pushed 2026-07-29T00:40Z, before any result was computed).
**Execution:** offline, read-only, scratchpad worktrees; arm A = `20e2511`
(0.3.0), arm B = `3c847df` (0.3.1); all six registered input days built in
both arms (12/12 builds, zero exclusions); arm B's 07-23 rebuild byte-matches
the served artifact; a double-build determinism spot check showed zero
decision-field differences. Repo tree untouched throughout.
**Verdict application is mechanical from the registered table. No action —
including the verdict's own remediation — ships without owner sign-off.**

## Results against the registered thresholds

### R1 — Intent (transition-continuity cliffs): **PASS**

Under the spec-restored veto (`final_delta < 0`), arm B produced **zero
incidents on all six day pairs**; arm A produced exactly one — Ixan Henderson
(AA→A, bucket_delta −11.35, final_delta −11.35) on 07-22→23, the known
incident. 0.3.1 does fix the thing it was aimed at. (Notably, arm A shows no
incidents on any later pair: the cliff class it addresses fired exactly once
in six days.)

### R2 — Scope (blast radius): **FAIL, on all three sub-criteria**

Pooled across six days (affected = |Δscore| ≥ 0.01):

| Registered threshold | Measured | Result |
|---|---|---|
| (a) intended class carries ≥ 50% of Σ\|Δscore\| | **6.6%** (455 of 6,894) | FAIL |
| (b) unintended P95 \|Δscore\| ≤ 6.0 | **10.93** | FAIL |
| (c) zero unintended top-100 entries/exits | **24 day-rows, 5 players** (Milbrandt, Pena, Fitz-Gerald, Harlan enter; King exits) | FAIL |

The classification was exceptionally clean: the intended class is **exactly**
the `continuity_floor_applied` population (87 row-days, 16 players, all
pitchers); every other affected row — 1,860 row-days, 354 distinct players,
93.4% of total score-change magnitude — is the incidental full-history
reliability rebasing. Its signature (all 10 largest unintended deltas): an
arm-A thin-sample penalty of −11.5 to −13.2 that disappears entirely in arm B
because the row leaves the calibrated population — no floor, no transition,
no bucket rule. Hitters received 0% intended effect; A+/AA/AAA carry nearly
all unintended magnitude.

### R3 — Calibration: **PASS, with a registered-metric caveat**

Both calibration builders ran offline in both arms on all six days. Every
headline statistic *as named by the artifacts* is identical between arms on
every day (status, tuning flags and their identities, watch counts, bucket
counts, readiness). Arm B is therefore not worse than arm A by any margin.
**Caveat, disclosed rather than buried:** the artifacts' own documentation
says they measure board composition and bucket review, not probabilistic
error — so R3 as registered demonstrates "no composition regression," not
"no calibration-quality regression." No error-statistic artifact exists to
measure; under the registration's rules this is a pass, not an N/A, but it is
a weak pass and the owner should weigh it as such.

## Mechanical verdict: **SPLIT-REMEDIATE**

Per the registered table (R1 pass + R3 pass + R2 fail): design a **0.3.2**
that keeps the transition-continuity floor (the intended, cleanly-separable
87-row mechanism that R1 validates) and reverts the unintended reliability
rebasing (the precedence swap in `_sample_reliability_score` and the
`thin_reliability` base change in `_bucket_calibration_adjustment`), shipped
as **one scheduled, disclosed public re-baseline** with its own design doc
and review. Approximate footprint of that re-baseline, from the study data:
~354 players return toward their 0.3.0 scores (median move ~2.5, P95 ~10.9),
including the five unintended top-100 boundary crossings; the 16
floor-protected pitchers keep their 0.3.1 treatment.

## Owner decision required

No branch, code, or artifact change accompanies this document. Options:
1. **Accept SPLIT-REMEDIATE** → commission the 0.3.2 design doc + review +
   one disclosed re-baseline.
2. **Override to REVERT or RATIFY** — either is an owner override of the
   registered rules and should be recorded as such with reasons.
3. **Adjudicate R3's caveat** → if the owner deems R3 void for lack of a true
   error metric, the registration routes the whole verdict to owner
   adjudication; the R1/R2 measurements stand either way.

Raw measurements, per-day tables, subgroup breakdowns, and saved boards are
preserved in the study scratchpad (`eval031/`) and summarized in this
document's source study report.
