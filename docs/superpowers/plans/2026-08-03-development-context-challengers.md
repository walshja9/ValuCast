# Development Context Challengers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the exact registered `development_density` and `position_value_x` feature definitions in readiness-only form without scoring outcomes.

**Architecture:** Put the two pure feature functions beside the Plan 034 readiness code so one research trust boundary owns all unserved inputs. Extend the readiness artifact with deterministic feature coverage and hashes; do not call `train_role`, `_walk_forward`, or any scorer.

**Tech Stack:** Python 3 stdlib, pytest.

## Global Constraints

- Feature definitions, ordering, missing rules, and position values must match `docs/registration-2026-07-29-outcome-feature-challengers.md` exactly.
- No confirmatory outcome look is authorized.
- No new variants, injury proxy substitution, defensive grades, or athleticism fields.
- Results remain research-only and score-inert.

---

### Task 1: Frozen feature functions

**Files:**
- Modify: `prospects/challenger_readiness.py`
- Modify: `tests/test_prospect_challenger_readiness.py`

**Interfaces:**
- Produces: `development_density_features(row: dict, role: str) -> tuple[float, ...]`
- Produces: `position_value_features(row: dict) -> tuple[float, float, float]`

- [ ] **Step 1: Write exact-definition tests**

```python
def test_development_density_matches_registration():
    row = {"plate_appearances": 500, "games_played": 100, "innings_pitched": 150}
    assert development_density_features(row, "hitter") == (5.0, 100 / 132)
    assert development_density_features(row, "pitcher") == (1.5,)
    assert development_density_features({}, "hitter") == (0.0, 0.0)

def test_position_value_x_matches_registration():
    row = {"position": "SS", "level": "AA", "age": 20.5}
    assert position_value_features(row) == (0.95, 1.9, 0.0)
    assert position_value_features({"position": "OF", "level": "X", "age": 20}) == (0.5, 0.0, 0.0)
```

- [ ] **Step 2: Run and confirm missing-function failures**

Run: `python -m pytest tests/test_prospect_challenger_readiness.py -k "development_density or position_value" -q`

Expected: FAIL because the functions are not defined.

- [ ] **Step 3: Implement the frozen definitions**

```python
POSITION_VALUE = {
    "C": 1.0, "SS": 0.95, "CF": 0.80, "2B": 0.65, "3B": 0.55,
    "RF": 0.40, "LF": 0.30, "1B": 0.15, "DH": 0.0,
}

def development_density_features(row: dict, role: str) -> tuple[float, ...]:
    games = _number(row.get("games_played")) or 0.0
    if role == "hitter":
        pa = _number(row.get("plate_appearances")) or 0.0
        return (pa / games if games > 0 else 0.0, min(1.0, games / 132.0))
    if role == "pitcher":
        ip = _number(row.get("innings_pitched")) or 0.0
        return (ip / games if games > 0 else 0.0,)
    raise ValueError("role must be hitter or pitcher")
```

For `position_value_features`, import `LEVEL_CODE` and `EXPECTED_AGE` from `prospects.model`, use the registered `0.5` unknown-position fallback, and emit `(p, p * youth, p * level)`.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_prospect_challenger_readiness.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add prospects/challenger_readiness.py tests/test_prospect_challenger_readiness.py
git commit -m "feat: implement registered development context features"
```

### Task 2: Readiness-only feature coverage

**Files:**
- Modify: `prospects/challenger_readiness.py`
- Modify: `scripts/build_prospect_challenger_readiness.py`
- Modify: `tests/test_prospect_challenger_readiness.py`
- Modify: `data/validation/prospect_challenger_readiness.json`

**Interfaces:**
- Extends: `build_plan034_readiness(...)`
- Produces: `registered_context_challengers` with definition hash, role counts, feature widths, and `confirmatory_scoring_authorized=false`

- [ ] **Step 1: Write the failing readiness test**

```python
def test_registered_context_challengers_are_implemented_but_unspent():
    report = build_plan034_readiness(_contract(), _registration(), None, as_of="2026-08-03")
    challengers = report["registered_context_challengers"]
    assert challengers["development_density"]["feature_width"] == {"hitter": 2, "pitcher": 1}
    assert challengers["position_value_x"]["feature_width"] == {"hitter": 3}
    assert challengers["confirmatory_scoring_authorized"] is False
    assert challengers["registered_look_spent"] is False
```

- [ ] **Step 2: Run and confirm missing-section failure**

Run: `python -m pytest tests/test_prospect_challenger_readiness.py::test_registered_context_challengers_are_implemented_but_unspent -q`

Expected: FAIL with `KeyError: 'registered_context_challengers'`.

- [ ] **Step 3: Add only deterministic coverage**

For every historical row, call the registered feature functions and count role rows/feature widths. Hash the JSON-serialized constant definitions with SHA-256. Do not read `outcome`, call `_walk_forward`, or emit MAE/gate values.

- [ ] **Step 4: Prove outcome mutation invariance**

```python
def test_context_readiness_is_invariant_to_outcome_mutation():
    first = build_plan034_readiness(_contract(), _registration(), None, as_of="2026-08-03")
    changed = _contract()
    for row in changed["historical"]["rows"]:
        row["outcome"] = "star"
    second = build_plan034_readiness(changed, _registration(), None, as_of="2026-08-03")
    assert first["registered_context_challengers"] == second["registered_context_challengers"]
```

- [ ] **Step 5: Rebuild and test**

Run:

```powershell
python -m pytest tests/test_prospect_challenger_readiness.py -q
python scripts/build_prospect_challenger_readiness.py --as-of 2026-08-03
```

Expected: tests pass; artifact says implemented, unspent, unauthorized.

- [ ] **Step 6: Commit**

```powershell
git add prospects/challenger_readiness.py scripts/build_prospect_challenger_readiness.py tests/test_prospect_challenger_readiness.py data/validation/prospect_challenger_readiness.json
git commit -m "data: audit registered context challenger readiness"
```
