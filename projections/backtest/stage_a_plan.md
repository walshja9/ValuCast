# Stage A specification: unsealed artifact checks on the prospect model

Checkout read: D:/CodexWorktrees/valucast-model-audit-20261103 (origin/master 606ca393). Static reading only. Source files read: prospects/model.py, impact_oof.py, raw_input_builder.py, input_contract.py, gate.py, stage1_outcome_proof.py (signatures only), scripts/run_stage1_maturation_rerun.py (seed constants only), tests/test_impact_oof.py (fixture names only). No data/, docs/ or plans/ content was opened, and no metric values appear here.

Status of this document: this is the specification. It is the pre-registered interpretation table (section 9). Its SHA-256 goes into the freeze manifest (section 8), so it must not change after the freeze.

## 0. What Stage A is and is not

- Allowed claim: "a named artifact is, or is not, large enough to explain the observed walk-forward result on already-spent cohorts."
- Not allowed: any statement that the model has predictive skill, that the published rank (prospects/rank_v1.py composite) is validated, or that the model "passes". Stage A does not test rank_v1.py at all. model.py feeds rank_v1 with weight 0.76 (build_shadow_model, release_contract), so a clean Stage A says nothing about the composite.
- Sealed set: cohort 2022 (rows and the MLB seasons of its players). Cohorts 2020 and 2021 rows are also never loaded: MATURE_THROUGH = 2019 already excludes them from every training and gate path (_historical_rows model.py:625, _historical_impact_rows :662), so loading them buys nothing.

## 1. Inputs and the 2022 exclusion (enforced at load, before any computation)

### 1.1 Exactly one real input file

`prospects.input_contract.VALUCAST_INPUT_PATH` = ROOT/data/prospects/prospect_model_inputs.json (input_contract.py:9). It carries everything Stage A needs:
- `historical.rows` (dataset rows, with `cohort_year`, `mlbam_id`, `role`, `outcome`, features, draft fields)
- `historical_mlb_seasons` (dict `"<mlbam_id>_<role>"` -> list of season dicts; fields limited to `_MLB_SEASON_FIELDS`, raw_input_builder.py:163-177)
- `current.hitters/pitchers`
- `mlb_service` (precomputed totals; Stage A recomputes these instead, see 7.5)

Nothing else is read. Not data/models/*, not data/validation/*, not archives, not any registry or docs file.

Optional, only for the dedup rule probe in Stage 7: data/prospects/raw/mlb_prospect_seasons_cache.json (raw_input_builder.py:28). It is read through the same loader and the same exclusion, and used only to ask "does a team-like key exist on non-sealed rows" (key-set only, no values copied). If that file is skipped, the dedup rule is the max-sample rule (7.2).

### 1.2 Loader: `load_sealed_safe_contract(path) -> SafeContract`

New function in the new research module (section 3). Order of operations, all inside the one function, nothing returned until it finishes:

1. `payload = json.loads(path.read_bytes())`. Record `input_sha256 = sha256(bytes)` (bytes only, no content). Parsing necessarily materialises the 2022 rows in memory. That cannot be avoided with a plain JSON file, and the plan does not pretend otherwise. They are dropped before any other code can see them.
2. Reject the contract if `prospects.input_contract.validate_factual_contract(payload)` returns problems (input_contract.py:61).
3. `sealed_ids = {int(r["mlbam_id"]) for r in rows if int(r["cohort_year"]) == 2022 and r.get("mlbam_id")}` over ALL roles. Use a module constant `SEALED_COHORT = 2022`.
4. Build the safe copy:
   - `rows` = rows with `cohort_year <= MATURE_THROUGH` (read the constant, never write it) AND `mlbam_id not in sealed_ids`. A player who appears in both an old cohort row and a 2022 row is removed entirely (rows and seasons). Do NOT keep the old row with its seasons stripped: `_impact_target` (model.py:576) would then label that player 0.0, which is a wrong label, not a missing one.
   - `historical_mlb_seasons` = entries whose id is not in `sealed_ids`. Seasons are not filtered by calendar year: the 2022 season of a 2016-cohort player is legitimate.
   - `historical.cohorts` and `omitted_cohorts` metadata: discarded (they can carry per-cohort counts).
   - `current`: kept (it is the live board, not an outcome). Current-board rows whose id is in `sealed_ids` are removed for the board stages only (see 7.5).
   - `mlb_service`: discarded and recomputed (7.5).
5. Return `SafeContract` with the filtered pieces, `sealed_ids_sha256 = sha256(sorted ids)` and four integers (n sealed rows seen, n sealed ids, n dual-cohort players removed, n current-board ids excluded). The integers go only in the results file. The id set itself never leaves the process and is never written.
6. The raw `payload` reference is deleted (`del payload`) and the function returns.

Known residual: a 2022-cohort player who is absent from the dataset rows cannot be identified. If the dataset builder omitted such a player, nothing in this code can block their seasons. The owner should treat "sealed set = players with a cohort-2022 row in the contract" as the working definition.

### 1.3 The guard (runtime abort)

`assert_no_sealed(rows, seasons_by_player, sealed_ids)` raises `SealedDataError` if any of: a row has `cohort_year >= 2020`; any row `mlbam_id` is in `sealed_ids`; any seasons key's id is in `sealed_ids`. It is called:
- on entry to every stage function (a decorator `@sealed_guarded` on the stage entry points), and
- once more over the objects held for serialisation (results contain no player ids at all, so the output check is "no key or value contains an id from `sealed_ids`" as a string-scan of the serialised bytes).

`SealedDataError` is never caught by the stage code. The runner turns it into the status line `STAGE_A status=abort_sealed` with no other output, and writes no results file.

### 1.4 Can the exclusion be tested on synthetic rows? Yes.

Section 10, tests T1-T6. The loader and guard are pure dict/list functions, so the test builds a synthetic contract with sentinel ids (e.g. 9_000_001+, outside any real range) in 2022 rows and in their seasons, runs the loader, and asserts the sentinels are absent from every returned structure, from the stage outputs and from the serialised results bytes.

## 2. Existing functions to reuse (no new parameters needed, no served edits)

Signatures as read:

| Function | Signature | Used for |
|---|---|---|
| prospects/model.py `_historical_rows` :625 | `(rows, role, mature_through=MATURE_THROUGH)` | outcome-axis rows |
| `_historical_impact_rows` :662 | `(rows, role, seasons_by_player, references, mature_through=MATURE_THROUGH)` | impact-axis rows and labels |
| `_impact_references` :528 | `(seasons_by_player)` | reference tables; pass pre-filtered dicts to change the reference universe |
| `_active_impact_categories` :553 | `(references, role)` | category coverage |
| `_walk_forward` :877 | `(role_rows, model_kind="ridge", ridge_lambda=RIDGE_LAMBDA, neighbor_feature_key="features")` | observed gate replay; equivalence oracle for the fast engine |
| `train_role` :994 | `(role, dataset_rows, now=None)` | outcome gate, outcome model for board |
| `train_impact_role` :1047 | `(role, dataset_rows, seasons_by_player, references, now=None, *, fold_local_evidence=False, mature_through=None)` | impact gate, both reference regimes |
| `score_current` :1470 | `(contract, role_models, impact_models)` | board scores and ranks |
| `_fit_prediction_model` :759, `_predict_model` :783, `_fit_prior` :808, `_prior_predict` :823, `_fit_neighbors` :828, `_neighbor_predict` :848, `_rank_concordance` :861 | as named | equivalence checks |
| `_outcome_feature_names` :484, `_outcome_feature_vector` :385, `_regress_current_features` :1360 | as named | column ablation indices, raw-vs-regressed scoring |
| prospects/impact_oof.py `fold_local_impact_oof` :115 | `(dataset_rows, seasons_by_player, role, mature_through=MATURE_THROUGH)` | training-only references (item 4); reuse as is |
| impact_oof `_fold_reference_contract` :67, `cohort_player_bootstrap` :220, `_canonical_sha256` :44 | `(templates, role, seasons_by_player, test_year)`; `(rows,*,baseline_error_key,seed,resamples)`; `(payload)` | reference counts and hashes; paired bootstrap; hashing |
| prospects/gate.py `decide_gate` :34 | keyword-only `(metric, model_score, baselines, sample_size, cv_method, validated_through, min_sample, min_improvement_pct, lower_is_better, now)` | gate status under null and observed; use the same constants MIN_GATE_SAMPLE (250; x2 pooled), MIN_GATE_IMPROVEMENT_PCT (2.0) |
| prospects/stage1_outcome_proof.py `_metric` :49, `auc` :39 | `(name, predictions, targets)` | Spearman / Kendall / AUC ordering deltas |
| prospects/raw_input_builder.py `_service_totals` :811, constants ROOKIE_AB_LIMIT=131, ROOKIE_IP_LIMIT=51 | `(mlb_seasons, mlbam_id, role)` | service recomputation |

What does NOT exist and how it is obtained without editing served code:

1. Label permutation, column ablation and a per-fold training filter (purge). `_walk_forward` has none of them. Obtain them in a research-only fast engine (3.2) that is verified equal to `_walk_forward` on the observed (unpermuted, unpurged, unablated) inputs. Alternative for ablation only: pass rows whose `features` lists have the column deleted; `_walk_forward` then works as is (slow path, used as a cross-check).
2. A switch for "train references only" in `train_impact_role`: not needed. `fold_local_evidence=True` already exists (:1054) and the full-store path is the default. The reference universe is changed by passing different `seasons_by_player` into `_impact_references`.
3. A switch to turn off serve-only steps in `score_current`. Not needed. The stale-current and pedigree-shrink corrections write their raw and corrected values into the row (`stale_current_correction`, `pedigree_shrink_correction`, `pooled_shadow`), and the raw regression-free score is rebuilt in the research module from `_outcome_feature_vector` + `_predict_model`. Do not toggle module flags (POOLED_SHADOW_ENABLED etc.) in-process.
4. Deduplication. Done on the `seasons_by_player` dict before it is passed in. `_impact_references`, `_impact_target` and `_service_totals` all take the dict, so no served change.

Nothing in Stage A requires editing prospects/model.py or any served module.

## 3. New code (research only)

- `projections/backtest/prospect_stage_a.py`: loader, guard, fast engine, null generators, stage functions, canonical writer.
- `scripts/run_prospect_stage_a.py`: CLI runner, status line, hashing, environment guards.
- `tests/test_prospect_stage_a.py`: synthetic tests only (section 10).
- `projections/backtest/stage_a_freeze.json`: freeze manifest (section 8).

None are imported by app.py or any served path. `prospects/impact_oof.py` is the existing precedent (research-only, "serving_import": None).

### 3.1 Row preparation

Per (role, axis) build the observed rows with the served builders:
- outcome axis: `_historical_rows(safe_rows, role, 2019)`; folds use `neighbor_feature_key="baseline_features"` and `RIDGE_LAMBDA` (train_role :994-1002).
- impact axis: `refs = _impact_references(safe_seasons)` then `_historical_impact_rows(safe_rows, role, safe_seasons, refs, 2019)`; folds use lambda = `HITTER_IMPACT_RIDGE_LAMBDA` (3.0) for hitters and `RIDGE_LAMBDA` (10.0) for pitchers, and `neighbor_feature_key="features"` for the 25-NN baseline plus `baseline_features` for the canonical 25-NN baseline (train_impact_role :1060-1104).
Four families: outcome-hitter, outcome-pitcher, impact-hitter, impact-pitcher. All stages report all four.

### 3.2 Fast engine

Pure numpy re-implementation of the walk-forward (folds are `cohorts[2:]`, i.e. test cohorts 2016-2019 if all six cohorts are present; train = all earlier cohorts):
- ridge: standardise with per-column mean and population std (`or 1.0` for zero std), add intercept, penalise all but the intercept, predict clipped to [0, 1] (model.py:724-756).
- hurdle: arrival fit on `target > 0`; conditional fit on the subset with `target > 0`, standardised on the subset; prediction = product (model.py:765-788). Under permutation the conditional subset changes every draw, so the engine re-standardises and re-solves it each draw. This is a w x w solve per fold (w about 40), a few ms.
- prior: `_fit_prior` cell means with PRIOR_K = 40 over `level|age-bucket` cells, vectorised by cell index.
- 25-NN: neighbor sets depend on features only, not labels. Compute them once per fold with the same expression as model.py:853-855, in pure Python with the builtin `sum` and `sorted((dist, index))`, not a numpy re-implementation. Builtin `sum` on floats is compensated from Python 3.12 and plain left-to-right before that, so only the builtin matches the served code on every interpreter. The cost is one served-speed kNN pass per fold, cached for all draws. Under permutation the prediction is the mean of permuted train targets at the cached indices. The results file records the Python version. Production builds run on 3.11, so tied neighbor sets on another interpreter can differ slightly from production; the equivalence gate compares engine to served on the same interpreter.
- Gate MAE and the pooled `decide_gate` call use the served `decide_gate` unchanged.

Equivalence test (also the first real-data gate, stage 0): on the unpermuted observed rows the engine must match `_walk_forward` on every prediction vector to absolute tolerance 1e-8, and match the gate `improvement_pct`. If not, the run aborts before any null. Run served `_walk_forward` once per family; expect minutes per family because the served kNN is pure Python.

## 4. Seeds, counts, bootstrap

- Master seed `SEED = 20261103`. Avoid 20261001, 36061 and 37083 as instructed. Do not use any value from the forbidden list in scripts/run_stage1_maturation_rerun.py; 20261103 is not in it, and the freeze test (T14) asserts `SEED not in FORBIDDEN_SEEDS | {20261001, 36061, 37083, RULE4_RESERVED_SEED}` by importing that script's constants read-only. 72127 (impact_oof default) is also forbidden.
- Per-draw independence and resumability: `np.random.SeedSequence([SEED, stage_id, family_id, config_id]).spawn(B)`, so draw i is a pure function of (SEED, stage, family, config, i). Chunking, restarting or capping cannot change any draw.
- Permutation count: B = 5000 for the label-permutation nulls (stage 1, 2), B = 2000 for the best-of-k null (stage 3, 8 configurations each draw). Minimum acceptable is 2000. p-values use `(1 + count(null >= obs)) / (B + 1)`; with B = 2000 the smallest reportable p is about 0.0005.
- Observed-effect bootstrap (descriptive intervals only, never used for the nulls): reuse `cohort_player_bootstrap` (equal weight cohorts, then players within cohort; impact_oof.py:220) with resamples 5000, seed = `SeedSequence([SEED, 99, family_id]).generate_state(1)[0]`.
- Ordering deltas: pooled Spearman (primary) and AUC for `target > 0`, via `stage1_outcome_proof._metric`, as model minus level_age_prior and model minus 25-NN, pooled over the test folds; per-fold values reported too. Kendall tau-b only on the observed rows, not inside the null loop.

## 5. Runtime estimate and staging

Estimates are for one laptop core, assuming the numpy engine; the served pure-Python paths dominate stages 0, 5, 7.

| Stage | Content | Rough time |
|---|---|---|
| 0 | load, guard, hash inputs, engine-vs-served equivalence, observed replay | 5-15 min |
| 1 | N1 within-cohort permutation, 5000 draws x 4 families | 10-30 min |
| 2 | N2 cell-stratified permutation (within cohort x level|age-bucket), 5000 draws x 4 families | 10-30 min |
| 3 | best-of-k selection null, 2000 draws x 8 configs x 4 families | 30-90 min |
| 4 | purge variants | < 5 min |
| 5 | impact references | 15-40 min |
| 6 | serve-path skew | 5-15 min |
| 7 | duplicate-season measurement (two full pipeline passes plus board) | 30-60 min |

Total about 2-5 hours. Control: `--stage N` (single stage), `--reps B` (cap draws, result marked `partial` and excluded from the interpretation table), `--budget-minutes M` (stop at the next draw boundary, checkpoint, mark partial), checkpoint every 250 draws to the results directory, resume by skipping completed draw indices. A partial stage is never interpreted. Run order: 0, 4, 6, 1, 2, 5, 3, 7 (cheap descriptive stages first).

## 6. Stage definitions

All stages: families = outcome-hitter, outcome-pitcher, impact-hitter, impact-pitcher. Test folds are the cohorts the served walk-forward uses.

### Stage 1 (question 1): label permutation null, N1

Permute `target` among rows of the same cohort, within a role and axis. Features, folds, baselines' neighbor sets unchanged. Per draw recompute: pooled model MAE, prior MAE, 25-NN MAE (and canonical 25-NN for impact), `improvement_pct` against the best baseline (same rule as `decide_gate`), gate status via `decide_gate`, pooled Spearman delta vs each baseline, AUC delta. Report: observed value, null mean/sd/quantiles, one-sided p, null false-"active" rate (share of draws where `decide_gate` returns active).

### Stage 2 (question 1, sharper): cell-stratified null, N2

Same as N1 but permute within cohort x (level, age-bucket) cells (`model._age_bucket`). This keeps whatever the level-age prior legitimately knows, so the null tests the model's increment over the prior and over the neighbors, not the structure both share. N1 alone is too easy a null: any model that learns level or age beats a world where labels ignore level and age. N2 is the informative one for "is the margin more than fitting noise".

### Stage 3 (question 2): best-of-k selection null

Configurations (same folds, same permutation applied to all configurations within a draw):
- Feature set F: with vs without the promoted pedigree column(s). Hitter: drop `inverse_draft_pick` and `draft_record_known` (model.py:149-150, comment :136-148 says the lift comes from inverse_draft_pick; draft_record_known is inert). Pitcher: with vs without the PITCHER_PEDIGREE_FEATURES block (model.py:255). Indices from `_outcome_feature_names(role)`. The 25-NN and canonical baselines keep their original vectors across configurations, so baselines do not move.
- Architecture A: `hurdle_ridge` vs `ridge` (comment at model.py:1839 says the v0.6 hitter hurdle was selected retrospectively).
- Ridge lambda L: 3.0 vs 10.0 (HITTER_IMPACT_RIDGE_LAMBDA vs RIDGE_LAMBDA).
k = 2 x 2 x 2 = 8 configurations per family. The realised choice is (promoted features, hurdle, lambda 3.0 for hitter impact / 10.0 otherwise).

Per draw: margin_c = `improvement_pct` of configuration c; record max_c margin_c. Also record the max over k = 2 (architecture only), 4 (architecture x lambda), 8. Report: observed margin of the realised configuration, observed best-of-8 margin, null distribution of the max at k = 2, 4, 8, p = share of null maxima at least as large as the observed realised margin.
Stated lower bound: k = 8 counts only the three choices visible in code and comments. The repo also contains challenger modules (model_v07.py, prospect_v09.py, prospect_v2_candidate.py, level_translation_challenger.py and others) which suggest more variants were tried; the true selection pool is unknown without the registry, which this plan does not open. So the test at k = 8 is a lower bound on selection, never a complete correction. The owner or the registry holder should supply the true k if known; the runner takes `--k-extra N` which multiplies the null by drawing the max of N additional pure-noise configurations (each an independent permutation of the labels drawn for the same fold structure, scored with the realised configuration) as a sensitivity row. Pre-declare N in {0, 8, 24}.

### Stage 4 (question 3): purge variants (descriptive)

Label windows run `cohort + 1 .. cohort + OUTCOME_HORIZON_YEARS` (model.py:45, :595). For test cohort T, training cohort c has a label that used seasons after T when `c + 4 > T`.
- P-drop: per fold keep only training cohorts with `c + 4 <= T`. With cohorts 2014-2019 this leaves no training cohort for T = 2016 and 2017, one (2014) for 2018, two (2014, 2015) for 2019. Report which folds exist, their n, MAE and ordering deltas versus the same folds unpurged. `decide_gate` min_sample will usually return `insufficient_sample`; report the raw margins and say so.
- P-clip (impact axis only, labels recomputable): for each fold recompute training labels from seasons in `(c, min(c + 4, T)]` by passing a clipped `seasons_by_player` to `_historical_impact_rows`, same references regime as the served full-store path and also the training-only path. This keeps all training rows but removes future-of-origin seasons from their labels. The outcome-axis (bust/role/star) label comes precomputed in the dataset rows and cannot be recomputed here.
Before running, verify from the dataset builder source (search scripts/ and prospects/ for the outcome horizon, not data/) that the outcome label window is also cohort + 4; if it is not, record the actual window in the freeze manifest and use it.
Purge is descriptive only: no pass/fail.

### Stage 5 (question 4): impact references

Variants for the impact axis (both roles), all through served functions:
- R0 full-store: `_impact_references(safe_seasons)` + `train_impact_role(..., fold_local_evidence=False)` (the served gate path; build_shadow_model :1766-1783). Safe means ex-sealed ids only; later cohorts' seasons (2020, 2021 players, and seasons after each cohort's window) remain, as in the live store.
- R1 window-only all players: `_impact_references` on seasons clipped to each player's own `(cohort, cohort+4]` window, still including test-cohort players. Isolates "later seasons" from "test-cohort leakage".
- R2 training-only (fold-local): `impact_oof.fold_local_impact_oof` as is (it already restricts references to training-fold players and window seasons, :67-112 and :131-145). The validity of reuse: it takes `dataset_rows`, `seasons_by_player`, `role`, `mature_through`, and needs no change. Its output rows carry per-player errors; its `reference_sha256`, counts and category coverage go to the report.
For each: reference sizes per category, shift of category percentile cutpoints (largest absolute rank displacement at deciles), share of training labels that move, gate `improvement_pct` and status, paired cohort-then-player bootstrap of (R0 error - R2 error) using `cohort_player_bootstrap`. Note `_active_impact_categories` (:553) can switch categories on or off between variants (80% coverage rule); record any change.
What is already done: impact_oof does R2. Not done there: R1, and the pitcher-side comparison against R0 on identical rows.

### Stage 6 (question 5): serve-path skew

Compute on the live board produced by `score_current` using models trained on safe rows only (train_role / train_impact_role with a fixed `now` string so nothing is time dependent):
- Support counts, by role: live rows in levels A and A+ (training rows come from `LEVEL_CODE` levels present in the training set, so count live levels absent from the training rows), live rows with no draft record or no `draft_pick_number` (international / undrafted; compare the training share), live rows with sample below the minimum training sample, and rows with any feature outside the training min-max range (count of rows, count of features, top five feature names by count; names only, no player data).
- Serve-only steps (what training never does): sample-reliability regression of the whole feature vector (`_regress_current_features` :1360; training rows are never shrunk), line selection by largest sample (`_select_current_records` :1196), stale-current correction (:1566-1609), pedigree-shrink correction, pitchers only (:1635-1667), pooled shadow (observe only; not applied to the served score). For each: number of rows touched and the distribution (mean, quartiles, max) of the signed score change, taken from the recorded correction fields; for regression, rebuild the unshrunk score via `_outcome_feature_vector` + `_predict_model` on `role_model["prediction_model"]` and compare.
- Effect on rank: how many rows change rank by more than 10 positions if each step is turned off (research-side recomputation, not a flag).
Counts and summaries only; no player ids or names.

### Stage 7 (question 6): repeated MLB seasons

#### 7.1 What the code says
- `_statsapi_service_seasons` (raw_input_builder.py:496-553) appends every `splits` entry with sport id 1, so a traded player gets one row per team plus a combined row. Stored fields are only `year` plus counting and rate stats; no team key is stored. The contract copy is further reduced by `_only(row, _MLB_SEASON_FIELDS[role])` (:954), so even if the raw cache held a team key the contract would not.
- Consumers that treat every row as a season: `_impact_references` (model.py:540-546, every row meeting the sample minimum), `_impact_target` (:589-621, takes the maximum across rows, so a small team-stint line with an extreme rate can set the label), `_service_totals` (raw_input_builder.py:811-821, sums every row, so graduation, `ab >= 131` / `ip >= 51`, can be reached early and a candidate dropped at `score_current` :1508).
- The writer of the historical cache is not in raw_input_builder.py; the implementing agent should locate it with a grep restricted to scripts/ and prospects/ (not data/) and record whether it also appends per-team rows.

#### 7.2 Dedup rules (applied to `seasons_by_player` copies, never to served code)
Group rows by (player key, year). Groups of size 1 are untouched.
- D1 (primary): keep the single row with the largest sample (`pa` for hitters, `ip` for pitchers). A combined row's sample is at least any team row's, so D1 keeps the combined row when one exists. Ties: keep the first in list order.
- D2 (sensitivity): dedupe only groups where the largest-sample row is verified to be a combined row, meaning its `pa`/`ip` equals the sum of the others within 0.01 (0.34 for innings stored as thirds) and at least one of `hr`/`r`/`rbi`/`sb`/`so` also matches the sum. Others are left as is.
- Classification counts: groups by type (verified combined, no combined row, identical duplicate, other). If "no combined row" groups exist, D1 keeps one team row and understates that season; this cannot be fixed because averaging rates would need hit and walk counts that the stored fields do not have (avg and ops without ab/h, era/whip without er). Report the count.
- If the optional raw-cache probe finds a team-like key on non-sealed rows, add D3: keep the row with no team (combined row) when present, otherwise D1.

#### 7.3 Measurements (A0 = as stored, safe ids only; A1 = D1; A2 = D2)
- Prevalence: share of players with a repeated season, per role, per cohort (aggregate counts).
- Labels: per cohort and role, share of training rows whose impact label changes, mean and max absolute change, direction (up or down), restricted to the full-store regime and to the training-only regime.
- References: counts per category before and after, and the decile cutpoints shift.
- Gate results: `train_impact_role` and (outcome axis unchanged by construction, report as such) gate status and `improvement_pct` under A0, A1, A2, for both reference regimes (R0 and R2), per role and pooled (`impact_board_gate` equivalent, min_sample doubled as in :1819).
- Service facts: recompute `_service_totals` for current candidates under A0 and A1 and count `graduated` flips.
- Current board (7.5): scores, ranks, top-25 / top-50 / top-100 overlap, rank-order Spearman between A0 and A1, maximum rank move, count of rows that enter or leave the board.

#### 7.4 No fix is applied or proposed in the output; the report states measurements only.

#### 7.5 Can the current-board comparison run without touching a 2022 outcome? Yes, with a cost.
Board scoring reads training rows (cohorts <= 2019), full-store reference seasons and the candidate's own MiLB line plus MLB service totals. The only 2022 risk is a current-board player who is also a cohort-2022 player: their MLB seasons would enter the reference store and their service sum. Procedure: remove those ids from `current`, from the reference store (already done by the loader) and from the service recomputation. The board compared is the live board minus those players. A0 vs A1 on that board is internally consistent, but absolute ranks differ from the published board by the removed players, and no statement about those players can be made. State their count (aggregate) in the results. The comparison also uses recomputed `mlb_service` from the contract's own seasons; assert that for non-removed candidates the recomputed A0 totals equal the stored `mlb_service` fields, otherwise stop (contract inconsistent).

## 7. Where it runs and keeping output out of public logs

- Runs on the owner's Windows machine, from a clean checkout at the frozen commit, never in GitHub Actions. The runner refuses to start if `GITHUB_ACTIONS`, `CI` or `RUNNER_OS` is set, if `git status --porcelain` is non-empty, or if `git diff --name-only <manifest code commit> HEAD` lists anything other than the manifest file.
- Command shape: `PYTHONPATH="src;." python scripts/run_prospect_stage_a.py --out "D:/UserData/Alex/Documents/Codex/2026-11-03/valucast-model-audit/stage-a-results" --stage all`.
- The real-data mode additionally requires `VALUCAST_STAGE_A_REAL=1`; without it the runner only does `--synthetic`.
- Output directory is resolved and must not be under the repo root; created if absent.
- stdout/stderr: exactly one line at the end, `STAGE_A status=<ok|partial|abort_sealed|abort_hash|abort_equiv|error> results_sha256=<64 hex>`. No other print. Exceptions are caught in `main()` and reported only by class name mapped to a status code, never the message (messages can contain values). `warnings.simplefilter("ignore")`, no tqdm, no logging handlers. Pytest is never run against real data.
- Result files: `stage-0.json` ... `stage-7.json`, plus `results.json` (canonical JSON: sorted keys, `separators=(",", ":")`, UTF-8, `\n` line endings, written by Python only; the repo's PS5.1 UTF-8 corruption warning applies, never rewrite them with Get/Set-Content). `results_sha256` = SHA-256 of `results.json` bytes, which embeds each stage file's SHA-256. All results are aggregates; no names, no ids.
- Nothing in the repo is written. The freeze manifest is written before the run (section 8), not by the run.
- Nothing unworkable found. Caveats the owner should know: (a) the 2022 rows are parsed in memory before being dropped; (b) the sealed set is defined by the dataset rows only (1.2); (c) numpy/scipy versions must be recorded in the results file because summation order can change the last digits; (d) long runs on a laptop should keep it plugged in and not sleeping; resume is supported.

## 8. Freeze procedure

Before the first real-data run, commit one manifest, `projections/backtest/stage_a_freeze.json`, containing (hashes and constants only, no data-derived values):
1. Commit id of the checkout the code was frozen on. The manifest is committed on top of that commit, so HEAD is one commit later and differs only by the manifest file.
2. SHA-256 of: `projections/backtest/prospect_stage_a.py`, `scripts/run_prospect_stage_a.py`, `tests/test_prospect_stage_a.py`, this plan file (stage-a-plan.md), and the served files read: prospects/model.py, impact_oof.py, gate.py, input_contract.py, raw_input_builder.py, stage1_outcome_proof.py.
3. SEED, B for each stage, configuration grid for stage 3 (named list), dedup rule definitions, purge rule, pre-declared thresholds from section 9, `SEALED_COHORT`, `MATURE_THROUGH` value read from the module (the manifest records it; the manifest check fails if it is not 2019).
4. SHA-256 of the real input bytes (computed with `--hash-inputs`, which reads bytes only and prints one line). This pins which data the run is allowed to read.
5. Python, numpy, scipy versions.
The runner verifies every item at start (`abort_hash` on mismatch). The manifest cannot contain its own hash; the owner writes the manifest commit id on the results cover note.

Synthetic proof, required before the first real run:
- `--synthetic` builds a planted-signal contract and a no-signal contract in a temp directory, runs stages 0-7 end to end with small B, and checks: engine equals `_walk_forward` (T7); the planted signal is found at the extreme tail of N1, N2 and best-of-k; the no-signal contract's p-values are not extreme in a calibration loop (200 independent synthetic datasets, share of p <= 0.05 within a binomial band around 0.05); sealed sentinels never appear anywhere (T1-T6); the status line format holds (T15).
- All synthetic runs write to a temp path, not to the stage-a-results directory.

## 9. Interpretations fixed before any data is read

Thresholds below are conventions chosen now; they are not derived from data. "Observed" means the model as served (realised configuration).

### Stage 1 and 2 (permutation nulls)
- Observed p <= 0.01 for a family: the observed margin (or ordering delta) is not a product of the walk-forward machinery fitting label noise under this fold structure. This rules out: a pure noise/overfit artifact, a bug that makes the model beat baselines on any labels, and tie or clipping behaviour manufacturing a margin. It does NOT rule out: leakage that carries real label information (full-store references, label windows crossing the fold origin, duplicate seasons), selection across configurations, nonstationarity, or skill on an unseen cohort. It is not evidence of skill.
- 0.01 < p <= 0.05: ambiguous; no statement.
- p > 0.05 for a family where the live gate is active: reason for concern. The served margin is within what the pipeline produces on label noise.
- Null false-active rate (share of draws where `decide_gate` returns active) greater than 5% under N2 for a family: reason for concern about the gate rule's discrimination for that family, whatever the observed value.
- Median null `improvement_pct` under N2 above half of the 2.0% threshold: reason for concern (the gate threshold sits near the noise level).
- Order of reliability: N2 over N1. If N1 is extreme and N2 is not, the margin is explained by what the level-age prior already knows, which is a statement about the baselines being weak, not about the model.

### Stage 3 (best-of-k)
- Observed realised margin vs null max at k = 8: share of null maxima >= observed <= 0.01: the hitter margin is not explained by choosing the best of those 8 configurations on these folds (lower bound on selection, see 3). 0.01 to 0.05: ambiguous. Above 0.05: reason for concern, the margin is within what best-of-8 selection yields on noise. The k = 2 and k = 4 rows and the `--k-extra` rows are reported as sensitivity, interpreted the same way.
- It does NOT rule out selection across choices not in this grid, and does not establish skill.

### Stage 4 (purge)
- Descriptive. Reason for concern: in the folds that survive purging, the sign of the margin against the best baseline differs from the unpurged result, or the margin falls by 50% or more. Because only 1-2 folds survive and training is 1-2 cohorts, a non-concern result is "no contradiction seen", not confirmation. A fold with `insufficient_sample` is reported as such. P-clip: same flags.

### Stage 5 (references)
- Concern if, under training-only references (R2), the gate status changes from active to anything else, or the margin falls by 50% or more versus R0, or the paired bootstrap of (R0 error - R2 error) excludes zero in the direction of R0 being better. Not a concern if R2 margin is within the bootstrap interval of R0 and the status is unchanged. This tests whether later or test-cohort seasons in the reference tables helped the served margin; it does not test skill.
- A category flipping in or out of `_active_impact_categories` between variants is reported as a structural difference.

### Stage 6 (serve-path skew)
- Concern if more than 10% of live board rows in the top 100 of either role are outside training support (level absent from training, no draft record where training rows were all drafted, or feature outside training range on 3 or more features), or if any serve-only step changes more than 10% of rows by more than 0.02 in score or moves more than 10% of rows by more than 10 rank positions. Otherwise no concern flagged. The gate was validated on training-like rows, so a large out-of-support share means the gate says little about those live rows. It does not mean the live scores are wrong.

### Stage 7 (repeated seasons)
- Concern if any of: impact gate status changes for either role under A1 vs A0 (either reference regime); more than 5% of training impact labels change; any `graduated` flip among current candidates; board top-50 overlap A0 vs A1 below 45 of 50, or rank-order Spearman below 0.99. Below those, the duplication is measured and judged small. In every case the output is measurement for the owner; no fix is authorized and none is recommended in the results.

### Global
- Stage A cannot show predictive skill, cannot validate rank_v1, and cannot speak to cohorts 2021+ or any sealed data. A "no concern" overall result means only that the checked artifacts are not enough to explain the observed margins on spent cohorts. A "concern" result means the specific named artifact could produce a margin of this size.

## 10. Synthetic test list (tests/test_prospect_stage_a.py, no real data)

Loader and guard
- T1 Loader drops all `cohort_year == 2022` rows and all seasons of ids in those rows; sentinels absent from output.
- T2 A player with an old-cohort row and a 2022-cohort row is removed entirely (row and seasons), not relabelled to 0.0.
- T3 Cohorts 2020 and 2021 rows are dropped; `historical.cohorts` metadata is not propagated.
- T4 `assert_no_sealed` raises on: a 2022 row, a 2020 row, a sealed id in rows, a sealed id in seasons keys. The runner converts it to `abort_sealed` with no results file.
- T5 Sentinel ids and sentinel values never appear in serialised stage outputs or `results.json` (byte scan).
- T6 Calendar-year-2022 seasons of non-sealed players are kept (exclusion is by player, not season year).

Engine fidelity
- T7 Engine equals `_walk_forward` (predictions to 1e-8, gate `improvement_pct`) on a synthetic dataset, for ridge and hurdle, for outcome (baseline_features neighbors) and impact (features neighbors) settings.
- T8 kNN distance and tie-break reproduce the served neighbor sets exactly, including a dataset with duplicate feature rows.
- T9 Permutation preserves per-cohort (and per-cell for N2) multisets of labels, keeps row order, is a pure function of (SEED, stage, family, config, draw index), and is independent of chunking and resume.
- T10 Constant column and zero-variance conditional subset behave like the served code (std 1.0 fallback).

Stage logic
- T11 Planted-signal dataset: observed in the extreme tail of N1, N2 and best-of-k. No-signal datasets: calibration loop of p-values within a binomial band.
- T12 Best-of-k: with identical configurations the max equals the single value; the max is never below any member.
- T13 Purge: folds for T < first cohort + 4 are absent; kept cohorts satisfy `c + 4 <= T`; P-clip labels use seasons only up to T.
- T14 Reference variants: R2 equals `impact_oof.fold_local_impact_oof` output on the same synthetic input; the freeze test asserts `SEED` is not in the forbidden seed set and not 20261001, 36061, 37083.
- T15 Dedup: D1 keeps the largest-sample row; D2 only dedupes verified combined rows; a synthetic trade (two team rows plus a combined row) is reduced to one row; a no-combined-row group is flagged; `_service_totals` before/after changes in the expected direction.
- T16 Impact label with an inflating small-sample team row: A0 label is higher than A1, as the max-across-rows logic implies.
- T17 Serve-skew counts on a synthetic board with planted A-level, undrafted and out-of-range rows return the planted counts.

Runner and freeze
- T18 Status line is exactly one line with the specified format; an exception yields the `error` status with no message text; no output other than that line (capture stdout and stderr).
- T19 Refuses to run when `GITHUB_ACTIONS` or `CI` is set, when the output directory is inside the repo, or when `VALUCAST_STAGE_A_REAL` is missing for real data.
- T20 Freeze check: manifest mismatch on any hashed file or on `MATURE_THROUGH != 2019` aborts with `abort_hash`.
- T21 Canonical JSON output is byte-stable across two runs with the same seed (same hash), including after a simulated stop and resume.
- T22 No write inside the repo (checked by comparing a file listing before and after a synthetic run).

## 11. Risks and limits (short)

- Biggest risk: the 2022 exclusion rests on the dataset rows' definition of the 2022 cohort; unlisted players cannot be blocked. Second: the permutation nulls test a no-association world, so they cannot detect leakage that carries real information (the full-store reference tables and overlapping label windows are exactly that), which is why stages 4, 5 and 7 exist.
- The best-of-k grid is a lower bound on the real selection pool.
- Nothing in this plan requires editing prospects/model.py or any served module.

## 12. Amendments before the freeze (no section 9 threshold changed)

These come from the build and a fresh adversarial review. They override earlier text where they differ.

1. Service check (7.5): compare recomputed A0 totals to the stored `mlb_service` fact only for candidates that have one. The builder creates facts only for eligible candidates, so a current row without a fact is not an inconsistency. A mismatch on a row that has a fact still aborts.
2. Output check (1.3): the serialized-byte substring scan is replaced by a structural walk of the results. Integer values equal to a sealed id, and strings containing a sealed id as a whole token (not preceded or followed by a word character or a dot), abort the run. Floats and hashes are not scanned, since their digits can match an id by chance.
3. R1 references (Stage 5): an entry in `historical_mlb_seasons` with no historical cohort row has no window. It is left out of R1 and counted. It does not abort the run.
4. Checkpoints are bound to the code hashes, the manifest constants and the library versions as well as the input and seed. A resume cannot use draws from different frozen code.
5. An undefined ordering statistic in a null draw counts as at least as extreme as the observed value, keeping B as the denominator. The count of undefined draws is reported. This is conservative: it can only raise a p-value.
6. Selection-off (Stage 6) forces the first eligible input line while keeping the rest of the player's records available as comparators, so a change in score is not wrongly attributed to line selection when it comes from losing a stale-current comparator.
7. Each output file destination is checked, not just the directory: an existing symlink or a path resolving inside the repo refuses the write.
8. `VALUCAST_POOLED_SHADOW` and any other environment flag read by the served scorer must be at its default for a real run. The effective values are recorded in the manifest and checked at start.
9. Stage 6 score-change comparisons round to four decimals, the served score precision, before comparing to 0.02.
10. Recorded choices from the build. Sealed current candidates are removed during loading. Private cohort metadata is kept in memory for R1 windows only and never serialized. Raw margins are reported separately when `decide_gate` returns `insufficient_sample`. Selection-off is defined as the first eligible input line. The 45-of-50 flag is inapplicable when a board has fewer than 50 rows, and the overlap is still reported. Timing stays outside canonical results. Synthetic calibration uses a 99% binomial band and compares null max to null max, with the realized-versus-max comparison reported separately.
11. Unverified assumption: the bust/role/star label's four-year window. Permitted source searches did not find the outcome-dataset builder. Stage 4 therefore assumes cohort + 4 for the outcome axis and says so in its results.
