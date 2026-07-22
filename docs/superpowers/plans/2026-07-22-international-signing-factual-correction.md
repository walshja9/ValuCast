# International Signing Factual Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply 13 verified international signing bonuses only to Prospect Rank v1's existing factual-investment component and reproduce the approved board preview without changing either trained prospect model.

**Architecture:** `run_prospect_rank_v1` loads the committed evidence artifact and passes it explicitly to `build_prospect_rank_v1`. A small rank-local overlay returns a copied input contract with verified bonuses filled only where missing; the canonical contract and the already-built v0.6 and universal/dynasty artifacts remain untouched.

**Tech Stack:** Python standard library, pytest, existing Prospect Rank v1 and coverage-audit builders.

## Global Constraints

- No new dependency or new model.
- The core v0.6 and universal model artifacts remain byte-identical.
- No weights, formulas, availability adjustments, governors, pitcher controls, holds, or publication rules change.
- Evidence is keyed by MLBAM ID and limited to `international_amateur_free_agent` hitters.
- Invalid, duplicate, unmatched, or conflicting evidence fails closed; an identical existing value is a no-op.
- Generated rank/public artifacts are not committed or published before Claude review, Codex final review, and explicit user approval.

---

### Task 1: Rank-local verified investment overlay

**Files:**
- Modify: `prospects/rank_v1.py`
- Modify: `tests/test_prospect_rank_v1.py`

**Interfaces:**
- Consumes: `investment_evidence: dict | None` with `rows[]` containing `mlbam_id`, `acquisition_type`, `signing_bonus`, `source_name`, `source_url`, and `source_checked_at`.
- Produces: `_with_verified_investment_facts(input_contract: dict, investment_evidence: dict | None) -> tuple[dict, dict]` and an optional `investment_evidence` argument on `build_prospect_rank_v1`.

- [ ] **Step 1: Write the failing overlay tests**

Add focused tests that prove:

```python
corrected, audit = _with_verified_investment_facts(
    _input_contract(),
    _investment_evidence(mlbam_id=1, signing_bonus=950_000),
)
assert corrected["current"]["hitters"][0]["signing_bonus"] == 950_000
assert audit == {"artifact": "valucast_international_signing_facts", "as_of": "2026-07-22", "applied_count": 1, "idempotent_count": 0}
assert _input_contract()["current"]["hitters"][0].get("signing_bonus") is None
```

Also assert that duplicate IDs, unsupported acquisition types, missing source fields, unmatched IDs, and conflicting existing bonuses raise `ValueError`, while an identical existing bonus increments `idempotent_count` and does not fail.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_prospect_rank_v1.py -k "verified_investment" -q
```

Expected: collection or assertion failure because `_with_verified_investment_facts` and the new argument do not exist.

- [ ] **Step 3: Implement the minimum overlay**

In `prospects/rank_v1.py`, use shallow dictionary/list copies rather than mutating the canonical contract:

```python
def _with_verified_investment_facts(input_contract, investment_evidence):
    if investment_evidence is None:
        return input_contract, {"artifact": None, "as_of": None, "applied_count": 0, "idempotent_count": 0}
    # Validate policy and rows, index unique MLBAM IDs, copy current hitters,
    # fill only missing signing_bonus values, and reject mismatches.
```

Call it once at the start of `build_prospect_rank_v1`, use the returned rank-local contract for `_input_lookup`, and expose the audit fields under `input_artifacts`. Do not pass the overlay to either model builder.

- [ ] **Step 4: Run focused and full rank tests**

```powershell
python -m pytest tests/test_prospect_rank_v1.py -k "verified_investment" -q
python -m pytest tests/test_prospect_rank_v1.py -q
```

Expected: all selected tests pass, then the complete rank test file passes.

- [ ] **Step 5: Commit Task 1**

```powershell
git add prospects/rank_v1.py tests/test_prospect_rank_v1.py
git commit -m "Apply verified signing facts to prospect rank"
```

### Task 2: Production runner, policy, and coverage honesty

**Files:**
- Modify: `prospects/rank_v1.py`
- Modify: `data/prospects/raw/international_signing_facts.json`
- Modify: `prospects/coverage_audit.py`
- Modify: `tests/test_prospect_rank_v1.py`
- Modify: `tests/test_prospect_coverage_audit.py`
- Modify: `scripts/validate_prospect_coverage_audit.py`
- Modify: `docs/audit-2026-07-22-international-investment-evidence.md`

**Interfaces:**
- Consumes: `INVESTMENT_EVIDENCE_PATH` in the normal rank runner.
- Produces: rank artifact provenance that says the evidence feeds the direct rank score but not the v0.6 or universal model.

- [ ] **Step 1: Write failing runner and coverage tests**

Add a temporary-path runner test:

```python
result = run_prospect_rank_v1(
    prospect_universe_path=universe_path,
    dynasty_layer_path=layer_path,
    prospect_model_path=model_path,
    input_contract_path=contract_path,
    investment_evidence_path=evidence_path,
    availability_path=None,
    mlb_roster_status_path=roster_path,
    artifact_path=artifact_path,
    archive_dir=archive_dir,
)
payload = json.loads(artifact_path.read_text())
assert payload["input_artifacts"]["investment_evidence_applied_count"] == 1
```

Update the coverage test to expect corrected rank rows in ordinary scoring-input coverage and no remaining `resolved_scoring_gaps` for applied evidence.

- [ ] **Step 2: Run the tests and verify RED**

```powershell
python -m pytest tests/test_prospect_rank_v1.py tests/test_prospect_coverage_audit.py -k "investment" -q
```

Expected: failure because the runner does not yet load the evidence path and the audit still describes evidence as observational-only.

- [ ] **Step 3: Wire the evidence into the runner and make policy truthful**

Add `INVESTMENT_EVIDENCE_PATH`, load it in `run_prospect_rank_v1`, and pass it to `build_prospect_rank_v1`. Bump `RANK_VERSION` from `0.2.8` to `0.2.9`.

Change the evidence policy to:

```json
{
  "kind": "factual_rank_input",
  "feeds_rank_score": true,
  "feeds_v06_model": false,
  "feeds_universal_model": false,
  "changes_ranks_or_values": true,
  "permitted_use": "prospect_rank_v1_factual_investment_context_only"
}
```

Update coverage-audit copy and documentation so scoring coverage reflects the resulting rank artifact and no text claims the evidence remains observational-only.

- [ ] **Step 4: Run focused tests**

```powershell
python -m pytest tests/test_prospect_rank_v1.py tests/test_prospect_coverage_audit.py -k "investment" -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add prospects/rank_v1.py prospects/coverage_audit.py tests/test_prospect_rank_v1.py tests/test_prospect_coverage_audit.py data/prospects/raw/international_signing_facts.json docs/audit-2026-07-22-international-investment-evidence.md
git commit -m "Wire international bonuses into factual rank context"
```

### Task 3: Exact preview, regression, and review packet

**Files:**
- Modify: `docs/superpowers/specs/2026-07-22-international-signing-factual-correction-design.md`
- Create: `docs/review-2026-07-22-international-signing-factual-correction.md`
- Do not modify: `data/models/valucast_prospect_model.json`
- Do not modify: `data/models/valucast_universal_prospect_model.json`

**Interfaces:**
- Consumes: the implemented rank runner and frozen current artifacts.
- Produces: a reviewer-facing record of exact board movement, test evidence, and the no-publication boundary.

- [ ] **Step 1: Generate the candidate rank only in an ignored temporary directory**

Run the rank builder with `artifact_path` and `archive_dir` under `tmp_investment_candidate/`. Compare its board against the committed board and assert the approved 13-player rank/value mapping:

```python
expected = {
    "Franklin Arias": (7, 55.95), "Luis Lara": (8, 54.50),
    "Josue De Paula": (11, 51.85), "Jesus Made": (13, 50.26),
    "Esmerlyn Valdez": (17, 47.76), "Angel Genao": (21, 45.70),
    "Leo De Vries": (22, 45.53), "Hector Rodriguez": (23, 45.31),
    "Juneiker Caceres": (24, 45.00), "Nelson Rada": (27, 44.37),
    "Pedro Ramirez": (32, 42.70), "Lazaro Montes": (38, 41.72),
    "Leo Bernal": (40, 40.79),
}
```

Also assert zero unrelated value changes, unchanged top-50 membership, and unchanged top-25/top-50 role composition.

- [ ] **Step 2: Verify model artifacts remain byte-identical**

```powershell
git diff --exit-code -- data/models/valucast_prospect_model.json data/models/valucast_universal_prospect_model.json
```

Expected: exit 0 with no output.

- [ ] **Step 3: Run full verification**

```powershell
python -m pytest tests/test_prospect_rank_v1.py tests/test_prospect_coverage_audit.py tests/test_valucast_quality_governor.py -q
python -m pytest -q
git diff --check
git status --short
```

Expected: all tests pass; no whitespace errors; only intended source, test, policy, and review files differ.

- [ ] **Step 4: Write the review packet**

Record the exact diff scope, RED/GREEN commands, preview mapping, unchanged model hashes, governance boundary, and explicit statement that no generated public artifact or deployment was produced.

- [ ] **Step 5: Commit Task 3**

```powershell
git add docs/superpowers/specs/2026-07-22-international-signing-factual-correction-design.md docs/review-2026-07-22-international-signing-factual-correction.md
git commit -m "Document signing correction verification"
```

### Task 4: Universal-model feasibility assessment

**Files:**
- Create: `docs/audit-2026-07-22-international-bonus-universal-feasibility.md`
- Do not modify: `prospects/universal.py`
- Do not modify: any model or rank artifact

**Interfaces:**
- Consumes: current universal feature contract, historical-input coverage, Plan 034, and the completed direct-only correction evidence.
- Produces: a read-only recommendation stating whether an acquisition-aware challenger is currently executable or what data blocks it.

- [ ] **Step 1: Audit the real historical coverage**

Count historical hitter rows with signing bonuses by acquisition type, cohort, and outcome maturity. Verify whether international signing type is reconstructable rather than inferred from a missing draft pick.

- [ ] **Step 2: Audit the current universal feature path**

Trace `signing_bonus_log` and `signing_bonus_known` through training, current scoring, and walk-forward validation. Document why the existing Rule 4 relationship cannot be claimed for international signees without acquisition-type history.

- [ ] **Step 3: Decide readiness without an outcome look**

Use only coverage and reconstructability checks. Do not run Plan 034 outer cohorts or fit candidate outcome models. Recommend either `ready_for_registered_challenger_design` or `blocked_on_historical_international_signing_facts`.

- [ ] **Step 4: Write and verify the audit**

```powershell
rg -n "TBD|TODO|public superiority|automatic promotion" docs/audit-2026-07-22-international-bonus-universal-feasibility.md
git diff --check
```

Expected: no placeholders, no public superiority claim, and no automatic-promotion language.

- [ ] **Step 5: Commit Task 4**

```powershell
git add docs/audit-2026-07-22-international-bonus-universal-feasibility.md
git commit -m "Assess universal international bonus readiness"
```

## Final Review Boundary

Stop after Task 4. Provide the branch, commits, full test evidence, exact preview, and review packet for Claude. Address review findings, rerun verification, then perform Codex's independent final review. Do not merge, regenerate committed public artifacts, dispatch a workflow, deploy, or publish without a new explicit user instruction.
