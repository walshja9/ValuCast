# Plan 028: Fix the prospect model's pitcher lean — bind the stale-pedigree cap on the main score path, price pitcher risk (concordance-gap down-weight + attrition base-rate discount), and (only if the first two land clean) decorrelate the outcome/impact blend; comparability epoch bumped so the re-baseline is masked, AOTC funnel provably untouched

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md` —
> unless a reviewer dispatched you and told you they maintain the index.
>
> **This is a MODEL-SURGERY plan.** It changes what the prospect model scores. That
> means (1) master auto-deploys valucast.app via Render, so do NOT push — the
> reviewer gates the push after rerunning the backtest gate; (2) a deliberate
> re-score is a big re-baseline, so the **comparability epoch MUST be bumped**
> (Step 6) or movers/buys/value-trend surfaces will report the fix-day
> discontinuity as real player movement; (3) the fix touches the same rank artifact
> the pre-registered AOTC scorecard reads, so **AOTC integrity is a hard gate**
> (Step 7 + STOP conditions) — any change to what AOTC evaluates for already-matured
> calls is a STOP.
>
> **Drift check (run first)**:
> ```
> git log -1 --format=%h    # baseline for this plan is 125cd43c
> git diff --stat 125cd43c..HEAD -- prospects/rank_v1.py prospects/model.py prospects/availability.py prospects/buys.py prospects/calibration_report.py quality/valucast_governor.py prospects/outcome_backtest.py
> git status --short
> ```
> This plan was written against `125cd43c`. Every "Current state" line ref is
> accurate to that commit. If any in-scope file changed since, re-read the cited
> excerpt against the live code before proceeding; on a mismatch with an excerpt,
> treat it as a STOP condition. In particular the score-source branch
> (`_score_components`, `rank_v1.py:1065-1141`), the fallback-only pedigree cap
> (`_pedigree_score_cap` / `_pedigree_fallback_score_components`,
> `rank_v1.py:958-1023`), the pitcher outcome feature vector
> (`_outcome_feature_vector`, `model.py:350-393`), and the model-score blend
> (`_model_score`, `rank_v1.py:821-844`) are the load-bearing surgery surfaces —
> re-verify them at HEAD.

## Status

- **Priority**: **P1** (correctness / honesty leak: the public prospect board is
  governor-blocked as pitcher-heavy, two live stale-pedigree bugs are on the top-16,
  and the defect is *drifting up* — archive top-25 pitcher count went 7 → 10 → 8 →
  11 across June with no methodology change). This is the fix the governor's own
  `next_allowed_step: repair_model_quality_before_public_promotion` and the model's
  own remediation string (`calibration_report.py:469`) call for.
- **Effort**: **L** (model surgery). Three fixes in strict priority order, with a
  hard cut line that runs **bottom-up**: (a) stale-pedigree decay/cap is highest ROI
  and must ship; (b) pitcher risk pricing ships if (a) leaves the defect only
  partially corrected (expected); (c) blend decorrelation is a retrain-and-measure
  hypothesis and is **CUTTABLE** — do it only if (a)+(b) land clean. The retrain in
  (c) IS its own validation.
- **Risk**: **HIGH**. This is a deliberate re-score of the live prospect board.
  Sharp edges: (1) **over-correction** — burying the three legitimately-elite arms
  with real consensus support (Anderson 807739, Hernandez 815825, Sloan) instead of
  correcting the defect; the acceptance gate exists to catch exactly this. (2)
  **AOTC contamination** — the fix touches the rank artifact the frozen AOTC
  scorecard reads; the pre-registered funnel for already-matured calls must be
  provably unchanged. (3) **re-baseline as fake movement** — without the epoch bump
  the fix-day looks like every prospect moved (the 7/7 retrain jitter already caused
  a public "Riley Quick buys-board" incident; a *deliberate* re-baseline without
  epoch handling would be worse). (4) **chasing tie-noise** — the top band is
  tie-fragile (ranks 9-17 span ~0.81 pts/rank); NEVER hand-tune to exactly 7.
- **Depends on**: none in flight. **Composes with** the separate small
  buys-momentum re-baseline-masking fix shipping ~7/13 (public commitment): 028 must
  **not depend on it** and must **not conflict** with it — both touch the
  re-baseline-masking surface, so coordinate the epoch/momentum handling (see Step
  6). If that fix has already landed at execution time, read its diff first and
  confirm the epoch bump here is additive, not a re-do.
- **Category**: model fix (correctness — prospect scoring).
- **Planned at**: commit `125cd43c`, 2026-07-11. Evidence base:
  `docs/governor-review-2026-07-13-pitcher-lean-memo.md` (every claim verified
  against committed artifacts on 7/11).
- **Execution window**: **STRICTLY post-7/13, AFTER the AOTC unlock is confirmed.**
  Do not start until the 7/13 ledger-week AOTC unlock is confirmed live. Model
  changes are gated behind it precisely because they touch the AOTC-scored path.

## Why this matters

The quality governor blocks the public prospect board with
`prospect_top_board_role_shape` = FAIL: the top-25 holds 11 pitchers against a hard
cap of 7 (`quality/valucast_governor.py:459-462`;
`data/models/valucast_quality_governor.json` blocked check). The 7/13 governor
review (`docs/governor-review-2026-07-13-pitcher-lean-memo.md`) verified against the
committed 7/11 archive that **this is a model defect, not a defensible contrarian
view**:

- **The field is not pitcher-heavy — our board is the outlier.** Ranking the
  identical universe by internal consensus source-rank median holds 5-6 pitchers in
  the top-25 at every coverage floor, never 11. Of our 11 top-25 pitchers, **8 sit
  outside the field's consensus top-25**. Only **Anderson (807739), Hernandez
  (815825), Sloan** have real consensus support. We diverge on *draft slot*, not on
  a *performance* thesis, and the industry has seen the same pro lines.
- **The divergence is pedigree, not performance.** The pitcher OUTCOME axis is 100%
  draft-pedigree for 8 of 11 top-25 arms (≥73% for all 11); the largest single
  driver is `pick_value` / inverse draft round for 10 of 11.
- **The model predicts pitchers worst.** Its own realized-outcome backtest orders
  pitchers near-randomly: adapter rank-concordance **hitter 0.779 vs pitcher 0.490**
  (0.5 = coin flip), top-quartile precision 0.374 vs 0.256, dynasty Brier 0.158 vs
  0.222 (`data/models/valucast_prospect_outcome_backtest.json`,
  `evidence.adapter_fixed_horizon.roles[0]=hitter` / `roles[1]=pitcher`). The board
  concentrates its top-25 on the role its own eval trusts least, for a 2024-26 draft
  cohort entirely outside the ≤2019 validation window.
- **The peak layer cannot mark anyone down.** `negative_delta_count = 0` in all 14
  buckets of `data/models/valucast_prospect_peak_projection_calibration.json` — it
  never prices downside.
- **There is zero pitcher-attrition discount anywhere.** A healthy, full-sample
  pitcher gets the same availability discount as a healthy hitter
  (`prospects/availability.py` — every discount is gated on injury / staleness /
  thin-sample, none on a structural role base rate).
- **Two live stale-pedigree bugs**: **Gabriel Hughes** (mlbam 687312, 2022 draft
  slot, ~6-40 IP current line, FV 40, consensus ~#571, 2 boards) sits at **#10**;
  **Owen Murphy** (mlbam 702566, 2022 pick, ~20 IP) at **#16**. A 3-4-year-old draft
  slot plus a weak current line ranking top-16 is a defect, not a view.

## The mechanistic root cause (why the existing guardrails miss it) — READ THIS FIRST

The memo says the governor's pedigree guardrails "pass at 0.0" while Hughes/Murphy
are live pedigree bugs. Here is exactly why, verified in-code at `125cd43c`. **The
fix must make these existing guardrails BIND, not bolt on a parallel mechanism if
extending them suffices.**

1. **There already IS a pedigree cap — but it only fires on the no-sample fallback
   path.** `rank_v1.py:_score_components` (line 1065) has three score-source
   branches (line 1087-1119):
   - `if model_score is not None:` → source `"prospect_model_v0_6"`, score =
     `0.76*model_score + …` (line 1087-1096). **No pedigree cap is applied here.**
   - `elif investment_score >= PEDIGREE_MIN_INVESTMENT_SCORE:` → source
     `PEDIGREE_SCORE_SOURCE` ("prospect_pedigree_v0_7"), score via
     `_pedigree_fallback_score_components` (line 1098-1108) — **this is the ONLY
     branch that calls `_pedigree_score_cap`** (`rank_v1.py:958-1023`; caps
     `PEDIGREE_HITTER_SCORE_CAP=48.0` / `PEDIGREE_PITCHER_SCORE_CAP=45.5`).
   - `else:` → `"universal_fallback"` (line 1109-1118).

   Hughes and Murphy **have a current-season sample → they have a `model_score` →
   they take the FIRST branch** and are scored `"prospect_model_v0_6"`. The pedigree
   cap literally never executes for them.

2. **The pedigree features are inside the main model_score, uncapped and
   un-decayed.** The pitcher outcome feature vector `model.py:_outcome_feature_vector`
   (line 350-393) contains, for role `pitcher`, the exact pedigree features the memo
   names — with no years-since-draft decay:
   - line 383: `_zero_num(record.get("pick_value"))`
   - line 384: `1.0 / (draft_pick or 999.0)` (inverse draft pick)
   - line 385: `1.0 / (draft_round or 99.0)` (inverse_draft_round)
   - line 386: `_safe_log1p(bonus)` (log signing bonus)

   A 2022 pick carries these at full strength in 2026 exactly like a fresh 2026
   draftee. These flow through `_model_score` (`rank_v1.py:821-844`, the
   `0.58*outcome + 0.42*impact` blend, `MODEL_COMPONENT_WEIGHTS` line 128-129) into
   the `model_score` component at 0.76 weight — the whole time bypassing every
   pedigree guardrail.

3. **The governor's pedigree checks count the WRONG population.**
   `_prospect_pedigree_rate` (`valucast_governor.py:571-600`) and its siblings filter
   rows where `(row.get("score_source") or row.get("value_source")) ==
   PEDIGREE_SCORE_SOURCE` (line 581). Hughes/Murphy carry `score_source =
   "prospect_model_v0_6"`, so they contribute **zero** to `pedigree_count` and the
   rate reports 0.0 / passing. The guardrail measures pedigree-*fallback* rows and is
   structurally blind to pedigree dominance that rides inside a `model_score`.

4. **The existing years-since-draft decay only modulates a CONFIDENCE spare, never
   the point estimate.** `_pedigree_spare_credit` (`rank_v1.py:1205-1223`) decays by
   years-since-draft (`PEDIGREE_SPARE_FRESH_YEARS=2.0` →
   `PEDIGREE_SPARE_STALE_YEARS=5.0`) — but its own docstring (line 1210) states it
   "Modulates the confidence haircut, never the point estimate." So the decay
   machinery exists but is wired to the wrong lever for this bug: it softens a
   thin-sample confidence penalty, it does not shrink a stale pedigree feature's
   contribution to the score.

**Conclusion for the fix**: the stale-pedigree defect lives on the
`prospect_model_v0_6` MAIN path (Hughes/Murphy have a sample), not the pedigree
fallback path where the cap already runs. Fix (a) must attenuate the pedigree
features' contribution to `model_score` on the main path (decay by years-since-draft
and/or cap the pedigree share when the current sample is adequate-and-mediocre), and
must make the governor guardrail bind on that population (so it can no longer report
0.0 while pedigree carries an arm to #10). Prefer extending the *existing* cap/decay
constants and the *existing* governor check over inventing a parallel mechanism.

## Current state

Verified against the live files at `125cd43c`. Read each cited line yourself before
building on it.

### The score-source branch and the fallback-only pedigree cap (`prospects/rank_v1.py`)

- **`_score_components` (line 1065-1141)** — the three-way branch (line 1087-1119)
  documented above. Role is in scope in this function; the pedigree fallback path
  passes `role` into `_pedigree_score_cap`, which already differentiates
  `PEDIGREE_PITCHER_SCORE_CAP` (45.5) from `PEDIGREE_HITTER_SCORE_CAP` (48.0,
  line 964).
- **`_model_score` (line 821-844)** — blends `expected_outcome_score` (0.58) and
  `expected_category_impact_score` (0.42) into the 0-100 `model_score`. It reads a
  `model_profile` and does **not** currently receive `role` — a pitcher-specific
  down-weight (fix b) either threads `role` into this function or applies at the
  `_score_components` call site (line 1087-1096) where role is already available.
- **Module constants** (verified values):
  `MODEL_COMPONENT_WEIGHTS = {"expected_outcome_score": 0.58,
  "expected_category_impact_score": 0.42}` (line 127-130);
  `SCORE_WEIGHTS["prospect_model_v0_6"]["model_score"] = 0.76` (line 136);
  `PEDIGREE_SPARE_FRESH_YEARS=2.0` / `PEDIGREE_SPARE_STALE_YEARS=5.0` (line 87-88);
  `PEDIGREE_MIN_INVESTMENT_SCORE=90.0` (line 110);
  `PEDIGREE_HITTER_SCORE_CAP=48.0` / `PEDIGREE_PITCHER_SCORE_CAP=45.5` (line
  111-112); `PEDIGREE_UPPER_LEVEL_BONUS_CAP=1.25`,
  `PEDIGREE_HIGH_SAMPLE_BONUS_CAP=0.75`, `PEDIGREE_CAP_COMPRESSION_WINDOW=1.5` (line
  113-115); `PEDIGREE_SCORE_SOURCE = "prospect_pedigree_v0_7"` (line 42).
- **`_pedigree_spare_credit` (line 1205-1223)** — the years-since-draft decay that
  modulates the confidence haircut only (docstring line 1210). Reuse its
  fresh/stale-years constants for the fix (a) decay so the two agree on what "stale"
  means, but wire the new decay to the *point estimate* / pedigree feature share.

### The pitcher feature vector and the shared-base collinearity (`prospects/model.py`)

- **`_feature_vector` (line 289-315)** — the base role feature vector (pitcher branch
  line 304-314: k/9, bb/9, k-bb%, era, whip, youth, level, is_starter).
- **`_outcome_feature_vector` (line 318-393)** — starts from `_feature_vector` (line
  319) and appends the extended pitcher features **including the pedigree block at
  line 383-386** (pick_value, inverse draft pick, inverse draft round, log bonus).
- **`_canonical_impact_feature_vector` (line 396+)** — the impact head's feature
  vector, **also derived from the same `_feature_vector` base** (line 396). This
  shared base is the source of the outcome↔impact collinearity (memo: top-25 r=0.92
  for pitchers vs 0.78 hitters). Fix (c)'s decorrelation target.
- **`_impact_target` (line 476-517)** — the impact regression target. For each
  post-cohort season it takes `max(group_scores)` over `IMPACT_CATEGORY_GROUPS[role]`
  (line 515-516) then `max(scores, default=0.0)` over seasons (line 517). The
  role-shape `max()` over starter/reliever group shapes **can only push impact up**
  — fix (c) reconsiders this.

### The availability layer — no structural pitcher attrition discount (`prospects/availability.py`)

- **771 lines.** Every discount is *conditional*: `MAX_RISK_DISCOUNT=0.12`,
  `SEVERE_IL_DISCOUNT=0.30`, `SHORT_IL_DISCOUNT=0.12` (line 29-31);
  `_staleness_signal` (line 305-329) fires on prior-season sample / days-stale;
  `_status_discount` (line 332-339) fires on IL status; the thin-workload signals
  (line 282-301, e.g. `thin_pitcher_workload_under_12_ip`) fire on small samples.
- **Role IS branched, but only inside conditional signals** (line 321/324/327 give
  pitchers a slightly larger staleness discount than hitters; line 282-294 flag thin
  pitcher workloads). **There is NO unconditional, structural role base-rate discount
  applied to a healthy full-sample pitcher.** A pitcher with a fresh, adequate line
  and no IL flag gets `discount = 0.0`, identical to a hitter. This is exactly where
  fix (b)'s pitcher attrition base-rate discount slots in — a floor that applies
  regardless of injury/staleness signals. `apply_availability_adjustment`
  (`availability.py:560`, imported in `rank_v1.py:18`) applies `score * (1.0 -
  discount)` at line 575; the per-player discount is assembled in `_profile`'s final
  `max(...)` combination (`availability.py:502-514`, the `max()` at ~505-510) where
  `role` is in scope (~line 462) — fold a `pitcher_attrition_discount` into that
  `max()`. **CAVEAT**: `MAX_RISK_DISCOUNT=0.12` (line 29) ceilings that branch and
  `apply_availability_adjustment` re-clamps to 0.12 unless the basis is
  `official_mlb_il` / `manual_override` — so a modest base-rate discount composes
  under that ceiling; do not expect it to stack unbounded.

### The governor role-shape block and the mis-targeted pedigree checks (`quality/valucast_governor.py`)

- **`_prospect_top_board_role_shape` (line 436-489)** — the blocking check. Fails
  when `top25_pitcher_count > MAX_TOP25_PROSPECT_PITCHER_COUNT` (=7) OR
  `top50_pitcher_rate > MAX_TOP50_PROSPECT_PITCHER_RATE` (=0.30). These thresholds are
  IMPORTED (governor line 17/20) from **`prospects/calibration_report.py:31-32`**
  (`MAX_TOP25_PITCHER_COUNT=7`, `MAX_TOP50_PITCHER_RATE=0.30`) — so "do not touch the
  thresholds" means do not touch them in calibration_report.py either.
  `PROSPECT_INVESTMENT_TOP_N=25` (line 85), `PROSPECT_FALLBACK_TOP_N=50` (line 77).
  `_is_pitcher_row` (line 379-381) = positions ∩ {P,SP,RP} or role=="pitcher".
  **Do NOT touch these thresholds** — the count is tie-noise and the review verdict is
  "no governor change, fix the model."
- **`_prospect_pedigree_rate` (line 571-600)**, `_prospect_lower_minors_pedigree`
  (~line 620-684), `_prospect_pedigree_cap_plateau` (line 717-749) — the pedigree
  guardrails the memo reports "passing at 0.0." All filter on `score_source ==
  PEDIGREE_SCORE_SOURCE` (e.g. line 581, 628), so they are blind to pedigree
  dominance inside a `prospect_model_v0_6` score. `MAX_TOP50_PEDIGREE_RATE=0.35`
  (line 81), `MAX_TOP25_EXACT_PEDIGREE_CAP_COUNT=3` (line 87). Making a guardrail
  *bind* on the main-path pedigree population is part of fix (a).

### The acceptance-gate backtest artifact + builder

- **Artifact**: `data/models/valucast_prospect_outcome_backtest.json`. The
  gate metrics live at `evidence.adapter_fixed_horizon.roles[i]`, with
  `roles[0].role == "hitter"` and `roles[1].role == "pitcher"` (verified). Per role:
  `candidate_rank_concordance`, `candidate_top_quartile_precision`,
  `candidate_multiclass_brier`; the dynasty layer mirrors at
  `evidence.dynasty_fixed_horizon.roles[i]` with `candidate_multiclass_brier`.
  Current values (the numbers the fix must improve for pitcher without degrading
  hitter): hitter concordance **0.7791**, pitcher concordance **0.4903**; hitter
  top-quartile precision 0.3736 vs pitcher 0.2557; dynasty Brier hitter 0.1577 vs
  pitcher 0.2218.
- **Builder**: `scripts/build_prospect_outcome_backtest.py` (no CLI args; calls
  `prospects.outcome_backtest.run_outcome_backtest()`). Rerun with
  `python scripts/build_prospect_outcome_backtest.py`. Its validator is
  `scripts/validate_prospect_outcome_backtest.py`; both are wired into the daily
  build (`run_daily_public_build.py`).

### The frozen AOTC scoring path (do NOT touch)

- **`prospects/ahead_of_consensus.py`** and
  **`scripts/build_ahead_of_consensus_scorecard.py`** are frozen (pre-registered AOTC
  scoring). The scorecard artifact is
  `data/models/valucast_ahead_of_consensus_scorecard.json` (built from the
  `valucast_prospect_rank_v1` archive dir).
- **AOTC is RANK-COUPLED — so "the artifact regenerates identically" is NOT a valid
  integrity check.** `ahead_of_consensus.py` computes `divergence = consensus_rank -
  valucast_rank` where `valucast_rank` **IS the model rank** (`ahead_of_consensus.py:128,135`),
  and the enrollment guards gate on it (`_is_guarded`, line 160-167: `valucast_rank
  <= MAX_VALUCAST_RANK(300)`, `divergence >= MIN_DIVERGENCE(25)`). The scorecard
  builder replays the dated archive through those same guards
  (`build_ahead_of_consensus_scorecard.py:77-79`) and its catch-up attribution diffs
  `valucast_rank` now-vs-then (line 255). Therefore a genuine model re-score is
  **EXPECTED to move the scorecard funnel** — divergence, guard-eligibility, and
  catch-up numbers all shift with the rank. There is no "unchanged artifact" to
  assert. The one-way isolation the `feeds_model_score: False` flags describe is the
  REVERSE direction (AOTC output never feeds back into the model — the model stays
  blind to consensus); forward, the model rank is a primary AOTC input.
- **What AOTC integrity therefore means here**: the pre-registered **scoring LOGIC**
  is frozen and untouched — the funnel may move only because its `valucast_rank`
  INPUT moved (the legitimate consequence of the fix), never because the scoring code
  changed. The integrity gate (Step 7) is: (1) the two frozen files are **zero-diff**
  (the scorecard's math/guards/thresholds are byte-identical), and (2) the movement
  in the regenerated scorecard is attributable ENTIRELY to rank changes on the fixed
  arms, with no change to the guard thresholds, the enrollment rule, or the catch-up
  formula. Word every AOTC STOP condition around *expected rank-driven movement*, not
  artifact identity.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Rebuild the model→rank chain (the re-score) | run the prospect chain in `run_daily_public_build.py:BUILD_STEPS` order: `build_prospect_model.py` (only if model shape changed) → `build_prospect_availability.py` → `build_prospect_rank_v1.py` → `build_public_dynasty_snapshot.py` | each rewrites its artifact, no exception |
| **Acceptance gate: rebuild the UPSTREAM backtests, THEN re-aggregate.** The outcome-backtest builder only RE-AGGREGATES pre-built inputs — it does NOT rebuild them. | `python scripts/build_prospect_adapter_backtest.py` && `python scripts/build_prospect_dynasty_backtest.py` && `python scripts/build_prospect_forward_validation.py` && `python scripts/build_prospect_outcome_backtest.py` | fresh concordance; a bare `build_prospect_outcome_backtest.py` alone reports STALE numbers |
| Read the gate metrics after a rerun | `python -c "import json;d=json.load(open('data/models/valucast_prospect_outcome_backtest.json'));r=d['evidence']['adapter_fixed_horizon']['roles'];print('hitter',r[0]['candidate_rank_concordance'],'pitcher',r[1]['candidate_rank_concordance'])"` | pitcher > 0.4903, hitter ≈ 0.7791 (not materially lower) |
| Rebuild the governor + read the blocking check | `python scripts/build_valucast_quality_governor.py` then `python -c "import json;d=json.load(open('data/models/valucast_quality_governor.json'));print([c for c in d.get('checks',d) if 'role_shape' in str(c)][:1])"` (adjust to the artifact's actual shape) | role-shape check present; count reported |
| Consensus-alignment check (INTERNAL only) | see Step 5 helper — reads `context_only.source_ranks` internally; NEVER publishes per-source ranks | Anderson/Hernandez/Sloan stay top-25 |
| **AOTC integrity: frozen SCORING LOGIC zero-diff** (the real check — AOTC is rank-coupled, so the artifact IS expected to move) | `git diff --stat 125cd43c..HEAD -- prospects/ahead_of_consensus.py scripts/build_ahead_of_consensus_scorecard.py` | empty (no changes) |
| **AOTC integrity: scorecard movement is rank-attributable only** | rebuild the scorecard; confirm the guard thresholds / enrollment rule / catch-up formula in the artifact metadata are unchanged and any funnel movement traces to the re-scored arms (Step 7) | thresholds unchanged; movement only from rank input |
| Epoch bump verification | `python -c "from prospects.buys import PROSPECT_BUYS_EPOCH;print(PROSPECT_BUYS_EPOCH)"` | the NEW epoch string (not `2026-06-22-role-normalization`) |
| Targeted suites (executor) | `python -m pytest -q tests/test_prospect_rank_v1.py tests/test_prospect_model.py tests/test_prospect_availability.py tests/test_valucast_quality_governor.py tests/test_prospect_outcome_backtest.py` (adjust to the real test filenames) | all pass |
| Full suite (reviewer gate) | `python -m pytest -q` | all pass; then restore the byproduct |
| Restore pytest byproduct | `git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json` | file back to HEAD (pytest dirties it — NEVER commit it) |

> The exact rank-build and test filenames must be confirmed against HEAD in Step 0
> (do not guess). The invocations above are the shape, not verbatim gospel where a
> `(adjust …)` note appears.

## Scope

**In scope** (the files you may modify — FIX (a) and FIX (b); FIX (c) is cuttable):

- **`prospects/rank_v1.py`** — FIX (a): attenuate the pedigree features' contribution
  to `model_score` on the `prospect_model_v0_6` main path (decay by years-since-draft
  and/or cap the pedigree share when the current sample is adequate-and-mediocre),
  reusing the existing pedigree constants/decay where possible. FIX (b): the
  pitcher-specific outcome/impact down-weight (either thread `role` into `_model_score`
  or apply at the `_score_components` call site, line 1087-1096). New constants live
  here next to the existing `PEDIGREE_*` / `MODEL_COMPONENT_WEIGHTS` block.
- **`prospects/model.py`** — FIX (a) if the cleanest place to decay the pedigree
  features (line 383-386) is at feature construction rather than at scoring; FIX (c)
  (cuttable): decorrelate the outcome/impact feature bases and/or reconsider the
  `max()`-over-role-shape impact target (line 495-517). Any change here that alters
  the trained model shape triggers a retrain (see Step 4c).
- **`prospects/availability.py`** — FIX (b): add a **role-based pitcher attrition
  base-rate discount** (a structural floor applied to every pitcher regardless of
  injury/staleness signal), documented in methodology. Slot it into the per-player
  discount assembly (~line 460-480) where `role` is resolved; keep it distinct from
  and composable with the existing conditional discounts (do not double-count).
- **`quality/valucast_governor.py`** — FIX (a): make a pedigree guardrail BIND on the
  main-path pedigree population (so it can no longer report 0.0 while pedigree carries
  an arm to #10). Prefer extending an existing check's population (e.g. count
  main-path rows whose pedigree share exceeds a threshold) over a wholly new check.
  **Do NOT touch** `MAX_TOP25_PROSPECT_PITCHER_COUNT` / `MAX_TOP50_PROSPECT_PITCHER_RATE`
  or the role-shape thresholds.
- **`prospects/buys.py`** — the **comparability epoch bump** (Step 6): change
  `PROSPECT_BUYS_EPOCH` (line 32) from `"2026-06-22-role-normalization"` to a new
  descriptive string (e.g. `"2026-07-14-pitcher-lean-model-fix"`). This is the
  re-baseline-masking lever for movers/buys/value-trend surfaces.
- **Methodology copy** (`templates/methodology.html` or the relevant methodology
  surface — confirm in Step 0): document the pitcher attrition base-rate discount and
  the pitcher concordance-gap down-weight (cite the memo's 0.49-vs-0.78 gap and the
  structural-attrition rationale — a healthy pitcher prospect carries availability
  risk a hitter does not).
- **The regenerated committed artifacts**: the rank artifact, the governor artifact,
  the outcome-backtest artifact, and the availability artifact — all regenerated by
  their builders, staged explicitly by path. **Never `git add -A`.**
- **Tests**: new/updated assertions in the prospect-rank, model, availability, and
  governor test files (see Test plan).

**Cut line (bottom-up — the reviewer applies it at planning/review time):**

- **FIX (a) — stale-pedigree decay/cap — MUST SHIP.** Highest ROI; kills the
  Hughes/Murphy class and dampens the 8 divergent arms. Non-cuttable.
- **FIX (b) — pitcher risk pricing (concordance-gap down-weight + attrition
  discount) — SHIPS unless (a) alone fully corrects the defect** (it will not: the
  memo's counterfactual shows an ~8-pt effective pedigree correction lands top-25 at
  ~9 pitchers, so (a)+(b) are needed together). Ship (b) with (a).
- **FIX (c) — blend decorrelation — CUTTABLE.** It is a retrain-and-measure
  hypothesis (the memo flags the double-count / max()-over-roles as reconstructed
  from code, not a committed writeup; per-player stake ~2-8 pts is an estimate). Do
  (c) ONLY if (a)+(b) land clean AND there is session budget for a retrain that
  passes the backtest gate. If (c) does not improve the gate, **revert it** — the
  retrain is its own validation, and a null result is a valid outcome to report.

**Out of scope** (do NOT touch):

- **The governor role-shape thresholds** (`MAX_TOP25_PROSPECT_PITCHER_COUNT=7`,
  `MAX_TOP50_PROSPECT_PITCHER_RATE=0.30`). The review verdict is explicit: fix the
  model, not the thresholds. Relaxing them would publish a board the field disagrees
  with on 8 of 11 top arms.
- **The frozen AOTC files**: `prospects/ahead_of_consensus.py`,
  `scripts/build_ahead_of_consensus_scorecard.py`. Zero-diff required.
- **Publishing per-source ranks.** The consensus-alignment checks read
  `context_only.source_ranks` **INTERNALLY only** — never render or export a
  per-source rank (ToS; aggregate median + board count only is the site's standard).
- **The peak-projection layer's downside pricing.** The `negative_delta_count=0`
  finding is real but re-architecting the peak layer to price downside is a separate,
  larger plan — this plan does NOT open it. (Note it in methodology/maintenance as a
  known limitation the pitcher risk pricing partially compensates for.)
- **The "routing cliff Adams/Jenkins" finding.** Per the memo it is a **hitter-tail
  resolution artifact, NOT part of the pitcher story** — do NOT cite it as motivation
  and do NOT touch the role-quantile normalization on its account.
- **DD feeds** (`data/dd/*`). ValuCast is DD-independent; the untracked
  `data/dd/dd_dynasty_feed.json` in the tree is not staged, ever.

## Git workflow

- Work directly on `master` (repo convention), but **do NOT push**: master
  auto-deploys valucast.app via Render. Commit locally; the reviewer reruns the
  backtest gate + full suite + the AOTC-integrity diff and gates the push.
- **NEVER `git add -A` / `commit -am`** — untracked feeds (`data/dd/*`) and the
  pytest byproduct must not be swept in. Stage each in-scope file + each regenerated
  artifact explicitly by path. **Never `git stash`.**
- Do NOT stage `data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`
  (pytest byproduct — `git checkout --` it after any pytest run) or
  `data/dd/dd_dynasty_feed.json`.
- Commit message style (short imperative subject), e.g.
  `Fix prospect pitcher lean: bind stale-pedigree cap on main score path + pitcher risk pricing; bump comparability epoch`.

## Steps

### Step 0: Confirm the surgery surfaces and gate plumbing are live before touching anything

Confirm each cited surface at HEAD (STOP if any is refactored away or already
changed):
```
# The three-way score-source branch + the fallback-only cap:
python -c "import prospects.rank_v1 as r; import inspect; s=inspect.getsource(r._score_components); print('prospect_model_v0_6' in s, '_pedigree_fallback_score_components' in s)"   # True True
python -c "import prospects.rank_v1 as r,inspect; print('_pedigree_score_cap' in inspect.getsource(r._pedigree_fallback_score_components))"   # True
# The pitcher pedigree features in the outcome vector:
python -c "import prospects.model as m,inspect; s=inspect.getsource(m._outcome_feature_vector); print('pick_value' in s and 'draft_round' in s and 'signing_bonus' in s.replace('bonus','signing_bonus') or 'bonus' in s)"   # True
# The blend + weights:
python -c "from prospects.rank_v1 import MODEL_COMPONENT_WEIGHTS,SCORE_WEIGHTS; print(MODEL_COMPONENT_WEIGHTS, SCORE_WEIGHTS['prospect_model_v0_6']['model_score'])"   # {...0.58...0.42...} 0.76
# The governor pedigree checks filter on PEDIGREE_SCORE_SOURCE:
python -c "import quality.valucast_governor as g,inspect; print('PEDIGREE_SCORE_SOURCE' in inspect.getsource(g._prospect_pedigree_rate))"   # True
# The epoch constant and the backtest gate:
python -c "from prospects.buys import PROSPECT_BUYS_EPOCH; print(PROSPECT_BUYS_EPOCH)"   # 2026-06-22-role-normalization
python -c "import json;d=json.load(open('data/models/valucast_prospect_outcome_backtest.json'));r=d['evidence']['adapter_fixed_horizon']['roles'];print(r[0]['role'],r[0]['candidate_rank_concordance'],r[1]['role'],r[1]['candidate_rank_concordance'])"   # hitter 0.7791 pitcher 0.4903
# Confirm the AOTC unlock actually happened (the execution gate) — inspect the AOTC scorecard/governor state per whatever signals the unlock; do NOT proceed if still locked.
```
Also record the **pre-fix baselines**: copy
`data/models/valucast_prospect_outcome_backtest.json` (Step 4 acceptance-gate
comparison) and `data/models/valucast_ahead_of_consensus_scorecard.json` (Step 7 —
NOT for byte-diff, since AOTC is rank-coupled and WILL move; only to confirm the
scoring PARAMETERS/thresholds are unchanged) to a scratch location. Confirm the
prospect build chain order in `run_daily_public_build.py:BUILD_STEPS`
(`build_prospect_model` → `build_prospect_availability` → `build_prospect_rank_v1` →
… → `build_prospect_adapter_backtest`/`build_prospect_dynasty_backtest` →
`build_prospect_forward_validation` → `build_prospect_outcome_backtest`) and the real
test filenames.

**Verify**: all confirmations match. If any surface is gone or the AOTC unlock is not
confirmed, STOP.

### Step 1: FIX (a) — bind the stale-pedigree decay/cap on the MAIN score path

Attenuate the pedigree features' contribution to `model_score` for players who take
the `prospect_model_v0_6` branch, decayed by years-since-draft and/or capped as a
share of the outcome/impact axes **when the current-season performance sample is
adequate and mediocre**. Two viable implementation loci (pick the simpler that fully
binds; document the choice):

1. **At feature construction (`model.py:_outcome_feature_vector`, line 383-386)**:
   multiply the pedigree features (pick_value, inverse draft pick, inverse draft
   round, log bonus) by a years-since-draft decay factor (reuse the fresh/stale-years
   semantics of `_pedigree_spare_credit`: full weight ≤ ~2 years since draft, decayed
   to a floor by ~5 years). This changes the trained model shape → **triggers a
   retrain** (Step 4c). Cleanest conceptually (the feature is genuinely staler), but
   heavier.
2. **At scoring (`rank_v1.py:_score_components`, main branch line 1087-1096)**: cap
   the pedigree-attributable share of `model_score` when (i) years-since-draft is
   high AND (ii) the current sample is adequate (clears a pitch/IP/PA floor) AND (iii)
   the current line is mediocre (below a role percentile). No retrain, but requires a
   way to attribute the pedigree share of `model_score` (the model's per-feature
   contribution or a pedigree-only re-score delta). Lighter, more surgical.

**Hard constraints on fix (a):**
- **Must kill the Hughes/Murphy class**: a 3-4-year-old draft slot + weak current
  line must not price to top-16. Verify Hughes (687312) and Murphy (702566) drop out
  of the top-16 after the fix.
- **Must NOT touch the fresh-draftee class**: 2025-26 picks with no pro sample are
  legitimately pedigree-priced (they go through the `PEDIGREE_SCORE_SOURCE` fallback
  or have low years-since-draft). The decay must be ~1.0 for fresh picks. Verify a
  known fresh 2025/26 pick is unmoved.
- **Make the governor guardrail bind**: extend an existing pedigree check
  (`valucast_governor.py`) so a main-path row whose pedigree share is dominant AND
  stale is counted, so the guardrail can no longer report 0.0 while the defect is
  live. Prefer extending `_prospect_pedigree_rate` (or a sibling) over a parallel
  check.

**Verify**:
- Rebuild the rank artifact; Hughes (687312) and Murphy (702566) are out of the
  top-16; a fresh 2025/26 pick is unmoved; the extended governor pedigree check now
  reflects a non-zero main-path pedigree count.

### Step 2: FIX (b) part 1 — pitcher outcome/impact concordance-gap down-weight

Down-weight the pitcher outcome/impact contributions to reflect the measured
0.49-vs-0.78 concordance gap (the model's own remediation:
`calibration_report.py:469` → "Review pitcher outcome weighting and availability
gates"). Apply a pitcher-specific multiplier to `model_score` (or to the
outcome/impact blend components) so the role the backtest orders near-randomly does
not dominate the top board. Thread `role` into `_model_score` (`rank_v1.py:821-844`)
or apply at the `_score_components` call site where `role` is available. Keep hitter
scoring untouched (its concordance is 0.78 and must not degrade).

**Verify**:
- Pitcher scores compress relative to hitters at parity of raw performance; hitter
  scores unchanged (byte-identical hitter rows vs pre-(b) where (a) didn't touch
  them). Anderson/Hernandez/Sloan still present in the top-25 (they survive because
  they have genuine performance, not just pedigree).

### Step 3: FIX (b) part 2 — pitcher attrition base-rate discount in `availability.py`

Add a **role-based structural attrition discount** applied to every pitcher
regardless of injury/staleness signal (a healthy pitcher prospect carries
attrition risk a healthy hitter does not — the TINSTAAPP base rate). Slot it into the
per-player discount assembly (~`availability.py:460-480`) where `role` is resolved,
composed with (not double-counting) the existing conditional discounts. Pick a
modest, documented base rate (state the chosen value + rationale in the artifact
metadata and methodology). This must be distinct from the thin-workload / staleness
signals so it applies to a full-sample healthy arm too.

**Verify**:
- A healthy, full-sample pitcher with no IL/staleness flag now carries a non-zero
  attrition discount; an equivalent hitter does not. The discount is documented in
  the availability artifact metadata and methodology copy.

### Step 4: Rebuild, rerun the ACCEPTANCE GATE, and check consensus survival

**4a — Rebuild the full chain in BUILD_STEPS order** (confirmed in Step 0). At
minimum: `build_prospect_model` (only if the model shape changed — fix (a) locus-1 or
fix (c)), then `build_prospect_availability`, `build_prospect_rank_v1`, then the
UPSTREAM backtests `build_prospect_adapter_backtest` and
`build_prospect_dynasty_backtest` and `build_prospect_forward_validation`, then the
governor (`build_valucast_quality_governor`). **The outcome-backtest builder only
RE-AGGREGATES these upstream artifacts — it does not rebuild them.** Skipping the
upstream rebuilds makes the "acceptance gate" report STALE pre-fix numbers.

**4b — Acceptance gate (non-negotiable): re-aggregate and read the fresh metrics.**
```
python scripts/build_prospect_outcome_backtest.py
python -c "import json;d=json.load(open('data/models/valucast_prospect_outcome_backtest.json'));r=d['evidence']['adapter_fixed_horizon']['roles'];print('hitter',r[0]['candidate_rank_concordance'],'pitcher',r[1]['candidate_rank_concordance'])"
```
- **Pitcher `candidate_rank_concordance` MUST IMPROVE** over the pre-fix 0.4903.
- **Hitter `candidate_rank_concordance` MUST NOT degrade materially** below 0.7791
  (define "material" with the reviewer; a trivial jitter down is acceptable, a real
  drop is a STOP). Also check top-quartile precision and dynasty Brier move the right
  way (pitcher Brier ↓ from 0.2218 is the confirming signal).

**4c — Retrain gate (only if a fix changed the model shape — i.e. fix (a) locus 1, or
fix (c)).** If the trained model was retrained, the backtest rerun above IS the
validation. A retrain that does not improve pitcher concordance without degrading
hitter is a failed fix — revert that locus and use the scoring-side (no-retrain)
approach for (a), or cut (c).

**4d — Consensus survival (INTERNAL check).** Read `context_only.source_ranks` from
the rank artifact internally (never publish) and confirm **Anderson (807739),
Hernandez (815825), Sloan** remain in the top-25. Their survival is the tell that the
fix corrected the defect rather than deleting pitchers. If any of the three fell out,
the fix over-corrected — STOP and re-tune.

**Verify**: pitcher concordance up, hitter not materially down, the three
consensus-supported arms top-25.

### Step 5: FIX (c) — blend decorrelation (CUTTABLE; only if (a)+(b) landed clean)

Only proceed if (a)+(b) passed Step 4 and there is session budget. Two sub-levers:
1. **Decorrelate the outcome/impact heads**: they run on transformations of the same
   `_feature_vector` base (`model.py:319`/`396`), near-collinear (r=0.92 elite
   pitchers). Options: a single pitcher head, or a decorrelated impact feature basis.
2. **Reconsider the `max()`-over-role-shape impact target** (`model.py:495-517`):
   the `max()` over starter/reliever group shapes can only push impact up.

Both require **retrain-and-measure** — the retrain IS the validation. Rerun the
acceptance gate (Step 4b). If pitcher concordance does not improve (or hitter
degrades), **revert (c)** and ship (a)+(b) only. Report the null result honestly.

**Verify**: if kept, the backtest gate improves further; if not, (c) is reverted and
the tree matches the post-(b) state.

### Step 6: Bump the comparability epoch (re-baseline masking) — MANDATORY

A deliberate re-score is a big re-baseline. Bump `PROSPECT_BUYS_EPOCH`
(`prospects/buys.py:32`) from `"2026-06-22-role-normalization"` to a new descriptive
string (e.g. `"2026-07-14-pitcher-lean-model-fix"`). This resets the
forward-validation evidence clock (docstring line 30-31) and makes movers / buys /
value-trend surfaces mask the fix-day discontinuity instead of reporting it as player
movement.

- **Compose with the ~7/13 buys-momentum re-baseline-masking fix** (public
  commitment): if that fix has already landed, read its diff and confirm the epoch
  bump here is additive and does not conflict with its momentum masking. If it has
  not landed, this epoch bump must not depend on it — 028's masking stands alone via
  the epoch. Coordinate so the two do not double-mask or fight.

**Verify**:
- `python -c "from prospects.buys import PROSPECT_BUYS_EPOCH;print(PROSPECT_BUYS_EPOCH)"`
  → the new string.
- The buys/movers/value-trend surfaces treat the fix-day as an epoch boundary (no
  spurious "everyone moved" mover rows on the fix-day rebuild).

### Step 7: AOTC integrity gate (non-negotiable) — the SCORING LOGIC is frozen; the funnel is EXPECTED to move

**AOTC is rank-coupled** (see Current state): `valucast_rank` is the model rank and
the scorecard replays the archive through the enrollment guards, so a genuine
re-score MOVES the funnel. Do NOT assert artifact identity — that would be wrong.
Assert that the frozen *scoring logic* is untouched and the movement is
rank-attributable only.

**7a — Frozen scoring-logic files zero-diff:**
```
git diff --stat 125cd43c..HEAD -- prospects/ahead_of_consensus.py scripts/build_ahead_of_consensus_scorecard.py
```
→ empty. Any change to these two files (the divergence formula, the guard thresholds
`MAX_VALUCAST_RANK=300` / `MIN_DIVERGENCE=25`, the catch-up formula, the enrollment
rule) is a STOP.

**7b — Scorecard movement is rank-attributable only.** Rebuild
`data/models/valucast_ahead_of_consensus_scorecard.json` and confirm: the guard
thresholds / enrollment rule / catch-up formula recorded in the artifact metadata are
identical to the pre-fix copy saved in Step 0, and any change in the funnel
(divergence, enrolled set, catch-up) is explained by the re-scored arms' new
`valucast_rank`, NOT by any change in how a call is scored. A funnel that moved is
FINE and expected; a funnel that moved because a guard/formula changed is a STOP.

**Verify**: frozen files unchanged; the scorecard's scoring parameters unchanged;
funnel movement traces to rank input only.

### Step 8: Full suite + restore the byproduct

```
python -m pytest -q
git checkout -- data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json
git status --short
```
**Verify**: full suite green; `git status` shows ONLY in-scope files + the
regenerated artifacts (rank, governor, availability, outcome-backtest, and — if
regenerated — the AOTC scorecard, which must be identical for past calls). The
untracked `data/dd/*` is NOT staged and the archive byproduct is restored.

## Test plan

- **`tests/test_prospect_rank_v1.py`** (fix a + b scoring):
  1. **Stale-pedigree binds on the main path**: a synthetic pitcher record with a
     4-year-old draft slot + a mediocre adequate current line does NOT price into the
     top band; the pedigree share of its `model_score` is attenuated.
  2. **Fresh draftee unaffected**: a synthetic 2025/26 pick with no pro sample (or
     ≤2 years since draft) keeps full pedigree pricing.
  3. **Pitcher concordance-gap down-weight**: at parity of raw performance, a pitcher
     scores below what it would pre-fix; a hitter is unchanged.
  4. **Regression lock on the three consensus arms**: Anderson/Hernandez/Sloan
     (fixture rows) stay in the top band.
- **`tests/test_prospect_model.py`** (fix a locus-1 / fix c, if taken): the pedigree
  feature decay applies at feature construction; the decorrelated basis / revised
  impact target (if (c) kept) produces the expected feature shapes.
- **`tests/test_prospect_availability.py`** (fix b part 2): a healthy full-sample
  pitcher carries the new base-rate attrition discount; an equivalent hitter does
  not; the discount composes with (does not double-count) existing conditional
  discounts.
- **`tests/test_valucast_quality_governor.py`** (fix a governor binding): a
  main-path row with dominant stale pedigree is now counted by the extended pedigree
  check (no longer 0.0); the role-shape thresholds are unchanged.
- **`tests/test_prospect_outcome_backtest.py`**: the gate metric key paths resolve
  (`evidence.adapter_fixed_horizon.roles[0/1]`); a guard that pitcher concordance is
  not silently degraded by a future change (a floor assertion, tuned to the post-fix
  value).
- **AOTC integrity** (an assertion or a reviewer-run diff): the frozen files are not
  imported-and-monkeypatched; the scorecard funnel for a fixed set of matured calls
  is stable across a re-score.
- **Epoch**: an assertion that `PROSPECT_BUYS_EPOCH` changed (so a future silent
  re-baseline without an epoch bump is caught).
- Final: `python -m pytest -q` all green, then restore the archive byproduct.

## Done criteria

- [ ] `python -m pytest -q` exits 0; the byproduct file restored after.
- [ ] **FIX (a) ships and binds on the main path**: Hughes (687312) and Murphy
      (702566) are out of the top-16; a fresh 2025/26 pick is unmoved; a governor
      pedigree guardrail now BINDS on the main-path pedigree population (no longer
      reports 0.0 while the defect is live).
- [ ] **FIX (b) ships**: pitcher outcome/impact is down-weighted to reflect the
      0.49-vs-0.78 concordance gap AND a role-based pitcher attrition base-rate
      discount exists in `availability.py`, applied to healthy full-sample pitchers
      and documented in methodology (citing the memo's structural-attrition
      rationale).
- [ ] **ACCEPTANCE GATE**: pitcher `candidate_rank_concordance` IMPROVED over 0.4903
      and hitter `candidate_rank_concordance` did NOT degrade materially below 0.7791
      — measured after rebuilding the UPSTREAM backtests (adapter + dynasty + forward)
      THEN re-aggregating via `scripts/build_prospect_outcome_backtest.py` (a bare
      outcome-backtest rerun reports stale numbers).
- [ ] **CONSENSUS SURVIVAL**: Anderson (807739), Hernandez (815825), Sloan remain
      top-25 (checked via `context_only.source_ranks` INTERNALLY; no per-source rank
      published).
- [ ] **NO hand-tuning to exactly 7 top-25 pitchers.** Success is backtest metrics +
      consensus alignment; the governor clears when it clears. It is ACCEPTABLE for
      the banner to REMAIN UP after (a)+(b) (expected shape ~9 P top-25).
- [ ] **FIX (c)** either landed with a backtest-gate improvement, or was cut/reverted
      with a reported null result (the tree matches the post-(b) state).
- [ ] **COMPARABILITY EPOCH bumped**: `PROSPECT_BUYS_EPOCH` changed from
      `2026-06-22-role-normalization`; movers/buys/value-trend mask the fix-day
      discontinuity; no conflict with the ~7/13 buys-momentum masking fix.
- [ ] **AOTC INTEGRITY**: `prospects/ahead_of_consensus.py` and
      `scripts/build_ahead_of_consensus_scorecard.py` are zero-diff (the scoring
      LOGIC — divergence formula, guard thresholds, catch-up — is untouched). The
      scorecard funnel MAY move (AOTC is rank-coupled; expected), but only because the
      `valucast_rank` input moved on the re-scored arms — never because a
      guard/formula/threshold changed.
- [ ] The governor role-shape thresholds
      (`MAX_TOP25_PROSPECT_PITCHER_COUNT`/`MAX_TOP50_PROSPECT_PITCHER_RATE`) are
      UNTOUCHED.
- [ ] `plans/README.md` status row updated.

## STOP conditions

- **Over-correction — any of Anderson (807739), Hernandez (815825), Sloan falls out
  of the top-25.** The fix deleted pitchers instead of correcting the defect. STOP
  and re-tune (the concordance-gap down-weight is too aggressive, or the pedigree
  decay is hitting genuine-performance arms).
- **Hitter concordance degrades materially** (`roles[0].candidate_rank_concordance`
  drops meaningfully below 0.7791). A pitcher fix must not damage hitter ordering.
  STOP.
- **Pitcher concordance does NOT improve** after (a)+(b). The fix did not correct the
  defect it targets — do not ship a re-score that only moves the count without
  improving the measured ordering. STOP and reconsider the mechanism.
- **Anyone proposes hand-tuning to exactly 7 top-25 pitchers**, or relaxing the
  governor role-shape thresholds. The count is tie-noise (swung 7→11 across June with
  no methodology change); tuning to a target count is chasing jitter and would
  publish a board the field disagrees with. STOP.
- **The frozen AOTC scoring-logic files would change** (`ahead_of_consensus.py` /
  `build_ahead_of_consensus_scorecard.py`), OR the scorecard's guard thresholds /
  enrollment rule / catch-up formula would change. (Note: the funnel *numbers* moving
  is EXPECTED — AOTC is rank-coupled — so do NOT stop on movement itself; stop only if
  the scoring LOGIC changed.) STOP.
- **The comparability epoch is NOT bumped** but the model was re-scored. Shipping a
  deliberate re-baseline without the epoch bump reports the fix-day as fake player
  movement (the 7/7 jitter already caused a public incident). STOP until Step 6 is
  done.
- **The fix touches the fresh-draftee class** (2025/26 no-sample picks lose their
  legitimate pedigree pricing). The decay must be a no-op for fresh picks. STOP and
  narrow the decay.
- **Someone cites the "routing cliff Adams/Jenkins" finding as motivation.** It is a
  hitter-tail artifact, not part of this pitcher fix. Do not act on it here.
- **A per-source rank is about to be published** by a consensus-alignment check. The
  `source_ranks` reads are INTERNAL only. STOP.
- **The score-source branch, the fallback-only cap, the pitcher feature vector, or
  the model-score blend was refactored away** at HEAD. Re-locate and re-verify before
  editing; do not build on a stale line ref.

## Non-goals

- **No governor threshold changes.** Fix the model, not the cap.
- **No re-architecting the peak-projection layer to price downside.** The
  `negative_delta_count=0` limitation is noted, not solved here — a separate plan.
- **No hand-tuned target pitcher count.** The count falls out of the mechanism.
- **No per-source rank publication.** Aggregate median + board count only (ToS).
- **No touching the AOTC scoring logic.** The frozen files stay zero-diff; the funnel
  is allowed to move via the rank input (AOTC is rank-coupled), never via a scoring
  change.
- **No acting on the Adams/Jenkins routing-cliff finding** (hitter-tail artifact).

## Rollout order

1. **FIX (a)** — stale-pedigree decay/cap on the main path + the governor guardrail
   binding. Rebuild, confirm Hughes/Murphy drop and the fresh class is unmoved.
2. **FIX (b)** — pitcher concordance-gap down-weight (Step 2) + attrition base-rate
   discount (Step 3).
3. **Acceptance gate** (Step 4) — rerun the outcome backtest; confirm pitcher
   concordance up, hitter not down, the three consensus arms survive.
4. **FIX (c)** (only if (a)+(b) clean and budget) — retrain-and-measure decorrelation;
   keep only on a gate improvement, else revert.
5. **Epoch bump** (Step 6) — mask the re-baseline.
6. **AOTC integrity gate** (Step 7) — frozen files zero-diff, scorecard identical for
   past calls.
7. **Full suite + restore byproduct** (Step 8).

## Risks

- **Over-correction burying elite un-pitched arms.** The Anderson/Hernandez/Sloon
  tier has real consensus support; an aggressive pedigree/pitcher down-weight could
  bury them. Mitigation: the acceptance gate (concordance) + the explicit
  three-arm-survival check, both hard STOP conditions.
- **The count is noisy, so any fix looks unstable day-to-day.** The top band is
  tie-fragile (7↔11 swing with no methodology change); a fix landing at "8" one day
  may print "7" or "9" the next. Judge success on backtest metrics + consensus
  alignment, never a single day's count.
- **AOTC contamination.** The fix touches the rank artifact the frozen scorecard
  reads. Mitigation: frozen files zero-diff + the matured-call funnel identity check.
- **Re-baseline as fake movement.** Without the epoch bump the fix-day looks like
  every prospect moved. Mitigation: mandatory Step 6, composed with the ~7/13
  buys-momentum masking fix.
- **Fix (c) is a reconstructed hypothesis.** The double-count / max()-over-roles
  levers are code-reconstructed, per-player stake (~2-8 pts) estimated. Treat as
  hypothesis-to-validate: the retrain IS the validation, and a null result → revert.
- **Retrain jitter.** If fix (a) locus-1 or (c) retrains the model, the artifact
  churns beyond the intended change. Mitigation: prefer the no-retrain scoring-side
  locus for (a) where it fully binds; gate every retrain on the backtest.

## Maintenance notes

- **The defect is main-path pedigree dominance, not fallback pedigree.** The
  pre-existing `_pedigree_score_cap` only ever fired on the no-sample fallback
  (`PEDIGREE_SCORE_SOURCE`) branch; the bug rode inside `prospect_model_v0_6` scores
  where no cap and no years-since-draft decay applied to the pedigree features
  (`model.py:383-386`). If a future change reintroduces uncapped/undecayed pedigree
  on the main path, the Hughes/Murphy class returns — keep the fixture regression
  lock.
- **The governor guardrail must count the population it polices.** The pedigree
  checks were blind because they filtered on `score_source == PEDIGREE_SCORE_SOURCE`;
  the fix made a guardrail bind on main-path pedigree. Do not revert that population
  extension.
- **Pitchers are the model's weakest axis (0.49 concordance) on an out-of-validation
  cohort.** The concordance-gap down-weight + attrition discount are the honest
  response until the model earns better pitcher ordering. Revisit the down-weight
  magnitude only against a fresh backtest, never against a day's count.
- **The epoch is the re-baseline honesty lever.** Any future deliberate re-score must
  bump `PROSPECT_BUYS_EPOCH` too, or movers/buys report fake movement.
- **AOTC stays blind to the model score for past calls.** Future flagging shifts with
  the re-score (expected); matured calls are frozen. Never edit the frozen AOTC files
  to accommodate a model change.

## Amendments — 2026-07-12 (external audit, verified; supersede conflicting text above)

Four design defects found by the 7/12 Sol audit and independently verified against
the code. Where these conflict with anything above, the amendment wins.

1. **The concordance gate cannot validate the preferred scoring-side path (supersedes
   the acceptance gate as sole criterion).** `prospects/adapter_backtest.py` imports
   neither `rank_v1.py` nor `prospects/availability.py` — `candidate_rank_concordance`
   is computed on trained-model category projections and NEVER sees the scoring-side
   pedigree cap, the concordance-gap multiplier at the rank layer, or the attrition
   discount. The >0.4903 pitcher-concordance gate therefore validates ONLY
   model.py-retrain changes (fix a locus-1 / fix c). For the "lighter, surgical"
   scoring-side loci, the acceptance check is instead the rank-artifact assertion set:
   Hughes and Murphy leave the top 16, the three named consensus arms
   (Anderson 807739 / Hernandez 815825 / Sloan) survive the top 25, and the governor's
   pitcher-share checks pass. Do not present concordance as validating those loci.

2. **The epoch bump does NOT mask the fix-day re-score on buys/movers (corrects
   Step 6 and the "epoch is the honesty lever" maintenance note).** `PROSPECT_BUYS_EPOCH`
   is emitted as metadata and a forward-validation clock marker only; nothing in
   `momentum_score`/`clean_tail` consumes it. The actual masking is the
   `STEP_THRESHOLD = 6.0` step guard in `web/buy_score.py` — shared by BOTH buys and
   movers (there is no movers/buys asymmetry). Consequence: a fix-day score drop
   under 6 points stays inside the momentum window and prints as real cooling on
   both surfaces. The executor must either (i) verify the fix-day per-player deltas
   exceed 6.0 for every player the fix moves, or (ii) add explicit fix-day
   epoch-boundary handling to `clean_tail` keyed on the epoch date, or (iii) accept
   and disclose the sub-6-point contamination. Pick one in the diff; silence is not
   an option.

3. **The three AOTC acceptance clauses are mutually incompatible as written — this
   ONE rule replaces them.** The frozen AOTC *scoring logic* (divergence formula,
   guard thresholds, catch-up attribution) must be zero-diff. The funnel — INCLUDING
   matured-call membership — MAY move, because `_is_guarded` is rank-coupled
   (valucast_rank <= 300 AND divergence >= 25): a re-scored arm can legitimately fall
   out of the guarded set. Strike every "funnel stable for matured calls" /
   "scorecard identical for past calls" acceptance criterion; a reviewer must not
   STOP on rank-attributable funnel movement, and must not demand past-call identity
   the code cannot deliver. What IS a stop: any diff in the AOTC scoring files
   themselves.

4. **The pedigree "adequate sample" floor must be numeric and ramped, not a cliff.**
   "Adequate (clears a pitch/IP/PA floor)" is never assigned a number above. The
   executor must (i) pick explicit floors (IP for pitchers, PA for hitters, stated in
   the diff), and (ii) engage the cap on a RAMP across the floor (e.g. linear
   phase-in over the final 25% of the floor) rather than a hard step — a hard step
   hands a stale draftee full pedigree at 29.9 IP and a multi-point cliff at 30.0 IP,
   and later mid-season crossings are outside the one-time epoch mask (and, per
   amendment 2, unmasked on buys/movers below 6 points). Add a score-continuity
   sweep around every chosen boundary to the test plan.

## Epoch-batch additions — 2026-07-12 audit #2 (Sol model-core audit, all verified)

The following confirmed defects ride 028's SINGLE epoch bump. The epoch bump's
scope statement must name all of them — none may ship separately (each would
otherwise cost its own public re-baseline).

- **A. Availability thin-sample cliffs (audit F1, CRITICAL).** Two unreconciled
  mechanisms: availability.py's discrete IP/PA floors gate rank_v1.py's
  CONTINUOUS thin_current_sample_confidence penalty ON/OFF, producing verified
  score cliffs of +15.38 (upper starter at 45 IP), +15.60 (lower starter 30 IP),
  +11.49 (reliever 12 IP), +14.66 (upper hitter 150 PA), -14.17 (GS 2->3 at
  20 IP). Fix: taper the continuous penalty to zero as reliability rises instead
  of gating it on the discrete status flip (the discrete availability DISCOUNT
  steps of ~1-2 pts may stay). This is the same cliff class amendment 4 bans at
  the pedigree floor — fix both with the same ramp idiom.
- **B. Call-up renormalization split (audit F2).** rank_v1.py Pass-2 board
  renormalization excludes ALL active-roster ids, leaving retained rookie
  call-ups on the Pass-1 full-universe distribution while their board neighbors
  use the board distribution (~66 of 69 call-up scores shift <=0.68 pts /
  <=41 rank spots if unified). Fix: exclude only service-graduated ids at the
  Pass-2 predicate so every main-board row shares one distribution. NOTE: the
  plan's earlier "do NOT touch the role-quantile normalization" line refers to
  028's own surgery; this is an explicitly scoped ADDITION to the epoch bump.
- **C. Consensus identity joins (audit F3, CRITICAL).** HKB/Pipeline snapshot
  builders join on normalized name ONLY (PL/STS add role only) — the MIN
  catcher Luis Hernandez (801346) publicly carries consensus 36 built from the
  17-year-old SFG shortstop's HKB/PL/Pipeline ranks. Fix: key joins on
  (normalized_name + age/team tolerance) using the Team/Age/Level columns the
  source files already carry; unmatched-on-attribute rows go to the unmatched
  list, never silently collide. Verified blast radius: zero AOTC ledger calls
  affected (all collision identities rank far past the 300 enrollment ceiling),
  /gaps unaffected; one player card wrong today.
- **D. Category-impact label leakage (audit F4).** model.py _impact_target has
  no upper season clip (dynasty/adapter backtests correctly clip at cohort+4),
  so walk-forward folds train on post-fold outcomes and the shadow artifact's
  "4.15% OOS" gate-reason is in-sample. Fix: clip at cohort_year +
  OUTCOME_HORIZON_YEARS in the 3c retrain this plan already schedules. FOLLOW-UP
  (unverified lead from the verifier, NOT yet a finding): prospects/universal.py
  _future_seasons also uses an unbounded window — assess during execution.
  RESOLVED 2026-07-13 (Phase 0): confirmed a real training-label leak — the
  training feed (`build_shadow_model`) passes the raw, unclipped seasons dict all
  the way down to `_future_seasons`. Fixed by clipping the seasons feed upstream
  in `build_shadow_model` (new `_horizon_clipped_seasons`), NOT inside
  `_future_seasons`, which the mature-cohort evaluator legitimately reads in full.
  The served universal re-emit is code-only for now and MUST ride this plan's
  epoch bump (do not rebuild/push the served model without it).

## Acceptance-gate restatement — 2026-07-12 (audit F5, verified; supersedes the 0.4903 baseline)

The pre-registered pitcher baseline 0.4903 was computed on a TRUNCATED cohort:
adapter_backtest.py drops any established pitcher whose representative season
lacks QS (58 genuine successful-outcome seasons removed; 1,069 obs instead of
1,127). Verified corrected numbers (QS=0 imputation, replay reproduces the
committed artifact bit-for-bit before the correction): pitcher concordance
baseline 0.4903 -> 0.4692 on n=1127; improvement over baseline 4.61% -> 3.61%;
hitter numbers unchanged (0.7791, n=1091). Therefore, executor order:

1. FIRST fix the QS exclusion (impute QS=0 for pre-QS-era/missing seasons, or
   score the pitcher concordance on the QS-free category subset — state which
   in the diff) and re-emit the backtest artifact.
2. THEN the acceptance gate becomes: pitcher candidate_rank_concordance
   IMPROVED over the corrected baseline (expected ~0.4692) on the corrected
   n=1127 cohort. The 0.4903 figure is dead — improving over it on the
   truncated cohort proves nothing.
3. The rank-artifact assertions from amendment 1 (Hughes/Murphy out of top 16,
   three consensus arms in top 25, governor pitcher-share green) are unchanged.

## Memo correction — 2026-07-12 (audit F7, verified)

The pitcher-lean memo's claim that "the peak layer cannot mark anyone down"
(and this plan's line repeating it) is literally false: five committed
projections carry negative deltas (min -4.66 — Yoniel Curet). The zero came
from peak_calibration.py's negative_delta_count counting only deltas <= -10.
Correct reading: the peak layer's downside signal EXISTS but is small; the
counter is mislabeled. Fix in this batch: count all negative deltas (keep a
separate big_negative_delta_count if the >=10 cut is wanted) and rename
honestly. The memo's conclusion (pitcher downside adjustment is effectively
absent at material magnitudes) still stands.
