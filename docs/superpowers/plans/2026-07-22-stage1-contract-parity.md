# Stage 1 Contract and Stage 2 Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the existing prospect outcome artifacts behind one validated Stage 1 contract and route Prospect Rank v1 through it without changing any player score, rank, value, or publication decision.

**Architecture:** Reuse the existing v0.6 model, universal outcome layer, dynasty layer, Rank v1 builder, identity rules, and atomic artifact writes. A small in-memory contract validates the served incumbent artifacts, binds their profiles by `(mlbam_id, role)`, and rejects research, stale, malformed, or identity-conflicted inputs before Stage 2 scoring. This plan stops after exact parity; front-office baselines, challenger fitting, and the direct-investment ablation receive separate plans after review.

**Tech Stack:** Python 3.14, standard library, pytest, existing JSON artifacts and builders.

## Global Constraints

- Preserve the model freeze and failed stale-pedigree-decay flag.
- Do not change prospect predictions, score weights, normalization, ranks, values, pitcher caps, Role Watch, holds, publication decisions, or public copy.
- Do not create a fitted Stage 2 model or add dependencies.
- Do not allow a research or shadow challenger artifact to reach Rank v1.
- Keep hitter and pitcher identities separate by `(mlbam_id, role)`.
- Preserve the existing identity-only fallback for a valid universe player with no eligible Stage 1 profile.
- Reject artifact-level contract failures before writing a new rank artifact; the prior atomic artifact remains the served fallback.
- Modify only the files named in this plan and generated artifacts explicitly produced by the named builders.
- Do not push or deploy during implementation.

---

### Task 1: Correct the served-artifact metadata contract

**Files:**
- Modify: `prospects/universal.py:1070-1101`
- Modify: `prospects/dynasty.py:121-189`
- Modify: `tests/test_universal_prospect_model.py:280-305`
- Modify: `tests/test_prospect_dynasty_layer.py:54-65`
- Modify generated: `data/models/valucast_universal_prospect_model.json`
- Modify generated: `data/models/valucast_prospect_dynasty_layer.json`

**Interfaces:**
- Consumes: current universal and dynasty artifact dictionaries.
- Produces: `release_contract` metadata declaring actual served consumers while retaining `status="shadow_only"` as a provenance label.

- [ ] **Step 1: Write RED tests for honest serving metadata**

Add these assertions to the existing artifact-contract tests:

```python
def test_universal_output_declares_its_indirect_live_consumer():
    payload = build_shadow_model(_contract())
    assert payload["status"] == "shadow_only"
    assert payload["release_contract"] == {
        "artifact_status_semantics": "provenance_label_not_serving_status",
        "consumer": "prospect_dynasty_layer",
        "indirect_consumer": "prospect_rank_v1",
        "feeds_live_valucast_rank": True,
        "standalone_public_board": False,
    }
    assert not any(
        "never consumed by the live prospect board" in text
        for text in payload["limitations"]
    )


def test_dynasty_layer_declares_rank_v1_as_its_live_consumer():
    payload = build_layer(_universal())
    assert payload["status"] == "shadow_only"
    assert payload["release_contract"] == {
        "artifact_status_semantics": "provenance_label_not_serving_status",
        "consumer": "prospect_rank_v1",
        "feeds_live_valucast_rank": True,
        "feeds_live_dd_value": False,
        "standalone_public_board": False,
    }
    assert payload["layer_contract"]["rank_free"] is True
    assert payload["layer_contract"]["value_free"] is True
```

Keep the existing v0.6 assertion that `release_contract.consumer` is
`prospect_rank_v1` and `feeds_live_valucast_rank` is true.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_universal_prospect_model.py tests/test_prospect_dynasty_layer.py tests/test_prospect_model.py -k "release or consumer or shadow_output or layer_is"
```

Expected: the new universal test fails because `release_contract` is absent;
the new dynasty test fails because the artifact currently says its live
consumer is blocked.

- [ ] **Step 3: Add truthful metadata without changing calculations**

In `prospects/universal.py`, add this top-level field to the returned payload:

```python
"release_contract": {
    "artifact_status_semantics": "provenance_label_not_serving_status",
    "consumer": "prospect_dynasty_layer",
    "indirect_consumer": "prospect_rank_v1",
    "feeds_live_valucast_rank": True,
    "standalone_public_board": False,
},
```

Replace the inaccurate universal limitation with:

```python
"This outcome artifact feeds Prospect Rank v1 through the dynasty signal layer; it is not itself a standalone public board."
```

In `prospects/dynasty.py`, add:

```python
"release_contract": {
    "artifact_status_semantics": "provenance_label_not_serving_status",
    "consumer": "prospect_rank_v1",
    "feeds_live_valucast_rank": True,
    "feeds_live_dd_value": False,
    "standalone_public_board": False,
},
```

Do not change `decision_signal`, any probabilities, or any layer profile. Keep
the existing research-gate fields as evidence metadata, but replace the false
`promotion.live_consumer="blocked"` and `feeds_live_valucast_rank=False` values
with `"prospect_rank_v1"` and `True`. Replace the inaccurate limitation about
blocked live consumers with:

```python
"The layer feeds Prospect Rank v1 as an incumbent component; new model versions still require dated forward evidence."
```

- [ ] **Step 4: Run Task 1 tests GREEN**

Run:

```powershell
python -m pytest -q tests/test_universal_prospect_model.py tests/test_prospect_dynasty_layer.py tests/test_prospect_model.py
```

Expected: all selected tests pass and no numerical profile assertion changes.

- [ ] **Step 5: Rebuild only the two metadata-corrected artifacts**

Run:

```powershell
python scripts/build_universal_prospect_model.py
python scripts/build_prospect_dynasty_layer.py
```

Before accepting generated changes, compare profile-only hashes against HEAD:

```powershell
@'
import hashlib, json, subprocess
from pathlib import Path

for path in (
    "data/models/valucast_universal_prospect_model.json",
    "data/models/valucast_prospect_dynasty_layer.json",
):
    before = json.loads(subprocess.check_output(["git", "show", f"HEAD:{path}"], text=True))
    after = json.loads(Path(path).read_text(encoding="utf-8"))
    encode = lambda rows: json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encode(before["profiles"])).digest() == hashlib.sha256(encode(after["profiles"])).digest(), path
    print(path, "profiles unchanged")
'@ | python -
```

Expected: both lines report `profiles unchanged`. Revert any unrelated archive
or generated churn rather than including it.

- [ ] **Step 6: Review checkpoint and commit**

Review the metadata diff before continuing because it corrects an existing
governance contradiction.

```powershell
git add prospects/universal.py prospects/dynasty.py tests/test_universal_prospect_model.py tests/test_prospect_dynasty_layer.py data/models/valucast_universal_prospect_model.json data/models/valucast_prospect_dynasty_layer.json
git commit -m "Correct prospect artifact serving metadata"
```

---

### Task 2: Add the in-memory Stage 1 contract

**Files:**
- Create: `prospects/stage1_contract.py`
- Create: `tests/test_stage1_contract.py`

**Interfaces:**
- Produces: `build_stage1_contract(prospect_model: dict, dynasty_layer: dict, expected_generated_at: str, *, state: str = "incumbent") -> dict`.
- Returned keys: `contract_version`, `state`, `generated_date`, `model_version`, `layer_version`, `profiles_by_key`.
- `profiles_by_key` maps `(str(mlbam_id), role)` to `model_profile` and `outcome_profile` copies.
- Consumed by Task 3 in `prospects/rank_v1.py`.

- [ ] **Step 1: Write the contract RED tests**

Create `tests/test_stage1_contract.py`:

```python
from copy import deepcopy

import pytest

from prospects.stage1_contract import build_stage1_contract


def _model():
    return {
        "model_version": "0.6.1",
        "input_contract": {"generated_at": "2026-07-22T00:00:00+00:00"},
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "ranked": [{"mlbam_id": 1, "role": "hitter", "expected_outcome_score": 0.6}],
    }


def _layer():
    return {
        "generated_at": "2026-07-22T00:00:00+00:00",
        "layer_version": "0.1.0",
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "profiles": [{"mlbam_id": 1, "role": "hitter", "outcome_distribution": {}}],
    }


def test_contract_binds_served_profiles_without_mutating_inputs():
    model, layer = _model(), _layer()
    before = deepcopy((model, layer))
    result = build_stage1_contract(model, layer, "2026-07-22T00:00:00+00:00")
    assert result["contract_version"] == "1.0.0"
    assert result["state"] == "incumbent"
    assert result["generated_date"] == "2026-07-22"
    assert result["profiles_by_key"][("1", "hitter")]["model_profile"]["expected_outcome_score"] == 0.6
    assert result["profiles_by_key"][("1", "hitter")]["outcome_profile"]["mlbam_id"] == 1
    assert (model, layer) == before


@pytest.mark.parametrize("state", ["research", "shadow", "candidate"])
def test_contract_rejects_non_served_states(state):
    with pytest.raises(ValueError, match="Stage 1 state"):
        build_stage1_contract(_model(), _layer(), "2026-07-22", state=state)


def test_contract_rejects_stale_or_non_serving_artifacts():
    layer = _layer()
    layer["generated_at"] = "2026-07-21T00:00:00+00:00"
    with pytest.raises(ValueError, match="generated date"):
        build_stage1_contract(_model(), layer, "2026-07-22")

    layer = _layer()
    layer["release_contract"]["feeds_live_valucast_rank"] = False
    with pytest.raises(ValueError, match="not authorized"):
        build_stage1_contract(_model(), layer, "2026-07-22")


@pytest.mark.parametrize("bucket", ["ranked", "profiles"])
def test_contract_rejects_duplicate_or_invalid_identity(bucket):
    model, layer = _model(), _layer()
    source = model if bucket == "ranked" else layer
    source[bucket].append(deepcopy(source[bucket][0]))
    with pytest.raises(ValueError, match="duplicate"):
        build_stage1_contract(model, layer, "2026-07-22")

    model, layer = _model(), _layer()
    source = model if bucket == "ranked" else layer
    source[bucket][0]["role"] = "two_way"
    with pytest.raises(ValueError, match="role"):
        build_stage1_contract(model, layer, "2026-07-22")
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_stage1_contract.py
```

Expected: collection fails because `prospects.stage1_contract` does not exist.

- [ ] **Step 3: Implement the smallest contract**

Create `prospects/stage1_contract.py` using only the standard library:

```python
"""Validated boundary between prospect outcome artifacts and fantasy ranking."""
from copy import deepcopy
from datetime import datetime

CONTRACT_VERSION = "1.0.0"
SERVED_STATES = frozenset({"incumbent", "promoted"})
ROLES = frozenset({"hitter", "pitcher"})


def _date(value: object) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _index(rows: list[dict], label: str) -> dict[tuple[str, str], dict]:
    out = {}
    for row in rows:
        role = str(row.get("role") or "").lower()
        mlbam_id = row.get("mlbam_id")
        if role not in ROLES:
            raise ValueError(f"Stage 1 {label} profile has invalid role")
        if isinstance(mlbam_id, bool) or not str(mlbam_id or "").isdigit():
            raise ValueError(f"Stage 1 {label} profile has invalid MLBAM identity")
        key = (str(mlbam_id), role)
        if key in out:
            raise ValueError(f"Stage 1 {label} profile has duplicate identity {key}")
        out[key] = deepcopy(row)
    return out


def build_stage1_contract(
    prospect_model: dict,
    dynasty_layer: dict,
    expected_generated_at: str,
    *,
    state: str = "incumbent",
) -> dict:
    if state not in SERVED_STATES:
        raise ValueError(f"Stage 1 state is not served: {state}")
    for label, payload in (("model", prospect_model), ("layer", dynasty_layer)):
        release = payload.get("release_contract") or {}
        if release.get("consumer") != "prospect_rank_v1" or release.get("feeds_live_valucast_rank") is not True:
            raise ValueError(f"Stage 1 {label} artifact is not authorized for Rank v1")
    expected_date = _date(expected_generated_at)
    model_date = _date((prospect_model.get("input_contract") or {}).get("generated_at"))
    layer_date = _date(dynasty_layer.get("generated_at"))
    if not expected_date or {model_date, layer_date} != {expected_date}:
        raise ValueError("Stage 1 artifacts do not match the expected generated date")
    models = _index(prospect_model.get("ranked") or [], "model")
    outcomes = _index(dynasty_layer.get("profiles") or [], "outcome")
    profiles = {
        key: {
            "mlbam_id": key[0],
            "role": key[1],
            "model_profile": models.get(key),
            "outcome_profile": outcomes.get(key),
        }
        for key in sorted(models.keys() | outcomes.keys())
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "state": state,
        "generated_date": expected_date,
        "model_version": prospect_model.get("model_version"),
        "layer_version": dynasty_layer.get("layer_version"),
        "profiles_by_key": profiles,
    }
```

- [ ] **Step 4: Run Task 2 tests GREEN**

Run:

```powershell
python -m pytest -q tests/test_stage1_contract.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add prospects/stage1_contract.py tests/test_stage1_contract.py
git commit -m "Add served Stage 1 prospect contract"
```

---

### Task 3: Route Rank v1 through the Stage 1 contract

**Files:**
- Modify: `prospects/rank_v1.py:22-35, 322-343, 1971-2020, 2055-2077, 2295-2308`
- Modify: `tests/test_prospect_rank_v1.py:208-262, 815-850, 1478-1515`

**Interfaces:**
- Consumes: `build_stage1_contract(...)` from Task 2.
- Produces: unchanged Rank v1 board rows plus Stage 1 contract metadata under `input_artifacts`.

- [ ] **Step 1: Make the shared Rank v1 fixtures contract-valid**

Add the following metadata to `_dynasty_layer()`:

```python
"release_contract": {
    "consumer": "prospect_rank_v1",
    "feeds_live_valucast_rank": True,
},
```

Add the following metadata to `_prospect_model()`:

```python
"input_contract": {"generated_at": "2026-06-13T12:00:00+00:00"},
"release_contract": {
    "consumer": "prospect_rank_v1",
    "feeds_live_valucast_rank": True,
},
```

- [ ] **Step 2: Write RED integration tests**

Add:

```python
def test_rank_v1_reports_the_served_stage1_contract():
    payload = build_prospect_rank_v1(
        _universe(), _dynasty_layer(), _prospect_model(), _input_contract()
    )
    assert payload["input_artifacts"]["stage1_contract_version"] == "1.0.0"
    assert payload["input_artifacts"]["stage1_state"] == "incumbent"
    assert payload["input_artifacts"]["stage1_profile_count"] == 2


def test_rank_v1_rejects_a_research_stage1_state():
    with pytest.raises(ValueError, match="Stage 1 state"):
        build_prospect_rank_v1(
            _universe(),
            _dynasty_layer(),
            _prospect_model(),
            _input_contract(),
            stage1_state="research",
        )
```

Import `pytest` if it is not already imported.

- [ ] **Step 3: Run the integration tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_prospect_rank_v1.py -k "served_stage1_contract or research_stage1_state"
```

Expected: failures because `stage1_state` and contract metadata do not exist.

- [ ] **Step 4: Bind the existing lookups through the contract**

In `prospects/rank_v1.py`, import:

```python
from prospects.stage1_contract import build_stage1_contract
```

Add a keyword-only argument to `build_prospect_rank_v1`:

```python
stage1_state: str = "incumbent",
```

At the start of the function, before any scoring, build the contract using the
input artifact timestamp:

```python
stage1 = build_stage1_contract(
    prospect_model,
    dynasty_layer,
    input_contract.get("generated_at"),
    state=stage1_state,
)
stage1_by_key = stage1["profiles_by_key"]
```

Retain the current quantile-normalization implementation. Build `model_by_key`
and `layer_by_key` only from copies already accepted into `stage1_by_key`:

```python
model_by_key = _model_lookup(
    {
        "ranked": [
            profile["model_profile"]
            for profile in stage1_by_key.values()
            if profile["model_profile"] is not None
        ]
    }
)
layer_by_key = _layer_lookup(
    {
        "profiles": [
            profile["outcome_profile"]
            for profile in stage1_by_key.values()
            if profile["outcome_profile"] is not None
        ]
    }
)
```

Then use the accepted profile in the board loop:

```python
stage1_profile = stage1_by_key.get(key) or {}
layer_profile = layer_by_key.get(key)
model_profile = model_by_key.get(key)
```

Do not change `_score_components`, normalization weights, missing-profile
fallback, availability adjustment, bucket calibration, or tiebreakers.

Add to `input_artifacts`:

```python
"stage1_contract_version": stage1["contract_version"],
"stage1_state": stage1["state"],
"stage1_profile_count": len(stage1_by_key),
```

- [ ] **Step 5: Run Rank v1 tests GREEN**

Run:

```powershell
python -m pytest -q tests/test_prospect_rank_v1.py
```

Expected: every existing Rank v1 test and the new contract tests pass without
changing expected scores or ranks.

- [ ] **Step 6: Review checkpoint and commit**

Review the diff specifically for any score-math, weight, normalization, or
fallback change. None is permitted.

```powershell
git add prospects/rank_v1.py tests/test_prospect_rank_v1.py
git commit -m "Route prospect ranking through Stage 1 contract"
```

---

### Task 4: Prove atomic failure and canonical board parity

**Files:**
- Modify: `tests/test_prospect_rank_v1.py:1478-1515`
- Create: `docs/audit-2026-07-22-stage1-contract-parity.md`

**Interfaces:**
- Consumes: canonical Stage 1 contract and `run_prospect_rank_v1` atomic writer.
- Produces: regression proof that rejected Stage 1 inputs leave the existing rank artifact untouched and accepted inputs preserve the board exactly.

- [ ] **Step 1: Write the atomic-failure RED test**

Add beside the runner test:

```python
def test_run_rank_v1_leaves_previous_artifact_on_stage1_rejection(tmp_path):
    universe_path = tmp_path / "universe.json"
    layer_path = tmp_path / "layer.json"
    model_path = tmp_path / "model.json"
    input_path = tmp_path / "input.json"
    artifact_path = tmp_path / "rank.json"
    universe_path.write_text(json.dumps(_universe()), encoding="utf-8")
    bad_layer = _dynasty_layer()
    bad_layer["release_contract"]["feeds_live_valucast_rank"] = False
    layer_path.write_text(json.dumps(bad_layer), encoding="utf-8")
    model_path.write_text(json.dumps(_prospect_model()), encoding="utf-8")
    input_path.write_text(json.dumps(_input_contract()), encoding="utf-8")
    artifact_path.write_text("previous promoted artifact", encoding="utf-8")

    with pytest.raises(ValueError, match="not authorized"):
        run_prospect_rank_v1(
            prospect_universe_path=universe_path,
            dynasty_layer_path=layer_path,
            prospect_model_path=model_path,
            input_contract_path=input_path,
            availability_path=None,
            mlb_roster_status_path=None,
            artifact_path=artifact_path,
            archive_dir=tmp_path / "archive",
        )
    assert artifact_path.read_text(encoding="utf-8") == "previous promoted artifact"
```

- [ ] **Step 2: Run the atomic test GREEN**

Run:

```powershell
python -m pytest -q tests/test_prospect_rank_v1.py -k "leaves_previous_artifact"
```

Expected: PASS because contract validation occurs before the atomic write.

- [ ] **Step 3: Generate a temporary canonical Rank v1 artifact**

Run without overwriting tracked rank or archive files:

```powershell
@'
from pathlib import Path
from prospects.rank_v1 import run_prospect_rank_v1

root = Path(".tmp-stage1-parity")
root.mkdir(exist_ok=True)
print(run_prospect_rank_v1(
    artifact_path=root / "rank.json",
    archive_dir=root / "archive",
))
'@ | python -
```

- [ ] **Step 4: Compare every board decision with the pre-migration artifact**

Run:

```powershell
@'
import hashlib, json
from pathlib import Path

before = json.loads(Path("data/models/valucast_prospect_rank_v1.json").read_text(encoding="utf-8"))
after = json.loads(Path(".tmp-stage1-parity/rank.json").read_text(encoding="utf-8"))
assert before["board"] == after["board"]
encode = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
print("board_count", len(after["board"]))
print("board_sha256", hashlib.sha256(encode(after["board"])).hexdigest())
print("exact_board_parity", True)
'@ | python -
```

Expected: `exact_board_parity True`. If the current artifact and current inputs
are from different dates, stop and rebuild both sides from the same pre-change
commit in separate temporary worktrees; never waive parity.

- [ ] **Step 5: Write the parity audit**

Create `docs/audit-2026-07-22-stage1-contract-parity.md` containing:

```markdown
# Stage 1 Contract Parity Audit

Date: 2026-07-22
Status: zero-behavior-change migration verified

- Stage 1 contract version: 1.0.0
- Served state: incumbent
- Canonical board rows compared: 2,851
- Canonical board SHA-256: `e2626fee0e993d3e7e52e371e917a162bb561130d21bae2b372ca154a0de7d46`
- Exact board parity: true
- Research/shadow artifacts accepted by Stage 2: false
- Rejected contract overwrites prior artifact: false
- Model freeze preserved: true
- Failed stale-pedigree-decay flag preserved: true
- Live score/rank/value/cap/Role Watch/publication change: false
```

The recorded count and hash are the July 22 pre-migration baseline. If Step 4
does not reproduce both values, stop and explain the input drift; do not update
the audit to a new baseline during this implementation. Do not claim byte
parity for top-level metadata that intentionally adds the contract fields;
claim exact board parity.

- [ ] **Step 6: Remove temporary files and commit**

Remove `.tmp-stage1-parity` using native PowerShell after resolving and checking
that it is inside this worktree:

```powershell
$target = (Resolve-Path .tmp-stage1-parity).Path
$root = (Resolve-Path .).Path
if (-not $target.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) { throw "unsafe temp path" }
Remove-Item -LiteralPath $target -Recurse -Force
git add tests/test_prospect_rank_v1.py docs/audit-2026-07-22-stage1-contract-parity.md
git commit -m "Prove Stage 1 ranking parity"
```

---

### Task 5: Document the boundary and run final verification

**Files:**
- Modify: `docs/prospect-model.md`
- Verify only: `data/models/valucast_prospect_model.json`
- Verify only: `data/models/valucast_prospect_rank_v1.json`

**Interfaces:**
- Consumes: completed Stage 1 contract and parity audit.
- Produces: accurate coworker-facing architecture documentation.

- [ ] **Step 1: Update the model documentation**

Add a concise `Stage 1 / Stage 2 boundary` section to
`docs/prospect-model.md`:

```markdown
## Stage 1 / Stage 2 boundary

Stage 1 is ValuCast's real-baseball outcome layer. It produces role-specific
arrival, sustained-role, and representative MLB production forecasts. The
served incumbent currently binds Prospect Model v0.6 with the universal/dynasty
outcome profile through contract version 1.0.0.

Stage 2 is the deterministic Rank v1 and downstream league-value translation.
It consumes only an incumbent or promoted Stage 1 contract plus timestamped
availability/opportunity and league-format rules. Research and shadow artifacts
are rejected before scoring. The Stage 1 contract migration changed no board
score, rank, value, cap, Role Watch, or publication decision.
```

Remove or correct any nearby claim that the universal/dynasty artifacts are
never consumed by the live rank. Do not rewrite unrelated model history.

- [ ] **Step 2: Run focused suites**

Run:

```powershell
python -m pytest -q tests/test_stage1_contract.py tests/test_prospect_rank_v1.py tests/test_prospect_model.py tests/test_universal_prospect_model.py tests/test_prospect_dynasty_layer.py tests/test_public_data_refresh.py
```

Expected: all selected tests pass.

- [ ] **Step 3: Verify frozen artifacts and feature flags**

Run:

```powershell
@'
import hashlib, subprocess
from pathlib import Path
from prospects import model

for path in (model.ARTIFACT_PATH,):
    rel = path.relative_to(Path.cwd()).as_posix()
    current = hashlib.sha256(path.read_bytes()).hexdigest()
    prior = hashlib.sha256(subprocess.check_output(["git", "show", f"HEAD:{rel}"])).hexdigest()
    assert current == prior, rel
assert model.LEVEL_TRANSLATION_FITTED_ENABLED is False
assert model.PITCHER_STRIKE_PCT_ENABLED is False
assert model.PITCHER_STALE_PEDIGREE_DECAY_ENABLED is False
print("frozen model and failed flags preserved")
'@ | python -
```

Use the pre-task commit rather than the immediately previous Task commit as the
comparison base if executing tasks in separate commits. The two intentionally
metadata-corrected universal/dynasty artifacts are excluded from the frozen
profile hash check because Task 1 already proves their profile arrays unchanged.

- [ ] **Step 4: Run the full regression suite**

Run:

```powershell
python -m pytest -q
```

Expected: the complete suite passes. Re-check `git status --short` afterward and
revert unrelated generated churn.

- [ ] **Step 5: Run final hygiene**

Run:

```powershell
git diff --check
git status --short
```

Expected: only the planned documentation change remains uncommitted; no temp
directory, cache, unrelated artifact, workflow, rank, or value change appears.

- [ ] **Step 6: Commit documentation**

```powershell
git add docs/prospect-model.md
git commit -m "Document two-stage prospect boundary"
```

## Review and stopping point

After Task 5, stop for an independent review. Do not begin front-office
baseline construction, challenger evaluation, Stage 2 investment ablation,
public copy, deployment, or promotion in this plan. The next plan may begin
only after exact board parity and serving-contract honesty are approved.
