# Prospect Translation Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a no-outcome readiness artifact for Plan 034 that validates identity, raw/model-field separation, fold boundaries, and AAA evidence coverage while refusing outer scoring before the registered trigger.

**Architecture:** Add one pure readiness module and one CLI. The module reads the existing factual contract and Plan 034 registration, reports only schema/coverage facts, and contains no outcome scorer or model importer.

**Tech Stack:** Python 3 stdlib, pytest.

## Global Constraints

- Plan 033 is spent and must never run again.
- Plan 034 cannot score an outer cohort before `2027-01-01` and a reviewed implementation amendment.
- Identity is `mlbam_id:role`; cohort identity is `cohort_year:mlbam_id:role`.
- Missing AAA evidence is reported, never zero-filled.
- The artifact is research-only and cannot feed ranks, values, caps, Role Watch, publication, or claims.

---

### Task 1: Plan 034 no-outcome readiness builder

**Files:**
- Create: `prospects/challenger_readiness.py`
- Create: `tests/test_prospect_challenger_readiness.py`

**Interfaces:**
- Produces: `build_plan034_readiness(contract: dict, registration: dict, aaa_features: dict | None, *, as_of: str) -> dict`
- Produces: `assert_no_outer_scoring(report: dict) -> None`

- [ ] **Step 1: Write failing trigger and identity tests**

```python
def test_plan034_readiness_refuses_outer_scoring_before_trigger():
    report = build_plan034_readiness(_contract(), _registration(), None, as_of="2026-08-03")
    assert report["status"] == "waiting_for_vintage"
    assert report["outer_scoring_authorized"] is False
    assert "not_before:2027-01-01" in report["blockers"]
    assert_no_outer_scoring(report)

def test_plan034_readiness_blocks_duplicate_cohort_role_identity():
    contract = _contract()
    contract["historical"]["rows"].append(dict(contract["historical"]["rows"][0]))
    report = build_plan034_readiness(contract, _registration(), None, as_of="2026-08-03")
    assert report["identity_audit"]["duplicates"] == ["2019:1:hitter"]
    assert report["outer_scoring_authorized"] is False
```

- [ ] **Step 2: Run and confirm import failure**

Run: `python -m pytest tests/test_prospect_challenger_readiness.py -q`

Expected: FAIL because `prospects.challenger_readiness` does not exist.

- [ ] **Step 3: Implement the pure builder**

The module must define this frozen boundary:

```python
RAW_GUARD_FIELDS = frozenset({
    "age", "level", "plate_appearances", "innings_pitched",
    "games_played", "games_started", "sample_season",
})
MODEL_FEATURE_NAMESPACE = "fold_local_transformed_features"
NOT_BEFORE = "2027-01-01"
```

`build_plan034_readiness` must:

1. validate unique cohort-role identities;
2. count hitter and pitcher rows separately;
3. report AAA row count and per-field missing counts from `aaa_features["rows"]`;
4. set `missing_value_policy` to `preserve_null_never_zero_fill`;
5. set `raw_guard_fields` and `model_feature_namespace` as separate outputs;
6. set every serving/claim flag false; and
7. set `outer_scoring_authorized` false unless the date trigger, season/horizon flags, and reviewed amendment are all true. The first implementation has no amendment input, so it always remains false.

`assert_no_outer_scoring` raises `RuntimeError` if `outer_scoring_authorized` is true.

- [ ] **Step 4: Add AAA missingness and two-way tests**

```python
def test_plan034_readiness_preserves_two_way_roles_and_null_aaa_fields():
    contract = _contract(two_way=True)
    aaa = {"rows": [{"mlbam_id": 1, "role": "hitter", "avg_exit_velocity": None}]}
    report = build_plan034_readiness(contract, _registration(), aaa, as_of="2026-08-03")
    assert report["identity_audit"]["role_counts"] == {"hitter": 1, "pitcher": 1}
    assert report["aaa_statcast"]["missing_by_field"]["avg_exit_velocity"] == 1
    assert report["aaa_statcast"]["zero_filled_count"] == 0
```

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_prospect_challenger_readiness.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add prospects/challenger_readiness.py tests/test_prospect_challenger_readiness.py
git commit -m "feat: add Plan 034 no-outcome readiness gate"
```

### Task 2: Readiness CLI and sealed artifact

**Files:**
- Create: `scripts/build_prospect_challenger_readiness.py`
- Create: `data/validation/prospect_challenger_readiness.json`
- Modify: `tests/test_prospect_challenger_readiness.py`

**Interfaces:**
- Consumes: `data/prospects/prospect_model_inputs.json`, `plans/034-post-2026-prospect-challenger-epoch.md`, and optional `data/models/valucast_aaa_statcast_features.json`
- Produces: `data/validation/prospect_challenger_readiness.json`

- [ ] **Step 1: Write the failing CLI test**

```python
def test_readiness_cli_writes_research_only_artifact(tmp_path):
    result = subprocess.run([
        sys.executable, "scripts/build_prospect_challenger_readiness.py",
        "--output", str(tmp_path / "readiness.json"),
        "--as-of", "2026-08-03",
    ], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads((tmp_path / "readiness.json").read_text())
    assert payload["outer_scoring_authorized"] is False
    assert payload["source_policy"]["feeds_rank_or_value"] is False
```

- [ ] **Step 2: Run and confirm missing script failure**

Run: `python -m pytest tests/test_prospect_challenger_readiness.py::test_readiness_cli_writes_research_only_artifact -q`

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement the CLI using stdlib only**

Use `argparse`, `json`, `re`, and `Path`. Extract the JSON between `post-2026-challenger-registration` markers, call `build_plan034_readiness`, and write with a temporary file followed by `os.replace`.

- [ ] **Step 4: Build the committed artifact**

Run:

`python scripts/build_prospect_challenger_readiness.py --as-of 2026-08-03`

Expected: status `waiting_for_vintage`, `outer_scoring_authorized=false`, no outcome metrics.

- [ ] **Step 5: Commit**

```powershell
git add scripts/build_prospect_challenger_readiness.py tests/test_prospect_challenger_readiness.py data/validation/prospect_challenger_readiness.json
git commit -m "data: record prospect challenger readiness"
```
