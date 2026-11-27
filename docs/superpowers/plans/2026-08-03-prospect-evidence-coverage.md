# Prospect Evidence Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic missing-investment and availability-evidence diagnostics without changing any score, rank, value, or penalty.

**Architecture:** Extend the two existing audit producers: `prospects.coverage_audit` owns investment completeness and `prospects.availability` owns status/sample provenance. Add fields only to their research artifacts and validate the new shapes at the existing validators.

**Tech Stack:** Python 3, stdlib JSON/datetime, pytest.

## Global Constraints

- Prospect Rank v1 remains frozen at bucket calibration `0.3.2`.
- Do not change investment weights, missing-value fallbacks, availability discounts, precedence, ranks, values, or publication.
- Missing evidence remains missing; never infer a signing amount.
- External ranks remain display/evaluation context only.

---

### Task 1: Missing-investment evidence queue

**Files:**
- Modify: `prospects/coverage_audit.py`
- Modify: `scripts/validate_prospect_coverage_audit.py`
- Test: `tests/test_prospect_coverage_audit.py`

**Interfaces:**
- Consumes: `build_prospect_coverage_audit(rank_payload: dict, investment_evidence: dict | None) -> dict`
- Produces: `investment_context.missing_evidence_queue: list[dict]`, keyed by `identity_key = "<mlbam_id>:<role>"`

- [ ] **Step 1: Write the failing queue test**

```python
def test_coverage_audit_emits_deterministic_missing_evidence_queue():
    payload = build_prospect_coverage_audit(_rank_payload([
        _row(2, "prospect_model_v0_6"),
        _row(1, "prospect_model_v0_6", role="pitcher"),
    ]))
    queue = payload["investment_context"]["missing_evidence_queue"]
    assert [row["identity_key"] for row in queue] == ["10001:pitcher", "10002:hitter"]
    assert all(row["verified_amount"] is None for row in queue)
    assert all(row["changes_ranks_or_values"] is False for row in queue)
```

- [ ] **Step 2: Run the test and confirm the missing key failure**

Run: `python -m pytest tests/test_prospect_coverage_audit.py::test_coverage_audit_emits_deterministic_missing_evidence_queue -q`

Expected: FAIL with `KeyError: 'missing_evidence_queue'`.

- [ ] **Step 3: Add the smallest queue builder**

```python
def _missing_investment_queue(rows: list[dict], evidence_by_mlbam: dict[int, dict]) -> list[dict]:
    queue = []
    for row in rows:
        mlbam_id = _clean_int(row.get("mlbam_id"))
        role = str(row.get("role") or "")
        if mlbam_id is None or role not in {"hitter", "pitcher"}:
            continue
        if _factual_investment(row) is not None or mlbam_id in evidence_by_mlbam:
            continue
        queue.append({
            "identity_key": f"{mlbam_id}:{role}",
            "mlbam_id": mlbam_id,
            "role": role,
            "name": row.get("name"),
            "rank": row.get("rank"),
            "acquisition_type": _context(row).get("acquisition_type"),
            "draft_pick_number": _context(row).get("draft_pick_number"),
            "source_status": "missing_verified_evidence",
            "reason": "no_source_backed_investment_fact",
            "verified_amount": None,
            "changes_ranks_or_values": False,
        })
    return sorted(queue, key=lambda row: row["identity_key"])
```

Add the result under `investment_context` and bump `AUDIT_VERSION` from `0.4.0` to `0.5.0`.

- [ ] **Step 4: Require the queue in the validator**

```python
queue = investment_context.get("missing_evidence_queue")
if not isinstance(queue, list):
    problems.append("investment_context.missing_evidence_queue must be a list")
elif any(row.get("changes_ranks_or_values") is not False for row in queue):
    problems.append("investment_context.missing_evidence_queue must be non-serving")
```

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_prospect_coverage_audit.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add prospects/coverage_audit.py scripts/validate_prospect_coverage_audit.py tests/test_prospect_coverage_audit.py
git commit -m "feat: expose missing prospect investment evidence"
```

### Task 2: Availability provenance and unknown-vs-negative state

**Files:**
- Modify: `prospects/availability.py`
- Modify: `scripts/validate_prospect_availability.py`
- Test: `tests/test_prospect_availability.py`

**Interfaces:**
- Consumes: `_profile(key, rows, generated_at, override, il_lookup, active_roster_ids) -> dict`
- Produces: `evidence_state` and `evidence_provenance` on every profile

- [ ] **Step 1: Write failing provenance tests**

```python
def test_availability_records_selected_row_and_evidence_state():
    payload = build_prospect_availability(_input_contract())
    row = next(item for item in payload["profiles"] if item["mlbam_id"] == 20)
    assert row["evidence_state"] == "known_available"
    assert row["evidence_provenance"] == {
        "generated_at": "2026-06-13T12:00:00+00:00",
        "status_source": "current_sample",
        "selected_level": "A+",
        "selected_sample": 21.667,
        "selected_sample_unit": "IP",
        "selected_sample_fetched_date": "2026-06-13",
        "active_row_count": 2,
        "adjustment_reason": "none",
    }

def test_availability_distinguishes_unknown_from_negative():
    contract = _input_contract()
    contract["current"]["hitters"][0]["sample_fetched_date"] = None
    payload = build_prospect_availability(contract)
    row = next(item for item in payload["profiles"] if item["mlbam_id"] == 10)
    assert row["evidence_state"] == "unknown"
```

- [ ] **Step 2: Run both tests and confirm missing-field failures**

Run: `python -m pytest tests/test_prospect_availability.py -k "records_selected_row or distinguishes_unknown" -q`

Expected: FAIL because `evidence_state` is absent.

- [ ] **Step 3: Add provenance without changing score logic**

Add after `risk_basis` is calculated:

```python
status_source = (
    "manual_override" if override_present else
    "active_mlb_roster" if active_mlb_roster else
    "official_mlb_transactions" if il_status else
    "upstream_factual_status" if upstream_status else
    "current_sample"
)
known_timestamp = bool(_latest_sample_date(active_rows) or override or il_status)
evidence_state = (
    "unknown" if not known_timestamp else
    "known_available" if risk_basis == "none" else
    "known_limited" if risk_basis in {"current_sample_size", "sample_staleness", "official_mlb_rehab"} else
    "known_unavailable"
)
```

Return `evidence_state` plus an `evidence_provenance` object containing the generated timestamp, selected row fields, source, active-row count, and `risk_basis` as `adjustment_reason`. Do not alter `risk_discount`, `risk_basis`, `signals`, or `status`.

- [ ] **Step 4: Validate the new fields**

```python
if row.get("evidence_state") not in {
    "unknown", "known_available", "known_limited", "known_unavailable"
}:
    problems.append(f"profiles[{index}].evidence_state is invalid")
if not isinstance(row.get("evidence_provenance"), dict):
    problems.append(f"profiles[{index}].evidence_provenance must be an object")
```

- [ ] **Step 5: Prove scores are byte-equivalent**

Add a test that removes only `evidence_state` and `evidence_provenance` from the new payload and compares every legacy profile field to a payload built from the same fixture before the change. Then run:

`python -m pytest tests/test_prospect_availability.py -q`

Expected: all tests pass and existing discount assertions remain unchanged.

- [ ] **Step 6: Commit**

```powershell
git add prospects/availability.py scripts/validate_prospect_availability.py tests/test_prospect_availability.py
git commit -m "feat: audit prospect availability evidence"
```

### Task 3: Rebuild research artifacts and verify no serving change

**Files:**
- Modify: `data/models/valucast_prospect_coverage_audit.json`
- Modify: `data/models/valucast_prospect_availability.json`

- [ ] **Step 1: Capture serving hashes**

Run:

```powershell
git hash-object data/models/valucast_prospect_model.json
git hash-object data/models/valucast_prospect_rank_v1.json
git hash-object data/models/valucast_universal_prospect_model.json
```

Record the three hashes in the command log.

- [ ] **Step 2: Rebuild only the two audit artifacts**

Run:

```powershell
python scripts/build_prospect_coverage_audit.py
python scripts/build_prospect_availability.py
python scripts/validate_prospect_coverage_audit.py
python scripts/validate_prospect_availability.py
```

Expected: both validators exit 0.

- [ ] **Step 3: Recheck serving hashes**

Run the same three `git hash-object` commands. Expected: exact equality with Step 1.

- [ ] **Step 4: Commit**

```powershell
git add data/models/valucast_prospect_coverage_audit.json data/models/valucast_prospect_availability.json
git commit -m "data: refresh prospect evidence audits"
```
