# Public Snapshot Movers Readiness Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task.

**Goal:** Make the public snapshot's embedded quality governor evaluate the already-built native Movers artifact without changing prospect scoring or publication thresholds.

**Architecture:** Thread the existing Movers JSON payload through the public snapshot builder's established dependency-injection boundary. The standalone governor remains unchanged; the embedded evaluation receives the same artifact that the daily build creates before the public snapshot.

**Tech Stack:** Python 3, pytest, committed JSON artifacts.

## Constraints

- Do not alter prospect scores, score weights, role-shape thresholds, holds, or governor policy.
- Do not modify `prospects/rank_v1.py` or `quality/valucast_governor.py`.
- Preserve atomic publication: a missing or invalid Movers artifact must remain an honest red Movers check.
- Add no abstraction or dependency.
- Do not commit or push without user direction.

### Task 1: Add a failing dependency-forwarding regression

**Files:**

- Modify: `tests/test_public_dynasty_snapshot.py`
- Reference: `tests/test_public_dynasty_snapshot.py:669`

- [ ] Add this test next to the existing previous-rank forwarding regression:

```python
def test_build_snapshot_forwards_movers_to_governor(monkeypatch):
    movers = {
        "generated_at": "2026-08-10T12:00:00+00:00",
        "source_policy": {"mode": "native_daily_history"},
        "validation": {"ready_for_live_consumers": True},
    }
    captured = {}

    def fake_quality_governor(*args, **kwargs):
        captured["movers"] = kwargs.get("movers")
        return {
            "governor_version": "test",
            "ready_for_public_snapshot": True,
            "ready_for_buys_promotion": False,
            "blockers": [],
            "buy_blockers": [],
            "surface_readiness": {
                "dynasty": True,
                "prospects": True,
                "buys": False,
            },
            "surface_blockers": {
                "dynasty": [],
                "prospects": [],
                "buys": [],
            },
        }

    monkeypatch.setattr(snapshot_builder, "evaluate_quality_governor", fake_quality_governor)

    build_snapshot(
        _rank_payload(),
        mlb_layer=_ready_mlb_payload(),
        buy_signals=_buy_payload(),
        movers=movers,
    )

    assert captured["movers"] is movers
```

- [ ] Run the regression in isolation:

```powershell
python -m pytest -q tests/test_public_dynasty_snapshot.py::test_build_snapshot_forwards_movers_to_governor
```

Expected result: fail with `TypeError: build_snapshot() got an unexpected keyword argument 'movers'`.

### Task 2: Forward the existing Movers artifact

**Files:**

- Modify: `scripts/build_public_dynasty_snapshot.py:33`
- Modify: `scripts/build_public_dynasty_snapshot.py:1167`
- Modify: `scripts/build_public_dynasty_snapshot.py:1423`
- Modify: `scripts/build_public_dynasty_snapshot.py:1518`

**Interface:** `build_snapshot(..., movers: dict | None = None, ...) -> dict`

- [ ] Add the canonical artifact path beside the existing buy paths:

```python
MOVERS_PATH = ROOT / "data" / "models" / "valucast_prospect_movers.json"
```

- [ ] Add the optional `movers` dependency to `build_snapshot` immediately after `buy_review`:

```python
    movers: dict | None = None,
```

- [ ] Pass that dependency into the embedded governor call:

```python
        movers=movers,
```

- [ ] In `main()`, load the artifact without weakening missing-file behavior:

```python
    movers = _load_json(MOVERS_PATH) if MOVERS_PATH.exists() else None
```

- [ ] Pass it to the snapshot build:

```python
        movers=movers,
```

- [ ] Re-run the isolated regression:

```powershell
python -m pytest -q tests/test_public_dynasty_snapshot.py::test_build_snapshot_forwards_movers_to_governor
```

Expected result: `1 passed`.

### Task 3: Verify the repaired boundary without publishing artifacts

**Files:**

- Test: `tests/test_public_dynasty_snapshot.py`
- Test: `tests/test_valucast_quality_governor.py`
- Test: `tests/test_movers.py`

- [ ] Run the focused snapshot, governor, and Movers suite:

```powershell
python -m pytest -q tests/test_public_dynasty_snapshot.py tests/test_valucast_quality_governor.py tests/test_movers.py
```

Expected result: all selected tests pass.

- [ ] Evaluate the current checked-in artifacts in memory using the normal snapshot builder inputs. Assert that the embedded governor reports `ready_for_movers is True` and records Movers date `2026-08-10`. Do not call `write_snapshot()`.

- [ ] Run the complete repository suite:

```powershell
python -m pytest -q
```

Expected result: all tests pass.

- [ ] Review `git diff --check`, `git diff --stat`, and `git status --short`. Confirm that only this plan, the regression test, and the snapshot-builder wiring changed.

### Task 4: Preserve the prospect evidence gate

**Files:**

- No source changes.
- Evidence: `data/models/valucast_prospect_cross_role_shadow.json`
- Evidence: `data/models/valucast_prospect_outcome_backtest.json`
- Evidence: `data/models/valucast_prospect_forward_validation.json`

- [ ] Confirm the artifacts still forbid live score changes and manual board adjustments while forward evidence is collecting.
- [ ] Report the current top-25 and top-50 pitcher concentration as an intentionally unresolved publication blocker.
- [ ] Do not relax the governor threshold or add a pitcher haircut to make the status green.

### Task 5: Treat navigation consolidation as a separate design decision

**Files:**

- No UI changes in this plan.

- [ ] Complete the existing-surface design review before changing navigation.
- [ ] Get design approval under the repository's brainstorming workflow before implementation.
