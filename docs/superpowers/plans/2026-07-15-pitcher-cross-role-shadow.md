# Pitcher Cross-Role Shadow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the DD prospect adapter and replace its misleading evidence role with an honest, observe-only ValuCast cross-role shadow.

**Architecture:** Delete the DD-only branch from the existing prospect adapter and forward/outcome chains. Add one pure artifact builder that joins the frozen rank backtest, registered power study, current board, and measured AAA Statcast artifact without feeding any score path.

**Tech Stack:** Python 3.11+, JSON artifacts, pytest, GitHub Actions.

## Global Constraints

- Do not modify prospect scoring or rank ordering.
- Do not change `PITCHER_STALE_PEDIGREE_DECAY_ENABLED=False`.
- Do not hand-tune the board to seven pitchers.
- Missing or underpowered evidence must stay blocked/collecting.
- Use UTF-8 writes through Python/application code or Edit/apply-patch paths.

---

### Task 1: Retire the DD prospect adapter

**Files:**
- Modify: `prospects/adapters.py`
- Modify: `prospects/forward_shadow.py`
- Modify: `tests/test_prospect_league_adapters.py`
- Modify: `tests/test_prospect_league_ranks.py`
- Modify: `tests/test_prospect_forward_shadow.py`
- Modify: `.github/workflows/prospect-shadow.yml`
- Modify: `.github/workflows/daily-public-data.yml`
- Delete: `prospects/adapter_backtest.py`, `prospects/dd_adapter.py`, `prospects/dd_lens_feed.py`
- Delete: `scripts/build_prospect_adapter_backtest.py`, `scripts/build_dd_7x7_prospect_adapter.py`
- Delete: `tests/test_prospect_adapter_backtest.py`, `tests/test_dd_7x7_prospect_adapter.py`, `tests/test_dd_prospect_lens_feed.py`
- Delete: DD adapter/lens model, export, and archive JSON files.

**Interfaces:**
- Preserve: `adapt_categories(...)`, `build_adapter_artifact(...)`, public `ops_7x7` and `roto_5x5` presets.
- Change: `forward_shadow.build_report(...)` and `run_pipeline(...)` no longer accept or emit DD adapter paths/data.

- [ ] **Step 1: Write failing retirement assertions**

```python
def test_adapter_artifact_contains_only_public_presets():
    payload = build_adapter_artifact(_universal())
    assert set(payload["presets"]) == {"ops_7x7", "roto_5x5"}

def test_report_has_no_dd_adapter_contract(tmp_path):
    report = build_report(run_dir, dynasty_dir, index_dir)
    assert not any("dd_adapter" in key for key in report["summary"])
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_prospect_league_adapters.py tests/test_prospect_forward_shadow.py tests/test_public_data_refresh.py`

Expected: failures showing the `dd_7x7` preset and DD forward-shadow fields still exist.

- [ ] **Step 3: Delete DD-only code and simplify callers**

Remove the DD preset, imports, parameters, comparisons, readiness checks, manifest outputs, workflow tests/pathspecs, and tracked DD artifacts. Keep the generic adapter API unchanged.

- [ ] **Step 4: Run GREEN**

Run the RED command again; expect all selected tests to pass.

- [ ] **Step 5: Commit**

`git add` only Task 1 files and commit `Retire DD prospect adapter`.

### Task 2: Add the cross-role shadow artifact

**Files:**
- Create: `prospects/cross_role_shadow.py`
- Create: `scripts/build_prospect_cross_role_shadow.py`
- Create: `scripts/validate_prospect_cross_role_shadow.py`
- Create: `tests/test_prospect_cross_role_shadow.py`
- Modify: `scripts/run_daily_public_build.py`
- Modify: `scripts/validate_public_data_freshness.py`
- Modify: `tests/test_public_data_refresh.py`
- Modify: `.github/workflows/daily-public-data.yml`
- Create: `data/models/valucast_prospect_cross_role_shadow.json`

**Interfaces:**
- Produce: `build_cross_role_shadow(rank_backtest: dict, power_check: dict, rank_payload: dict, aaa_statcast: dict) -> dict`.
- Produce: `run_cross_role_shadow(...) -> dict` with atomic UTF-8 JSON write.
- Artifact statuses: `blocked`, `collecting`, `review_ready`.

- [ ] **Step 1: Write failing gate tests**

```python
def test_underpowered_pitcher_heavy_board_stays_collecting():
    payload = build_cross_role_shadow(rank_backtest(), power_check(0.015), board(10, 17), aaa(3))
    assert payload["status"] == "collecting"
    assert payload["checks"]["historical_absolute_competence"]["passed"] is True
    assert payload["checks"]["cross_role_change_power"]["passed"] is False
    assert payload["checks"]["current_role_shape"]["passed"] is False
    assert payload["checks"]["aaa_pitch_evidence_coverage"]["passed"] is False
    assert payload["source_policy"]["feeds_public_rank"] is False
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_prospect_cross_role_shadow.py`

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement the pure builder**

Implement only artifact loading, board integrity checks, the `0.60` absolute floor, `0.70` power floor, existing 7/30% shape limits, 60% coverage among AAA-eligible top-25 pitchers, total top-25 evidence breadth, 1-5 source consensus sensitivity, empirical AAA metric percentiles, and raw pitch-type evidence.

- [ ] **Step 4: Wire daily build, validation, freshness, and commit path**

Order the builder after `build_aaa_statcast_features.py` and before the unified outcome report. Add its validator and freshness fixture.

- [ ] **Step 5: Run GREEN and build the real artifact**

Run:

```powershell
python -m pytest -q tests/test_prospect_cross_role_shadow.py tests/test_public_data_refresh.py
python scripts/build_prospect_cross_role_shadow.py
python scripts/validate_prospect_cross_role_shadow.py
```

Expected: tests pass; real artifact reports historical absolute pass, power fail, current shape fail, eligible AAA coverage `1.00`, total top-25 evidence breadth `0.30`, overall `collecting`.

- [ ] **Step 6: Commit**

Commit Task 2 as `Add prospect cross-role shadow`.

### Task 3: Replace DD evidence and correct public language

**Files:**
- Modify: `prospects/outcome_backtest.py`
- Modify: `scripts/validate_prospect_outcome_backtest.py`
- Modify: `tests/test_prospect_outcome_backtest.py`
- Modify: `quality/valucast_governor.py`
- Modify: `tests/test_valucast_quality_governor.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_public_dynasty_snapshot.py`
- Modify: `tests/test_validate_valucast_quality_governor.py`
- Modify: `data/models/valucast_prospect_outcome_backtest.json`
- Modify: `data/models/valucast_quality_governor.json`
- Modify: `data/public/public_dynasty_snapshot.json`

**Interfaces:**
- `build_outcome_backtest(...)` consumes `cross_role_shadow` instead of `adapter_backtest`.
- Governor check id stays stable; blocked-state message becomes `Pitcher representation exceeds the publication range. Rankings remain visible, but the current evidence cannot justify either a cross-role score adjustment or relaxing the publication gate.`

- [ ] **Step 1: Write failing outcome/advisory tests**

Assert `evidence.cross_role_shadow` exists, `adapter_fixed_horizon` does not, the validator requires the new key, and blocked prospect surfaces carry the new calibration language.

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_prospect_outcome_backtest.py tests/test_valucast_quality_governor.py tests/test_app.py tests/test_public_dynasty_snapshot.py tests/test_validate_valucast_quality_governor.py`

Expected: failures on old adapter evidence and old pitcher-heavy message.

- [ ] **Step 3: Implement the minimal replacement**

Move the retired 20-point adapter evidence allocation to two honest 10-point checks: historical absolute competence and adequate cross-role change power. Keep forward evidence and all score-feed flags unchanged.

- [ ] **Step 4: Rebuild and validate artifacts**

Run:

```powershell
python scripts/build_prospect_outcome_backtest.py
python scripts/validate_prospect_outcome_backtest.py
python scripts/build_valucast_quality_governor.py
python scripts/validate_valucast_quality_governor.py
```

- [ ] **Step 5: Run GREEN and commit**

Run the RED command again, then commit `Replace DD evidence with cross-role shadow`.

### Task 4: Senior analytics validation and release gate

**Files:**
- Create: durable technical report through the report-building surface.
- Modify only generated artifacts proven necessary by the documented build commands.

- [ ] **Step 1: Recompute the headline values independently**

Verify current top-25/top-50 pitcher counts, consensus sensitivity, C0 cross-role concordance, maximum registered power, AAA coverage, and covered-player pitch metrics from raw artifact fields.

- [ ] **Step 2: Run focused verification**

```powershell
python -m pytest -q tests/test_prospect_cross_role_shadow.py tests/test_prospect_outcome_backtest.py tests/test_prospect_forward_shadow.py tests/test_prospect_league_adapters.py tests/test_prospect_league_ranks.py tests/test_valucast_quality_governor.py tests/test_app.py tests/test_public_data_refresh.py tests/test_public_dynasty_snapshot.py tests/test_validate_valucast_quality_governor.py
```

- [ ] **Step 3: Run full verification**

Run: `python -m pytest -q`

Expected: no regression beyond the baseline two failures; passing count must be reconciled for deleted/added tests.

- [ ] **Step 4: Verify scope**

Confirm no scoring diff in `prospects/model.py` or scoring portions of `prospects/rank_v1.py`, the decay flag remains false, no DD adapter runtime reference remains, and `git diff --check` passes.

- [ ] **Step 5: Build and validate the technical report**

Report the live diagnosis, retired DD surface, gate definitions, data-quality limitations, and exact reason the new shadow remains collecting.

- [ ] **Step 6: Stop before push**

Leave the verified commits on `codex/pitcher-cross-role-shadow`; do not push without explicit authorization and without checking that no daily-public-data run is in flight.
