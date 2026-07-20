# Prospect Proof Foundation V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fail-closed, research-only prospect challenger lane that corrects the documented evaluation leak, archives the missing prospective MiLB evidence, and can test a registered nonlinear production normalization without changing any live ValuCast decision.

**Architecture:** Keep every new evaluator and audit outside the production import graph. Reuse the current prospect input contract, `prospects.rank_backtest` production-path replay, and plan-032 proof primitives; pass a fold-filtered contract into the existing scorer instead of editing the incumbent model. Add one compact immutable daily observation archive, then register the one allowed outcome look before executing it.

**Tech Stack:** Python 3, stdlib JSON/hash/bisect/path utilities, existing NumPy and pytest, GitHub Actions YAML, existing ValuCast prospect artifacts.

## Global Constraints

- No live model retrain, rank change, value change, pitcher-cap change, Role Watch change, or publication change.
- Preserve `PITCHER_STALE_PEDIGREE_DECAY_ENABLED = False`, all failed-decay records, and every existing cross-role/level-translation/strike-percentage flag value.
- Do not edit `prospects/model.py`, `prospects/rank_v1.py`, `prospects/competition_benchmark.py`, or any served model artifact to implement the challenger.
- `data/validation/` is the only allowed output area for readiness and challenger results; no new production importer may read those outputs.
- The only authorized workflow edit is the guarded add and daily build step for `data/milb_observation_archive/`; no deploy is dispatched.
- The registered historical cutoff is cohort-season completion because the historical store cannot reconstruct an earlier intra-season cutoff.
- Same-level normalization requires 25 other peers; role-season fallback requires 250 other peers; exercised coverage must be at least 90% in every role and fold.
- Missing rows remain unavailable. Never replace a missing quantile, AAA Statcast component, role, QS, or outcome with zero, league average, or the Control representation.
- The challenger uses fresh seed `33021`; seeds `28013`, `28017`, `29001`, `31013`, and `31017` are forbidden.
- The 2020 cohort remains absent because affiliated Minor League Baseball had no 2020 season; do not synthesize a fold or add an unregistered sensitivity view.
- Hitters and pitchers are fitted, scored, reported, and verdicted separately. Starter and reliever AAA reports are also separate.
- External product and person names are forbidden from new public or validation artifacts.
- Use the pinned branch inputs at commit `16df0aee`: prospect input blob `4ce139871ae456b5289c68dad1e15d8191ff7ef5`; AAA Statcast blob `37533ad816d86bcf392ccce75bb15f0b745f0f74`; incumbent model blob `7a9b9d12ae0866ae3b460f3f02395a0e30949844`; live rank blob `4ed3f2603b93e5ecf319f501519303f6ff7c18fa`.
- Each task is a separate logical commit. Stop at both marked human/reviewer checkpoints.

## File Map

- `docs/prospect-model.md`: corrected human-readable and machine-readable live contract.
- `tests/test_prospect_model_contract.py`: prevents documentation/live-artifact drift.
- `prospects/realized_value_readiness.py`: pure readiness and two-way identity audit.
- `scripts/build_prospect_realized_value_readiness.py`: manual builder for the readiness artifact.
- `tests/test_prospect_realized_value_readiness.py`: QS, role, coverage, and replay fail-closed tests.
- `data/validation/valucast_prospect_realized_value_readiness.json`: committed audit result; never a production input.
- `prospects/challenger_eval.py`: quantile transformation, fold-local contract filtering, registered replay, and AAA disagreement logic.
- `tests/test_prospect_challenger_eval.py`: leakage, coverage, identity, missingness, and role-separation tests.
- `scripts/archive_milb_observations.py`: deterministic immutable daily archive writer.
- `tests/test_milb_observation_archive.py`: archive schema, hash, no-op, and mutation tests.
- `scripts/run_daily_public_build.py`: one ordered archive step immediately after the prospect shadow input pipeline.
- `.github/workflows/daily-public-data.yml`: one guarded `git add data/milb_observation_archive/` block.
- `tests/test_daily_workflow_wiring.py`: ordering and allow-list contract tests.
- `plans/033-prospect-normalized-production-gate.md`: immutable registration for the single research look.
- `plans/README.md`: register plan 033 as dark/research-only.
- `tests/test_prospect_normalized_production_registration.py`: locks registration constants to evaluator constants.
- `scripts/run_prospect_normalized_production_gate.py`: one-shot registered runner.
- `data/validation/valucast_prospect_normalized_production_gate.json`: private-by-design research result with no claim authorization.

---

### Task 1: Correct and lock the live prospect-model contract

**Files:**
- Modify: `docs/prospect-model.md`
- Create: `tests/test_prospect_model_contract.py`

**Interfaces:**
- Consumes: `data/models/valucast_prospect_model.json`, `data/models/valucast_prospect_rank_v1.json`, `data/models/valucast_prospect_model_v0_7.json`.
- Produces: a JSON object between `<!-- prospect-model-contract:start -->` and `<!-- prospect-model-contract:end -->` in `docs/prospect-model.md`.

- [ ] **Step 1: Write the failing documentation-contract test**

```python
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _documented_contract() -> dict:
    text = (ROOT / "docs/prospect-model.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- prospect-model-contract:start -->\s*```json\s*(\{.*?\})\s*```\s*"
        r"<!-- prospect-model-contract:end -->",
        text,
        flags=re.S,
    )
    assert match, "machine-readable prospect model contract is missing"
    return json.loads(match.group(1))


def test_documented_contract_matches_live_artifacts():
    documented = _documented_contract()
    model = _load(documented["live_model_artifact"])
    rank = _load(documented["live_rank_artifact"])
    preview = _load(documented["v0_7_artifact"])

    assert documented["model_score_consumed_by_live_rank"] is True
    assert rank["promotion"]["feeds_live_valucast_rank"] is True
    assert (
        rank["rank_contract"]["score_weights"]["prospect_model_v0_6"]["model_score"]
        == documented["live_model_score_weight"]
        == 0.76
    )
    impact = model["impact_target_contract"]
    assert impact["kind"] == documented["impact_target_kind"]
    assert impact["direct_7x7"] is documented["impact_target_direct_7x7"] is False
    assert impact["missing_pitcher_categories"] == documented["missing_pitcher_categories"] == ["qs"]
    assert preview["status"] == documented["v0_7_status"] == "shadow_preview"
    assert preview["model_contract"]["feeds_live_valucast_rank"] is False
    assert preview["model_contract"]["purpose"] == documented["v0_7_purpose"]
```

- [ ] **Step 2: Run the test and confirm the stale document fails**

Run: `python -m pytest tests/test_prospect_model_contract.py -q`

Expected: FAIL because the marker-delimited JSON contract is absent.

- [ ] **Step 3: Rewrite the stale claims and add the exact contract block**

Delete claims that the direct 7x7 target is active, that all direct-impact gates pass, and that neither model rank is consumed by the live board. Describe the incumbent as a partial-category model feeding Prospect Rank v1 and the v0.7 artifact as a non-live feature-readiness preview. Add this block verbatim:

````markdown
<!-- prospect-model-contract:start -->
```json
{
  "live_model_artifact": "data/models/valucast_prospect_model.json",
  "live_rank_artifact": "data/models/valucast_prospect_rank_v1.json",
  "model_score_consumed_by_live_rank": true,
  "live_model_score_weight": 0.76,
  "impact_target_kind": "partial_category_fantasy_impact",
  "impact_target_direct_7x7": false,
  "missing_pitcher_categories": ["qs"],
  "v0_7_artifact": "data/models/valucast_prospect_model_v0_7.json",
  "v0_7_status": "shadow_preview",
  "v0_7_purpose": "Feature-readiness preview for Prospect Model v0.7."
}
```
<!-- prospect-model-contract:end -->
````

- [ ] **Step 4: Run the focused and adjacent tests**

Run: `python -m pytest tests/test_prospect_model_contract.py tests/test_prospect_model.py tests/test_prospect_rank_v1.py tests/test_prospect_model_v07.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the contract correction**

```powershell
git add docs/prospect-model.md tests/test_prospect_model_contract.py
git commit -m "docs: lock the live prospect model contract"
```

#### Review checkpoint A — stop here

Do not start Task 2 until a reviewer confirms that the prose and machine-readable block match the three committed artifacts and that the test would fail on the old false claims.

---

### Task 2: Build the realized-value readiness and two-way identity audit

**Files:**
- Create: `prospects/realized_value_readiness.py`
- Create: `scripts/build_prospect_realized_value_readiness.py`
- Create: `tests/test_prospect_realized_value_readiness.py`
- Create: `data/validation/valucast_prospect_realized_value_readiness.json`

**Interfaces:**
- Consumes: `audit_realized_value_readiness(contract: dict, model_artifact: dict) -> dict`.
- Produces: schema `valucast_prospect_realized_value_readiness` with `status`, `identity_policy`, `category_coverage`, `cohorts`, `replay`, `blockers`, and `content_sha256`.
- Produces identity key `cohort_year:mlbam_id`, with the role frozen from the cohort-cutoff row.

- [ ] **Step 1: Write fail-closed tests before the audit**

```python
from copy import deepcopy

from prospects.realized_value_readiness import audit_realized_value_readiness


def _contract() -> dict:
    return {
        "historical": {
            "rows": [
                {"cohort_year": 2018, "mlbam_id": 10, "role": "hitter", "outcome": "role"},
                {"cohort_year": 2018, "mlbam_id": 20, "role": "pitcher", "outcome": "star"},
            ]
        },
        "historical_mlb_seasons": {
            "10_hitter": [{"year": 2019, "pa": 500, "r": 70, "hr": 20, "rbi": 75, "sb": 8, "avg": .270, "ops": .800, "so": 120}],
            "20_pitcher": [{"year": 2019, "ip": 150, "so": 170, "sv": 0, "hld": 0, "era": 3.50, "whip": 1.20, "k_bb": 3.2, "l": 8}],
        },
    }


def _model() -> dict:
    return {
        "impact_target_contract": {
            "canonical_hitter_categories": ["r", "hr", "rbi", "sb", "avg", "ops", "so"],
            "canonical_pitcher_categories": ["so", "qs", "sv_hld", "era", "whip", "k_bb", "l"],
            "direct_7x7": False,
            "missing_hitter_categories": [],
            "missing_pitcher_categories": ["qs"],
        }
    }


def test_missing_qs_blocks_realized_value_regret():
    report = audit_realized_value_readiness(_contract(), _model())
    assert report["status"] == "blocked"
    assert report["replay"]["realized_value_regret_ready"] is False
    assert report["category_coverage"]["pitcher"]["missing"] == ["qs"]
    assert "missing_pitcher_category:qs" in report["blockers"]


def test_conflicting_same_cohort_roles_fail_that_cohort_closed():
    contract = _contract()
    contract["historical"]["rows"].append(
        {"cohort_year": 2018, "mlbam_id": 20, "role": "hitter", "outcome": "role"}
    )
    report = audit_realized_value_readiness(contract, _model())
    assert report["cohorts"]["2018"]["identity_status"] == "blocked"
    assert report["identity_audit"]["conflicting_cohort_roles"] == ["2018:20"]


def test_later_role_change_is_disclosed_without_relabeling_prior_cohort():
    contract = _contract()
    contract["historical"]["rows"].append(
        {"cohort_year": 2019, "mlbam_id": 20, "role": "hitter", "outcome": "role"}
    )
    report = audit_realized_value_readiness(contract, _model())
    assert report["identity_audit"]["later_role_changes"] == [
        {"mlbam_id": "20", "roles_by_cohort": {"2018": "pitcher", "2019": "hitter"}}
    ]
    assert report["identity_policy"]["historical_role"] == "frozen_from_cohort_cutoff_row"


def test_zero_opportunity_is_counted_not_promoted_to_success():
    contract = deepcopy(_contract())
    contract["historical_mlb_seasons"]["10_hitter"] = []
    report = audit_realized_value_readiness(contract, _model())
    assert report["cohorts"]["2018"]["zero_opportunity"]["hitter"] == 1
```

- [ ] **Step 2: Run the tests and confirm the module is missing**

Run: `python -m pytest tests/test_prospect_realized_value_readiness.py -q`

Expected: collection ERROR for missing `prospects.realized_value_readiness`.

- [ ] **Step 3: Implement the pure audit with the frozen identity policy**

Use this public contract and exact policy; compute all counts from the supplied dictionaries and seal the report with canonical sorted JSON excluding `content_sha256`:

```python
IDENTITY_POLICY = {
    "identity_key": "integer_mlbam_id",
    "cohort_key": "cohort_year:mlbam_id",
    "one_row_per_cohort_identity": True,
    "historical_role": "frozen_from_cohort_cutoff_row",
    "later_role_changes": "disclosed_never_relabels_prior_cohort",
    "same_cohort_role_conflict": "block_affected_cohort",
    "common_pool": "unique_mlbam_identities",
    "role_results": "frozen_cohort_role",
}


def audit_realized_value_readiness(contract: dict, model_artifact: dict) -> dict:
    rows = list((contract.get("historical") or {}).get("rows") or [])
    seasons = contract.get("historical_mlb_seasons") or {}
    impact = model_artifact.get("impact_target_contract") or {}
    # Group by (cohort_year, mlbam_id), record duplicate rows and conflicting
    # same-cohort roles, then record role changes only across distinct cohorts.
    # A player has zero opportunity when its frozen-role season list contains no
    # season with year in (cohort_year, cohort_year + 4] and PA/IP above zero.
    # Category readiness comes from the canonical category lists plus the model
    # artifact's missing-category declarations; `sv_hld` requires both sv and hld.
    # `realized_value_regret_ready` is true only when every category, identity,
    # cohort, and exact-replay requirement is true. The current artifact must be
    # blocked because pitcher QS is absent.
```

The emitted replay contract must be exactly:

```python
"replay": {
    "historical_cutoff": "cohort_season_completion",
    "intra_season_cutoff_reconstructable": False,
    "retrospective_input_kind": "reconstructed_full_season",
    "exact_prospective_replay_ready": False,
    "partial_category_secondary_ready": (
        not impact.get("missing_hitter_categories")
        and bool(
            set(impact.get("canonical_pitcher_categories") or [])
            - set(impact.get("missing_pitcher_categories") or [])
        )
    ),
    "realized_value_regret_ready": False,
}
```

Do not calculate a substitute fantasy value when QS is missing.

- [ ] **Step 4: Add the manual builder**

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "data/prospects/prospect_model_inputs.json")
    parser.add_argument("--model", type=Path, default=ROOT / "data/models/valucast_prospect_model.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/validation/valucast_prospect_realized_value_readiness.json")
    args = parser.parse_args()
    report = audit_realized_value_readiness(_load(args.input), _load(args.model))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0
```

The builder is manual. Do not add it to `BUILD_STEPS`, `VALIDATE_STEPS`, or the daily workflow.

- [ ] **Step 5: Run focused tests and build the real audit artifact**

Run: `python -m pytest tests/test_prospect_realized_value_readiness.py -q`

Expected: PASS.

Run: `python scripts/build_prospect_realized_value_readiness.py`

Expected: writes the validation artifact with `status: "blocked"`, `realized_value_regret_ready: false`, and blocker `missing_pitcher_category:qs`.

- [ ] **Step 6: Commit the readiness audit**

```powershell
git add prospects/realized_value_readiness.py scripts/build_prospect_realized_value_readiness.py tests/test_prospect_realized_value_readiness.py data/validation/valucast_prospect_realized_value_readiness.json
git commit -m "feat: audit prospect realized-value readiness"
```

---

### Task 3: Add the leak-free quantile challenger evaluator without running the look

**Files:**
- Create: `prospects/challenger_eval.py`
- Create: `tests/test_prospect_challenger_eval.py`

**Interfaces:**
- Produces `normalize_rows(rows: list[dict], *, same_level_min: int = SAME_LEVEL_MIN_PEERS, role_season_min: int = ROLE_SEASON_MIN_PEERS) -> tuple[list[dict], dict]`, using `cohort_year` for historical rows and `sample_season` for current rows.
- Produces `fold_local_contract(contract: dict, test_year: int) -> dict`.
- Produces `prepare_fold(contract: dict, test_year: int) -> dict` containing Control/candidate contracts, common identities, and coverage diagnostics; it must not call the outcome scorer.
- Later Task 6 consumes `run_registered_replay(contract: dict, registration: dict) -> dict` and `build_aaa_disagreement(control_scores: dict, candidate_scores: dict, aaa: dict, current_rows: list[dict]) -> dict` from this module.

- [ ] **Step 1: Write the quantile, fallback, and leakage tests**

```python
import json
from pathlib import Path

from prospects.challenger_eval import (
    FORBIDDEN_SEEDS,
    HITTER_RATE_FIELDS,
    REGISTERED_SEED,
    fold_local_contract,
    normalize_rows,
    prepare_fold,
)


def _row(player, *, year=2018, role="hitter", level="AA", iso=.100):
    return {
        "mlbam_id": player,
        "cohort_year": year,
        "role": role,
        "level": level,
        "iso": iso,
        "k_pct": 20.0,
        "bb_pct": 8.0,
        "ops": .700,
        "avg": .250,
        "obp": .320,
        "slg": .380,
        "babip": .300,
    }


def test_leave_one_out_quantile_is_tie_aware_and_non_affine():
    rows = [_row(1, iso=.100), _row(2, iso=.200), _row(3, iso=.200), _row(4, iso=.900)]
    normalized, diagnostics = normalize_rows(rows, same_level_min=2, role_season_min=3)
    by_id = {row["mlbam_id"]: row for row in normalized}
    assert by_id[2]["iso"] == by_id[3]["iso"]
    assert [by_id[i]["iso"] for i in (1, 2, 4)] != [.1, .2, .9]
    assert diagnostics["unavailable"] == 0


def test_sparse_level_backs_off_and_sparse_role_season_is_unavailable():
    rows = [_row(i, level="AA" if i == 1 else "AAA", iso=i / 10) for i in range(1, 6)]
    normalized, diagnostics = normalize_rows(rows, same_level_min=2, role_season_min=3)
    assert diagnostics["backoff_rows"] >= 1
    _, blocked = normalize_rows(rows[:2], same_level_min=2, role_season_min=3)
    assert blocked["unavailable"] == 2


def test_outcome_mutation_cannot_change_normalized_inputs():
    rows = [_row(i, iso=i / 100) | {"outcome": "bust"} for i in range(1, 30)]
    first = normalize_rows(rows, same_level_min=25, role_season_min=250)
    mutated = [dict(row, outcome="star") for row in rows]
    second = normalize_rows(mutated, same_level_min=25, role_season_min=250)
    first_rates = [tuple(row[field] for field in HITTER_RATE_FIELDS) for row in first[0]]
    second_rates = [tuple(row[field] for field in HITTER_RATE_FIELDS) for row in second[0]]
    assert first_rates == second_rates
    assert first[1] == second[1]


def test_test_cohort_seasons_never_enter_fold_local_impact_references():
    contract = {
        "historical": {"rows": [
            {"mlbam_id": 1, "role": "hitter", "cohort_year": 2014},
            {"mlbam_id": 2, "role": "hitter", "cohort_year": 2018},
        ]},
        "historical_mlb_seasons": {
            "1_hitter": [
                {"year": 2015, "pa": 500, "hr": 10},
                {"year": 2020, "pa": 500, "hr": 40},
            ],
            "2_hitter": [{"year": 2019, "pa": 500, "hr": 99}],
        },
    }
    fold = fold_local_contract(contract, test_year=2018)
    assert set(fold["historical_mlb_seasons"]) == {"1_hitter"}
    assert [season["year"] for season in fold["historical_mlb_seasons"]["1_hitter"]] == [2015]


def test_registered_seed_is_fresh_and_forbidden_seeds_stay_forbidden():
    assert REGISTERED_SEED == 33021
    assert REGISTERED_SEED not in FORBIDDEN_SEEDS
    assert FORBIDDEN_SEEDS == {28013, 28017, 29001, 31013, 31017}
```

- [ ] **Step 2: Run the tests and confirm the evaluator is absent**

Run: `python -m pytest tests/test_prospect_challenger_eval.py -q`

Expected: collection ERROR for missing `prospects.challenger_eval`.

- [ ] **Step 3: Implement the minimal nonlinear transform**

Define only the existing factual rate fields:

```python
HITTER_RATE_FIELDS = ("iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip")
PITCHER_RATE_FIELDS = ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")
SAME_LEVEL_MIN_PEERS = 25
ROLE_SEASON_MIN_PEERS = 250
MIN_EXERCISED_COVERAGE = 0.90
REGISTERED_SEED = 33021
FORBIDDEN_SEEDS = {28013, 28017, 29001, 31013, 31017}


def _loo_quantile(value: float, peers: list[float]) -> float:
    ordered = sorted(peers)
    left = bisect_left(ordered, value)
    right = bisect_right(ordered, value)
    return (left + right) / (2.0 * len(ordered))
```

`normalize_rows` must:

1. define `reference_season` as `cohort_year` for historical rows and `sample_season` for current rows, failing the row closed when neither exists;
2. group reference values by `(role, reference_season, level, field)` and `(role, reference_season, field)`;
3. exclude the current row by `(reference_season, mlbam_id, role)`;
4. use the same-level pool when it has at least 25 other values, otherwise the role-season pool when it has at least 250;
5. mark the whole row unavailable if any registered rate field lacks a valid number or reference pool;
6. return only available transformed rows plus per-role/per-year counts for same-level, backoff, unavailable, and exercised coverage;
7. copy every non-rate field unchanged and never use `outcome` or `historical_mlb_seasons` to calculate a transform or reference pool.

- [ ] **Step 4: Add fold-local impact filtering and dry preparation**

Import `OUTCOME_HORIZON_YEARS` from `prospects.dynasty_backtest` and reuse `_horizon_clipped_seasons` from `prospects.universal`; do not duplicate either contract.

```python
def fold_local_contract(contract: dict, test_year: int) -> dict:
    train_through = test_year - OUTCOME_HORIZON_YEARS
    training_rows = [
        row
        for row in contract["historical"]["rows"]
        if int(row.get("cohort_year") or 9999) <= train_through
    ]
    train_keys = {
        f"{row['mlbam_id']}_{row['role']}"
        for row in training_rows
    }
    clipped = _horizon_clipped_seasons(
        training_rows,
        contract.get("historical_mlb_seasons") or {},
    )
    fold = deepcopy(contract)
    fold["historical_mlb_seasons"] = {
        key: clipped[key]
        for key in clipped
        if key in train_keys
    }
    return fold
```

`prepare_fold` normalizes the complete historical input table first, restricts both Control and candidate to the candidate’s available `(cohort_year, mlbam_id, role)` identities, applies `fold_local_contract` to both, and raises if the fold/role identity sets differ. It returns contracts and coverage only; it does not call `_fold_board_scores`.

- [ ] **Step 5: Prove the real input exercises the challenger without looking at outcomes**

Add a test that loads `data/prospects/prospect_model_inputs.json`, removes the `outcome` key from every row before calling `normalize_rows`, and asserts:

```python
assert diagnostics["overall"]["rows"] == 6756
for fold in diagnostics["folds"].values():
    for role in ("hitter", "pitcher"):
        assert fold[role]["exercised_coverage"] >= 0.90
```

The expected reviewed data state is 100% coverage in all six folds, with role-season peer pools of 336–410. The test must not train, score, rank, or inspect `outcome`.

Run: `python -m pytest tests/test_prospect_challenger_eval.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the evaluator foundation**

```powershell
git add prospects/challenger_eval.py tests/test_prospect_challenger_eval.py
git commit -m "feat: add leak-free prospect challenger evaluator"
```

---

### Task 4: Add the compact immutable MiLB observation archive

**Files:**
- Create: `scripts/archive_milb_observations.py`
- Create: `tests/test_milb_observation_archive.py`
- Modify: `scripts/run_daily_public_build.py`
- Modify: `.github/workflows/daily-public-data.yml`
- Modify: `tests/test_daily_workflow_wiring.py`
- Create: `data/milb_observation_archive/2026-07-20.json`

**Interfaces:**
- Produces `build_snapshot(contract: dict) -> dict` and `write_snapshot(snapshot: dict, output_dir: Path) -> tuple[Path, str]`, where status is `created` or `unchanged`.
- Consumes `current.fetched_date`, `current.season`, `current.hitters`, and `current.pitchers` from the canonical input contract.

- [ ] **Step 1: Write archive immutability and schema tests**

```python
import json

import pytest

from scripts.archive_milb_observations import build_snapshot, write_snapshot


def _contract():
    return {"current": {"fetched_date": "2026-07-20", "season": 2026, "hitters": [{
        "mlbam_id": 10, "role": "hitter", "team": "Erie SeaWolves", "level": "AA",
        "source_kind": "current_season", "age": 20, "plate_appearances": 120,
        "iso": .190, "k_pct": 18.0, "bb_pct": 11.0, "ops": .820,
        "avg": .270, "obp": .360, "slg": .460, "babip": .310,
    }], "pitchers": [{
        "mlbam_id": 20, "role": "pitcher", "team": "Toledo Mud Hens", "level": "AAA",
        "source_kind": "current_season", "age": 23, "innings_pitched": 50.0,
        "k_per_9": 10.5, "bb_per_9": 2.7, "k_bb_pct": 24.0,
        "era": 3.10, "whip": 1.08, "games_started": 8, "is_starter": True,
    }]}}


def test_snapshot_contains_only_registered_factual_fields_and_a_seal():
    snapshot = build_snapshot(_contract())
    assert snapshot["observation_date"] == "2026-07-20"
    assert [row["mlbam_id"] for row in snapshot["rows"]] == [10, 20]
    assert snapshot["rows"][0]["sample_unit"] == "PA"
    assert snapshot["rows"][1]["sample_unit"] == "IP"
    assert "outcome" not in json.dumps(snapshot)
    assert len(snapshot["input_sha256"]) == 64
    assert len(snapshot["content_sha256"]) == 64


def test_same_date_same_content_is_noop_but_changed_content_fails(tmp_path):
    snapshot = build_snapshot(_contract())
    path, status = write_snapshot(snapshot, tmp_path)
    assert status == "created"
    assert write_snapshot(snapshot, tmp_path) == (path, "unchanged")
    changed_contract = _contract()
    changed_contract["current"]["hitters"][0]["iso"] = .999
    changed = build_snapshot(changed_contract)
    with pytest.raises(ValueError, match="sealed date"):
        write_snapshot(changed, tmp_path)


def test_unknown_organization_stays_null_not_invented():
    contract = _contract()
    contract["current"]["hitters"][0]["team"] = "Unknown Club"
    row = build_snapshot(contract)["rows"][0]
    assert row["organization"] is None
    assert row["organization_status"] == "unknown"
```

- [ ] **Step 2: Run the test and confirm the script is absent**

Run: `python -m pytest tests/test_milb_observation_archive.py -q`

Expected: collection ERROR for missing `scripts.archive_milb_observations`.

- [ ] **Step 3: Implement the deterministic snapshot**

Use `prospects.universe.MINOR_TEAM_MLB_AFFILIATES` for known affiliations. Store rates under a role-specific `rates` object; do not copy rank, value, outcome, market, availability, injury, or external-board fields.

```python
HITTER_FIELDS = ("iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip")
PITCHER_FIELDS = ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def build_snapshot(contract: dict) -> dict:
    current = contract["current"]
    rows = []
    for role, plural, sample_key, unit, fields in (
        ("hitter", "hitters", "plate_appearances", "PA", HITTER_FIELDS),
        ("pitcher", "pitchers", "innings_pitched", "IP", PITCHER_FIELDS),
    ):
        for source in current.get(plural) or []:
            team = source.get("team")
            organization = MINOR_TEAM_MLB_AFFILIATES.get(team)
            row = {
                "mlbam_id": int(source["mlbam_id"]),
                "role": role,
                "organization": organization,
                "organization_status": "known" if organization else "unknown",
                "minor_team": team,
                "level": source.get("level"),
                "source_kind": source.get("source_kind"),
                "observation_date": current["fetched_date"],
                "season": current["season"],
                "age": source.get("age"),
                "sample": source.get(sample_key),
                "sample_unit": unit,
                "rates": {field: source.get(field) for field in fields},
            }
            if role == "pitcher":
                row["role_facts"] = {"games_started": source.get("games_started"), "is_starter": source.get("is_starter")}
            rows.append(row)
    rows.sort(key=lambda row: (row["role"], row["mlbam_id"]))
    payload = {
        "artifact": "valucast_milb_observation_archive",
        "schema_version": 1,
        "observation_date": current["fetched_date"],
        "season": current["season"],
        "source": "data/prospects/prospect_model_inputs.json#current",
        "input_sha256": _canonical_hash(current),
        "rows": rows,
        "content_sha256": "",
    }
    payload["content_sha256"] = _canonical_hash({k: v for k, v in payload.items() if k != "content_sha256"})
    return payload
```

`write_snapshot` writes `<observation_date>.json`; it returns unchanged for an identical seal and raises `ValueError("sealed date changed")` for different content at the same date.

- [ ] **Step 4: Wire the one authorized daily step and guarded add**

Insert `("scripts/archive_milb_observations.py",)` immediately after `("scripts/run_prospect_shadow_pipeline.py",)` in `BUILD_STEPS`.

Add exactly this guarded block after the existing AAA archive block:

```yaml
          if [ -d data/milb_observation_archive ]; then
            git add data/milb_observation_archive/
          fi
```

Extend `tests/test_daily_workflow_wiring.py` with:

```python
def test_milb_observation_archive_runs_after_prospect_input_pipeline():
    build = _build_commands()
    assert build.index("scripts/run_prospect_shadow_pipeline.py") < build.index(
        "scripts/archive_milb_observations.py"
    )


def test_allowlist_publishes_milb_observation_archive_with_guard():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert (
        "if [ -d data/milb_observation_archive ]; then\n"
        "            git add data/milb_observation_archive/\n"
        "          fi"
    ) in workflow
```

- [ ] **Step 5: Build the first snapshot and run the CI shakedown**

Run: `python scripts/archive_milb_observations.py`

Expected: creates `data/milb_observation_archive/2026-07-20.json`.

Run: `python scripts/archive_milb_observations.py`

Expected: reports `unchanged`; the file hash does not change.

Run: `python -m pytest tests/test_milb_observation_archive.py tests/test_daily_workflow_wiring.py tests/test_public_data_refresh.py -q`

Expected: PASS. The delivery is not “shipped” until the GitHub Actions workflow passes once after push.

- [ ] **Step 6: Commit only the authorized archive changes**

```powershell
git add scripts/archive_milb_observations.py tests/test_milb_observation_archive.py scripts/run_daily_public_build.py .github/workflows/daily-public-data.yml tests/test_daily_workflow_wiring.py data/milb_observation_archive/2026-07-20.json
git commit -m "feat: archive daily MiLB observations"
```

#### Review checkpoint B — stop before registration

Do not create plan 033 and do not run any Control/candidate outcome comparison until a reviewer verifies Tasks 2–4, the input pins, the 100%-input-coverage dry check, the fold-local season filter, the archive immutability, and production isolation. Changes requested after registration would consume the multiplicity budget.

---

### Task 5: Register the single normalized-production research look

**Files:**
- Create: `plans/033-prospect-normalized-production-gate.md`
- Modify: `plans/README.md`
- Create: `tests/test_prospect_normalized_production_registration.py`

**Interfaces:**
- Produces marker-delimited JSON between `<!-- normalized-production-registration:start -->` and `<!-- normalized-production-registration:end -->`.
- Locks constants against `prospects.challenger_eval` before any scored run.

- [ ] **Step 1: Write the registration-lock test**

```python
import json
import re
from pathlib import Path

from prospects import challenger_eval
from prospects.realized_value_readiness import IDENTITY_POLICY


ROOT = Path(__file__).resolve().parents[1]


def _registration() -> dict:
    text = (ROOT / "plans/033-prospect-normalized-production-gate.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- normalized-production-registration:start -->\s*```json\s*(\{.*?\})\s*```\s*"
        r"<!-- normalized-production-registration:end -->",
        text,
        flags=re.S,
    )
    assert match
    return json.loads(match.group(1))


def test_registration_matches_code_and_cannot_authorize_a_public_claim():
    registration = _registration()
    assert registration["seed"] == challenger_eval.REGISTERED_SEED == 33021
    assert set(registration["forbidden_seeds"]) == challenger_eval.FORBIDDEN_SEEDS
    assert registration["same_level_min_other_peers"] == challenger_eval.SAME_LEVEL_MIN_PEERS == 25
    assert registration["role_season_min_other_peers"] == challenger_eval.ROLE_SEASON_MIN_PEERS == 250
    assert registration["minimum_exercised_coverage"] == challenger_eval.MIN_EXERCISED_COVERAGE == .90
    assert registration["public_claim_eligible"] is False
    assert registration["future_public_primary"] == "realized_value_regret"
    assert registration["research_primary"] == "ordinal_percentile_rank_mae"
    assert registration["hitters_and_pitchers_separate"] is True
    assert registration["v0_7_baseline"] == "excluded_unstable_prediction_contract"
    assert registration["combined_promotion_variant"] == "unavailable_until_prospective_archive_matures"
    assert registration["identity_policy"] == IDENTITY_POLICY
    assert registration["realized_value_readiness"]["required_ready"] is False
```

- [ ] **Step 2: Run the test and confirm registration is absent**

Run: `python -m pytest tests/test_prospect_normalized_production_registration.py -q`

Expected: FAIL because plan 033 does not exist.

- [ ] **Step 3: Write plan 033 with the exact immutable registration**

The prose must distinguish the current research endpoint from the blocked future public endpoint. The current look can decide whether to retain the challenger for further study; it cannot prove format-specific superiority. Include this exact JSON contract:

```json
{
  "protocol": "prospect-normalized-production-v1",
  "registered_at": "2026-07-20",
  "base_commit": "16df0aeeb4ac11a41c9ff279240b60a055aee3bf",
  "prospect_input_git_blob": "4ce139871ae456b5289c68dad1e15d8191ff7ef5",
  "aaa_statcast_git_blob": "37533ad816d86bcf392ccce75bb15f0b745f0f74",
  "incumbent_model_git_blob": "7a9b9d12ae0866ae3b460f3f02395a0e30949844",
  "live_rank_git_blob": "4ed3f2603b93e5ecf319f501519303f6ff7c18fa",
  "historical_cutoff": "cohort_season_completion",
  "realized_value_readiness": {
    "artifact": "data/validation/valucast_prospect_realized_value_readiness.json",
    "required_status": "blocked",
    "required_ready": false,
    "blocking_category": "qs"
  },
  "identity_policy": {
    "identity_key": "integer_mlbam_id",
    "cohort_key": "cohort_year:mlbam_id",
    "one_row_per_cohort_identity": true,
    "historical_role": "frozen_from_cohort_cutoff_row",
    "later_role_changes": "disclosed_never_relabels_prior_cohort",
    "same_cohort_role_conflict": "block_affected_cohort",
    "common_pool": "unique_mlbam_identities",
    "role_results": "frozen_cohort_role"
  },
  "variants": ["control", "normalized_production"],
  "rate_fields": {
    "hitter": ["iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip"],
    "pitcher": ["k_per_9", "bb_per_9", "k_bb_pct", "era", "whip"]
  },
  "same_level_min_other_peers": 25,
  "role_season_min_other_peers": 250,
  "minimum_exercised_coverage": 0.9,
  "research_primary": "ordinal_percentile_rank_mae",
  "future_public_primary": "realized_value_regret",
  "secondary_endpoints": ["partial_category_best_season_impact", "pairwise_concordance", "top_25_regret", "calibration", "coverage", "fold_stability"],
  "within_single_look_reports": ["under_19_full_season_minors", "hitter_position_if_audit_passes", "aaa_statcast_component_disagreement"],
  "hitter_position_audit": {
    "minimum_non_null_coverage_each_fold": 0.9,
    "allowed_raw_labels": ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "OF", "DH"],
    "reject_delimiters": ["/", ",", ";"]
  },
  "hitters_and_pitchers_separate": true,
  "minimum_completed_cohorts": 3,
  "minimum_unique_players": 250,
  "minimum_relative_improvement_pct": 5.0,
  "maximum_single_cohort_regression_pct": 5.0,
  "maximum_role_regression_pct": 5.0,
  "bootstrap": "paired_hierarchical_cohort_then_player",
  "bootstrap_resamples": 10000,
  "bootstrap_interval": "two_sided_95_percentile",
  "seed": 33021,
  "forbidden_seeds": [28013, 28017, 29001, 31013, 31017],
  "v0_7_baseline": "excluded_unstable_prediction_contract",
  "combined_promotion_variant": "unavailable_until_prospective_archive_matures",
  "public_claim_eligible": false,
  "production_importer": false
}
```

Also register these adjudication rules in prose:

- input-coverage failure stops before outcome scoring and leaves the look unspent;
- once the script scores any outcome, the look is spent even if the model errors later;
- identity mismatch raises and records no comparative result;
- under-19, position, and AAA outputs are reports inside this look, never extra candidate-selection looks;
- position output is omitted unless non-null, stable historical position semantics pass the pre-run audit;
- the 2020 fold is absent by contract, not as an analyst choice;
- every status remains `research_only` or a failure state and `claim_authorized` remains false.

- [ ] **Step 4: Register plan 033 in the plans index**

Add one row to `plans/README.md` with status `REGISTERED + UNSPENT`, noting that realized-value regret remains blocked by the Task-2 audit and the ordinal study is research-only.

- [ ] **Step 5: Run the registration test and verify pinned inputs**

Run: `python -m pytest tests/test_prospect_normalized_production_registration.py -q`

Expected: PASS.

Run: `git diff --quiet 16df0aee -- data/prospects/prospect_model_inputs.json data/models/valucast_aaa_statcast_features.json data/models/valucast_prospect_model.json data/models/valucast_prospect_rank_v1.json`

Expected: exit 0.

- [ ] **Step 6: Commit the registration before executing the look**

```powershell
git add plans/033-prospect-normalized-production-gate.md plans/README.md tests/test_prospect_normalized_production_registration.py
git commit -m "docs: register normalized production challenger"
```

---

### Task 6: Execute the registered look once and build the AAA component-disagreement report

**Files:**
- Modify: `prospects/challenger_eval.py`
- Modify: `tests/test_prospect_challenger_eval.py`
- Create: `scripts/run_prospect_normalized_production_gate.py`
- Create: `data/validation/valucast_prospect_normalized_production_gate.json`
- Modify: `plans/033-prospect-normalized-production-gate.md`
- Modify: `plans/README.md`

**Interfaces:**
- Produces `run_registered_replay(contract: dict, registration: dict) -> dict`.
- Produces `eligible_fold_years(contract: dict) -> list[int]`, using the existing maturity horizon and omitted-cohort contract.
- Produces `score_current_variants(contract: dict) -> tuple[dict, dict, dict]`, returning Control ranks, candidate ranks, and current-population coverage.
- Produces `build_aaa_disagreement(control_scores: dict, candidate_scores: dict, aaa: dict, current_rows: list[dict]) -> dict`.
- The script writes one sealed artifact and exits nonzero on pin, identity, coverage, or immutability failure.

- [ ] **Step 1: Write execution tests without running the real look**

Add fixture-based tests that monkeypatch the imported scorer so no real outcome replay occurs:

```python
import json

from prospects import challenger_eval
from prospects.challenger_eval import build_aaa_disagreement, run_registered_replay


def _fixture_registration() -> dict:
    return {
        "seed": 33021,
        "minimum_exercised_coverage": .90,
        "minimum_completed_cohorts": 3,
        "minimum_unique_players": 250,
        "minimum_relative_improvement_pct": 5.0,
        "maximum_single_cohort_regression_pct": 5.0,
        "maximum_role_regression_pct": 5.0,
        "bootstrap_resamples": 10_000,
        "public_claim_eligible": False,
    }


def _prepared(coverage: float) -> dict:
    return {
        "control_contract": {"variant": "control"},
        "candidate_contract": {"variant": "normalized_production"},
        "coverage": {
            "hitter": {"exercised_coverage": coverage},
            "pitcher": {"exercised_coverage": coverage},
        },
    }


def test_control_and_candidate_use_identical_fold_identities(monkeypatch):
    monkeypatch.setattr(challenger_eval, "eligible_fold_years", lambda _contract: [2018])
    monkeypatch.setattr(challenger_eval, "prepare_fold", lambda _contract, _year: _prepared(1.0))
    fold = {
        "scores": {("1", "hitter"): .8, ("2", "pitcher"): .7},
        "tiers": {("1", "hitter"): 1.0, ("2", "pitcher"): .5},
    }
    monkeypatch.setattr(challenger_eval, "_fold_board_scores", lambda _contract, _year: (fold, {}))
    report = run_registered_replay({}, _fixture_registration())
    assert report["identity_set_equal"] is True
    assert report["claim_authorized"] is False
    assert report["public_claim_eligible"] is False


def test_below_ninety_percent_coverage_stops_before_any_score(monkeypatch):
    calls = []
    monkeypatch.setattr(challenger_eval, "eligible_fold_years", lambda _contract: [2018])
    monkeypatch.setattr(challenger_eval, "prepare_fold", lambda _contract, _year: _prepared(.89))
    monkeypatch.setattr(challenger_eval, "_fold_board_scores", lambda *_args, **_kwargs: calls.append(1))
    report = run_registered_replay({}, _fixture_registration())
    assert report["status"] == "invalid_coverage"
    assert report["registered_look_spent"] is False
    assert calls == []


def _aaa_fixture():
    control = {"10": 1, "20": 2, "30": 3, "40": 4}
    candidate = {"10": 2, "20": 1, "30": 3, "40": 4}
    aaa = {
        "gates": {"min_pitcher_pitches": 250, "min_hitter_bip": 100},
        "hitters": {"10": {"n_pitches": 500, "n_bip": 120, "avg_ev": 90.0}},
        "pitchers": {
            "20": {"n_pitches": 400, "overall": {"whiff_pct": 30.0}, "pitch_types": {}},
            "30": {"n_pitches": 300, "overall": {"whiff_pct": 25.0}, "pitch_types": {}},
        },
    }
    current = [
        {"mlbam_id": 10, "role": "hitter", "level": "AAA"},
        {"mlbam_id": 20, "role": "pitcher", "level": "AAA", "is_starter": True},
        {"mlbam_id": 30, "role": "pitcher", "level": "AAA", "is_starter": False},
        {"mlbam_id": 40, "role": "hitter", "level": "AAA"},
    ]
    return control, candidate, aaa, current


def test_missing_aaa_players_are_excluded_never_zero_filled():
    report = build_aaa_disagreement(*_aaa_fixture())
    assert report["missing_statcast_count"] == 1
    assert all(row["components"] for group in report["groups"].values() for row in group["rows"])
    assert report["missing_ids"] == ["40"]
    assert "\"mlbam_id\": 40" not in json.dumps(report["groups"])


def test_pitcher_aaa_groups_do_not_mix_starters_and_relievers():
    report = build_aaa_disagreement(*_aaa_fixture())
    starter_ids = {row["mlbam_id"] for row in report["groups"]["pitcher_starter"]["rows"]}
    reliever_ids = {row["mlbam_id"] for row in report["groups"]["pitcher_reliever"]["rows"]}
    assert starter_ids == {20}
    assert reliever_ids == {30}
    assert starter_ids.isdisjoint(reliever_ids)
```

- [ ] **Step 2: Implement the one-look replay by reusing existing proof machinery**

For each eligible fold and role:

1. call `prepare_fold` and stop before scoring if either role is below 90%;
2. pass the fold-filtered Control and candidate contracts separately into `prospects.rank_backtest._fold_board_scores`;
3. assert exact score-key equality;
4. deterministically rank each role by descending score then MLBAM id;
5. build one plan-032 `build_cohort` per fold/role, using candidate as the internal `valucast` side and Control as the anonymous comparator;
6. call `prospects.competition_benchmark.build_track` separately for hitters and pitchers with criteria `3` cohorts, `250` unique players, `.90` coverage, `5%` improvement/regression caps, `top_k=25`, seed `33021`, and `10_000` resamples;
7. rename result labels from `valucast`/`competitor` to `normalized_production`/`control` in the private validation artifact;
8. force top-level and role-level `claim_authorized: false` and `public_claim_eligible: false`, regardless of statistical status.

The ordinal tier is the registered research primary. Keep the existing best-season partial-impact estimate secondary and disclose that it uses only the available categories. Do not calculate realized-value regret while Task 2 is blocked.

- [ ] **Step 3: Add the in-look subset and component reports**

- Under-19 report: filter the already-scored common pool to `age < 19` and full-season affiliated levels; report the same ordinal error only, with no independent verdict.
- Position report: first audit non-null coverage and within-player consistency. Emit `status: "omitted_failed_position_semantics"` unless the audit passes; do not coerce `DH`, `OF`, or multi-position strings into invented positions.
- Current score preparation: call `normalize_rows` separately on historical rows and the combined current hitter/pitcher rows; remove unavailable current identities from both variants; call `prospects.model.build_shadow_model` on Control and candidate contracts with `now=f"{contract['current']['fetched_date']}T23:59:59+00:00"`; read `valucast_prospect_rank` from each result; and require exact identity equality. These ranks are model-component research context, never a live Rank-v1 replacement.
- AAA report: intersect current AAA rows, Control ranks, candidate ranks, and the existing measured AAA artifact by MLBAM id. Report raw measured fields separately: hitters `whiff_pct`, `chase_pct`, `gb_pct`, `avg_ev`, `max_ev`, `hardhit_pct`, `avg_la`; pitchers `whiff_pct`, `csw_pct`, `zone_pct`, `chase_pct`, `gb_pct` plus per-pitch-type measured fields. Preserve `n_pitches`, hitter `n_bip`, pitch-type `n`, and the artifact’s qualification gates as reliability context. Do not average components into Stuff, Skill, or a percentage-match score. Split pitcher rows by the current factual `is_starter` field. Strong measured pitch traits do not imply starter volume, health, availability, or future MLB innings.
- Snapshot interpretation: promotion and demotion remain distinct dated observations; do not infer direction, transaction date, reason, or pre/post split unless two sealed observations establish ordering. The AAA report reads the existing measured artifact by hash and never copies missing components as zero.

- [ ] **Step 4: Implement the pin-checked one-shot script**

The runner must:

```python
EXPECTED_GIT_BLOBS = {
    "data/prospects/prospect_model_inputs.json": "4ce139871ae456b5289c68dad1e15d8191ff7ef5",
    "data/models/valucast_aaa_statcast_features.json": "37533ad816d86bcf392ccce75bb15f0b745f0f74",
    "data/models/valucast_prospect_model.json": "7a9b9d12ae0866ae3b460f3f02395a0e30949844",
    "data/models/valucast_prospect_rank_v1.json": "4ed3f2603b93e5ecf319f501519303f6ff7c18fa",
}
```

Verify each with `git hash-object`, validate that the sealed Task-2 readiness artifact remains `blocked` with `realized_value_regret_ready: false` because QS is missing, refuse an existing non-identical output artifact, load plan 033’s marker JSON, call `run_registered_replay`, attach `build_aaa_disagreement`, seal the JSON, and write only `data/validation/valucast_prospect_normalized_production_gate.json`. It must not accept a seed override or variant override.

- [ ] **Step 5: Run all fixture tests before spending the look**

Run: `python -m pytest tests/test_prospect_challenger_eval.py tests/test_prospect_normalized_production_registration.py tests/test_competition_proof.py -q`

Expected: PASS with no real output artifact created or changed.

- [ ] **Step 6: Execute exactly once**

Run: `python scripts/run_prospect_normalized_production_gate.py`

Expected: one sealed validation artifact, `registered_look_spent: true`, exact Control/candidate identity equality, per-fold/per-role coverage diagnostics, separate hitter and pitcher research results, and `claim_authorized: false`. Do not rerun with another seed or altered threshold.

- [ ] **Step 7: Record the result without changing the registration**

Append a dated “Result” section to plan 033 and update its index status to `SPENT — RESEARCH ONLY`. Record wins, losses, coverage, intervals, subset omissions, and AAA missingness. Do not edit the frozen JSON registration block.

- [ ] **Step 8: Commit the spent look atomically**

```powershell
git add prospects/challenger_eval.py tests/test_prospect_challenger_eval.py scripts/run_prospect_normalized_production_gate.py data/validation/valucast_prospect_normalized_production_gate.json plans/033-prospect-normalized-production-gate.md plans/README.md
git commit -m "research: run normalized production challenger"
```

---

### Task 7: Prove production isolation and finish the branch

**Files:**
- Modify: `tests/test_prospect_challenger_eval.py`
- Modify: `docs/superpowers/specs/2026-07-20-prospect-proof-foundation-v2-design.md`

**Interfaces:**
- Consumes every Task 1–6 output.
- Produces no new runtime or served artifact.

- [ ] **Step 1: Add the production-import isolation test**

```python
from pathlib import Path


def test_challenger_outputs_are_not_imported_by_production_decisions():
    root = Path(__file__).resolve().parents[1]
    forbidden = (
        "valucast_prospect_realized_value_readiness.json",
        "valucast_prospect_normalized_production_gate.json",
        "prospects.challenger_eval",
    )
    production_paths = [
        root / "app.py",
        root / "prospects/rank_v1.py",
        root / "prospects/availability.py",
        root / "prospects/cross_role_shadow.py",
        root / "scripts/build_valucast_buys.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in production_paths)
    for token in forbidden:
        assert token not in text
```

- [ ] **Step 2: Verify frozen flags and served artifacts**

Run: `git diff 16df0aee -- prospects/model.py prospects/rank_v1.py prospects/availability.py prospects/cross_role_shadow.py app.py`

Expected: no output.

Run: `git diff --quiet 16df0aee -- data/models/valucast_prospect_model.json data/models/valucast_prospect_rank_v1.json`

Expected: exit 0.

Run: `rg -n "PITCHER_STALE_PEDIGREE_DECAY_ENABLED =|PITCHER_OUTCOME_ROLE_SPLIT_ENABLED =|PITCHER_PER_GROUP_SHRINK_ENABLED =|LEVEL_TRANSLATION_FITTED_ENABLED =|PITCHER_STRIKE_PCT_ENABLED =" prospects/model.py`

Expected: every flag remains `False`.

- [ ] **Step 3: Run focused validation, then the full suite**

Run: `python -m pytest tests/test_prospect_model_contract.py tests/test_prospect_realized_value_readiness.py tests/test_prospect_challenger_eval.py tests/test_milb_observation_archive.py tests/test_daily_workflow_wiring.py tests/test_prospect_normalized_production_registration.py tests/test_competition_proof.py -q`

Expected: PASS.

Run: `python -m pytest -q`

Expected: PASS with no failures.

- [ ] **Step 4: Mark the design implementation status honestly**

Add a short implementation record to the approved design containing commit ids and these states:

- docs contract: shipped on branch;
- readiness: blocked on missing pitcher QS and exact prospective replay;
- fold-local evaluator: research-only;
- observation archive: wired, awaiting/passed CI shakedown as applicable;
- normalized challenger: spent research result or still unspent if Task 6 stopped before scoring;
- Combined/promotion variant: not built;
- public superiority: not authorized;
- model freeze and failed-decay flag: preserved.

- [ ] **Step 5: Commit the isolation proof and implementation record**

```powershell
git add tests/test_prospect_challenger_eval.py docs/superpowers/specs/2026-07-20-prospect-proof-foundation-v2-design.md
git commit -m "test: prove prospect challenger isolation"
```

- [ ] **Step 6: Push for review without deploying**

Run: `git push origin codex/prospect-proof-foundation-v2`

Expected: push succeeds. Do not dispatch `deploy.yml` or the daily refresh workflow.

## Explicitly deferred by data gates

- Do not build the Combined normalized-production-plus-promotion variant until the prospective MiLB archive contains dated transitions meeting a separately registered sample/cohort floor.
- Do not build a format-specific realized-value scorer until the readiness audit has direct 7x7 category coverage, including QS, and exact replay requirements pass.
- Do not promote v0.7 to a baseline without a separate pre-registration contract proving a stable identical-population ranking prediction.
- Do not add a proprietary Hitter Skill+ or Pitcher Skill+ metric in this plan.
- Do not alter any live surface because of the research result, even if the result is favorable.
