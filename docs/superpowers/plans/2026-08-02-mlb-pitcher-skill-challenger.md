# MLB Pitcher Skill Challenger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether compact public MLB pitch-level evidence improves ValuCast's next-season pitcher skill forecasts beyond the frozen role-routed Marcel incumbent.

**Architecture:** Stream Baseball Savant pitches into small, immutable pitcher-season aggregates; fit fold-local ridge residual corrections for K/BF and BB/BF; reconstruct the existing K/9, BB/9, ERA, and WHIP outputs only inside a research evaluator; seal one fail-closed result artifact. No production importer or public metric is created.

**Tech Stack:** Python standard library, existing ValuCast projection/backtest modules, pytest, JSON artifacts, Git.

## Global Constraints

- Preserve the model freeze, failed-decay flag, pitcher publication veto, pitcher cap, Role Watch, ranks, values, projections, workflows, and served artifacts.
- Do not use Stockyard code, scores, labels, formulas, outputs, or private data.
- Do not add a machine-learning dependency. Reuse the repository's dependency-free ridge pattern.
- Do not fetch or inspect the historical result before the registration commit is frozen.
- Do not commit raw pitches. Cache only compact five-day accumulators under an ignored directory.
- A negative or inconclusive result completes the study; it does not authorize tuning another variant.
- A retrospective pass authorizes only a future shadow forecast. Promotion requires the untouched 2026 outcome season, separate review, and explicit owner authorization.

---

## Task 1: Register the one allowed study before seeing results

**Files:**

- Create: `plans/035-mlb-pitcher-skill-challenger.md`
- Modify: `plans/README.md`
- Create: `tests/test_mlb_pitcher_skill_registration.py`

- [ ] Write a failing registration contract test that parses the JSON block in Plan 035 and pins:

```python
assert registration["study_id"] == "mlb_pitcher_skill_challenger_v1"
assert registration["status"] == "registered_unspent"
assert registration["retrospective_target_seasons"] == [2020, 2021, 2022, 2023, 2024, 2025]
assert registration["statcast_feature_seasons"] == list(range(2015, 2025))
assert registration["minimum_input_pitches"] == 500
assert registration["ridge_lambda"] == 10.0
assert registration["bootstrap_seed"] == 35021
assert registration["outer_looks"] == 1
assert registration["feeds_live_projection"] is False
assert registration["feeds_rank_or_value"] is False
assert registration["feeds_pitcher_publication"] is False
assert registration["claim_eligible"] is False
```

- [ ] Before creating Plan 035, verify with `git grep` against its parent commit that seed `35021` has never appeared in a plan, study, script, validation artifact, or test fixture. The persistent contract test pins `35021` as this study's seed and pins the forbidden list to all existing held, spent, exploratory, and reserved seeds: `28013`, `28014`, `28015`, `28017`, `29001`, `29016`, `31013`, `31017`, `32019`, `33021`, `34021`, `34027`, `34031`, and `72127`.

- [ ] Register exactly these model and evaluation rules:

  - target residuals: actual next-season K/BF minus Control K/BF; actual next-season BB/BF minus Control BB/BF;
  - one combined feature set, with Shape, Location/Execution, and Arsenal reported only as in-look descriptive ablations;
  - fold rule: for target season `T`, train only examples whose outcome season is `< T`;
  - Control: `PitcherMarcelParams()` and `build_pitcher_projections` at the registration commit;
  - context comparators: same-season persistence and archived Steamer only where the exact same player, outcome, and forecast window exist; neither can train the challenger or rescue its gate;
  - scored folds: `2020..2025`, matching the canonical methodology scorecard;
  - input eligibility: at least 500 tracked pitches in feature season `T-1` and a Control projection for `T`;
  - meaningful pitch type: at least 50 pitches and at least 5% usage;
  - ridge lambda: `10.0`, no grid search;
  - correction clip: training-residual 5th and 95th percentiles, fitted independently inside each fold and target;
  - primary gate: at least 2% lower pooled out-of-sample MAE across K/9, BB/9, ERA, and WHIP; no endpoint or projected-role cohort worse by more than 1%; at least four of six folds improve; at least 250 scored pitcher-seasons;
  - paired hierarchical bootstrap: 10,000 resamples, completed target season then pitcher, seed `35021`, two-sided 95% percentile interval, descriptive only for this retrospective gate;
  - no second retrospective variant after the outer result is known;
  - prospective confirmation season: `2026`, evaluated only after that season is complete.

- [ ] Add Plan 035 to the `plans/README.md` status table as `REGISTERED — UNSPENT; RESEARCH ONLY`.

- [ ] Run:

```powershell
python -m pytest tests/test_mlb_pitcher_skill_registration.py -q
```

Expected first result: fail because Plan 035 does not exist. Add the plan and README row, rerun to green, then commit before any real Statcast acquisition:

```powershell
git add plans/035-mlb-pitcher-skill-challenger.md plans/README.md tests/test_mlb_pitcher_skill_registration.py
git commit -m "docs: register MLB pitcher skill challenger"
```

## Task 2: Build deterministic compact pitch aggregation

**Files:**

- Create: `projections/data/pitching_statcast.py`
- Create: `tests/test_pitching_statcast.py`
- Modify: `.gitignore`

- [ ] Start with synthetic pitch rows and failing tests for:

  1. MLBAM string identity;
  2. the pitcher-universe filter;
  3. exact Savant whiff convention, including `foul_tip` and `bunt_foul_tip`;
  4. zone, heart, edge, and waste geometry using each pitch's `sz_top`/`sz_bot`;
  5. clamped-rectangle edge distance for diagonal outside-zone pitches;
  6. pitch-label normalization, including unknown labels becoming `other`;
  7. associative merge of two chunk accumulators;
  8. sample gates at 500 total pitches and `max(50, 5% of total)` per pitch type;
  9. deterministic finalization independent of input order; and
  10. no raw pitch row or player name in the finalized artifact.

- [ ] Implement only pure aggregation primitives first:

```python
MIN_INPUT_PITCHES = 500
MIN_PITCH_TYPE_PITCHES = 50
MIN_PITCH_TYPE_USAGE = 0.05

def normalize_pitch_type(code: str | None) -> str: ...
def add_pitch(acc: dict, row: dict, eligible_ids: set[str]) -> None: ...
def merge_accumulators(left: dict, right: dict) -> dict: ...
def finalize_season(acc: dict, season: int) -> list[dict]: ...
```

The explicit pitch mapping is:

```text
FF/FA -> four_seam
SI    -> sinker
FC    -> cutter
SL    -> slider
ST    -> sweeper
CU/KC/CS -> curveball
CH    -> changeup
FS/FO -> splitter
KN    -> knuckleball
everything else -> other
```

- [ ] Store sufficient counts and sums to derive, without raw pitches:

  - whiff, CSW, called-strike, zone, heart, edge, and waste rates;
  - horizontal and vertical location dispersion;
  - pitch-type usage;
  - mean velocity, horizontal movement, induced vertical movement, spin, extension, and release position by normalized pitch type;
  - field-specific sample counts and missingness;
  - arsenal count, usage HHI, fastball share, maximum velocity separation, and maximum movement separation.

- [ ] Define eligible pitchers from the same season's committed MLB pitching backbone with `BF >= 100`. This removes position-player pitching while preserving qualified two-way-player pitching. Rows outside that universe never enter an accumulator.

- [ ] Add `projections/data/pitching_statcast_cache/` to `.gitignore`. This directory may contain compact five-day accumulator JSON only, never raw pitch CSV or pitch rows.

- [ ] Run to green:

```powershell
python -m pytest tests/test_pitching_statcast.py -q
```

- [ ] Commit:

```powershell
git add .gitignore projections/data/pitching_statcast.py tests/test_pitching_statcast.py
git commit -m "feat: aggregate MLB pitcher Statcast evidence"
```

## Task 3: Add bounded, immutable historical acquisition

**Files:**

- Modify: `projections/data/pitching_statcast.py`
- Create: `scripts/fetch_mlb_pitcher_statcast.py`
- Modify: `tests/test_pitching_statcast.py`

- [ ] Add failing tests for five-day inclusive date chunks, resumable compact-chunk caching, retries, source coverage, immutable finalized seasons, canonical hashes, and refusal to store a likely truncated pull.

- [ ] Reuse the existing Savant acquisition pattern from `projections/data/batted_balls.py` with this source shape:

```text
https://baseballsavant.mlb.com/statcast_search/csv
  ?all=true&type=details&player_type=pitcher
  &game_date_gt={start}&game_date_lt={end}
```

Parse the response as a stream. Never call `response.read()` for a full season and never write raw response bytes. Reduce each five-day response directly into an accumulator, then atomically cache that compact accumulator.

- [ ] Finalized files are immutable:

```text
projections/data/pitching_statcast/pitching_statcast_2015.json
...
projections/data/pitching_statcast/pitching_statcast_2025.json
projections/data/pitching_statcast/manifest.json
```

Each manifest row records season, regular-season date bounds, source query template, chunk count, eligible-pitcher count, qualified-feature-row count, unknown-pitch count/share, schema version, feature-contract version, and canonical SHA-256.

- [ ] Coverage gates fail loud when any expected chunk is missing, a chunk has no parseable pitches on a date range known to contain games, fewer than 250 finalized rows meet the 500-pitch floor, or unknown pitch labels exceed 2% of tracked pitches.

- [ ] Give the CLI explicit modes only:

```powershell
python scripts/fetch_mlb_pitcher_statcast.py --season 2015
python scripts/fetch_mlb_pitcher_statcast.py --start-season 2015 --end-season 2025
```

No workflow wiring, no implicit current-season refresh, and no default network call.

- [ ] Run focused tests, then a single recent-season smoke pull into a temporary directory. Verify no raw CSV remains and the compact result is small enough to review.

- [ ] Commit code and tests. Do not commit real historical artifacts until Task 6's pre-look audit passes.

## Task 4: Implement the fold-local residual challenger

**Files:**

- Create: `projections/models/pitcher_skill_challenger.py`
- Create: `tests/test_pitcher_skill_challenger.py`

- [ ] Write failing tests for:

  1. training examples use feature season `T-1` and outcome season `T`;
  2. test-season rows never contribute means, standard deviations, medians, pitch-type/hand references, ridge coefficients, or correction clips;
  3. the ridge result is deterministic;
  4. singular/constant columns do not crash;
  5. missing fields use training medians plus explicit known flags;
  6. fewer than 500 input pitches returns the Control rates exactly;
  7. a missing feature season returns Control exactly;
  8. corrections are clipped to training-residual P5/P95; and
  9. applying a correction never changes BF, IP, GS, G, QS, SV, HLD, HR, HBP, hits allowed, role, or opportunity.

- [ ] Implement one dependency-free residual model with no tuning API:

```python
@dataclass(frozen=True)
class PitcherSkillChallengerParams:
    ridge_lambda: float = 10.0
    minimum_input_pitches: int = 500
    residual_clip_quantiles: tuple[float, float] = (0.05, 0.95)

def fit_fold(training_rows: list[dict], params: PitcherSkillChallengerParams) -> dict: ...
def predict_rates(model: dict, control: dict, feature_row: dict | None) -> dict: ...
def apply_rates_to_control(control: dict, k_bf: float, bb_bf: float) -> dict: ...
```

- [ ] The registered feature vector contains only:

  - Control K/BF, Control BB/BF, and Control `p_sp`;
  - five usage-weighted, fold-relative shape deviations: velocity, IVB, handedness-normalized horizontal movement, spin, and extension, each referenced by normalized pitch type and pitcher hand using training rows only;
  - whiff, CSW, called-strike, zone, heart, edge, and waste rates;
  - horizontal and vertical location dispersion;
  - arsenal count, usage HHI, fastball share, maximum velocity separation, and maximum movement separation; and
  - a known flag for each nullable shape field.

Do not add age, injury, team, park, defense, contract, public rank, scouting grade, or opportunity fields.

- [ ] Reconstruct research-only outputs by changing K and BB counts at fixed Control BF/IP. ERA changes only through the existing FIP identity with Control HR/HBP and the same cFIP; WHIP changes only through BB at fixed hits allowed/IP. Assert the arithmetic against `marcel_pitcher.py` identities.

- [ ] Run:

```powershell
python -m pytest tests/test_pitcher_skill_challenger.py -q
```

- [ ] Commit:

```powershell
git add projections/models/pitcher_skill_challenger.py tests/test_pitcher_skill_challenger.py
git commit -m "feat: add research-only pitcher skill challenger"
```

## Task 5: Build the registered walk-forward evaluator

**Files:**

- Create: `projections/backtest/pitcher_skill_challenger_harness.py`
- Create: `scripts/run_mlb_pitcher_skill_challenger.py`
- Create: `tests/test_mlb_pitcher_skill_challenger_runner.py`

- [ ] Begin with a synthetic multi-season fixture and failing tests proving:

  - exact fold membership and no lookahead;
  - same-player, same-outcome, same-window Control/Challenger comparisons;
  - qualification uses the existing SP/RP IP floors;
  - cohort labels use Control `p_sp`, never target-season role;
  - pooled MAE weights individual pitcher outcomes rather than averaging fold ratios;
  - four-of-six fold-win logic;
  - endpoint and projected-role 1% regression guards;
  - minimum `n=250` guard;
  - deterministic hierarchical bootstrap at seed `35021`;
  - every stopped/failed path keeps `claim_eligible: false`; and
  - result writing is atomic and refuses to overwrite a spent result.

- [ ] The runner must load Plan 035's JSON registration and refuse to run if code constants, fold seasons, seed, feature names, thresholds, or source hashes differ.

- [ ] Report same-season persistence and exact-window archived Steamer as context-only comparators when available. Missing Steamer coverage must be counted and disclosed, never imputed; neither comparator participates in the Control-versus-Challenger gate.

- [ ] Produce one result payload at:

```text
data/validation/mlb_pitcher_skill_challenger_result.json
```

Required top-level boundary fields:

```json
{
  "research_only": true,
  "feeds_live_projection": false,
  "feeds_rank_or_value": false,
  "feeds_pitcher_publication": false,
  "claim_eligible": false
}
```

The payload also records Control and Challenger MAE by endpoint/fold/projected role, paired deltas, bootstrap interval, coverage/fallback counts, all three descriptive feature-family ablations, gate criteria, final verdict, source hashes, code commit, and registration hash. Never write player-level predictions.

- [ ] Restrict verdicts to:

```text
retrospective_pass_shadow_only
validated_underperformance
no_material_improvement
invalid
spent_error
```

- [ ] Run the synthetic evaluator tests to green and commit.

## Task 6: Freeze implementation, acquire data, and spend one look

**Files:**

- Modify: `plans/035-mlb-pitcher-skill-challenger.md`
- Create: `projections/data/pitching_statcast/*.json`
- Create: `docs/studies/2026-08-02-mlb-pitcher-skill-challenger/README.md`
- Create: `data/validation/mlb_pitcher_skill_challenger_result.json`

- [ ] Before any outer scoring, run the no-result readiness mode:

```powershell
python scripts/run_mlb_pitcher_skill_challenger.py --check-readiness
```

It must verify all 2015–2024 feature seasons and 2020–2025 outcomes exist, identities are unique, every fold has training history, source manifests reconcile, at least 250 pitcher-seasons are scoreable, no serving importer references the challenger, and the registration seed is fresh.

- [ ] Acquire 2015–2025 compact seasons. The 2025 feature artifact is collected for a later 2026 shadow but is forbidden from the retrospective folds. Review season counts, unknown-label shares, missingness, and compact artifact sizes before committing them.

- [ ] Amend Plan 035 once, before results, with the implementation commit, canonical source hashes, observed source row counts, and readiness artifact hash. The amendment may stop or narrow the study for coverage failure; it may not add features, change endpoints, relax gates, change folds, or change seed.

- [ ] Obtain independent code/method review of the frozen runner, joins, and registration. Fix defects before running. Any substantive model/gate change requires a new unspent registration; do not patch it after seeing results.

- [ ] Commit the amendment and compact source artifacts, verify the tree is clean, then run exactly once:

```powershell
python scripts/run_mlb_pitcher_skill_challenger.py --spend-registered-look
```

- [ ] Generate the study README directly from the sealed result. It must lead with the verdict, sample, folds, endpoint/cohort gate table, uncertainty, fallbacks, and the prospective-confirmation requirement. It must explicitly say that a retrospective pass is not a public superiority claim.

- [ ] Commit the sealed result and report without touching any production projection, rank, value, publication, app, or workflow file.

## Task 7: Verify freeze boundaries and hand off the decision

**Files:** No new files expected.

- [ ] Run focused and full verification:

```powershell
python -m pytest tests/test_mlb_pitcher_skill_registration.py tests/test_pitching_statcast.py tests/test_pitcher_skill_challenger.py tests/test_mlb_pitcher_skill_challenger_runner.py -q
python -m pytest tests/test_pitching_harness.py tests/test_pitcher_projection.py -q
python -m pytest -q
git diff --check
```

- [ ] Prove the live boundaries stayed untouched:

```powershell
git diff origin/master -- app.py templates static .github prospects/rank_v1.py quality/valucast_governor.py projections/models/marcel_pitcher.py projections/models/pitcher_params.py
```

Expected result: no diff in those paths.

- [ ] Inspect imports and grep for forbidden serving connections:

```powershell
rg -n "pitcher_skill_challenger|mlb_pitcher_skill_challenger" app.py templates static quality prospects .github
```

Expected result: no matches.

- [ ] Verify the result keeps all four fail-closed boundary flags false and `research_only: true`, contains no competitor names, and contains no player-level prediction rows.

- [ ] Hand off only one of these decisions:

  - `retrospective_pass_shadow_only`: freeze a dated 2026 shadow after the season, then wait for actual 2026 outcomes;
  - `validated_underperformance` or `no_material_improvement`: retain the incumbent and close the challenger;
  - `invalid` or `spent_error`: disclose the invalid/spent state and do not rerun.

No result in this plan authorizes a live model change.

## Done Criteria

- [ ] Registration was committed before any historical result was inspected.
- [ ] Compact Statcast artifacts are reproducible and raw pitches are absent from Git.
- [ ] All preprocessing, references, imputation, clipping, and fitting are fold-local.
- [ ] The one registered retrospective look is sealed and cannot be overwritten.
- [ ] The result reports endpoint, fold, role, coverage, fallback, and uncertainty evidence.
- [ ] Existing projection, rank, value, cap, veto, Role Watch, and publication behavior is byte-identical.
- [ ] Full tests pass and the worktree is clean except for explicitly preserved user files outside this worktree.
