# Prospect Rank vNext Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task.

**Goal:** Transplant the smallest reproducible prospect-research lineage onto current master, implement the owner-approved v2.3 combined-board development screen, register it before outcome access, and freeze exactly one terminal known-data result without changing anything served.

**Architecture:** Keep Prospect Rank v1 as the untouched production incumbent. Reconstruct three historical folds from a frozen through-2021 contract, preserve the supported v1 hitter ladder, substitute the frozen v0.9 pitcher ladder, and fit one five-parameter monotone cross-role map. Compare that candidate independently with a same-family v1-ladder control and the fold-reconstructed v1 product logic. A single runner owns deterministic metrics, one shared bootstrap sample plan, the mandatory pooled-development fit, and the durable `reserved -> outcome_access_spent -> terminal` receipt state machine.

**Tech Stack:** Python 3, NumPy, SciPy, pytest, Ruff, Git object IDs, canonical JSON hashes, and atomic `os.replace` publication.

## Authority and phase boundary

- Baseline design: `docs/superpowers/specs/2026-08-20-prospect-rank-vnext-current-board-design.md` at `1737468b16717ee6f7d24ea08b8444fdde3442f2`.
- Implementation starts from current master baseline `e48360faddab5504638324f70cddae25f7b7bc65` plus the approved design commit.
- Use only a D: worktree. Do not use or create a C: checkout.
- Keep every temporary/test write on D:. Before each new PowerShell process used for this plan, run the exact setup below; every pytest command also names the same `--basetemp` explicitly. Do not run two pytest processes against this shared base at once.

```powershell
$phaseATempRoot = [IO.Path]::GetFullPath("D:\CodexScratch\valucast-vnext-phase-a")
if (-not $phaseATempRoot.StartsWith("D:\CodexScratch\valucast-vnext-phase-a", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Phase A temporary path escaped D:\CodexScratch"
}
$phaseASystemTemp = Join-Path $phaseATempRoot "system"
New-Item -ItemType Directory -Force $phaseASystemTemp | Out-Null
$env:TEMP = $phaseASystemTemp
$env:TMP = $phaseASystemTemp
function Assert-NativeSuccess([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed with exit $LASTEXITCODE" }
}
```

PowerShell 5.1 does not stop on native-command failures. Every `python`/`git` command below must be followed immediately by `Assert-NativeSuccess`, except where the block explicitly captures and adjudicates `$LASTEXITCODE`.

- This plan covers **Phase A only**.
- This plan does not authorize the canonical runner. Stop for a new explicit owner approval after the reviewed registration is merged to master.
- A Phase A pass writes inert evidence only. It does not authorize R1, R4, current-rank routing, shadow archives, governor staging, publication, deployment, or a registry verdict.
- Phase B does not exist unless the terminal receipt records `development_qualified: true`; write its plan only after that result.
- Do not merge, cherry-pick, or replay the 40-commit `codex/pitcher-validation-program` branch wholesale.
- Do not run the obsolete v2.3 plan or its runner from `1201b799`; it lacks the product comparator, top-25 gates, pooled confidence bounds, candidate-concordance floor, and amended spend boundary.
- Add no dependency and no runtime feature flag.

## Non-goals and forbidden paths

Phase A must not modify any of these paths:

```text
prospects/current_rank.py
data/models/valucast_prospect_rank_v1.json
data/prediction_archive/valucast_prospect_rank_v1/**
data/validation/valucast_prospect_2022_confirmation_manifest.json
data/models/valucast_model_registry.json
data/public/public_dynasty_snapshot.json
data/models/valucast_quality_governor.json
scripts/build_public_dynasty_snapshot.py
scripts/build_valucast_quality_governor.py
.github/workflows/daily-public-data.yml
app.py
templates/**
static/**
```

Also forbid every 2022 outcome/confirmation input, current public rank/value, consensus rank, market rank/value, governor result, player name, and role quota from fitting.

## Portable provenance contract

The old receipts contain Windows working-tree SHA-256 values for some files. Those hashes are historical receipt data, but they are not portable across Git checkout line-ending conversion. Phase A therefore binds each dependency in two portable ways:

1. the exact Git blob object ID; and
2. a canonical payload hash:
   - JSON: `canonical_sha256(json.loads(raw_text))` using the existing canonical JSON helper;
   - source text: SHA-256 after UTF-8 decode and newline normalization to `\n`.

Preserve the old receipt fields byte-for-byte. Do not rewrite or reseal them. The new registration records the portable bindings alongside the legacy hashes and explains that distinction.

### Canonical research runtime

The registered fit and every exact reproduction use the already-proven D: host runtime below; ordinary synthetic CI tests may run on the repository's supported Python matrix but may not produce or certify canonical artifacts.

```text
implementation: CPython 3.14.3, MSC v.1944 64 bit
platform: Windows-11-10.0.26200-SP0, AMD64
numpy: 1.26.4
scipy: 1.17.1
```

Plan 038 binds these literals. Before reservation, resume, outcome access, or reproduction, the runner requires `tuple(sys.version_info[:3]) == (3, 14, 3)`, `sys.version_info.releaselevel == "final"`, `sys.version_info.serial == 0`, and exact matches for `platform.python_implementation()`, `platform.python_compiler()`, `platform.platform()`, `platform.machine()`, `numpy.__version__`, and `scipy.__version__`; it refuses on any mismatch. Every receipt records them. Do not relax the comparison or reseal output from another runtime; a pre-spend runtime change requires a reviewed replacement registration.

### Frozen artifact blobs

Transplant these exact Git objects from `1201b799`:

| Path | Git blob | Canonical whole-payload SHA-256 | Internal receipt hash |
|---|---|---|---|
| `data/validation/valucast_prospect_v2_development_contract.json` | `2bd549347227235061c51444fdd709bd69153dee` | `df573b47d652eed14b8289919dbe2696cd7c9b96bd68c678fc124dabfa5a92b3` | `input_sha256=df573b47d652eed14b8289919dbe2696cd7c9b96bd68c678fc124dabfa5a92b3` |
| `data/models/valucast_prospect_model_v0_9.json` | `788ba04a054474430a4cdb01e3ac783795cfa088` | `90b8c303f011c48a4806aa8300d949e85ecb82999bf975ce5d3d3320c7f59663` | `artifact_sha256=048876c0f64365ae9960a3b1987558c9e190f4c2eec87b743bb52f2fd4146c4e` |
| `data/validation/valucast_prospect_rank_v2_1_development.json` | `195febb61a0867da213d2fca096d02e58289a218` | `a0b1fd17a08aa4b6d64854ee5a9ef92df79f6e76fd1aa4ae2de6a4d3d81dd7ba` | `artifact_sha256=cb2c518da530acf20d50766d1925eff6da52193227e15569c7479120e2c998db` |
| `data/validation/valucast_prospect_rank_v2_2_development.json` | `44e7d8a26259f06cdc9b5cfa5c48c9b5c9c4b214` | `fa9b58a55a3d950c52b8a23aeeb14ebf6d3731b873e9c4b2028ffd23f66b4178` | `artifact_sha256=9fc70d71e8d3cefa76506748c5dc9caa46ac083692320d2164ac137a95855191` |

Do not transplant the v0.8 model artifact, failed v3/v4 diagnostic maps, target-correction receipt, raw data refreshes, current artifacts, or 2022 confirmation manifest. The development contract, frozen v0.9 model, and two sealed terminal predecessor receipts are the minimal data closure.

### Exact research source blobs

Restore only these runtime dependencies from `1201b799`:

| Path | Git blob | Normalized-source SHA-256 |
|---|---|---|
| `prospects/prospect_v2_target.py` | `abb5b89bff8d41ca9079c2389f0da9a17eaf284b` | `d76b74ca7217fd6577d5149b253990b37690b74f2038e148d5a4ea9fea4ee39b` |
| `prospects/prospect_v2_candidate.py` | `e81583a336d6f64089887b0f3bdbefa38eb63909` | `7baa179c66fa6855272b3e0419ccbf1f8990450c87fc5f31990a2983c8fdcacc` |
| `prospects/prospect_v09.py` | `592d1fbc93e4bb0b13a10fae87507116acdb41c9` | `da56390d9c53c577cdf6ea070f16f106616da44874b8ea32b678210a35450dad` |
| `prospects/cross_role_calibration.py` | `bd83d626b8e039f3202e72ccf8c06a98fb7a3899` | `914d87cc33304619471792ba95a32af22140f666b92fd14fab97a0fa7863f73b` |
| `prospects/rank_v2.py` | `5907fe49246dc247eb777bfaab5fbcd2b3cb6d31` | `8f8435217fce43e77ae6b64115b04b36413d89cea53daab29a49108eb70261f2` |

The predecessor receipts retain their old ladder/joint modules and v2.1/v2.2 runners' hashes as immutable historical fields. Do not restore those unused executable files. They are not needed to validate the sealed receipts or run v2.3.

Relevant historical hashes remain:

```text
prospects/prospect_v2_candidate.py  7baa179c66fa6855272b3e0419ccbf1f8990450c87fc5f31990a2983c8fdcacc
prospects/prospect_v09.py           da56390d9c53c577cdf6ea070f16f106616da44874b8ea32b678210a35450dad
prospects/rank_v2.py                8f8435217fce43e77ae6b64115b04b36413d89cea53daab29a49108eb70261f2
prospects/rank_v1.py                ab8c44102b7750bd174f4080099ad1926950e38c88ad0ff609c25540328f4f1d
prospects/ladder_calibration.py      b5406fad7a77592711631c0ff79c33d7288a843a197423b149f859a84737703b
scripts/build_prospect_v21_candidate.py b1bbc29eaed6e425bd79f89d342808347e1f90509ff86babac59c420447799f5
prospects/joint_ladder_calibration.py b61b70a178f2e88554b19f40f7bed2531a74167d63e23ba81e2bfc4a78c29c81
scripts/build_prospect_v22_candidate.py 0e65ddaabd22555ae19b3ea0d77b5a5f30ff66366a95748c4d7b03c763c13c7d
```

The old v2.1 receipt's `prospects/rank_v1.py` hash describes its historical Windows checkout. Do not force the live current-master file to equal that platform-specific hash. Keep the receipt immutable, prove the current v1 wrapper's behavior is unchanged, and bind the final reviewed current-master reconstruction port separately in Plan 038.

## File map

### Shared lineage seam

- Modify: `prospects/stage1_contract.py`
- Modify: `prospects/rank_v1.py`
- Modify: `prospects/rank_backtest.py`
- Modify: `prospects/universe.py`
- Modify: `prospects/model.py`
- Modify: `prospects/impact_oof.py`
- Modify: `tests/test_stage1_contract.py`
- Modify: `tests/test_prospect_rank_v1.py`
- Modify: `tests/test_prospect_rank_backtest.py`
- Modify: `tests/test_prospect_model.py`
- Modify: `tests/test_impact_oof.py`
- Modify: `tests/test_stage1_outcome_proof.py`

### Frozen lineage files

- Create the five exact runtime source files and four exact JSON artifacts listed above.
- Restore the relevant predecessor tests from the reviewed research lineage:
  - `tests/test_prospect_v2_target.py`
  - `tests/test_prospect_rank_v2.py`
  - `tests/test_prospect_rank_v21.py`

Do not restore `tests/test_prospect_v2_candidate.py`, `tests/test_prospect_v09.py`, ladder/joint tests, or the old v2.1/v2.2 runner tests. The first two fit against the real outcome-bearing development contract; the others cover omitted diagnostic code or obsolete decision rules. New v2.3 tests exercise the transplanted candidate/v0.9 functions only with synthetic in-memory fixtures. `tests/test_prospect_v23_lineage.py` replaces the old lineage checks with portable Git-object validation while preserving the terminal receipts unchanged.

### New Phase A implementation

- Create: `prospects/role_slope_joint_calibration.py`
- Create: `scripts/build_prospect_v23_candidate.py`
- Create: `tests/test_prospect_v23_lineage.py`
- Create: `tests/test_role_slope_joint_calibration.py`
- Create: `tests/test_prospect_v23_development.py`

### Registration

- Create: `plans/038-prospect-vnext-phase-a.md`
- Modify: `plans/031-pitcher-strike-pct-gate.md`
- Modify: `plans/034-post-2026-prospect-challenger-epoch.md`
- Modify: `plans/README.md`
- Create: `data/validation/valucast_prospect_rank_v2_3_registration.json`

### Canonical outputs, absent until the authorized run

- Always terminal: `data/validation/valucast_prospect_rank_v2_3_development.json`
- Qualified only: `data/models/valucast_prospect_joint_ladder_calibrator_v5.json`

## Task 1: Transplant and lock the frozen lineage

**Files:** all shared-lineage and frozen-lineage files listed above; `tests/test_prospect_v23_lineage.py`.

- [ ] Start with a RED lineage test. It must fail because the four frozen artifacts and five v2 runtime modules do not yet exist.

Make the first failing assertion message contain `missing frozen Phase A dependency`; this gives the RED command an exact failure to adjudicate rather than treating any pytest failure as success.

The test must assert immutable byte provenance without JSON-decoding any of the four frozen predecessor payloads. It may decode and validate the new v2.3 receipt/map only after those outputs exist:

```python
EXPECTED_BLOBS = {
    "data/validation/valucast_prospect_v2_development_contract.json": "2bd549347227235061c51444fdd709bd69153dee",
    "data/models/valucast_prospect_model_v0_9.json": "788ba04a054474430a4cdb01e3ac783795cfa088",
    "data/validation/valucast_prospect_rank_v2_1_development.json": "195febb61a0867da213d2fca096d02e58289a218",
    "data/validation/valucast_prospect_rank_v2_2_development.json": "44e7d8a26259f06cdc9b5cfa5c48c9b5c9c4b214",
}

EXPECTED_SOURCE_BLOBS = {
    "prospects/prospect_v2_target.py": "abb5b89bff8d41ca9079c2389f0da9a17eaf284b",
    "prospects/prospect_v2_candidate.py": "e81583a336d6f64089887b0f3bdbefa38eb63909",
    "prospects/prospect_v09.py": "592d1fbc93e4bb0b13a10fae87507116acdb41c9",
    "prospects/cross_role_calibration.py": "bd83d626b8e039f3202e72ccf8c06a98fb7a3899",
    "prospects/rank_v2.py": "5907fe49246dc247eb777bfaab5fbcd2b3cb6d31",
}
```

Use `git hash-object --path=$relativePath $absolutePath` in the development-only test to compare index-normalized content with the registered Git object. Do not compare raw Windows checkout bytes.

Also assert the v2.3 output state is internally consistent: before any v2.3 receipt both canonical output paths are absent; a terminal qualified receipt requires the sealed map; terminal failed requires no map; terminal `spent_error` may have only the explicitly untrusted, untracked orphan described in Task 9. Keep the explicit pre-run `Test-Path` checks in Tasks 7 and 8. The exact Git blobs already bind the contract, targets, internal seals, and predecessor terminal states. Those semantics are validated by the canonical runner only after `outcome_access_spent`; no pre-registration test may call `json.loads` on the four frozen files, reconstruct a real fold, fit a real model/map, or calculate a v2.3 metric.

- [ ] Run the RED test:

```powershell
$redOutput = @(python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider tests/test_prospect_v23_lineage.py 2>&1)
$redExit = $LASTEXITCODE
$redOutput | Write-Output
if ($redExit -ne 1 -or (($redOutput -join "`n") -notmatch "missing frozen Phase A dependency")) {
    throw "Task 1 did not fail for the registered missing-dependency reason"
}
```

Expected result: fail on the first missing frozen path.

- [ ] Restore the exact new-only files and JSON objects mechanically from the Git object IDs above. Do not hand-reformat the large JSON files.

- [ ] Port only these reviewed shared seams:

1. `prospects/stage1_contract.py`

```python
def build_stage1_contract(
    prospect_model: dict,
    dynasty_layer: dict,
    expected_generated_at: str,
    *,
    state: str = "incumbent",
    expected_model_version: str = "0.6.1",
    expected_model_consumer: str = "prospect_rank_v1",
    expected_layer_consumer: str = "prospect_rank_v1",
    expected_score_source: str = "prospect_model_v0_6",
    expected_model_feed: bool = True,
    expected_layer_feed: bool = True,
) -> dict:
```

The default path must preserve v1 exactly. Candidate state must require every supplied expectation, reject mixed row sources, and never accept a feeding candidate artifact.

2. `prospects/rank_v1.py`

Extract the existing scorer into:

```python
def build_prospect_rank_from_stage1(
    prospect_universe: dict,
    stage1: dict,
    input_contract: dict,
    prospect_availability: dict | None = None,
    milb_history_by_key: dict | None = None,
    mlb_roster_status: dict | None = None,
    require_mlb_roster_status: bool = False,
    investment_evidence: dict | None = None,
    *,
    investment_permitted_use: str,
    rank_name: str,
    rank_version: str,
    score_source: str,
    model_score_field: str | None,
    normalize_role_quantiles: bool,
    manual_graduated_ids: set[str] | None = None,
    consensus_snapshots: dict[str, dict] | None = None,
) -> dict:
```

Keep `build_prospect_rank_v1` as a thin wrapper with the exact incumbent constants and behavior. Do not change weights, rounding, sort order, quantile normalization, bucket rules, or any current artifact.

3. `prospects/rank_backtest.py`

```python
def _eligible_fold_rows(
    contract: dict,
    test_year: int,
    *,
    mature_through: int | None = None,
) -> dict:

def build_fold_rank_context(
    contract: dict,
    test_year: int,
    *,
    mature_through: int | None = None,
) -> dict:
```

The legacy default remains unchanged. The explicit through-2021 development contract may reconstruct 2018, 2019, and 2021 only.

Port the research fold's exact factual target exclusion; without it, the historical pitcher replay attempts to fit quality-start rate from zero rows:

```python
unavailable_targets = set()
if mature_through is not None and not any(
    season.get("qs") is not None
    for key, values in clipped_seasons.items()
    if key.endswith("_pitcher")
    for season in values
):
    unavailable_targets.add(("pitcher", "representative_qs_per_180"))
```

Filter `TARGET_SPECS` by that set only inside the explicit historical fold path. Add a regression proving default/current behavior still retains `representative_qs_per_180`, explicit historical replay omits it when every clipped pitcher season lacks a non-null `qs`, and one factual non-null `qs` retains it.

4. `prospects/universe.py`

Add only `current_orgs: dict | None = None` as a keyword-only override. Passing `{}` must prevent historical fold reconstruction from reading current organization state.

5. `prospects/model.py` and `prospects/impact_oof.py`

Do not copy the global serving change from `6a9ac224`. Add one keyword-only research seam to the existing function:

```python
def train_impact_role(
    role: str,
    dataset_rows: list[dict],
    seasons_by_player: dict,
    references: dict,
    now: str | None = None,
    *,
    fold_local_evidence: bool = False,
    mature_through: int | None = None,
) -> dict:
```

When `fold_local_evidence` is false, execute the current `_walk_forward` path byte-for-byte. Only `rank_backtest.build_fold_rank_context` passes `fold_local_evidence=True` plus its explicit `mature_through`, which calls `impact_oof.fold_local_impact_oof`. Port only the `mature_through` forwarding needed by that call. Do not copy `served_impact_gate_certification`, limitation-removal, or current `build_shadow_model` changes from the research branch. Tests must spy that current v1 never calls the fold-local branch and that historical replay does.

- [ ] Preserve the exact `prospects/rank_v2.py` reconstruction API:

```python
def build_fold_contract(source_contract: dict, test_cohort: int) -> dict:

def reconstruct_fold_ladders(
    fold_contract: dict,
    pitcher_profiles: list[dict],
    test_cohort: int,
) -> dict:
```

`reconstruct_fold_ladders` must retain each incumbent row's emitted two-decimal `score`, original emitted `rank`, score source, role, name, and MLBAM identity. The v2.3 runner calls this helper directly.

- [ ] Add a narrow exemption to `tests/test_stage1_outcome_proof.py` for exactly these two root-relative, frozen, non-serving source files:

```text
prospects/prospect_v2_candidate.py
prospects/prospect_v09.py
```

The proof-import ban must continue to apply everywhere else. The exemption test must separately assert that neither file is imported by a production current-rank consumer and that current production still hardcodes v1 during Phase A. Do not add `prospects/current_rank.py` in this phase.

- [ ] Run the dependency and parity gates:

```powershell
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_prospect_v23_lineage.py `
  tests/test_prospect_v2_target.py `
  tests/test_prospect_rank_v2.py `
  tests/test_prospect_rank_v21.py
Assert-NativeSuccess "Task 1 frozen-lineage tests"

python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_prospect_rank_v1.py `
  tests/test_stage1_contract.py `
  tests/test_prospect_rank_backtest.py `
  tests/test_prospect_model.py `
  tests/test_impact_oof.py `
  tests/test_stage1_outcome_proof.py -k "importer or wrapper or fold or contract"
Assert-NativeSuccess "Task 1 v1 parity tests"
```

Expected result: all selected tests pass; canonical v1, v0.8, public, governor, registry, and v2.3 output paths remain unchanged/absent.

- [ ] Commit:

```powershell
$task1Paths = @(
  "prospects/stage1_contract.py",
  "prospects/rank_v1.py",
  "prospects/rank_backtest.py",
  "prospects/universe.py",
  "prospects/model.py",
  "prospects/impact_oof.py",
  "prospects/prospect_v2_target.py",
  "prospects/prospect_v2_candidate.py",
  "prospects/prospect_v09.py",
  "prospects/cross_role_calibration.py",
  "prospects/rank_v2.py",
  "data/validation/valucast_prospect_v2_development_contract.json",
  "data/models/valucast_prospect_model_v0_9.json",
  "data/validation/valucast_prospect_rank_v2_1_development.json",
  "data/validation/valucast_prospect_rank_v2_2_development.json",
  "tests/test_stage1_contract.py",
  "tests/test_prospect_rank_v1.py",
  "tests/test_prospect_rank_backtest.py",
  "tests/test_prospect_model.py",
  "tests/test_impact_oof.py",
  "tests/test_stage1_outcome_proof.py",
  "tests/test_prospect_v2_target.py",
  "tests/test_prospect_rank_v2.py",
  "tests/test_prospect_rank_v21.py",
  "tests/test_prospect_v23_lineage.py"
)
git add -- $task1Paths
Assert-NativeSuccess "stage Task 1"
git diff --cached --name-only
Assert-NativeSuccess "inspect Task 1 staged paths"
git commit -m "deps: transplant frozen prospect v23 lineage"
Assert-NativeSuccess "commit Task 1"
```

Before committing, reject the staged diff if it includes any forbidden path or any data file beyond the four frozen artifacts.

## Task 2: Implement the five-parameter role-slope calibrator

**Files:**

- Create: `prospects/role_slope_joint_calibration.py`
- Create: `tests/test_role_slope_joint_calibration.py`

- [ ] Write failing tests for the complete input and map contract.

Public interfaces:

```python
def fit_role_slope_joint_map(rows: list[dict]) -> dict:

def score_role_slope_joint_ladders(
    hitters: list[dict],
    pitchers: list[dict],
    mapping: dict,
) -> list[dict]:
```

The fitting row key set is exact:

```python
FIT_KEYS = {
    "mlbam_id",
    "role",
    "source_ladder_position",
    "ladder_score",
    "outcome",
    "target",
    "test_cohort",
}
```

Any missing or extra fitting key fails. This physically excludes name, market, consensus, current rank/value, governor, and role quota from fitting.

Test these invariants:

- both roles and all three outcome classes are present;
- identities are unique `(mlbam_id, role)` pairs;
- rows sort by fold `[2018, 2019, 2021]`, role `[hitter, pitcher]`, source position, numeric MLBAM ID;
- role means and population standard deviations use training rows only and `ddof=0`;
- hitter design rows are `[z, 0, 0]`; pitcher rows are `[0, z, 1]`;
- parameter vector is exactly `[tau_bust_role, log_gap, beta_hitter, beta_pitcher, gamma]`;
- both slopes are finite and strictly positive after the reused unconstrained fit;
- thresholds, offset, centers, scales, log likelihood, probabilities, and expected tiers are finite;
- scales are strictly positive;
- probabilities lie in `[0,1]` and sum to one;
- the source ladders are not mutated;
- scoring preserves within-role order and reports zero inversions;
- board order is unrounded expected tier descending, source position ascending, numeric MLBAM ID ascending;
- a resealed malformed map still fails validation;
- repeated fitting of the same rows is deterministic.

- [ ] Run the RED tests:

Keep the missing-module import inside the test body so pytest reports one failed test, not a collection error. The failure text must name `prospects.role_slope_joint_calibration`.

```powershell
$redOutput = @(python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider tests/test_role_slope_joint_calibration.py 2>&1)
$redExit = $LASTEXITCODE
$redOutput | Write-Output
if ($redExit -ne 1 -or (($redOutput -join "`n") -notmatch "prospects\.role_slope_joint_calibration")) {
    throw "Task 2 did not fail for the registered missing-module reason"
}
```

Expected result: import failure for the missing module.

- [ ] Implement the smallest module that passes by reusing only:

```python
from prospects.ordinal_calibration_power import (
    _expected_tier,
    _fit_ordered_logit,
    _ordered_probabilities,
)
from prospects.prospect_v2_target import canonical_sha256
```

Do not add a new optimizer, model class, config layer, or shared metric module.

The design matrix is:

```python
z = (ladder_score - role_mean) / role_scale
design = [z, 0.0, 0.0] if role == "hitter" else [0.0, z, 1.0]
```

Store only the fixed architecture, fitted parameters, thresholds, role standardization, row counts, full sorted fitting-row hash, optimizer receipt, and canonical artifact seal. Compute `training_rows_sha256 = canonical_sha256(sorted_fit_rows)` after projecting every row to the exact seven `FIT_KEYS` and applying the registered deterministic row order. When fitting rows are available, validation must recompute this hash; an identity-only hash is insufficient. The map contract is exact:

```python
{
    "schema": "valucast_prospect_role_slope_joint_ladder_map_v1",
    "version": "1.0.0",
    "design": [
        "role_standardized_ladder_score:hitter",
        "role_standardized_ladder_score:pitcher",
        "is_pitcher",
    ],
    "params": [tau_bust_role, log_gap, beta_hitter, beta_pitcher, gamma],
    "thresholds": {"bust_role": tau_bust_role, "role_star": tau_role_star},
    "role_slopes": {"hitter": beta_hitter, "pitcher": beta_pitcher},
    "pitcher_offset": gamma,
    "role_standardization": {
        "hitter": {"mean": hitter_mean, "std": hitter_std},
        "pitcher": {"mean": pitcher_mean, "std": pitcher_std},
    },
    "row_count": row_count,
    "row_count_by_role": {"hitter": hitter_count, "pitcher": pitcher_count},
    "training_rows_sha256": training_rows_sha256,
    "iterations": iterations,
    "log_likelihood": log_likelihood,
    "artifact_sha256": artifact_sha256,
}
```

`artifact_sha256` is `canonical_sha256` of the object without that field. Validation requires the exact displayed top-level key set and exact nested key sets. Require a five-float finite `params`; derive `thresholds.bust_role == params[0]`, `thresholds.role_star == params[0] + exp(params[1])`, `role_slopes.hitter == params[2]`, `role_slopes.pitcher == params[3]`, and `pitcher_offset == params[4]`; require each positive slope/scale, integer positive role counts, `row_count == sum(row_count_by_role.values())`, and a lowercase 64-hex `training_rows_sha256`. Reject any mismatch even when the outer seal recomputes.

Scored rows preserve all source fields except they deliberately overwrite any inherited `rank` and `final_score`, then add/replace exactly `tier_probabilities={"bust", "role", "star"}`, `calibrated_expected_tier`, `calibrator_version`, and `calibrator_sha256`; the new `final_score` equals the unrounded calibrated expected tier. The product comparator never passes through this scorer and retains its original emitted rank/score. Adapt the v4 validator/scorer rather than inventing a second artifact vocabulary.

- [ ] Run focused and predecessor calibration tests:

```powershell
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_role_slope_joint_calibration.py `
  tests/test_ordinal_calibration_power.py
Assert-NativeSuccess "Task 2 calibration tests"
python -m ruff check prospects/role_slope_joint_calibration.py tests/test_role_slope_joint_calibration.py
Assert-NativeSuccess "Task 2 Ruff"
```

- [ ] Commit:

```powershell
git add prospects/role_slope_joint_calibration.py tests/test_role_slope_joint_calibration.py
Assert-NativeSuccess "stage Task 2"
git commit -m "feat: add prospect v23 role-slope calibration"
Assert-NativeSuccess "commit Task 2"
```

## Task 3: Build the exact three-fold evaluator and product comparator

**Files:**

- Create: `scripts/build_prospect_v23_candidate.py`
- Create: `tests/test_prospect_v23_development.py`

- [ ] Write RED tests for these pure interfaces:

```python
def reconstruct_development_ladders(
    contract: dict,
    v09_model: dict,
) -> dict[int, dict]:

def reconstruct_product_board(
    incumbent_hitters: list[dict],
    incumbent_pitchers: list[dict],
) -> list[dict]:

def align_by_identity(
    reference: list[dict],
    rows: list[dict],
    label: str,
) -> list[dict]:

def mae(rows: list[dict], score_field: str) -> float:

def cross_role_concordance(rows: list[dict], score_field: str) -> float:

def top25_target_sum(rows: list[dict], *, product: bool = False) -> float:

def build_fold_result(
    year: int,
    ladders: dict[int, dict],
    candidate_map: dict,
    control_map: dict,
) -> dict:

def development_qualification(report: dict) -> dict:
```

- [ ] Pin the fold contract exactly:

```python
DEVELOPMENT_FOLDS = (2018, 2019, 2021)
TRAINING_FOLDS_BY_TEST = {
    2018: (2019, 2021),
    2019: (2018, 2021),
    2021: (2018, 2019),
}
```

For each held-out fold:

- candidate = v1 hitters plus frozen v0.9 pitchers;
- the frozen v0.9 pitcher ladder comes only from the sealed artifact's existing `oof_rows`, filtered by `role == "pitcher"` and `test_cohort`; this path must never call `fit_v09_model`, refit v0.9, or substitute current-profile rows;
- controlled comparator = v1 hitters plus v1 pitchers;
- candidate and control independently fit their own five-parameter map on exactly the other two folds;
- product comparator = held-out incumbent hitters and pitchers sorted by `(-emitted two-decimal score, score-source order, role, name, numeric MLBAM ID)`;
- the rebuilt product board must retain original emitted ranks exactly `1..n`;
- all three boards must have the exact same identities and targets.

- [ ] Implement and hand-check the metrics:

```text
MAE = mean(abs(expected_tier - target))

Cross-role concordance:
  hitter-pitcher pairs only
  exclude equal targets
  correct ordering = 1
  reversed ordering = 0
  exact score tie = 0.5
  undefined if no eligible pair
```

Product scores are not probabilities. Never compute product-comparator MAE.

Top-25 selection is exact:

- candidate/control: first 25 under unrounded calibrated order;
- product: original emitted ranks `1..25`;
- fewer than 25 rows or any selection other than exactly 25 fails closed.

- [ ] Pin all six per-fold gates:

```text
candidate_mae - control_mae < 0
candidate_concordance - control_concordance > 0
candidate_concordance > 0.5
candidate_concordance - product_concordance > 0
candidate_top25_target_sum >= control_top25_target_sum
candidate_top25_target_sum >= product_top25_target_sum
```

Every rule applies independently in all three folds. No pooled mean, summary, or majority can rescue a failed fold.

Tests must individually flip each operator, exercise equality at every strict boundary, reorder identities adversarially, duplicate/drop an identity, change a target, break the v1 product tie order, and show that held-out target mutation cannot alter either fitted map.

- [ ] Run the RED tests:

Keep the missing-runner import inside the test body so pytest reports one failed test, not a collection error. The failure text must name `scripts.build_prospect_v23_candidate`.

```powershell
$redOutput = @(python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider tests/test_prospect_v23_development.py -k "fold or product or identity or concordance or top25" 2>&1)
$redExit = $LASTEXITCODE
$redOutput | Write-Output
if ($redExit -ne 1 -or (($redOutput -join "`n") -notmatch "scripts\.build_prospect_v23_candidate")) {
    throw "Task 3 did not fail for the registered missing-runner reason"
}
```

Expected result: import failure for the missing runner.

- [ ] Implement only the pure reconstruction, comparator, metrics, and fold verdict. Do not add file I/O or call `main()` yet.

- [ ] Run the focused suite:

```powershell
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_prospect_v23_development.py -k "fold or product or identity or concordance or top25"
Assert-NativeSuccess "Task 3 development tests"
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_prospect_v23_lineage.py `
  tests/test_role_slope_joint_calibration.py
Assert-NativeSuccess "Task 3 lineage/calibrator tests"
python -m ruff check scripts/build_prospect_v23_candidate.py tests/test_prospect_v23_development.py
Assert-NativeSuccess "Task 3 Ruff"
```

- [ ] Commit:

```powershell
git add scripts/build_prospect_v23_candidate.py tests/test_prospect_v23_development.py
Assert-NativeSuccess "stage Task 3"
git commit -m "feat: add prospect v23 combined-board screen"
Assert-NativeSuccess "commit Task 3"
```

## Task 4: Add the single deterministic bootstrap and mandatory pooled fit

**Files:**

- Modify: `scripts/build_prospect_v23_candidate.py`
- Modify: `tests/test_prospect_v23_development.py`

- [ ] Add RED tests for:

```python
def build_bootstrap_summary(
    folds: dict,
    *,
    seed: int = 39017,
    replicates: int = 10_000,
) -> dict:

def build_development_artifacts(
    contract: dict,
    model: dict,
    registration: dict,
) -> tuple[dict, dict | None]:
```

- [ ] Build one bootstrap plan per replicate from one stream:

```python
rng = np.random.default_rng(39017)
```

For every replicate:

1. iterate folds `[2018, 2019, 2021]`;
2. within each fold, iterate roles `[hitter, pitcher]`;
3. sort numeric MLBAM IDs ascending;
4. call `rng.choice(ids, size=len(ids), replace=True)` once;
5. reuse the resulting identities and multiplicities for candidate, control, product, and every metric;
6. do not refit any map;
7. calculate each fold delta and equal-weight the three fold deltas.

Track valid replicates separately for:

```text
candidate-minus-control MAE
candidate-minus-control concordance
candidate-minus-product concordance
```

Use exactly:

```python
np.percentile(values, [2.5, 97.5], method="linear")
```

Discard an undefined replicate only for the affected metric. Fail unless each metric retains at least `9_900` valid replicates.

Strict pooled gates:

```text
MAE interval upper bound < 0
control-concordance interval lower bound > 0
product-concordance interval lower bound > 0
```

Tests must prove the sample plan is deterministic, built once, shared across all metrics/comparators, respects multiplicity, does not refit, uses linear percentiles, and fails each bound and valid-count floor independently.

- [ ] Add the mandatory pooled-development fit:

- Call `fit_role_slope_joint_map(pooled_candidate_rows)` exactly once on all candidate hitter/pitcher rows from 2018, 2019, and 2021.
- Call it only after every fold rule and pooled interval passes.
- Do not fit a pooled control map.
- A controlled optimizer/map-validation failure is a completed scientific `failed` result with `failed_structural: ["pooled_final_fit"]`; an unexpected infrastructure exception follows the post-marker `spent_error` path. Both are terminal and nonqualified.
- `development_qualified` may be `true` only after the pooled map validates and seals.

- [ ] Freeze the arithmetic, not just the verdict. Every completed scientific receipt contains this exact deterministic `result` key set; no extra or missing keys are allowed:

```text
{
  "fold_order": [2018, 2019, 2021],
  "folds": {
    "<each of 2018, 2019, 2021>": {
      "status": "<completed | structural_failure>",
      "failure_stage": "<registered stage | null>",
      "identity_count_by_role": {"hitter": "<positive integer>", "pitcher": "<positive integer>"},
      "identity_sha256_by_role": {"hitter": "<64-hex>", "pitcher": "<64-hex>"},
      "target_sha256": "<64-hex>",
      "metrics": {
        "candidate_mae": "<finite number | null>",
        "control_mae": "<finite number | null>",
        "candidate_control_mae_delta": "<finite number | null>",
        "candidate_concordance": "<finite number | null>",
        "control_concordance": "<finite number | null>",
        "product_concordance": "<finite number | null>",
        "candidate_control_concordance_delta": "<finite number | null>",
        "candidate_product_concordance_delta": "<finite number | null>",
        "candidate_top25_target_sum": "<finite number | null>",
        "control_top25_target_sum": "<finite number | null>",
        "product_top25_target_sum": "<finite number | null>"
      },
      "gates": {
        "candidate_control_mae": "<boolean | null>",
        "candidate_control_concordance": "<boolean | null>",
        "candidate_concordance_floor": "<boolean | null>",
        "candidate_product_concordance": "<boolean | null>",
        "candidate_control_top25": "<boolean | null>",
        "candidate_product_top25": "<boolean | null>"
      },
      "structural_checks": {
        "identity_sets_equal": "<boolean | null>",
        "targets_equal": "<boolean | null>",
        "candidate_map_valid": "<boolean | null>",
        "control_map_valid": "<boolean | null>",
        "product_rank_reproduced": "<boolean | null>",
        "top25_complete": "<boolean | null>"
      },
      "failed_gates": [],
      "failed_structural": []
    }
  },
  "bootstrap": {
    "status": "<completed | not_attempted_fold_failure>",
    "seed": 39017,
    "replicates": 10000,
    "minimum_valid_replicates": 9900,
    "interval": {"lower_percentile": 2.5, "upper_percentile": 97.5, "method": "linear"},
    "sample_plan_sha256": "<64-hex | null>",
    "metrics": {
      "candidate_control_mae_delta": {"point": "<finite number | null>", "lower": "<finite number | null>", "upper": "<finite number | null>", "valid_replicates": "<integer | null>", "gate_passed": "<boolean | null>"},
      "candidate_control_concordance_delta": {"point": "<finite number | null>", "lower": "<finite number | null>", "upper": "<finite number | null>", "valid_replicates": "<integer | null>", "gate_passed": "<boolean | null>"},
      "candidate_product_concordance_delta": {"point": "<finite number | null>", "lower": "<finite number | null>", "upper": "<finite number | null>", "valid_replicates": "<integer | null>", "gate_passed": "<boolean | null>"}
    }
  },
  "failed_folds": [],
  "failed_bootstrap": [],
  "failed_structural": [],
  "pooled_fit": {"attempted": "<boolean>", "status": "<not_attempted_qualification_failure | validated | failed>", "row_count": "<integer>", "training_rows_sha256": "<64-hex | null>", "map_artifact_sha256": "<64-hex | null>"}
}
```

The angle-bracket values are schema notation, not output strings. The actual `folds` object has exactly the keys `2018`, `2019`, and `2021`, each with the identical fold-result key set shown. Compute each fold's `target_sha256` as canonical JSON over sorted `[numeric_mlbam_id, role, target]` rows. A `completed` fold requires every metric and gate to be non-null. A `structural_failure` fold sets `failure_stage` to exactly one of `identity_alignment`, `target_alignment`, `candidate_map`, `control_map`, `product_reconstruction`, `metric_contract`, or `top25_contract`; only values downstream of that stage are null, the failed check is false, and `failed_structural` contains that stage. Ordinary gate failures still have a `completed` fold with complete arithmetic. Bootstrap runs whenever all folds are `completed`, even when an ordinary fold gate fails; otherwise its status is `not_attempted_fold_failure` and its sample-plan hash and metric values are null. Failed lists use the registered fold/gate order. `pooled_fit.status` is exactly `not_attempted_qualification_failure`, `validated`, or `failed`; not-attempted uses row count `0` and null hashes, validated carries both exact hashes, and failed carries the attempted row count/training hash but a null map hash. A terminal `spent_error` instead has `result: null` plus a sealed `error` object containing stage, exception type, and message. The receipt's `artifact_sha256` covers the entire result/error object. `--reproduce` and the independent result review must rebuild and compare the completed `result` and optional map exactly.

- [ ] Run focused tests:

```powershell
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider tests/test_prospect_v23_development.py -k "bootstrap or pooled or qualification or final_fit"
Assert-NativeSuccess "Task 4 pooled tests"
```

Expected result after implementation: pass, with the synthetic spy proving one pooled fit only.

- [ ] Commit:

```powershell
git add scripts/build_prospect_v23_candidate.py tests/test_prospect_v23_development.py
Assert-NativeSuccess "stage Task 4"
git commit -m "feat: seal prospect v23 pooled qualification"
Assert-NativeSuccess "commit Task 4"
```

## Task 5: Seal the canonical one-run state machine

**Files:**

- Modify: `scripts/build_prospect_v23_candidate.py`
- Modify: `tests/test_prospect_v23_development.py`

- [ ] Use one positive data-read allowlist, not a denylist:

```python
CANONICAL_READ_PATHS = (
    "data/validation/valucast_prospect_rank_v2_3_registration.json",
    "data/validation/valucast_prospect_v2_development_contract.json",
    "data/models/valucast_prospect_model_v0_9.json",
    "data/validation/valucast_prospect_rank_v2_1_development.json",
    "data/validation/valucast_prospect_rank_v2_2_development.json",
)
```

Reproduction may additionally read the terminal receipt and, on qualification, the v5 pooled map. Every application-data read goes through the same allowlist-enforcing loader. Code files are validated separately against the registration's canonical source hashes.

Treat items 2-5 as outcome-bearing. In the canonical runner, the registration is the only application-data payload that may be decoded before the durable spent marker. Pre-registration infrastructure checks may compare exact Git objects and normalized source hashes, but may not semantically decode row-level frozen inputs, reconstruct real folds, fit real models/maps, or compute any v2.3 metric.

- [ ] Implement this exact state graph in the canonical receipt path:

```text
absent
  -> reserved
  -> outcome_access_spent
       |-> completed(status=qualified, development_qualified=true)
       |-> completed(status=failed, development_qualified=false)
       `-> spent_error
```

Rules:

- every normal, resume, recovery, and reproduction invocation acquires one nonblocking OS-held exclusive lock for its entire lifetime; resolve the repository-wide path as `Path(git rev-parse --path-format=absolute --git-common-dir) / "valucast-prospect-v23.lock"` so linked worktrees serialize against the same file, and never implement check-then-replace without this lock;
- on Windows open the lock as `a+b`, ensure it contains at least one byte, flush, seek to byte zero, and hold `msvcrt.locking(..., LK_NBLCK, 1)` until cleanup unlocks that same byte; on POSIX hold `fcntl.flock(..., LOCK_EX | LOCK_NB)` on the same open handle;
- the lock file may persist, but the OS releases the lock on process exit/crash; never delete the lock file while another process could hold it;
- resolve an immutable repository-wide spend token beside the lock at `Path(git_common_dir) / "valucast-prospect-v23-spent.json"`; it binds registration id/hash, execution SHA, resolved execution-worktree root, runtime tuple, and its own canonical seal;
- normal invocation requires `VALUCAST_V23_APPROVED_EXECUTION_SHA`, validates it as exactly 40 lowercase hexadecimal characters equal to current `HEAD`, requires that spend token and canonical outputs are absent, then exclusively creates `reserved` after validating that approved execution SHA, registration seal, exact input/source Git blob identities, normalized source hashes, runtime, arguments, and output absence without decoding frozen JSON;
- a second normal invocation always refuses;
- `--resume-reserved` accepts only `reserved` and an absent spend token; it requires the same `VALUCAST_V23_APPROVED_EXECUTION_SHA`, which must equal both current `HEAD` and the receipt's recorded SHA, then before spending verifies the registration seal, exact Git blob identities, normalized source hashes, runtime, and output absence without decoding any frozen JSON payload;
- immediately before the first outcome-bearing open, atomically publish the sealed spend token under the common-dir lock, then atomically replace the worktree receipt `reserved` with `outcome_access_spent`; only after both are durable may any outcome-bearing file open;
- the spend token is never deleted, replaced, or weakened; every normal/resume invocation in every linked worktree refuses once it exists, and the terminal receipt records its exact SHA-256;
- after that marker, decode each frozen payload exactly once and validate every registered canonical/internal hash before using any row or reconstructing any fold; any mismatch is terminal `spent_error`, never a new look;
- after the byte/seal checks, call the transplanted `prospects.prospect_v2_target.validate_development_contract(contract)` exactly once and require `[]`; it already checks the full schema, source policy, row/role counts, horizon, thresholds, and re-derives every outcome from frozen seasons; validate each predecessor receipt as terminal/non-serving before reconstructing a fold;
- any caught post-marker exception becomes terminal `spent_error` with stage, exception type, and message;
- expected model/metric contract failures are converted inside the pure evaluator into a completed scientific `failed` payload; only unexpected execution/I/O exceptions use `spent_error`;
- `--seal-interrupted-spend` accepts only a matching immutable spend token plus the bound execution worktree's `reserved` or `outcome_access_spent` receipt; after acquiring the lock, it converts that abandoned state to `spent_error` without reopening inputs or recomputing; a live process cannot lose the lock and therefore cannot be misclassified;
- completed pass, completed failure, and `spent_error` refuse every normal/resume invocation;
- `--reproduce` accepts only a completed receipt, recomputes from frozen inputs, compares the sealed payload/map exactly, writes nothing, and accepts no knobs;
- runtime CLI arguments other than no arguments, `--resume-reserved`, `--seal-interrupted-spend`, or `--reproduce` fail.

The environment variable is transport, not a model knob: Plan 038 binds its exact name and validation rule. `--seal-interrupted-spend` requires it to equal the spend token and receipt execution SHA; `--reproduce` instead validates the immutable execution SHA already sealed in the terminal receipt so later result commits can reproduce without pretending their `HEAD` is the execution commit.

- [ ] Make the terminal receipt the commit marker.

Canonical paths:

```python
RECEIPT_PATH = ROOT / "data" / "validation" / "valucast_prospect_rank_v2_3_development.json"
CALIBRATOR_PATH = ROOT / "data" / "models" / "valucast_prospect_joint_ladder_calibrator_v5.json"
```

Every durable receipt state uses schema `valucast_prospect_rank_v2_3_development_v1` and includes `registration_id`, `execution_sha`, the exact runtime tuple, `status`, `stage`, `development_qualified`, `cli_exit_code`, and `artifact_sha256`. `development_qualified` and `cli_exit_code` are `null` while reserved/spent. In terminal states, `development_qualified` is boolean and `cli_exit_code` is exactly `0` for qualified, `1` for completed scientific failure, or `2` for `spent_error`; `development_qualified` is always `false` for `spent_error`. Seal the canonical object without `artifact_sha256`, then require an exact recomputation before every transition or staging decision.

Write behavior:

- render JSON with `allow_nan=False`;
- write a same-directory temporary file;
- flush and `fsync` it;
- confirm the expected prior receipt state;
- publish with `os.replace`;
- best-effort directory `fsync`;
- remove any leftover temporary file.

On qualification, publish the sealed v5 pooled map first, then finalize the receipt containing its exact hash. On scientific failure, publish only the receipt. An orphan map beside a spent/error receipt is inert and never justifies a rerun.

Both terminal payloads must contain `feeds_live_rank: false` and `feeds_value: false`. The receipt must contain the literal `development_qualified` boolean; `status` is not a substitute.

- [ ] Add protocol tests:

- first outcome-bearing open observes `outcome_access_spent`;
- concurrent reservation loses before outcome access;
- concurrent `--resume-reserved` loses the OS lock before reading or changing the receipt;
- concurrent invocations from two different linked worktrees resolve the same Git-common-dir lock and only one enters;
- a missing, malformed, wrong-HEAD, or receipt-mismatched `VALUCAST_V23_APPROVED_EXECUTION_SHA` refuses before outcome access;
- after one worktree publishes the common spend token, a sequential normal/resume invocation from a second linked worktree refuses permanently even if its local canonical output path is absent;
- a live process holding the lock with an `outcome_access_spent` receipt cannot be reclassified by a second process;
- pre-marker error remains resumable only with unchanged execution SHA, registration seal, input/source Git blob identities, normalized source hashes, runtime, arguments, and output absence;
- post-marker exception becomes `spent_error`;
- interrupted spent state becomes `spent_error` without recomputation;
- atomic-replace failure preserves the prior durable state;
- completed scientific failure writes no v5 map; a forced failure after map publication but before terminal-receipt publication leaves an orphan map and recovers only to `spent_error`;
- pass writes map first and receipt last;
- reproduction is byte/payload exact and writes nothing;
- `test_terminal_receipt_schema_and_seal` rejects every malformed state/schema/seal and accepts each exact terminal branch;
- tests monkeypatch every path into a temporary D: directory and never invoke canonical `main()`.

- [ ] Run all new Phase A tests:

```powershell
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_prospect_v23_lineage.py `
  tests/test_role_slope_joint_calibration.py `
  tests/test_prospect_v23_development.py
Assert-NativeSuccess "Task 5 Phase A tests"
python -m ruff check `
  prospects/role_slope_joint_calibration.py `
  scripts/build_prospect_v23_candidate.py `
  tests/test_prospect_v23_lineage.py `
  tests/test_role_slope_joint_calibration.py `
  tests/test_prospect_v23_development.py
Assert-NativeSuccess "Task 5 Ruff"
python -m compileall -q `
  prospects/role_slope_joint_calibration.py `
  scripts/build_prospect_v23_candidate.py
Assert-NativeSuccess "Task 5 compile"
```

- [ ] Commit:

```powershell
git add scripts/build_prospect_v23_candidate.py tests/test_prospect_v23_development.py
Assert-NativeSuccess "stage Task 5"
git commit -m "fix: seal prospect v23 one-run protocol"
Assert-NativeSuccess "commit Task 5"
```

## Task 6: Review the implementation before registration

No registration exists yet, so substantive code corrections remain ordinary reviewed implementation changes rather than amendments to a registered hypothesis.

- [ ] Run the complete focused compatibility gate:

```powershell
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_prospect_v23_lineage.py `
  tests/test_role_slope_joint_calibration.py `
  tests/test_prospect_v23_development.py `
  tests/test_prospect_rank_v1.py `
  tests/test_stage1_contract.py `
  tests/test_prospect_rank_backtest.py `
  tests/test_prospect_model.py `
  tests/test_impact_oof.py `
  tests/test_prospect_v2_target.py `
  tests/test_prospect_rank_v2.py `
  tests/test_prospect_rank_v21.py `
  tests/test_ordinal_calibration_power.py
Assert-NativeSuccess "Task 6 focused compatibility tests"

python -m ruff check prospects scripts tests
Assert-NativeSuccess "Task 6 Ruff"
python -m compileall -q prospects scripts
Assert-NativeSuccess "Task 6 compile"
git diff --check
Assert-NativeSuccess "Task 6 diff check"
git status --short
Assert-NativeSuccess "Task 6 status"
```

- [ ] Run the full suite once before registration:

```powershell
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider
Assert-NativeSuccess "Task 6 full suite"
```

- [ ] Ask an independent reviewer to inspect:

- dependency minimality and forbidden-path diff;
- v1 wrapper parity and fold-local evidence;
- exact product comparator/tie semantics;
- all six per-fold gates;
- bootstrap sample-plan reuse and confidence bounds;
- no fitting input outside the exact seven-key schema;
- output/state-machine ordering;
- absence of both canonical v2.3 outputs; and
- proof that no metric-bearing canonical build was invoked.

- [ ] Apply any approved correction, rerun the affected focused suites and full suite, and commit narrowly. Do not create the registration until this review is PASS.

## Task 7: Register Plan 038 and retire conflicting model tracks

**Files:** registration files listed in the File map.

Use Plan 038 because `plans/037-pre2014-cross-role-calibration-supersession.md` already exists on `origin/codex/pitcher-model-repair`; do not create a second Plan 037 identity.

- [ ] Create `plans/038-prospect-vnext-phase-a.md` with status `REGISTERED - UNSPENT - NO EXECUTION AUTHORIZED`.

It must bind:

- the approved design commit;
- the final implementation commit;
- candidate architecture and exact parameter order;
- the exact four-year `0/.5/1` outcome target and its PA/IP/OPS/ERA thresholds;
- folds and `TRAINING_FOLDS_BY_TEST`;
- per-fold identity counts and canonical identity hashes by role;
- the three comparator contracts and sort orders;
- all six per-fold rules and strict operators;
- top-25 mechanics;
- bootstrap seed, stream/order, replicate count, valid floor, percentile method, and no-refit rule;
- a seed-hygiene receipt proving the standalone integer token `39017`, matched as `(^|[^0-9])39017([^0-9]|$)`, and every structured seed field have no occurrence in Git ancestry strictly before approved design commit `1737468b16717ee6f7d24ea08b8444fdde3442f2`; decimal substrings such as `0.390174` do not count. The receipt also proves the integer is absent from every forbidden/held/spent/reserved seed set and appears after that commit only in the enumerated design, implementation plan, registration, runner, tests, and terminal receipt;
- mandatory pooled fit;
- the exact canonical CPython/Windows/AMD64/NumPy/SciPy runtime tuple;
- exact positive read allowlist;
- code, JSON, artifact, and Git blob bindings;
- output paths, repository-common lock/spend-token paths, and state machine;
- owner-approved execution-SHA transport through required environment variable `VALUCAST_V23_APPROVED_EXECUTION_SHA`, including exact validation in normal/resume/recovery modes;
- CLI exit mapping exactly `0=qualified`, `1=completed scientific failed`, `2=protocol/infrastructure/spent_error`, with every other exit invalid;
- forbidden inputs and forbidden production paths;
- non-serving fields; and
- result mapping: qualified, failed, or spent_error, all terminal.

The registration must copy—not newly derive—the already-reviewed held-out identity-set receipts below. Hash exactly
`canonical_sha256(sorted([[int(row["mlbam_id"]), str(row["role"])] for row in role_rows]))`, where canonical JSON uses `sort_keys=True`, `separators=(",", ":")`, and `ensure_ascii=False`, and `role_rows` is restricted to one held-out fold and one role. Candidate and both comparators must reproduce the same identity set in every cell after the spend marker.

| Fold | Role | Count | Identity-set SHA-256 |
|---:|---|---:|---|
| 2018 | hitter | 345 | `6169bf1c3de6430b74e1d3b425aac491bfcbd364a13afe12abcbc8b2b7c838d0` |
| 2018 | pitcher | 352 | `d5214fdfc761a84dc21702aa76aee7c302ea635c9d722235f1de3b5631dd5b76` |
| 2019 | hitter | 360 | `fccc74b819ff48c03402e0d8b791a18bef43a67470b749dd26de3f651b7d059a` |
| 2019 | pitcher | 410 | `e49cf8d1b6419bb7b1ce989223f51ae5a96178ef10f2616a42d41ce411462958` |
| 2021 | hitter | 386 | `f0b4610897c4d5564259aa06c19c394b03a7f72d11e992028588eb4b6efbf21d` |
| 2021 | pitcher | 365 | `55f9a77380bcf8159b32dd54b7b17c1fbd3bff9a9e59e57c994060b3c85ccd27` |

Before registration, tests may compare these literal registration values but may not regenerate them from the real contract. The canonical runner regenerates and verifies them only after `outcome_access_spent`.

- [ ] Create the machine-readable mirror at `data/validation/valucast_prospect_rank_v2_3_registration.json`.

Minimum top-level schema:

```json
{
  "schema": "valucast_prospect_rank_v2_3_registration_v1",
  "registration_id": "plan_038_prospect_vnext_phase_a",
  "registration_status_at_seal": "registered_unspent",
  "candidate": {},
  "predecessors": {},
  "inputs": {},
  "sources": {},
  "folds": {},
  "comparators": {},
  "metrics": {},
  "bootstrap": {},
  "state_machine": {},
  "outputs": {},
  "forbidden_inputs": [],
  "forbidden_paths": [],
  "feeds_live_rank": false,
  "feeds_value": false
}
```

Treat that object as the unsigned payload, then add `artifact_sha256 = canonical_sha256(unsigned_payload)`. Validation requires exactly 64 lowercase hexadecimal characters and an exact recomputation match.

`registration_status_at_seal` is immutable historical metadata, not current status. After execution, current-status readers must use the terminal receipt plus the append-only Plan 038/index transition; they must never interpret the at-seal field as evidence that the look remains unspent.

- [ ] Record predecessor transitions append-only:

1. `plans/031-pitcher-strike-pct-gate.md`
   - model track superseded by Plan 038;
   - held seed `31013` was never executed and is retired forever;
   - bind the Git-history/search receipt proving no result artifact or runner invocation spent `31013`.

2. `plans/034-post-2026-prospect-challenger-epoch.md`
   - model-selection track superseded by Plan 038;
   - held seed `34021` is retired forever;
   - bind the Git-history/search receipt proving no result artifact or runner invocation spent `34021`;
   - separate `34027` buy-momentum and `34031` cross-universe tracks remain byte-for-byte unchanged and active, with a regression assertion over their registered subobjects.

3. `plans/README.md`
   - update Plan 031 and Plan 034 status text;
   - add Plan 038 as registered/unspent;
   - do not describe any metric result.

The machine registration stays immutable after merge. The later terminal-evidence commit appends the actual terminal status and receipt hash to Plan 038 and updates only Plan 038's status entry in `plans/README.md`; master must never continue to advertise `UNSPENT` after execution.

Also record the old local-only v2.3 documents `027a6efa` and `1201b799` as `superseded_unspent / retired_never_execute`; their runner is never authorized.

- [ ] Extend `tests/test_prospect_v23_development.py` so the runner validates the exact registration and refuses missing, extra, or altered fields, paths, rules, hashes, or identities.

- [ ] Run registration and no-output gates:

```powershell
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_prospect_v23_lineage.py `
  tests/test_prospect_v23_development.py
Assert-NativeSuccess "Task 7 registration tests"

if (Test-Path data/validation/valucast_prospect_rank_v2_3_development.json) {
    throw "v2.3 receipt exists before authorization"
}
if (Test-Path data/models/valucast_prospect_joint_ladder_calibrator_v5.json) {
    throw "v2.3 pooled map exists before authorization"
}
$registrationCommonDir = [IO.Path]::GetFullPath((git rev-parse --path-format=absolute --git-common-dir))
Assert-NativeSuccess "resolve registration Git common directory"
if (Test-Path -LiteralPath (Join-Path $registrationCommonDir "valucast-prospect-v23-spent.json")) {
    throw "v2.3 global spend token exists before registration review"
}
git diff --check
Assert-NativeSuccess "Task 7 diff check"
```

- [ ] Commit the registration separately:

```powershell
git add `
  plans/031-pitcher-strike-pct-gate.md `
  plans/034-post-2026-prospect-challenger-epoch.md `
  plans/038-prospect-vnext-phase-a.md `
  plans/README.md `
  data/validation/valucast_prospect_rank_v2_3_registration.json `
  tests/test_prospect_v23_development.py
Assert-NativeSuccess "stage Task 7"
git commit -m "data: register prospect v23 development screen"
Assert-NativeSuccess "commit Task 7"
```

From this commit forward, any substantive implementation or protocol correction requires a replacement unspent registration **only while v2.3 remains pre-spend**. Once any receipt reaches `outcome_access_spent` or a terminal state, v2.3 is globally closed: no replacement registration, seed, branch, path, or candidate may rerun it. Never silently edit the registered contract.

## Task 8: Independent pre-run review, PR, and master merge

- [ ] Have a fresh-context reviewer audit the exact registration commit for:

- code and input hashes;
- Git blob/canonical hash portability;
- arithmetic and gate operators;
- identity and target equality;
- bootstrap mechanics;
- allowlist and no-2022 boundary;
- receipt transitions and atomic writes;
- predecessor retirement;
- forbidden production paths; and
- absence of both outputs.

- [ ] Run the final inert infrastructure gate:

```powershell
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider
Assert-NativeSuccess "Task 8 full suite"
python -m ruff check prospects scripts tests
Assert-NativeSuccess "Task 8 Ruff"
git diff --check
Assert-NativeSuccess "Task 8 diff check"
git status --short --branch
Assert-NativeSuccess "Task 8 status"
```

Expected result: full suite green, clean branch, no canonical v2.3 output.

- [ ] Open a PR that contains only the approved design, Phase A infrastructure, frozen dependencies, tests, and registration. Require CI and the independent review to be green before merge.

- [ ] Merge the PR to master. Do not run the canonical builder from the feature branch.

- [ ] Create one fresh D: execution worktree and held result branch from the merged master, then verify:

```powershell
$executionPath = "D:\CodexWorktrees\valucast-v23-execution"
$resultBranch = "codex/prospect-v23-result"
if (Test-Path -LiteralPath $executionPath) { throw "execution path already exists" }
git -C D:\ValuCast fetch origin
if ($LASTEXITCODE -ne 0) { throw "origin fetch failed" }
git -C D:\ValuCast show-ref --verify --quiet "refs/heads/$resultBranch"
$localBranchStatus = $LASTEXITCODE
if ($localBranchStatus -eq 0) { throw "result branch already exists" }
if ($localBranchStatus -ne 1) { throw "local branch check failed" }
git -C D:\ValuCast ls-remote --exit-code --heads origin $resultBranch
$remoteBranchStatus = $LASTEXITCODE
if ($remoteBranchStatus -eq 0) { throw "remote result branch already exists" }
if ($remoteBranchStatus -ne 2) { throw "remote branch check failed" }
git -C D:\ValuCast worktree add -b $resultBranch $executionPath origin/master
Assert-NativeSuccess "create v2.3 execution worktree"
Set-Location -LiteralPath $executionPath
git status --short --branch
Assert-NativeSuccess "execution worktree status"
git diff --exit-code
Assert-NativeSuccess "execution worktree unstaged diff"
git diff --cached --exit-code
Assert-NativeSuccess "execution worktree staged diff"
$gitCommonDir = [IO.Path]::GetFullPath((git rev-parse --path-format=absolute --git-common-dir))
Assert-NativeSuccess "resolve Git common directory"
$spentToken = Join-Path $gitCommonDir "valucast-prospect-v23-spent.json"
if (Test-Path -LiteralPath $spentToken) { throw "v2.3 global spend token already exists" }
$registrationCommit = git log -1 --format=%H -- data/validation/valucast_prospect_rank_v2_3_registration.json
Assert-NativeSuccess "resolve v2.3 registration commit"
git merge-base --is-ancestor $registrationCommit origin/master
if ($LASTEXITCODE -ne 0) { throw "v2.3 registration is not merged to master" }

python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_prospect_v23_lineage.py `
  tests/test_role_slope_joint_calibration.py `
  tests/test_prospect_v23_development.py
Assert-NativeSuccess "Task 8 focused execution tests"
python -m ruff check `
  prospects/role_slope_joint_calibration.py `
  scripts/build_prospect_v23_candidate.py `
  tests/test_prospect_v23_lineage.py `
  tests/test_role_slope_joint_calibration.py `
  tests/test_prospect_v23_development.py
Assert-NativeSuccess "Task 8 focused Ruff"
python -m compileall -q `
  prospects/role_slope_joint_calibration.py `
  scripts/build_prospect_v23_candidate.py
Assert-NativeSuccess "Task 8 focused compile"
git diff --check
Assert-NativeSuccess "Task 8 execution diff check"

Test-Path data/validation/valucast_prospect_rank_v2_3_development.json
Test-Path data/models/valucast_prospect_joint_ladder_calibrator_v5.json
```

Expected result: both `Test-Path` calls print `False`.

- [ ] Capture `git rev-parse HEAD` as the proposed execution SHA and include that exact 40-character SHA in the independent pre-run review and owner-approval request.

- [ ] **STOP. Ask the owner for explicit authorization to execute that exact merged SHA.** Planning approval and PR approval are not execution approval. Do not infer the approved SHA from a later checkout; copy it from the approval record.

## Task 9: Execute exactly once and freeze the terminal result

Perform this task only after the owner explicitly authorizes the canonical run against the exact merged commit.

- [ ] Set `$approvedExecutionSha` to the exact 40-character SHA written in the owner approval, then enforce it before any runner invocation:

```powershell
$actualExecutionSha = git rev-parse HEAD
Assert-NativeSuccess "resolve execution HEAD"
if ($approvedExecutionSha -notmatch '^[0-9a-f]{40}$') {
    throw "owner-approved execution SHA must be exactly 40 lowercase hexadecimal characters"
}
if ($actualExecutionSha -ne $approvedExecutionSha) {
    throw "execution HEAD differs from the owner-approved SHA"
}
$executionStatus = git status --porcelain
Assert-NativeSuccess "execution clean-status check"
if ($executionStatus) {
    throw "execution worktree is not clean"
}
$env:VALUCAST_V23_APPROVED_EXECUTION_SHA = $approvedExecutionSha
```

Record `execution_sha=$approvedExecutionSha` in `reserved`, every later receipt state, and the terminal result. Re-run this equality check immediately before the command below.

- [ ] Invoke the canonical runner exactly once:

```powershell
if ($approvedExecutionSha -notmatch '^[0-9a-f]{40}$') { throw "reset the exact owner-approved execution SHA in this PowerShell process" }
$env:VALUCAST_V23_APPROVED_EXECUTION_SHA = $approvedExecutionSha
python -B scripts/build_prospect_v23_candidate.py
$runnerExit = $LASTEXITCODE
$receiptPath = "data/validation/valucast_prospect_rank_v2_3_development.json"
if (Test-Path -LiteralPath $receiptPath) {
    $postRunReceipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
    if ($postRunReceipt.status -in @("qualified", "failed", "spent_error") -and $runnerExit -ne [int]$postRunReceipt.cli_exit_code) {
        throw "canonical runner exit differs from its sealed terminal receipt"
    }
} else {
    throw "authorized canonical runner returned without creating a receipt; stop pre-spend and diagnose without retrying"
}
```

The registered CLI exit contract is `0=qualified`, `1=completed scientific failed`, `2=protocol/infrastructure/spent_error`; interpret it only with the sealed receipt. Any other exit code is invalid. This explicit capture is the exception to `Assert-NativeSuccess`.

Do not issue a second normal invocation. If and only if the command fails while the durable receipt still says `reserved`, the same owner authorization permits this one continuation after every registered binding and output condition is reverified:

```powershell
if ($approvedExecutionSha -notmatch '^[0-9a-f]{40}$') { throw "reset the exact owner-approved execution SHA in this PowerShell process" }
$env:VALUCAST_V23_APPROVED_EXECUTION_SHA = $approvedExecutionSha
python -B scripts/build_prospect_v23_candidate.py --resume-reserved
$runnerExit = $LASTEXITCODE
$postRunReceipt = Get-Content -Raw data/validation/valucast_prospect_rank_v2_3_development.json | ConvertFrom-Json
if ($postRunReceipt.status -in @("qualified", "failed", "spent_error") -and $runnerExit -ne [int]$postRunReceipt.cli_exit_code) {
    throw "resume exit differs from its sealed terminal receipt"
}
```

If the process stops after publishing the global spend token, wait until the original process is gone, then the one legal mutating recovery is:

```powershell
if ($approvedExecutionSha -notmatch '^[0-9a-f]{40}$') { throw "reset the exact owner-approved execution SHA in this PowerShell process" }
$env:VALUCAST_V23_APPROVED_EXECUTION_SHA = $approvedExecutionSha
python -B scripts/build_prospect_v23_candidate.py --seal-interrupted-spend
$runnerExit = $LASTEXITCODE
$postRunReceipt = Get-Content -Raw data/validation/valucast_prospect_rank_v2_3_development.json | ConvertFrom-Json
if ($postRunReceipt.status -ne "spent_error" -or $runnerExit -ne [int]$postRunReceipt.cli_exit_code) {
    throw "interrupted-spend recovery did not seal the registered exit contract"
}
```

That command may only seal `spent_error`; it may never reopen inputs or recompute.

- [ ] Interpret the terminal result mechanically:

- `qualified`: receipt exists with `development_qualified: true`; v5 pooled map exists and matches the receipt hash.
- `failed`: receipt exists with `development_qualified: false`; v5 pooled map is absent.
- `spent_error`: receipt records the terminal error; v5 pooled map is absent or inert and untrusted.

No result authorizes a second canonical run.

- [ ] For `qualified` or `failed`, run only non-mutating validators and reproduction:

```powershell
python -B scripts/build_prospect_v23_candidate.py --reproduce
Assert-NativeSuccess "reproduce v2.3 terminal result"
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_prospect_v23_lineage.py `
  tests/test_role_slope_joint_calibration.py `
  tests/test_prospect_v23_development.py
Assert-NativeSuccess "Task 9 terminal tests"
git diff --check
Assert-NativeSuccess "Task 9 diff check"
```

For `spent_error`, do not run `--reproduce`; validate only the receipt schema/seal and protected-path hashes. Run the state-aware lineage test after loading and validating the terminal receipt, as shown below.

- [ ] Append the observed terminal transition to `plans/038-prospect-vnext-phase-a.md`, recording exact status, receipt `artifact_sha256`, and execution SHA without editing the registered contract. Change only Plan 038's entry in `plans/README.md` from registered/unspent to the same terminal status.

- [ ] Commit the exact terminal evidence:

```powershell
$receiptPath = "data/validation/valucast_prospect_rank_v2_3_development.json"
python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider `
  tests/test_prospect_v23_development.py -k "terminal_receipt_schema_and_seal"
Assert-NativeSuccess "validate terminal receipt"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $receiptPath)) {
    throw "terminal receipt validation failed"
}
$receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
if ($receipt.schema -ne "valucast_prospect_rank_v2_3_development_v1") {
    throw "unexpected terminal receipt schema"
}
if ($receipt.status -notin @("qualified", "failed", "spent_error")) {
    throw "receipt is not terminal"
}
$expectedRunnerExit = switch ($receipt.status) {
    "qualified" { 0 }
    "failed" { 1 }
    "spent_error" { 2 }
}
if ([int]$receipt.cli_exit_code -ne $expectedRunnerExit) {
    throw "sealed terminal receipt carries the wrong CLI exit mapping"
}
if ($receipt.status -eq "spent_error") {
    python -B -m pytest --basetemp D:\CodexScratch\valucast-vnext-phase-a\pytest -q -p no:cacheprovider tests/test_prospect_v23_lineage.py
    Assert-NativeSuccess "validate spent-error protected paths"
}

# Append only the observed terminal transition; never rewrite the registered contract.
# Plan 038 records status, receipt artifact_sha256, and execution SHA.
# plans/README.md changes only Plan 038 from registered/unspent to its observed terminal status.
git add data/validation/valucast_prospect_rank_v2_3_development.json
Assert-NativeSuccess "stage v2.3 terminal receipt"
git add plans/038-prospect-vnext-phase-a.md plans/README.md
Assert-NativeSuccess "stage v2.3 terminal status docs"
if ($receipt.development_qualified -eq $true) {
    if (-not (Test-Path data/models/valucast_prospect_joint_ladder_calibrator_v5.json)) {
        throw "qualified receipt is missing the pooled map"
    }
    git add data/models/valucast_prospect_joint_ladder_calibrator_v5.json
    Assert-NativeSuccess "stage v2.3 pooled map"
} elseif ($receipt.status -eq "failed") {
    if (Test-Path data/models/valucast_prospect_joint_ladder_calibrator_v5.json) {
        throw "failed receipt unexpectedly produced a pooled map"
    }
} elseif ($receipt.status -eq "spent_error" -and (Test-Path data/models/valucast_prospect_joint_ladder_calibrator_v5.json)) {
    Get-FileHash -Algorithm SHA256 data/models/valucast_prospect_joint_ladder_calibrator_v5.json
    Write-Warning "Leaving the untrusted orphan map untracked for forensic review; do not add, move, delete, or trust it"
}
git diff --cached --name-only
Assert-NativeSuccess "inspect v2.3 result staged paths"
git commit -m "data: freeze prospect v23 development verdict"
Assert-NativeSuccess "commit v2.3 terminal result"
```

The staged file list must contain only the terminal receipt, the append-only Plan 038 and plan-index status updates, and, on qualification, the v5 pooled map.

- [ ] A different reviewer independently recomputes the pure payload, applies every registered rule by hand/code, checks the hashes and no-2022 boundary, verifies all production/current artifacts are unchanged, and writes a result review.

- [ ] Push the terminal-evidence-only commit to a held PR. Require the independent result review and CI to pass, then merge it. Verify current master contains the exact terminal receipt blob, matching Plan 038/index terminal status, and, only on qualification, the exact pooled-map blob. A local commit is not a durable frozen result.

- [ ] Close Phase A:

- If `failed` or `spent_error`: freeze the result, stop v2.3, keep v1 current, and propose no cutover work.
- If `qualified`: keep the result inert and ask for separate owner authorization to design Phase B for R1, R4, the vNext lineage pointer, two-vintage shadow burn-in, current-board construction, governor integration, and atomic cutover.

## Final acceptance

Phase A is complete only when all statements below are true:

- the approved design and exact registration preceded outcome access on master;
- the dependency closure is minimal and hash-bound;
- v1 production behavior and artifacts remained unchanged;
- the candidate used only the fixed v1 hitter ladder, frozen v0.9 pitcher ladder, and fixed five-parameter map;
- every per-fold rule and pooled bound was applied exactly;
- the product comparator reproduced emitted v1 score/rank semantics;
- the bootstrap used one registered sample stream and no refits;
- the receipt state proves one terminal execution history;
- only inert terminal evidence was committed;
- no Phase B, current-rank, R1, R4, governor, public, workflow, or deployment file changed; and
- a pass is described only as `development_qualified`, never `VALIDATED` or already current.
