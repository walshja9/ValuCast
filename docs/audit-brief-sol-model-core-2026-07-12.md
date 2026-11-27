# Sol Audit Brief #2 — Model Core — 2026-07-12

You are Sol, running the second independent, adversarial, **read-only** audit of
the ValuCast codebase. Your first audit (docs/audit-brief-sol-2026-07-12.md)
found four confirmed CRITICALs in the scorecard the night before it published.
This one goes after the bigger prize: **the model that produces the public
prospect board itself.** Every number on valucast.app descends from this code.

## Ground rules (same as audit #1, two additions)

- **Read-only.** No file edits, no commits, no `git add`/`stash`, no writes
  outside your own scratch space. You may RUN existing scripts only if they
  write nothing into the repo (check before running); if a check would require
  a rebuild/retrain, don't run it — label the finding HYPOTHESIS and state the
  exact command we should run to confirm.
- **Never run pytest** (it dirties a committed archive file).
- **Findings format (non-negotiable):** one-sentence defect + `file:line` + a
  concrete failure scenario (inputs/state → wrong number a user sees) +
  severity (CRITICAL = wrong number on a public surface / crash on a served
  path; MAJOR = broken invariant or visible wrong behavior; MINOR = the rest).
  No style notes, no refactor suggestions, no weight opinions.
- **Also report what you cleared,** per target, so silence is distinguishable
  from not-checked.
- **NEW — the fence:** the model core has no registered spec the way the
  scorecard did. Your standard is **internal consistency**: math errors, unit
  mismatches, double-counting, dead branches that were meant to be live,
  boundary cliffs/discontinuities, asymmetries between hitters and pitchers
  that the code's own comments don't intend, and code that contradicts its own
  docstrings/comments/plans. "I would weight age differently" is NOT a finding.
  If a judgment call looks wrong, you may flag it as HYPOTHESIS with the
  specific evidence that would decide it — one line, no essays.
- **NEW — recompute, don't trust:** when a comment or artifact claims a number
  (a cap, a share, a concordance, a bucket count), recompute it from the
  committed artifacts/archive and report yours.

## Why now (context)

Plan 028 (pitcher-lean model fix) executes in the days after 2026-07-13, and
every model fix costs a public epoch bump — a visible board re-baseline. Any
real defect you find in the next window rides the SAME epoch bump as 028: one
re-score, one disclosure, instead of two. Findings that arrive later cost a
second public shuffle. Your findings land exactly when fixes are cheapest.

## Target 1 (FIRST): the backtest/gate harness — the validator of everything

Files: `prospects/adapter_backtest.py`, `prospects/dynasty_backtest.py`,
`prospects/outcome_backtest.py`, `prospects/index_backtest.py`,
`prospects/gate.py`, `scripts/build_prospect_adapter_backtest.py` and siblings,
plus the committed backtest artifacts under `data/models/`.

This harness is THE GATE: model changes ship only if it passes them. A defect
here silently blesses bad models — highest blast radius in the repo. Your own
audit #1 already proved one blindness (the concordance gate never sees
`rank_v1.py` or `availability.py` — known, don't re-report). Hunt for more of
that class, at minimum:

1. **What does each gate metric actually measure vs what its name claims?**
   Trace `candidate_rank_concordance` and every pass/fail criterion end to end:
   which code paths are inside the measurement, which public-board paths are
   OUTSIDE it (unvalidatable-by-construction), and does any Done-criterion
   anywhere cite a gate that cannot see the change it gates?
2. **Leakage.** Do train/validation folds share players, seasons, or derived
   features? Does any feature computed from the label window leak into
   training? Is the fold split deterministic and honored everywhere?
3. **Survivorship and cohort construction.** Who is excluded from backtest
   cohorts (injured, graduated, released, never-ranked), and does the exclusion
   correlate with the outcome being predicted?
4. **Metric arithmetic.** Recompute at least one committed concordance/score
   from raw inputs. Ties, NaNs, empty cohorts, single-member cohorts —
   what do they do to the metric?

## Target 2: the scoring path — model.py → rank_v1.py → the public board

Files: `prospects/model.py`, `prospects/model_v07.py`, `prospects/rank_v1.py`,
`prospects/universal.py`,
`scripts/build_prospect_rank_v1.py`, `scripts/build_prospect_universe.py`,
`prospects/input_builder.py`, `prospects/raw_input_builder.py`,
`prospects/milb_translation.py`.

Known (don't re-report): the pitcher-lean itself and the fallback-only pedigree
cap (`plans/028-pitcher-lean-model-fix.md` + its 2026-07-12 amendments +
docs/governor-review-2026-07-13-pitcher-lean-memo.md — READ THESE FIRST so you
know what's already pinned). Hunt for what 028 does NOT cover:

1. **Boundary cliffs.** Every threshold in the scoring path (sample floors,
   age cutoffs, level gates, bucket-calibration edges like
   `moderate_thin_sample_confidence`): does crossing it by epsilon move a score
   by a step? List every cliff with its magnitude.
2. **Double-counting.** The same underlying signal (pedigree, level, age,
   sample size) entering the score through two features/adjustments that the
   comments treat as independent. The 028 root cause was one instance; find
   the others.
3. **Normalization seams.** `model_score_normalization`,
   `score_before_availability_adjustment` vs `score_before_bucket_calibration`
   ordering, the 0-100 mapping: is the adjustment order the one the comments
   claim, and can an adjustment applied pre-normalization be re-amplified
   post-normalization?
4. **Hitter/pitcher asymmetries** the code doesn't intend: features present
   for one role and silently zero/missing for the other, unit differences
   (PA vs IP vs pitches) treated as comparable.
5. **Availability interactions** (`prospects/availability.py`): discounts
   combine via `max()` by design — verify nothing bypasses that and stacks.

## Target 3: the peak-projection layer

Files: `prospects/peak_projection.py`, `prospects/peak_calibration.py`,
`scripts/build_prospect_peak_projection.py`,
`scripts/build_prospect_peak_calibration_report.py`, committed peak artifacts.

Known smell, unexplained (your job is to EXPLAIN it, not re-flag it): the
pitcher-lean memo records `neg_delta=0` across 14 calibration buckets — a
calibration that never adjusts downward. Determine from the code whether that
is (a) impossible-by-construction (a `max(0, ...)` or clamp that makes the
whole negative branch dead code), (b) genuinely absent in the data, or (c) a
sign/ordering bug. Then the usual sweep: bucket boundary handling, empty-bucket
fallbacks, whether the calibration is applied in the direction its own
docstring claims.

## Target 4: consensus ingestion (the other side of every public comparison)

Files: `prospects/consensus_gap.py`, `prospects/ahead_of_consensus.py`
(_divergence_row/_is_guarded internals — the scorecard consumers were audited
in #1; here audit the PRODUCERS), the five snapshot builders
(`scripts/build_hkb_consensus_snapshot.py`, `build_pipeline_consensus_snapshot.py`,
`build_prospectslive_consensus_snapshot.py`, `build_sts_consensus_snapshot.py`,
plus the fg_ord re-keyer), and `scripts/fetch_hkb_source.py`.

1. **Median arithmetic:** MIN_BOARDS handling, even-count medians, a board
   that ranks only its own top-N (truncation bias — is an unranked player on a
   short board treated as missing or as worst-rank?).
2. **Identity joins:** name/mlbam keying between sources — collisions,
   accents, twins (this repo has history here).
3. **Staleness semantics:** each source carries a different refresh date; does
   any consumer treat the aggregate as fresher than its stalest member without
   disclosure?

## Known issues — do NOT re-report

1. Pitcher lean, fallback-only pedigree cap, governor blindness (028 + memo).
2. Graduation gap: 7 players past rookie thresholds still on the board.
3. Buys momentum reacts to re-baselines; the 6-point step guard is the only
   mask; epoch is metadata-only (028 amendment 2).
4. `neg_delta=0` ×14 buckets is KNOWN as a smell — re-reporting it is zero
   credit; explaining its mechanism is the finding.
5. W (wins) category untrainable — no `w` in label seasons, upstream data gap.
6. The scorecard/ledger/trade/discipline surfaces — audited in #1, fixed
   2026-07-12; out of scope here.
7. `data/dd/dd_dynasty_feed.json` untracked in the worktree — expected.

## Deliverable

One report, findings ranked CRITICAL → MINOR in the required format, then the
cleared-areas list per target. Two special flags, at the very top when they
apply:

- **GATE FINDING** — anything that undermines the backtest harness itself.
  Plan 028's acceptance depends on this harness; if it's broken we must know
  BEFORE 028 executes, not after.
- **EPOCH BATCH** — any confirmed scoring-path defect whose fix would move
  public scores. These get batched into 028's epoch bump; list them together
  so nothing needs a second re-baseline later.
