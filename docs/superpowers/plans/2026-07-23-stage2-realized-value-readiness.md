# Stage 2 Realized-Value Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic research-only readiness artifact proving that the July 23 historical outcome store now supports all hitter and pitcher 7x7 categories while preserving the incumbent-target and prospective-replay blockers.

**Architecture:** Extend the existing pure readiness module with one additive audit that validates the committed QS sidecar, joins QS only in memory, and applies the incumbent category-coverage constants. Add one manual stdlib-only builder that writes one new artifact; leave the old audit, old artifact, model, inputs, ranks, values, and workflows untouched.

**Tech Stack:** Python 3, standard library (`argparse`, `hashlib`, `json`, `pathlib`), pytest, existing `prospects.model` coverage constants.

## Global Constraints

- Preserve `audit_realized_value_readiness(...)` behavior and keep `data/validation/valucast_prospect_realized_value_readiness.json` byte-identical.
- Keep `data/prospects/prospect_model_inputs.json`, `data/models/valucast_prospect_model.json`, and the QS sidecar byte-identical.
- Reuse `IMPACT_CATEGORIES`, `IMPACT_REFERENCE_MIN`, and `IMPACT_CATEGORY_COVERAGE`; do not create parallel coverage thresholds.
- Join QS only in memory; never repair or rewrite production inputs.
- Preserve the model freeze, failed-decay flag, and pitcher publication veto.
- Do not train, rebuild, rerun, promote, publish, deploy, wire workflows, or authorize claims.
- Add no dependency, package, abstraction framework, or generalized artifact utility.

---

### Task 1: Add the pure Stage 2 readiness audit

**Files:**
- Modify: `prospects/realized_value_readiness.py:1-224`
- Modify: `tests/test_prospect_realized_value_readiness.py:1-137`

**Interfaces:**
- Consumes: `contract: dict`, `model_artifact: dict`, validated-or-untrusted `qs_sidecar: dict`, and keyword-only `contract_sha256: str`.
- Produces: `audit_stage2_realized_value_readiness(...) -> dict` with deterministic `outcome_evidence`, `incumbent_impact_target`, `prospective_replay`, blockers, and `content_sha256`.
- Preserves: `audit_realized_value_readiness(...) -> dict` unchanged for all existing callers.

- [ ] **Step 1: Record the protected baseline**

Run:

```powershell
$files = @(
  "data/validation/valucast_prospect_realized_value_readiness.json",
  "data/prospects/prospect_model_inputs.json",
  "data/models/valucast_prospect_model.json",
  "data/validation/valucast_stage2_quality_starts.json"
)
$files | ForEach-Object { Get-FileHash -Algorithm SHA256 $_ }
python -m pytest tests/test_prospect_realized_value_readiness.py tests/test_stage2_quality_starts.py -q
```

Expected:

```text
The four SHA-256 values are recorded in the task notes.
11 passed
```

- [ ] **Step 2: Add the failing audit tests**

Add these imports and helpers to
`tests/test_prospect_realized_value_readiness.py`:

```python
import hashlib
import json

import pytest

from prospects.realized_value_readiness import (
    audit_realized_value_readiness,
    audit_stage2_realized_value_readiness,
)


def _canonical_hash(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _seal_sidecar(sidecar: dict) -> dict:
    sidecar["content_sha256"] = _canonical_hash(sidecar)
    return sidecar


def _sidecar(*, quality_starts: int = 12, games_started: int = 25) -> dict:
    return _seal_sidecar(
        {
            "schema": "valucast_stage2_quality_starts",
            "version": "1.0.0",
            "status": "ready",
            "input": {
                "path": "data/prospects/prospect_model_inputs.json",
                "sha256": "contract-hash",
                "cutoff_date": "2026-07-23",
            },
            "coverage": {},
            "validation": {"current_season_values_superseded": []},
            "rows": [
                {
                    "mlbam_id": 20,
                    "season": 2019,
                    "games_started": games_started,
                    "quality_starts": quality_starts,
                    "provenance": "derived_game_log",
                }
            ],
            "blockers": [],
        }
    )


def _stage2_report(
    contract: dict | None = None,
    sidecar: dict | None = None,
) -> dict:
    selected_contract = deepcopy(contract or _contract())
    selected_contract.setdefault("current", {})["fetched_date"] = "2026-07-23"
    return audit_stage2_realized_value_readiness(
        selected_contract,
        _model(),
        deepcopy(sidecar or _sidecar()),
        contract_sha256="contract-hash",
    )
```

Replace the original one-line readiness import with the grouped import above,
then append:

```python
def test_stage2_evidence_is_ready_without_overstating_overall_readiness():
    report = _stage2_report()

    assert report["outcome_evidence"]["status"] == "ready"
    assert report["outcome_evidence"][
        "retrospective_direct_7x7_evidence_ready"
    ] is True
    assert report["outcome_evidence"]["pitcher"]["active"] == [
        "so", "qs", "sv_hld", "era", "whip", "k_bb", "l"
    ]
    assert report["incumbent_impact_target"][
        "incumbent_direct_7x7_target_ready"
    ] is False
    assert report["prospective_replay"]["exact_prospective_replay_ready"] is False
    assert report["realized_value_regret_ready"] is False
    assert report["status"] == "blocked"
    assert report["blockers"] == [
        "impact_target_not_direct_7x7",
        "exact_prospective_replay_not_reconstructable",
    ]
    assert "missing_pitcher_category:qs" not in report["blockers"]


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("schema", "wrong", "qs_sidecar_schema_invalid"),
        ("version", "9.0.0", "qs_sidecar_version_unsupported"),
        ("status", "blocked", "qs_sidecar_status_not_ready"),
        ("content_sha256", "wrong", "qs_sidecar_content_sha256_mismatch"),
    ],
)
def test_stage2_sidecar_metadata_fails_closed(field, value, blocker):
    sidecar = _sidecar()
    sidecar[field] = value

    assert blocker in _stage2_report(sidecar=sidecar)["blockers"]


def test_stage2_sidecar_binding_fails_closed():
    wrong_hash = _sidecar()
    wrong_hash["input"]["sha256"] = "wrong"
    wrong_hash = _seal_sidecar(wrong_hash)
    wrong_cutoff = _sidecar()
    wrong_cutoff["input"]["cutoff_date"] = "2026-07-22"
    wrong_cutoff = _seal_sidecar(wrong_cutoff)
    wrong_path = _sidecar()
    wrong_path["input"]["path"] = "wrong.json"
    wrong_path = _seal_sidecar(wrong_path)
    malformed_input = _sidecar()
    malformed_input["input"] = []
    malformed_input = _seal_sidecar(malformed_input)

    assert "qs_sidecar_input_sha256_mismatch" in _stage2_report(
        sidecar=wrong_hash
    )["blockers"]
    assert "qs_sidecar_cutoff_mismatch" in _stage2_report(
        sidecar=wrong_cutoff
    )["blockers"]
    assert "qs_sidecar_input_path_mismatch" in _stage2_report(
        sidecar=wrong_path
    )["blockers"]
    assert "qs_sidecar_input_path_mismatch" in _stage2_report(
        sidecar=malformed_input
    )["blockers"]


def test_stage2_sidecar_identity_and_value_errors_fail_closed():
    missing = _sidecar()
    missing["rows"] = []
    missing = _seal_sidecar(missing)
    extra = _sidecar()
    extra["rows"].append(
        {
            "mlbam_id": 99,
            "season": 2019,
            "games_started": 1,
            "quality_starts": 0,
            "provenance": "derived_game_log",
        }
    )
    extra = _seal_sidecar(extra)
    duplicate = _sidecar()
    duplicate["rows"].append(deepcopy(duplicate["rows"][0]))
    duplicate = _seal_sidecar(duplicate)
    invalid = _sidecar(quality_starts=26, games_started=25)

    assert "qs_sidecar_missing_identity:20:2019" in _stage2_report(
        sidecar=missing
    )["blockers"]
    assert "qs_sidecar_extra_identity:99:2019" in _stage2_report(
        sidecar=extra
    )["blockers"]
    assert "qs_sidecar_duplicate_identity:20:2019" in _stage2_report(
        sidecar=duplicate
    )["blockers"]
    assert "qs_sidecar_invalid_row:0" in _stage2_report(
        sidecar=invalid
    )["blockers"]


def test_stage2_declared_sidecar_blocker_is_preserved():
    sidecar = _sidecar()
    sidecar["blockers"] = ["fetch_failed:20:2019"]
    sidecar = _seal_sidecar(sidecar)

    report = _stage2_report(sidecar=sidecar)

    assert "qs_sidecar_declared_blocker:fetch_failed:20:2019" in report["blockers"]


def test_stage2_current_season_supersession_must_be_disclosed():
    contract = _contract()
    contract["historical_mlb_seasons"]["20_pitcher"][0].update(
        {"year": 2026, "qs": 1}
    )
    sidecar = _sidecar(quality_starts=3)
    sidecar["rows"][0]["season"] = 2026
    sidecar["validation"]["current_season_values_superseded"] = [
        {
            "mlbam_id": 20,
            "season": 2026,
            "existing": 1,
            "derived": 3,
        }
    ]
    sidecar = _seal_sidecar(sidecar)

    disclosed = _stage2_report(contract=contract, sidecar=sidecar)
    sidecar["validation"]["current_season_values_superseded"] = []
    sidecar = _seal_sidecar(sidecar)
    undisclosed = _stage2_report(contract=contract, sidecar=sidecar)

    assert not any(
        blocker.startswith("qs_source_conflict:")
        for blocker in disclosed["blockers"]
    )
    assert "qs_source_conflict:20:2026" in undisclosed["blockers"]


def test_stage2_completed_season_qs_conflict_blocks():
    contract = _contract()
    contract["historical_mlb_seasons"]["20_pitcher"][0]["qs"] = 1

    assert "qs_source_conflict:20:2019" in _stage2_report(
        contract=contract
    )["blockers"]


def test_stage2_non_qs_category_below_coverage_blocks():
    contract = _contract()
    contract["historical_mlb_seasons"]["20_pitcher"][0]["k_bb"] = None

    report = _stage2_report(contract=contract)

    assert report["outcome_evidence"]["pitcher"]["missing"] == ["k_bb"]
    assert "missing_pitcher_category:k_bb" in report["blockers"]
    assert report["outcome_evidence"][
        "retrospective_direct_7x7_evidence_ready"
    ] is False


def test_stage2_report_and_hash_are_deterministic():
    first = _stage2_report()
    second = _stage2_report()

    assert first == second
    assert first["content_sha256"] == _canonical_hash(first)
```

- [ ] **Step 3: Run the new tests to verify RED**

Run:

```powershell
python -m pytest tests/test_prospect_realized_value_readiness.py -q
```

Expected:

```text
ERROR collecting tests/test_prospect_realized_value_readiness.py
ImportError: cannot import name 'audit_stage2_realized_value_readiness'
```

- [ ] **Step 4: Implement the minimal additive audit**

Append these helpers and the new public function to
`prospects/realized_value_readiness.py`. Do not edit
`audit_realized_value_readiness(...)`:

```python
def _stage2_category_coverage(seasons: dict, role: str) -> dict:
    from prospects.model import (  # Keep the old pure audit's import path unchanged.
        IMPACT_CATEGORIES,
        IMPACT_CATEGORY_COVERAGE,
        IMPACT_REFERENCE_MIN,
    )

    sample_field = "pa" if role == "hitter" else "ip"
    source_fields = {
        category: (["sv", "hld"] if category == "sv_hld" else [category])
        for category in IMPACT_CATEGORIES[role]
    }
    role_rows = [
        row
        for key, values in seasons.items()
        if str(key).endswith(f"_{role}")
        for row in (values or [])
        if isinstance(row, dict)
    ]
    eligible = []
    for row in role_rows:
        try:
            sample = float(row.get(sample_field) or 0)
        except (TypeError, ValueError):
            sample = 0
        if sample >= IMPACT_REFERENCE_MIN[role]:
            eligible.append(row)
    counts = {
        category: sum(
            all(row.get(field) is not None for field in fields)
            for row in eligible
        )
        for category, fields in source_fields.items()
    }
    best = max(counts.values(), default=0)
    threshold = best * IMPACT_CATEGORY_COVERAGE
    active = [
        category
        for category in IMPACT_CATEGORIES[role]
        if best and counts[category] >= threshold
    ]
    missing = [
        category
        for category in IMPACT_CATEGORIES[role]
        if category not in active
    ]
    return {
        "canonical": list(IMPACT_CATEGORIES[role]),
        "active": active,
        "missing": missing,
        "complete": bool(active) and not missing,
        "season_rows": len(role_rows),
        "eligible_reference_seasons": len(eligible),
        "coverage_ratio": IMPACT_CATEGORY_COVERAGE,
        "populated_reference_seasons": counts,
        "source_fields": source_fields,
    }


def _strict_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def audit_stage2_realized_value_readiness(
    contract: dict,
    model_artifact: dict,
    qs_sidecar: dict,
    *,
    contract_sha256: str,
) -> dict:
    base = audit_realized_value_readiness(contract, model_artifact)
    seasons = contract.get("historical_mlb_seasons") or {}
    blockers = [
        blocker
        for blocker in base["blockers"]
        if blocker.startswith(
            (
                "duplicate_cohort_identity:",
                "conflicting_cohort_roles:",
                "invalid_historical_row:",
            )
        )
        or blocker == "missing_historical_cohorts"
    ]

    expected_path = "data/prospects/prospect_model_inputs.json"
    current = contract.get("current")
    cutoff = str(
        current.get("fetched_date") or ""
        if isinstance(current, dict)
        else ""
    )
    if not isinstance(qs_sidecar, dict):
        qs_sidecar = {}
    sidecar_input = qs_sidecar.get("input")
    if not isinstance(sidecar_input, dict):
        sidecar_input = {}
    sidecar_validation = qs_sidecar.get("validation")
    if not isinstance(sidecar_validation, dict):
        sidecar_validation = {}
    if qs_sidecar.get("schema") != "valucast_stage2_quality_starts":
        blockers.append("qs_sidecar_schema_invalid")
    if qs_sidecar.get("version") != "1.0.0":
        blockers.append("qs_sidecar_version_unsupported")
    if qs_sidecar.get("status") != "ready":
        blockers.append("qs_sidecar_status_not_ready")
    for blocker in qs_sidecar.get("blockers") or []:
        blockers.append(f"qs_sidecar_declared_blocker:{blocker}")
    if sidecar_input.get("path") != expected_path:
        blockers.append("qs_sidecar_input_path_mismatch")
    if sidecar_input.get("sha256") != contract_sha256:
        blockers.append("qs_sidecar_input_sha256_mismatch")
    if sidecar_input.get("cutoff_date") != cutoff:
        blockers.append("qs_sidecar_cutoff_mismatch")
    if qs_sidecar.get("content_sha256") != _content_sha256(qs_sidecar):
        blockers.append("qs_sidecar_content_sha256_mismatch")

    source_identities = set()
    for key, values in seasons.items():
        if not str(key).endswith("_pitcher"):
            continue
        try:
            mlbam_id = int(str(key).rsplit("_", 1)[0])
        except ValueError:
            blockers.append(f"invalid_pitcher_season_key:{key}")
            continue
        for index, row in enumerate(values or []):
            year = _identity(row.get("year")) if isinstance(row, dict) else None
            if year is None:
                blockers.append(f"invalid_pitcher_season:{key}:{index}")
                continue
            identity = (mlbam_id, year)
            source_identities.add(identity)

    sidecar_rows = {}
    for index, row in enumerate(qs_sidecar.get("rows") or []):
        if not isinstance(row, dict):
            blockers.append(f"qs_sidecar_invalid_row:{index}")
            continue
        values = (
            row.get("mlbam_id"),
            row.get("season"),
            row.get("games_started"),
            row.get("quality_starts"),
        )
        if (
            not all(_strict_nonnegative_int(value) for value in values)
            or values[0] == 0
            or values[1] == 0
            or values[3] > values[2]
        ):
            blockers.append(f"qs_sidecar_invalid_row:{index}")
            continue
        identity = (values[0], values[1])
        if identity in sidecar_rows:
            blockers.append(
                f"qs_sidecar_duplicate_identity:{identity[0]}:{identity[1]}"
            )
            continue
        sidecar_rows[identity] = row

    for mlbam_id, season in sorted(source_identities - set(sidecar_rows)):
        blockers.append(f"qs_sidecar_missing_identity:{mlbam_id}:{season}")
    for mlbam_id, season in sorted(set(sidecar_rows) - source_identities):
        blockers.append(f"qs_sidecar_extra_identity:{mlbam_id}:{season}")

    disclosures = {
        (int(row["mlbam_id"]), int(row["season"])): (
            row.get("existing"),
            row.get("derived"),
        )
        for row in (
            sidecar_validation.get(
                "current_season_values_superseded"
            )
            or []
        )
        if isinstance(row, dict)
        and _identity(row.get("mlbam_id")) is not None
        and _identity(row.get("season")) is not None
    }
    cutoff_year = _identity(cutoff[:4])
    enriched = {
        key: [
            dict(row) if isinstance(row, dict) else row
            for row in (values or [])
        ]
        for key, values in seasons.items()
    }
    for key, values in enriched.items():
        if not str(key).endswith("_pitcher"):
            continue
        try:
            mlbam_id = int(str(key).rsplit("_", 1)[0])
        except ValueError:
            continue
        for row in values:
            if not isinstance(row, dict):
                continue
            year = _identity(row.get("year"))
            sidecar_row = sidecar_rows.get((mlbam_id, year))
            if sidecar_row is None:
                continue
            derived = sidecar_row["quality_starts"]
            existing = row.get("qs")
            if existing is not None and existing != derived:
                disclosed = disclosures.get((mlbam_id, year))
                allowed = (
                    year == cutoff_year
                    and disclosed == (existing, derived)
                )
                if not allowed:
                    blockers.append(f"qs_source_conflict:{mlbam_id}:{year}")
            row["qs"] = derived

    evidence = {
        role: _stage2_category_coverage(enriched, role)
        for role in _ROLES
    }
    for role in _ROLES:
        blockers.extend(
            f"missing_{role}_category:{category}"
            for category in evidence[role]["missing"]
        )
    evidence_blockers = list(blockers)
    evidence_ready = (
        evidence["hitter"]["complete"]
        and evidence["pitcher"]["complete"]
        and not evidence_blockers
    )

    impact = model_artifact.get("impact_target_contract") or {}
    incumbent_ready = (
        impact.get("direct_7x7") is True
        and not impact.get("missing_hitter_categories")
        and not impact.get("missing_pitcher_categories")
    )
    replay = dict(base["replay"])
    if not incumbent_ready:
        blockers.append("impact_target_not_direct_7x7")
    if not replay["exact_prospective_replay_ready"]:
        blockers.append("exact_prospective_replay_not_reconstructable")
    realized_ready = (
        evidence_ready
        and incumbent_ready
        and replay["exact_prospective_replay_ready"]
        and not blockers
    )

    report = {
        "schema": "valucast_stage2_realized_value_readiness",
        "version": "1.0.0",
        "status": "ready" if realized_ready else "blocked",
        "inputs": {
            "prospect_contract": {
                "path": expected_path,
                "sha256": contract_sha256,
                "cutoff_date": cutoff,
            },
            "model_artifact": {
                "path": "data/models/valucast_prospect_model.json",
            },
            "quality_starts_sidecar": {
                "path": (
                    "data/validation/valucast_stage2_quality_starts.json"
                ),
                "content_sha256": qs_sidecar.get("content_sha256"),
            },
        },
        "identity_policy": dict(base["identity_policy"]),
        "identity_audit": dict(base["identity_audit"]),
        "cohorts": dict(base["cohorts"]),
        "outcome_evidence": {
            "status": "ready" if evidence_ready else "blocked",
            "retrospective_direct_7x7_evidence_ready": evidence_ready,
            **evidence,
        },
        "incumbent_impact_target": {
            "direct_7x7": impact.get("direct_7x7") is True,
            "declared_hitter_categories": list(
                impact.get("hitter_categories") or []
            ),
            "declared_pitcher_categories": list(
                impact.get("pitcher_categories") or []
            ),
            "incumbent_direct_7x7_target_ready": incumbent_ready,
        },
        "prospective_replay": replay,
        "realized_value_regret_ready": realized_ready,
        "blockers": list(dict.fromkeys(blockers)),
    }
    report["content_sha256"] = _content_sha256(report)
    return report
```

- [ ] **Step 5: Run focused tests to verify GREEN**

Run:

```powershell
python -m pytest tests/test_prospect_realized_value_readiness.py -q
```

Expected:

```text
All readiness tests pass.
```

- [ ] **Step 6: Run adjacent QS tests**

Run:

```powershell
python -m pytest tests/test_prospect_realized_value_readiness.py tests/test_stage2_quality_starts.py -q
```

Expected:

```text
All focused and adjacent tests pass.
```

- [ ] **Step 7: Commit the pure audit**

Run:

```powershell
git add prospects/realized_value_readiness.py tests/test_prospect_realized_value_readiness.py
git diff --cached --check
git commit -m "feat: audit Stage 2 realized-value readiness"
```

Expected:

```text
One commit containing only the additive audit and its unit tests.
```

---

### Task 2: Add the manual builder and committed readiness artifact

**Files:**
- Create: `scripts/build_stage2_realized_value_readiness.py`
- Modify: `tests/test_prospect_realized_value_readiness.py`
- Create: `data/validation/valucast_stage2_realized_value_readiness.json`

**Interfaces:**
- Consumes: the exact prospect-input bytes, model artifact, and committed QS sidecar.
- Produces: one deterministic `valucast_stage2_realized_value_readiness` JSON artifact.
- Calls: `audit_stage2_realized_value_readiness(..., contract_sha256=<SHA-256 of exact input bytes>)`.

- [ ] **Step 1: Add the failing builder integration test**

Add these imports:

```python
import subprocess
import sys
from pathlib import Path
```

Append:

```python
def test_stage2_builder_writes_only_requested_output(tmp_path):
    root = Path(__file__).resolve().parents[1]
    protected = [
        root / "data/validation/valucast_prospect_realized_value_readiness.json",
        root / "data/prospects/prospect_model_inputs.json",
        root / "data/models/valucast_prospect_model.json",
        root / "data/validation/valucast_stage2_quality_starts.json",
    ]
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in protected
    }
    output = tmp_path / "readiness.json"

    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/build_stage2_realized_value_readiness.py"),
            "--output",
            str(output),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.exists()
    assert before == {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in protected
    }
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "valucast_stage2_realized_value_readiness"
    assert report["outcome_evidence"]["status"] == "ready"
    assert report["blockers"] == [
        "impact_target_not_direct_7x7",
        "exact_prospective_replay_not_reconstructable",
    ]
```

- [ ] **Step 2: Run the builder test to verify RED**

Run:

```powershell
python -m pytest tests/test_prospect_realized_value_readiness.py::test_stage2_builder_writes_only_requested_output -q
```

Expected:

```text
FAIL because scripts/build_stage2_realized_value_readiness.py does not exist.
```

- [ ] **Step 3: Add the minimal manual builder**

Create `scripts/build_stage2_realized_value_readiness.py`:

```python
"""Manually build the research-only Stage 2 readiness artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.realized_value_readiness import (  # noqa: E402
    audit_stage2_realized_value_readiness,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data/prospects/prospect_model_inputs.json",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "data/models/valucast_prospect_model.json",
    )
    parser.add_argument(
        "--quality-starts",
        type=Path,
        default=(
            ROOT / "data/validation/valucast_stage2_quality_starts.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / "data/validation/valucast_stage2_realized_value_readiness.json"
        ),
    )
    args = parser.parse_args()

    input_bytes = args.input.read_bytes()
    report = audit_stage2_realized_value_readiness(
        json.loads(input_bytes),
        _load(args.model),
        _load(args.quality_starts),
        contract_sha256=hashlib.sha256(input_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "Stage 2 readiness: "
        f"evidence={report['outcome_evidence']['status']} "
        f"overall={report['status']} -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the builder test to verify GREEN**

Run:

```powershell
python -m pytest tests/test_prospect_realized_value_readiness.py::test_stage2_builder_writes_only_requested_output -q
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Build the committed artifact**

Run:

```powershell
python scripts/build_stage2_realized_value_readiness.py
```

Expected:

```text
Stage 2 readiness: evidence=ready overall=blocked -> ...valucast_stage2_realized_value_readiness.json
```

- [ ] **Step 6: Verify the exact July 23 result**

Run:

```powershell
@'
import hashlib
import json
from pathlib import Path

path = Path("data/validation/valucast_stage2_realized_value_readiness.json")
report = json.loads(path.read_text(encoding="utf-8"))
body = {key: value for key, value in report.items() if key != "content_sha256"}
expected_hash = hashlib.sha256(
    json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()

assert report["outcome_evidence"]["status"] == "ready"
assert report["outcome_evidence"]["hitter"]["eligible_reference_seasons"] == 2862
assert report["outcome_evidence"]["pitcher"]["eligible_reference_seasons"] == 3806
assert report["outcome_evidence"]["pitcher"]["populated_reference_seasons"] == {
    "so": 3806,
    "qs": 3806,
    "sv_hld": 3806,
    "era": 3806,
    "whip": 3806,
    "k_bb": 3806,
    "l": 3806,
}
assert report["blockers"] == [
    "impact_target_not_direct_7x7",
    "exact_prospective_replay_not_reconstructable",
]
assert report["content_sha256"] == expected_hash
print(report["content_sha256"])
'@ | python -
```

Expected:

```text
One SHA-256 value and no assertion failure.
```

- [ ] **Step 7: Run the full focused verification**

Run:

```powershell
python -m pytest tests/test_prospect_realized_value_readiness.py tests/test_stage2_quality_starts.py -q
git diff --check
```

Expected:

```text
All focused and adjacent tests pass.
No whitespace errors.
```

- [ ] **Step 8: Recheck protected hashes**

Run the same four-file `Get-FileHash` command from Task 1, Step 1.

Expected:

```text
All four SHA-256 values exactly match the recorded baseline.
```

- [ ] **Step 9: Confirm scope**

Run:

```powershell
git status --short
git diff --stat
```

Expected changed paths:

```text
M  tests/test_prospect_realized_value_readiness.py
?? scripts/build_stage2_realized_value_readiness.py
?? data/validation/valucast_stage2_realized_value_readiness.json
```

The spec and plan commits are already present. No model, input, old artifact,
workflow, public surface, or publication file may appear.

- [ ] **Step 10: Commit the builder and artifact**

Run:

```powershell
git add scripts/build_stage2_realized_value_readiness.py tests/test_prospect_realized_value_readiness.py data/validation/valucast_stage2_realized_value_readiness.json
git diff --cached --check
git commit -m "data: record Stage 2 realized-value readiness"
```

Expected:

```text
One commit containing only the manual builder, its integration test, and the new artifact.
```

---

## Final verification

- [ ] Run:

```powershell
python -m pytest tests/test_prospect_realized_value_readiness.py tests/test_stage2_quality_starts.py tests/test_competition_proof.py -q
git status --short
git diff 32fa74a9..HEAD -- data/validation/valucast_prospect_realized_value_readiness.json data/prospects/prospect_model_inputs.json data/models/valucast_prospect_model.json
```

Expected:

```text
All tests pass.
The worktree is clean.
The protected-file diff is empty.
```

Do not push, merge, deploy, dispatch workflows, rebuild models, or alter live
rank/value/publication behavior during this plan.
