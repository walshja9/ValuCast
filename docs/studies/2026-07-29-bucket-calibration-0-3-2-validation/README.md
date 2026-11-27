# Validation Package: Bucket Calibration 0.3.2 Ship-Gates 1-4

Design: `docs/superpowers/specs/2026-07-29-bucket-calibration-0-3-2-design.md`.
Code under test: commit `dbcb881` (0.3.2 implementation). Method: the six
frozen study days rebuilt with arm-B code (`3c847df`) plus ONLY the 0.3.2
patch (isolating the calibration change; the 07-23 inputs predate the Stage 1
release contract, so current-HEAD code correctly fails closed on that day);
the current-board preview built from HEAD `dbcb881` on origin/master inputs.
Compared against the registered study's saved arm boards (regenerable per
`docs/studies/2026-07-28-bucket-calibration-0-3-1/README.md`).

## Results (gates_output.txt is the raw record)

- **Gate 1 (non-floor exactness): PASS** — 0 violations; every non-floor
  player's score matches 0.3.0 (arm A) exactly on all six days.
- **Gate 2 (floor retention): PASS** — 99 floor row-days checked, 0
  violations; floor sets identical to arm B, scores and annotations retained.
  (99 vs the study's 87: the study counted only floor rows whose score
  differed from 0.3.0 by >= 0.01; twelve floor row-days floored a penalty
  without materially changing the score.)
- **Gate 3 (veto clean): PASS** — restored `final_delta < 0` veto reports
  zero incidents on all six 0.3.2 day pairs.
- **Gate 4 (current-board preview): `preview_changes.csv`** — vs the served
  2026-07-28 board: 320 players change score (median |delta| 2.52); exactly
  five top-100 boundary crossings, the study's predicted set reversing their
  0.3.1 moves: Pena 79->163, Milbrandt 60->104, Fitz-Gerald 69->118,
  Harlan 95->102 leave the top 100; King 103->100 re-enters. Floor-protected
  players are unchanged vs served (they keep 0.3.1 treatment).

Gates 5-7 (full CI, committed raw tables, scheduled disclosed re-baseline
with final owner approval) are tracked in the design doc; gate 6 was
satisfied by the study package commit.
