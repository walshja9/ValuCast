# Prospect Model Independence and Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce prohibited research inputs at the factual contract boundary, prove Rank v1 mutation-invariance to context-only evidence, and assemble a precise Fable review packet.

**Architecture:** Strengthen the existing `validate_factual_contract` trust boundary with an exact-key denylist, then add one end-to-end rank invariance test and one new-research readiness test. Avoid a new policy framework.

**Tech Stack:** Python 3 stdlib, pytest, Git.

## Global Constraints

- Consensus, scouting/FV/tool grades, competitor outputs, market values, and current ValuCast order may be displayed or evaluated only after a prediction is frozen.
- Draft/signing facts remain permitted factual evidence.
- No broad substring rules that can reject legitimate baseball fields.
- No live score, rank, value, cap, Role Watch, pitcher veto, or publication change.

---

### Task 1: Prohibited-field validation at the factual boundary

**Files:**
- Modify: `prospects/input_contract.py`
- Create: `tests/test_prospect_research_independence.py`

**Interfaces:**
- Consumes: `validate_factual_contract(payload: dict) -> list[str]`
- Produces: exact-key row validation for historical and current feature rows

- [ ] **Step 1: Write the failing denylist test**

```python
@pytest.mark.parametrize("field", [
    "consensus_rank", "source_ranks", "fv", "tool_grades",
    "competitor_score", "market_value", "dynasty_value", "valucast_rank",
])
def test_factual_contract_rejects_prohibited_model_fields(field):
    payload = _factual_contract()
    payload["historical"]["rows"][0][field] = 1
    assert f"historical.rows[0].{field} is prohibited" in validate_factual_contract(payload)
```

- [ ] **Step 2: Run and confirm no rejection**

Run: `python -m pytest tests/test_prospect_research_independence.py::test_factual_contract_rejects_prohibited_model_fields -q`

Expected: FAIL because the validator currently checks policy flags only.

- [ ] **Step 3: Add an exact denylist and one shared row walker**

```python
PROHIBITED_MODEL_FIELDS = frozenset({
    "consensus_rank", "source_ranks", "public_source_consensus",
    "fv", "tool_grades", "competitor_score", "competitor_rank",
    "market_value", "dynasty_value", "valucast_rank",
})

def _prohibited_row_fields(rows: list[dict], label: str) -> list[str]:
    return [
        f"{label}[{index}].{field} is prohibited"
        for index, row in enumerate(rows)
        if isinstance(row, dict)
        for field in sorted(PROHIBITED_MODEL_FIELDS & row.keys())
    ]
```

Call it for `historical.rows`, `current.hitters`, and `current.pitchers` after type checks. Do not reject `draft_pick_number`, `signing_bonus`, `position`, `availability_status`, or model output fields outside the factual contract.

- [ ] **Step 4: Run contract and independence tests**

Run:

`python -m pytest tests/test_prospect_research_independence.py tests/test_stage1_contract.py tests/test_prospect_model.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add prospects/input_contract.py tests/test_prospect_research_independence.py
git commit -m "test: enforce prospect research input independence"
```

### Task 2: Rank v1 and readiness mutation-invariance

**Files:**
- Modify: `tests/test_prospect_research_independence.py`
- Test helper imports: `tests/test_prospect_rank_v1.py`

- [ ] **Step 1: Add Rank v1 mutation test**

Build Rank v1 twice from the existing minimal fixtures. In the second run mutate only context-only public ranks, scouting annotations, and legacy dynasty values. Compare:

```python
assert [(row["mlbam_id"], row["score"], row["rank"]) for row in first["board"]] == [
    (row["mlbam_id"], row["score"], row["rank"]) for row in second["board"]
]
```

- [ ] **Step 2: Add readiness rejection test**

```python
def test_new_challenger_readiness_rejects_prohibited_feature_rows():
    contract = _factual_contract()
    contract["historical"]["rows"][0]["source_ranks"] = {"field": 1}
    with pytest.raises(ValueError, match="source_ranks"):
        build_plan034_readiness(contract, _registration(), None, as_of="2026-08-03")
```

- [ ] **Step 3: Run the focused tests**

Run:

`python -m pytest tests/test_prospect_research_independence.py tests/test_prospect_rank_v1.py -q`

Expected: all pass; no production code changes beyond the factual-boundary validator.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_prospect_research_independence.py
git commit -m "test: prove prospect ranking independence"
```

### Task 3: Review packet and Fable prompt

**Files:**
- Create: `docs/review-packets/2026-08-03-prospect-evidence-improvement-fable.md`

- [ ] **Step 1: Record exact review scope**

The packet must list:

- base commit and head commit;
- the five workstreams and touched files;
- serving hashes before/after;
- focused and full test commands/results;
- proof that the pitcher result artifact is absent;
- proof that Plan 034 and C1/C2 looks remain unspent;
- known non-actions: no live scoring, no publication, no workflow dispatch; and
- the requested Fable adversarial questions.

- [ ] **Step 2: Write the Fable prompt verbatim**

```text
Review <base>..<head> as a senior sabermetrician, statistician, model-risk reviewer, and production engineer. Findings only; do not edit. Reproduce the investment queue and availability provenance, verify no score/rank/value change, attack Plan 034's no-outcome gate for any path that could score early, verify C1/C2 exactly match the frozen registration, and review the pitcher challenger chronology, provenance, pitch geometry, folds, fallback, target alignment, gate math, and absence of a serving importer or result artifact. Mutate consensus, scouting/FV, competitor, market, and current-ValuCast-rank fields to test score invariance. Treat any look-spending path, leakage, silent zero fill, identity collapse, or production reachability as P0. Report P1/P2 issues, unnecessary complexity, exact file:line evidence, commands run, and a checked-clean register. Do not run the registered pitcher outer look or any Plan 034/C1/C2 outcome scorer.
```

- [ ] **Step 3: Commit**

```powershell
git add docs/review-packets/2026-08-03-prospect-evidence-improvement-fable.md
git commit -m "docs: prepare prospect evidence review packet"
```

### Task 4: Final verification

**Files:**
- Verify all changed files

- [ ] **Step 1: Run focused suites**

```powershell
python -m pytest tests/test_prospect_coverage_audit.py tests/test_prospect_availability.py tests/test_prospect_challenger_readiness.py tests/test_prospect_research_independence.py tests/test_pitching_statcast.py tests/test_pitcher_skill_challenger.py tests/test_mlb_pitcher_skill_challenger_runner.py tests/test_mlb_pitcher_skill_registration.py -q
```

- [ ] **Step 2: Run the full suite**

Run: `python -m pytest -q`

Expected: all tests pass, excluding only already-declared skips.

- [ ] **Step 3: Verify freeze and artifact boundaries**

```powershell
git diff --check origin/master...HEAD
Test-Path data/validation/mlb_pitcher_skill_challenger_result.json
rg -n "pitcher_skill_challenger|mlb_pitcher_skill_challenger" app.py prospects/rank_v1.py templates web .github
```

Expected: clean diff; result path `False`; no serving or workflow importer.

- [ ] **Step 4: Push the review branch**

Outside the `12:20-13:15 UTC` no-push window:

`git push origin codex/prospect-evidence-improvement`
