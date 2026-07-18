# Prospect Transition Publication Veto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the atomic daily public refresh when a newly activated thin-sample calibration rule causes a material prospect value cliff while the underlying model score is stable.

**Architecture:** Add one pure prior/current continuity check to `quality/valucast_governor.py` and reuse one archive-selection helper from both governor build paths. Keep every score unchanged; the existing daily validator becomes fatal only when the exact continuity check is blocked.

**Tech Stack:** Python 3.14, pytest, existing ValuCast quality-governor and public-snapshot modules.

## Global Constraints

- Preserve Prospect Rank v1 scoring, availability thresholds, public values/ranks, format ranks, pitcher caps, Role Watch, buys, movers, and pitcher publication decisions.
- Reuse `web.buy_score.STEP_THRESHOLD` (`6.0`); do not add a second material-step dial.
- Match rows only on `(mlbam_id, role)` and compare only the latest dated archive strictly earlier than the current payload date.
- Cold start passes with `sample_ready: false`; a malformed selected baseline raises instead of silently skipping.
- Keep the model freeze, Steamer live source, failed pitcher-decay flag, and paused League Connect unchanged.
- Do not deploy or dispatch workflows from this branch.

---

### Task 1: Pure transition-continuity check

**Files:**
- Modify: `quality/valucast_governor.py`
- Test: `tests/test_valucast_quality_governor.py`

**Interfaces:**
- Produces: `_prospect_transition_continuity(current: dict | None, previous: dict | None) -> dict`
- Produces: `load_previous_prospect_rank(current: dict, archive_dir: Path | str = PROSPECT_RANK_ARCHIVE_DIR) -> dict | None`
- Consumes: existing `_check`, `_date_part`, `_identity_key`, `_components`, `_availability_component`, `_factual_context_component`, and `web.buy_score.STEP_THRESHOLD`.

- [ ] **Step 1: Write failing positive and negative-control tests**

Add a `_transition_rank_row(...)` helper that creates the exact minimal archive row shape. Test:

```python
def test_transition_continuity_blocks_new_material_thin_sample_cliff():
    prior = _transition_rank_payload("2026-07-17", [_transition_rank_row()])
    current = _transition_rank_payload(
        "2026-07-18",
        [_transition_rank_row(level="AA", status="thin_current_sample", score=20.0,
                              model_score=49.8, bucket_adjustment=-7.0,
                              bucket="thin_current_sample_confidence")],
    )
    check = _prospect_transition_continuity(current, prior)
    assert check["status"] == "blocked"
    assert check["metrics"]["incident_count"] == 1
```

Add separate tests proving: same-level pitcher `starter_role` transition blocks; no new thin rule passes; `abs(model_score_delta) > 1.0` passes; exactly `-STEP_THRESHOLD` bucket movement passes; continuing thin state passes; non-declining final score passes; `previous=None` passes with `sample_ready is False`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_valucast_quality_governor.py -k transition_continuity
```

Expected: collection/import failure because `_prospect_transition_continuity` does not exist.

- [ ] **Step 3: Implement the smallest pure check**

In `quality/valucast_governor.py`:

```python
from web.buy_score import STEP_THRESHOLD

PROSPECT_RANK_ARCHIVE_DIR = (
    ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
)
PROSPECT_TRANSITION_MODEL_DELTA_LIMIT = 1.0
PROSPECT_TRANSITION_SAMPLE_LIMIT = 12
PROSPECT_THIN_BUCKET = "thin_current_sample_confidence"
```

The pure check indexes prior rows by `_identity_key`, counts every matched row, and emits an incident only when all registered predicates are true. Its sample contains names, identity, role, transition fields, old/new ranks, active bucket rules, and rounded model/bucket/final deltas. Add it to `board_checks` with `SURFACE_PROSPECTS`, and add optional `previous_prospect_rank` to `evaluate_quality_governor`.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_valucast_quality_governor.py -k transition_continuity
python -m pytest -q tests/test_valucast_quality_governor.py
```

Expected: all selected tests pass.

---

### Task 2: Strict earlier-archive selection and both build paths

**Files:**
- Modify: `quality/valucast_governor.py`
- Modify: `scripts/build_public_dynasty_snapshot.py`
- Test: `tests/test_valucast_quality_governor.py`
- Test: `tests/test_public_dynasty_snapshot.py`

**Interfaces:**
- Consumes: `load_previous_prospect_rank(...)` from Task 1.
- Produces: `build_snapshot(..., previous_prospect_rank: dict | None = None) -> dict`.

- [ ] **Step 1: Write failing archive-selection tests**

Test that a directory containing `2026-07-17.json` and `2026-07-18.json` selects July 17 for a July 18 current payload. Test that malformed July 17 JSON raises `ValueError`. Add a snapshot integration test that monkeypatches `evaluate_quality_governor` and asserts `previous_prospect_rank` is forwarded unchanged.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest -q tests/test_valucast_quality_governor.py -k previous_prospect_rank
python -m pytest -q tests/test_public_dynasty_snapshot.py -k previous_prospect_rank
```

Expected: missing helper/argument failures.

- [ ] **Step 3: Implement shared selection and wiring**

`load_previous_prospect_rank` must sort only `*.json` filenames whose parsed date is strictly less than the current payload date, read the newest candidate once, validate that it is a dict with a list `board`, and raise `ValueError` for malformed content. Use it in:

```python
evaluate_quality_governor(..., previous_prospect_rank=previous_prospect_rank)
```

from both `build_public_dynasty_snapshot.main()` and `run_quality_governor(...)`. The pure `build_snapshot` receives the optional payload explicitly so unit tests do not read the repository archive implicitly.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_valucast_quality_governor.py tests/test_public_dynasty_snapshot.py
```

Expected: both modules pass.

---

### Task 3: Exact fatal validator guard

**Files:**
- Modify: `scripts/validate_valucast_quality_governor.py`
- Test: `tests/test_validate_valucast_quality_governor.py`

**Interfaces:**
- Consumes: governor `checks` entries with `id`, `status`, `message`, and `metrics`.
- Produces: one validator problem only when `id == "prospect_transition_continuity"` and `status == "blocked"`.

- [ ] **Step 1: Write failing validator tests**

Add one test whose only blocked Prospects check is `prospect_transition_continuity` and assert validation fails with the affected player name. Keep the existing pitcher-composition Prospects-only test as the negative control and assert it still returns no problems.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest -q tests/test_validate_valucast_quality_governor.py
```

Expected: the new continuity-veto test fails because Prospects-only blocks are currently advisory.

- [ ] **Step 3: Implement one exact-ID guard**

After shape validation, inspect `payload["checks"]` and append a problem for the blocked continuity check. Do not add Prospects to `gating_surfaces` and do not make any other Prospects-only check fatal.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_validate_valucast_quality_governor.py
```

Expected: all validator tests pass.

---

### Task 4: Historical replay and regression gate

**Files:**
- Test: `tests/test_valucast_quality_governor.py`

**Interfaces:**
- Consumes: committed `data/prediction_archive/valucast_prospect_rank_v1/*.json` and `_prospect_transition_continuity`.

- [ ] **Step 1: Add the Briceno regression test**

Load the July 17 and July 18 committed archives, run the pure check, and assert Josue Briceno reports level `A -> AA`, model delta `-0.09`, bucket delta `-17.57`, final delta `-19.66`, and blocked status.

- [ ] **Step 2: Run the 36-vintage replay**

Use the pure check across every consecutive committed archive and assert/report the registered aggregate: 617 matched transitions evaluated, 15 incidents, 3 hitters, and 12 pitchers. This is a verification command, not a new production script.

- [ ] **Step 3: Run focused and full verification**

Run:

```powershell
python -m pytest -q tests/test_valucast_quality_governor.py tests/test_public_dynasty_snapshot.py tests/test_validate_valucast_quality_governor.py tests/test_public_data_refresh.py tests/test_daily_workflow_wiring.py
python scripts/validate_valucast_quality_governor.py
python scripts/validate_public_dynasty_snapshot.py
python -m pytest -q
git diff --check
```

Expected: all commands pass. The current committed July 18 governor may remain valid because generated production artifacts are not rebuilt or committed on this branch.

- [ ] **Step 4: Commit and publish for review**

Commit the implementation separately from this plan, push `codex/prospect-transition-publication-gate`, and open a draft PR. Do not deploy or dispatch a workflow.
