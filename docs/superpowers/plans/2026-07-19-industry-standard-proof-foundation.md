# Industry-Standard Proof Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing competition benchmark into a private, preregistered proof engine that can authorize only scoped, anonymized ValuCast claims after the approved evidence gates pass.

**Architecture:** Reuse the existing file-based benchmark evaluator. Add the missing practical-effect, sample-floor, cohort-aware uncertainty, and role-segment gates; keep its ordinal results research-only because ordinal error is not an approved public primary metric; keep named captures and full row-level artifacts gitignored; derive a sanitized public artifact only from future authorized track-specific evaluators. This phase creates no public UI and changes no production model input.

**Tech Stack:** Python 3.10+, standard library, NumPy already used by the repository, pytest, Ruff, JSON artifacts.

## Global Constraints

- Preserve the current live model freeze and the failed decay flag.
- Comparison data must never affect production ranks, values, Role Watch, pitcher caps, or publication decisions.
- Competitor identities may exist only in the private evidence registry; never place them in app copy, share cards, social copy, public reports, marketing, or committed public artifacts.
- Predictions, eligible pools, outcomes, primary metrics, horizons, code versions, and input hashes must be frozen before outcomes.
- An industry-standard superiority claim requires at least three independent completed cohorts, 150 unique matched players, 90% outcome coverage, at least 5% relative primary-metric improvement, a cohort-aware paired 95% confidence interval excluding no difference, and no role or cohort more than 5% worse.
- Retrospective and exploratory results always remain claim-blocked.
- The current ordinal rank evaluator is exploratory. Only a later evaluator whose primary metric is `realized_value_regret` or `forward_rate_error` may request claim eligibility.
- Do not add a database, service, real-time comparison system, public scoreboard, or proprietary skill index.
- Do not push or dispatch a deploy workflow from this plan.

## Scope Split

This plan implements only the proof foundation. Challenger-model work requires separate registered plans after this foundation passes. Public distribution requires a separate plan after at least one claim is authorized. Until then, the sanitized public artifact is empty and no UI consumes it.

## File Map

- `prospects/competition_benchmark.py`: pure cohort construction, scoring, uncertainty, segment reporting, and deterministic claim policy.
- `scripts/build_competition_benchmark.py`: private-source loading, private artifact construction, public sanitization, validation, and atomic writes.
- `tests/test_competition_proof.py`: claim-boundary, immutability, privacy, and production-isolation contracts using anonymous synthetic sources.
- `.gitignore`: prevents named source registries, outcomes, and row-level benchmark artifacts from entering the public repository.
- `data/private/competition/`: gitignored named registry, outcomes, and row-level artifacts.
- `data/validation/valucast_competition_evidence.json`: sanitized aggregate artifact; committed only after its deterministic shape is established.
- `plans/032-competition-proof-lane.md`: generic registration and claim policy with no public source identities.
- `plans/README.md`: generic status summary.
- `docs/superpowers/specs/2026-07-19-competition-historical-replay-design.md`: generic retrospective description; source identity stays private.

---

### Task 1: Enforce the industry-standard claim gate

**Files:**
- Modify: `prospects/competition_benchmark.py:20-69`
- Modify: `prospects/competition_benchmark.py:104-283`
- Create: `tests/test_competition_proof.py`

**Interfaces:**
- Consumes: `build_cohort(..., valucast_rows: list[dict], competitor_rows: list[dict], ...) -> dict` rows with optional `role` values.
- Produces: `build_track(cohorts: list[dict], outcomes: dict[str, float], criteria: dict) -> dict` with `primary.relative_improvement_pct`, aggregate `segments`, and a fail-closed claim status.
- Produces: `_claim_decision(...) -> tuple[str, bool, str]`, returning public status, authorization, and statistical status from one policy boundary.

- [ ] **Step 1: Write failing policy tests**

Add the imports and tests below. Keep the small direct policy test so statistical fixture construction cannot obscure boundary errors.
Place the `_cohort` and `_outcomes` helpers shown below immediately after
`CRITERIA`, before the tests that call them.

```python
import copy

import pytest

from prospects.competition_benchmark import (
    MINIMUM_INDUSTRY_CLAIM_PLAYERS,
    _claim_decision,
    append_cohort,
    build_cohort,
    build_track,
)


CRITERIA = {
    "primary_metric": "ordinal_rank_error",
    "minimum_cohorts": 3,
    "minimum_unique_players": 150,
    "minimum_outcome_coverage": 0.90,
    "minimum_relative_improvement_pct": 5.0,
    "maximum_single_cohort_regression_pct": 5.0,
    "maximum_segment_regression_pct": 5.0,
    "top_k": 10,
    "bootstrap_seed": 32019,
    "bootstrap_resamples": 1_000,
}


def test_industry_claim_policy_requires_effect_ci_and_clean_subgroups():
    ready = {
        "evidence_ready": True,
        "ci_low": 0.01,
        "ci_high": 0.03,
        "relative_improvement_pct": 5.0,
        "cohort_regressions": [0.0, 2.0, 5.0],
        "segment_regressions": [1.0, 5.0],
        "top_k_non_regression": True,
        "claim_eligible": True,
        "criteria": {
            "minimum_relative_improvement_pct": 5.0,
            "maximum_single_cohort_regression_pct": 5.0,
            "maximum_segment_regression_pct": 5.0,
        },
    }

    assert _claim_decision(**ready) == (
        "validated_superiority",
        True,
        "validated_superiority",
    )

    for field, value in (
        ("relative_improvement_pct", 4.999),
        ("ci_low", 0.0),
        ("cohort_regressions", [5.001]),
        ("segment_regressions", [5.001]),
        ("top_k_non_regression", False),
    ):
        blocked = ready | {field: value}
        assert _claim_decision(**blocked) == (
            "no_significant_difference",
            False,
            "no_significant_difference",
        )

    research_only = ready | {"claim_eligible": False}
    assert _claim_decision(**research_only) == (
        "research_only",
        False,
        "validated_superiority",
    )


def test_industry_claim_floor_is_150_unique_players():
    assert MINIMUM_INDUSTRY_CLAIM_PLAYERS == 150


def test_build_cohort_preserves_role_for_guardrail_scoring():
    cohort = build_cohort(
        cohort_id="c1",
        registered_at="2026-07-19",
        track="test",
        valucast_rows=[
            {"mlbam_id": "1", "name": "One", "rank": 1, "role": "pitcher"}
        ],
        competitor_rows=[
            {"mlbam_id": "1", "name": "One", "rank": 2, "role": "pitcher"}
        ],
        sources={},
    )

    assert cohort["rows"][0]["role"] == "pitcher"


def test_append_cohort_rejects_a_changed_sealed_cohort():
    cohort = _cohort("c1")
    registry = {"cohorts": {}}
    append_cohort(registry, cohort)
    append_cohort(registry, copy.deepcopy(cohort))

    changed = copy.deepcopy(cohort)
    changed["rows"][0]["competitor_rank"] = 999
    changed["content_sha256"] = "changed"
    with pytest.raises(ValueError, match="immutable"):
        append_cohort(registry, changed)


def test_missing_outcomes_cannot_authorize_a_claim():
    result = build_track([_cohort("c1")], {}, CRITERIA)
    assert result["status"] == "collecting"
    assert result["claim_authorized"] is False
    assert result["primary"] is None
```

Use this synthetic cohort helper so the full-path superiority test uses three
non-overlapping 50-player cohorts:

```python
def _cohort(
    cohort_id: str,
    offset: int = 0,
    *,
    size: int = 50,
    valucast_wins: bool = True,
) -> dict:
    players = [
        {
            "mlbam_id": str(offset + i),
            "name": f"Player {offset + i}",
            "role": "hitter" if i <= size // 2 else "pitcher",
            "rank": i if valucast_wins else size + 1 - i,
        }
        for i in range(1, size + 1)
    ]
    baseline = [
        {
            "mlbam_id": str(offset + i),
            "name": f"Player {offset + i}",
            "role": "hitter" if i <= size // 2 else "pitcher",
            "rank": size + 1 - i if valucast_wins else i,
        }
        for i in range(1, size + 1)
    ]
    return build_cohort(
        cohort_id=cohort_id,
        registered_at="2026-07-19",
        track="test",
        valucast_rows=players,
        competitor_rows=baseline,
        sources={},
    )
```

Add a full-path test using offsets `0`, `50`, and `100`:

```python
def _outcomes(cohorts: list[dict]) -> dict[str, float]:
    result = {}
    for cohort in cohorts:
        ordered = sorted(
            cohort["rows"], key=lambda row: int(row["mlbam_id"])
        )
        for index, row in enumerate(ordered, start=1):
            result[f"{cohort['cohort_id']}:{row['mlbam_id']}"] = 51.0 - index
    return result


def test_ordinal_track_stays_research_only_after_150_unique_players():
    cohorts = [_cohort(f"c{i}", i * 50) for i in range(3)]
    result = build_track(cohorts, _outcomes(cohorts), CRITERIA)

    assert result["coverage"]["unique_players"] == 150
    assert result["primary"]["bootstrap_cohorts"] == 3
    assert result["primary"]["relative_improvement_pct"] >= 5.0
    assert result["status"] == "research_only"
    assert result["statistical_status"] == "validated_superiority"
    assert result["claim_authorized"] is False
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_competition_proof.py::test_industry_claim_policy_requires_effect_ci_and_clean_subgroups tests/test_competition_proof.py::test_industry_claim_floor_is_150_unique_players tests/test_competition_proof.py::test_build_cohort_preserves_role_for_guardrail_scoring -q
```

Expected: collection fails because `MINIMUM_INDUSTRY_CLAIM_PLAYERS` and `_claim_decision` do not exist.

- [ ] **Step 3: Add the minimum claim policy**

Add the constant near the imports and preserve role in each frozen row:

```python
MINIMUM_INDUSTRY_CLAIM_PLAYERS = 150


# Inside build_cohort's row dictionary:
"role": valucast[key].get("role") or competitor[key].get("role"),
```

Add the effect helper and claim policy after `_regression_pct`:

```python
def _relative_improvement_pct(candidate: float, baseline: float) -> float | None:
    if baseline == 0:
        return 0.0 if candidate == 0 else None
    return (baseline - candidate) / baseline * 100.0


def _claim_decision(
    *,
    evidence_ready: bool,
    ci_low: float | None,
    ci_high: float | None,
    relative_improvement_pct: float | None,
    cohort_regressions: list[float],
    segment_regressions: list[float],
    top_k_non_regression: bool,
    claim_eligible: bool,
    criteria: dict,
) -> tuple[str, bool, str]:
    if not evidence_ready:
        return "collecting", False, "collecting"
    if ci_high is not None and ci_high < 0:
        return (
            "validated_underperformance",
            False,
            "validated_underperformance",
        )
    practical_win = (
        relative_improvement_pct is not None
        and relative_improvement_pct
        >= float(criteria["minimum_relative_improvement_pct"])
    )
    clean_cohorts = all(
        value <= float(criteria["maximum_single_cohort_regression_pct"])
        for value in cohort_regressions
    )
    clean_segments = all(
        value <= float(criteria["maximum_segment_regression_pct"])
        for value in segment_regressions
    )
    if (
        ci_low is not None
        and ci_low > 0
        and practical_win
        and clean_cohorts
        and clean_segments
        and top_k_non_regression
    ):
        if claim_eligible:
            return "validated_superiority", True, "validated_superiority"
        return "research_only", False, "validated_superiority"
    return "no_significant_difference", False, "no_significant_difference"
```

Replace the player-only bootstrap with a paired hierarchical bootstrap that
resamples completed cohorts first and players within each sampled cohort. This
prevents one large board from supplying false precision:

```python
def _cohort_bootstrap_error_delta(
    cohort_deltas: list[np.ndarray],
    *,
    seed: int,
    resamples: int,
) -> dict:
    point = mean(float(values.mean()) for values in cohort_deltas)
    if len(cohort_deltas) < 2:
        return {"point": point, "low": None, "high": None}
    rng = np.random.default_rng(seed)
    draws = np.empty(resamples)
    for draw in range(resamples):
        cohort_picks = rng.integers(0, len(cohort_deltas), len(cohort_deltas))
        sampled_means = []
        for pick in cohort_picks:
            values = cohort_deltas[pick]
            player_picks = rng.integers(0, len(values), len(values))
            sampled_means.append(float(values[player_picks].mean()))
        draws[draw] = mean(sampled_means)
    low, high = np.percentile(draws, [2.5, 97.5])
    return {"point": point, "low": float(low), "high": float(high)}
```

- [ ] **Step 4: Add aggregate role metrics and route status through the policy**

Initialize `cohort_error_deltas = []` beside the other track accumulators. For
each scored cohort, append the paired per-player delta:

```python
cohort_error_deltas.append(
    np.asarray(competitor_errors) - np.asarray(valucast_errors)
)
```

When appending resolved rows in `build_track`, add:

```python
"role": row.get("role"),
"cohort_id": cohort["cohort_id"],
```

After the resolved arrays are built, calculate the role guardrails:

```python
segments = []
for role in sorted({row["role"] for row in resolved if row.get("role")}):
    role_rows = [row for row in resolved if row.get("role") == role]
    role_valucast = mean(row["valucast_error"] for row in role_rows)
    role_baseline = mean(row["competitor_error"] for row in role_rows)
    segments.append(
        {
            "role": role,
            "resolved": len(role_rows),
            "valucast_error": round(role_valucast, 6),
            "competitor_error": round(role_baseline, 6),
            "regression_pct": _regression_pct(role_valucast, role_baseline),
        }
    )
```

Initialize `"segments": []` and `"statistical_status": "collecting"` in the
base result so collecting tracks keep a stable schema; replace them with the
calculated values when outcomes exist.

Make the sample floor non-configurable downward:

```python
minimum_players = max(
    MINIMUM_INDUSTRY_CLAIM_PLAYERS,
    int(criteria["minimum_unique_players"]),
)
evidence_ready = (
    completed_cohorts >= int(criteria["minimum_cohorts"])
    and unique_players >= minimum_players
    and coverage >= float(criteria["minimum_outcome_coverage"])
)
```

Rename each cohort's `valucast_mae` and `competitor_mae` fields to the generic
`valucast_error` and `competitor_error`; the metric name carries the meaning.
Use equally weighted completed-cohort errors for the primary comparison and
call the hierarchical bootstrap:

```python
# Inside the cohort_metrics row:
"valucast_error": mean(valucast_errors),
"competitor_error": mean(competitor_errors),
"regression_pct": _regression_pct(
    mean(valucast_errors), mean(competitor_errors)
),

valucast_primary_error = mean(
    row["valucast_error"] for row in cohort_metrics
)
competitor_primary_error = mean(
    row["competitor_error"] for row in cohort_metrics
)
ci = _cohort_bootstrap_error_delta(
    cohort_error_deltas,
    seed=int(criteria["bootstrap_seed"]),
    resamples=int(criteria["bootstrap_resamples"]),
)
```

Replace the existing `primary` dictionary so it uses generic error fields that
future regret and rate evaluators can share:

```python
relative_improvement_pct = _relative_improvement_pct(
    valucast_primary_error, competitor_primary_error
)
primary = {
    "metric": "ordinal_rank_error",
    "valucast_error": round(valucast_primary_error, 6),
    "competitor_error": round(competitor_primary_error, 6),
    "competitor_minus_valucast_error": round(ci["point"], 6),
    "relative_improvement_pct": (
        round(relative_improvement_pct, 6)
        if relative_improvement_pct is not None
        else None
    ),
    "error_delta_ci_low": (
        round(ci["low"], 6) if ci["low"] is not None else None
    ),
    "error_delta_ci_high": (
        round(ci["high"], 6) if ci["high"] is not None else None
    ),
    "bootstrap_cohorts": len(cohort_error_deltas),
    "bootstrap_players": unique_players,
}
```

Store `segments` on the result, then replace the inline final status logic with:

```python
status, claim_authorized, statistical_status = _claim_decision(
    evidence_ready=evidence_ready,
    ci_low=ci["low"],
    ci_high=ci["high"],
    relative_improvement_pct=relative_improvement_pct,
    cohort_regressions=[row["regression_pct"] for row in cohort_metrics],
    segment_regressions=[row["regression_pct"] for row in segments],
    top_k_non_regression=(
        confirmers["valucast_top_k_regret"]
        <= confirmers["competitor_top_k_regret"]
    ),
    # This evaluator emits ordinal rank error, which is not an approved public
    # primary metric. Track-specific future evaluators call the same gate with
    # claim_eligible=True only for realized-value regret or forward rate error.
    claim_eligible=False,
    criteria=criteria,
)
base["segments"] = segments
base["status"] = status
base["claim_authorized"] = claim_authorized
base["statistical_status"] = statistical_status
```

Every registration criterion must include:

```json
{
  "minimum_relative_improvement_pct": 5.0,
  "maximum_segment_regression_pct": 5.0
}
```

- [ ] **Step 5: Run the tests and confirm GREEN**

Run:

```powershell
python -m pytest tests/test_competition_proof.py -q
python -m ruff check prospects/competition_benchmark.py tests/test_competition_proof.py
```

Expected: all competition benchmark tests pass and Ruff reports no errors.

- [ ] **Step 6: Commit the claim gate**

```powershell
git add prospects/competition_benchmark.py tests/test_competition_proof.py
git commit -m "test: lock industry-standard proof gate"
```

---

### Task 2: Separate private evidence from public evidence

**Files:**
- Modify: `.gitignore`
- Modify: `scripts/build_competition_benchmark.py:16-17`
- Modify: `scripts/build_competition_benchmark.py:36-204`
- Modify: `scripts/build_competition_benchmark.py:214-235`
- Modify: `tests/test_competition_proof.py`
- Create: `data/validation/valucast_competition_evidence.json`

**Interfaces:**
- Consumes: `build_artifact(existing: dict | None = None, source: dict | None = None) -> dict`, where omitted `source` loads the gitignored local registry.
- Produces: `build_public_artifact(private_artifact: dict, forbidden_identifiers: list[str]) -> dict`, containing only authorized aggregate results and anonymous source classes.
- Produces: `validate_public_artifact(payload: dict, forbidden_identifiers: list[str]) -> None`, which fails closed on an identity leak.

- [ ] **Step 1: Write failing public-boundary tests**

Add these tests using canary identities rather than real source names:

```python
import json

import scripts.build_competition_benchmark as competition_script
from scripts.build_competition_benchmark import (
    PRIVATE_ARTIFACT_PATH,
    PRIVATE_SOURCES_PATH,
    PUBLIC_ARTIFACT_PATH,
    build_artifact,
    build_public_artifact,
    validate_public_artifact,
)


def _private_artifact(*, authorized: bool) -> dict:
    return {
        "artifact": "valucast_competition_benchmark",
        "protocol_version": "proof-v1",
        "generated_at": "2026-07-19",
        "tracks": {
            "private-track-canary": {
                "competitor": "PRIVATE SOURCE CANARY",
                "public_source_class": "leading_public_prospect_boards",
                "public_task": "four-year prospect-selection regret",
                "cohorts": [{"cohort_id": "private-cohort-canary"}],
                "evaluation": {
                    "status": (
                        "validated_superiority" if authorized else "collecting"
                    ),
                    "claim_authorized": authorized,
                    "coverage": {"registered": 180, "resolved": 180, "rate": 1.0},
                    "primary": {
                        "metric": "realized_value_regret",
                        "valucast_error": 0.20,
                        "competitor_error": 0.25,
                        "competitor_minus_valucast_error": 0.05,
                        "relative_improvement_pct": 20.0,
                        "error_delta_ci_low": 0.01,
                        "error_delta_ci_high": 0.09,
                    },
                    "confirmers": {
                        "valucast_top_k_regret": 1.0,
                        "competitor_top_k_regret": 2.0,
                    },
                    "segments": [],
                    "cohorts": [
                        {
                            "cohort_id": "private-cohort-canary",
                            "registered": 180,
                            "resolved": 180,
                            "coverage": 1.0,
                            "valucast_error": 0.20,
                            "competitor_error": 0.25,
                            "regression_pct": -20.0,
                        }
                    ],
                },
            }
        },
    }


def test_public_artifact_is_empty_until_a_claim_is_authorized():
    public = build_public_artifact(
        _private_artifact(authorized=False),
        forbidden_identifiers=["PRIVATE SOURCE CANARY"],
    )
    assert public["results"] == []
    assert public["validation"]["public_claim_count"] == 0


def test_public_artifact_anonymizes_authorized_aggregate_evidence():
    forbidden = [
        "PRIVATE SOURCE CANARY",
        "private-track-canary",
        "private-cohort-canary",
    ]
    public = build_public_artifact(
        _private_artifact(authorized=True),
        forbidden_identifiers=forbidden,
    )
    body = json.dumps(public).casefold()
    assert all(value.casefold() not in body for value in forbidden)
    assert public["results"][0]["benchmark_class"] == (
        "leading_public_prospect_boards"
    )
    assert public["results"][0]["cohorts"][0]["cohort_number"] == 1
    assert "baseline_error" in public["results"][0]["primary"]


def test_public_validator_fails_closed_on_private_identity():
    with pytest.raises(ValueError, match="private identity leak"):
        validate_public_artifact(
            {"results": [{"label": "PRIVATE SOURCE CANARY"}]},
            ["PRIVATE SOURCE CANARY"],
        )


def test_private_paths_cannot_be_model_inputs():
    assert PRIVATE_SOURCES_PATH.as_posix().endswith(
        "data/private/competition/sources.json"
    )
    assert PRIVATE_ARTIFACT_PATH.as_posix().endswith(
        "data/private/competition/benchmark.json"
    )
    assert "models" not in PRIVATE_ARTIFACT_PATH.parts
    assert "models" not in PUBLIC_ARTIFACT_PATH.parts


def test_private_builder_accepts_anonymous_synthetic_registry(monkeypatch):
    rows = [
        {
            "mlbam_id": str(index),
            "name": f"Player {index}",
            "rank": index,
            "role": "hitter",
        }
        for index in range(1, 151)
    ]
    source = {
        "protocol_version": "proof-v1",
        "registered_at": "2026-07-19",
        "outcome_file": "data/private/competition/missing.json",
        "registrations": [
            {
                "track": "private-track-canary",
                "kind": "prospect_board_rank",
                "cohort_id": "private-cohort-canary",
                "registered_at": "2026-07-19",
                "competitor": "PRIVATE SOURCE CANARY",
                "task": "private task",
                "public_source_class": "leading_public_prospect_boards",
                "public_task": "four-year prospect-selection regret",
                "criteria": CRITERIA,
            }
        ],
    }
    monkeypatch.setattr(
        competition_script,
        "_prospect_board_rows",
        lambda _registration: (rows, rows, {}),
    )

    artifact = build_artifact(existing={}, source=source)

    track = artifact["tracks"]["private-track-canary"]
    assert track["public_source_class"] == "leading_public_prospect_boards"
    assert track["evaluation"]["status"] == "collecting"
    assert track["evaluation"]["claim_authorized"] is False
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_competition_proof.py::test_public_artifact_is_empty_until_a_claim_is_authorized tests/test_competition_proof.py::test_public_artifact_anonymizes_authorized_aggregate_evidence tests/test_competition_proof.py::test_public_validator_fails_closed_on_private_identity tests/test_competition_proof.py::test_private_paths_cannot_be_model_inputs tests/test_competition_proof.py::test_private_builder_accepts_anonymous_synthetic_registry -q
```

Expected: collection fails because the public artifact functions and path do not exist.

- [ ] **Step 3: Gitignore every named or row-level evidence file**

Append exactly:

```gitignore
# Private competition evidence: named sources and row-level results never ship.
data/private/competition/
data/manual/competition_benchmark_sources.json
data/manual/competition_benchmark_outcomes.json
data/models/valucast_competition_benchmark.json
data/manual/*historical_boards.json
data/validation/competition_historical_replay.json
scripts/build_competition_historical_replay.py
tests/test_competition_benchmark.py
```

Do not delete the existing local files. Copy them into the private directory
only after verifying that the resolved destination stays inside the workspace:

```powershell
$root = (Resolve-Path '.').Path
$private = [System.IO.Path]::GetFullPath((Join-Path $root 'data/private/competition'))
if (-not $private.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "private evidence path escaped the workspace"
}
New-Item -ItemType Directory -Force -Path $private | Out-Null
Copy-Item -LiteralPath 'data/manual/competition_benchmark_sources.json' -Destination (Join-Path $private 'sources.json')
if (Test-Path -LiteralPath 'data/models/valucast_competition_benchmark.json') {
    Copy-Item -LiteralPath 'data/models/valucast_competition_benchmark.json' -Destination (Join-Path $private 'benchmark.json')
}
if (Test-Path -LiteralPath 'tests/test_competition_benchmark.py') {
    $researchTests = Join-Path $private 'tests'
    New-Item -ItemType Directory -Force -Path $researchTests | Out-Null
    Move-Item -LiteralPath 'tests/test_competition_benchmark.py' -Destination (Join-Path $researchTests 'test_historical_replay.py')
}
```

The moved test is preserved as private research evidence and is no longer
collected by the repository's default `tests/` path. The anonymous
`tests/test_competition_proof.py` is its public replacement.

Confirm the boundary:

```powershell
git check-ignore data/private/competition/sources.json
git check-ignore data/private/competition/benchmark.json
```

Expected: both paths are printed.

- [ ] **Step 4: Make private-source loading injectable and generic**

Load the named evidence only from the private directory and allow tests to pass
an in-memory source:

```python
PRIVATE_DIR = ROOT / "data" / "private" / "competition"
PRIVATE_SOURCES_PATH = PRIVATE_DIR / "sources.json"
PRIVATE_ARTIFACT_PATH = PRIVATE_DIR / "benchmark.json"
PUBLIC_ARTIFACT_PATH = (
    ROOT / "data" / "validation" / "valucast_competition_evidence.json"
)


def build_artifact(
    existing: dict | None = None,
    source: dict | None = None,
) -> dict:
    source = source if source is not None else _load(PRIVATE_SOURCES_PATH)
    # Existing construction continues below unchanged.
```

Rename the two source-shape helpers and private registration kinds to generic categories:

```python
builders = {
    "prospect_board_rank": _prospect_board_rows,
    "pitcher_skill_rank": _pitcher_skill_rows,
}
try:
    row_builder = builders[registration["kind"]]
except KeyError as exc:
    raise ValueError(
        f"unsupported competition registration {registration['kind']}"
    ) from exc
valucast_rows, competitor_rows, sources = row_builder(registration)
```

The gitignored local registry must add safe public fields to each registration:

```json
{
  "public_source_class": "leading_public_prospect_boards",
  "public_task": "four-year prospect-selection regret"
}
```

The pitcher-skill registration uses `public_pitcher_skill_benchmarks` and a plain-language task with no identity. Preserve the private identity, URL, timestamp, capture, and hash fields locally.

Persist `public_source_class` and `public_task` in both `track_data` construction
paths and in the final private track dictionary:

```python
"public_source_class": registration["public_source_class"],
"public_task": registration["public_task"],
```

- [ ] **Step 5: Implement the sanitizer and fail-closed validator**

Add:

```python
def validate_public_artifact(
    payload: dict,
    forbidden_identifiers: list[str],
) -> None:
    body = json.dumps(payload, sort_keys=True).casefold()
    leaked = sorted(
        value
        for value in forbidden_identifiers
        if len(value.strip()) >= 4 and value.casefold() in body
    )
    if leaked:
        raise ValueError(f"private identity leak: {leaked}")


def build_public_artifact(
    private_artifact: dict,
    forbidden_identifiers: list[str],
) -> dict:
    results = []
    for track in private_artifact.get("tracks", {}).values():
        evaluation = track["evaluation"]
        if not evaluation.get("claim_authorized"):
            continue
        primary = evaluation["primary"]
        confirmers = evaluation["confirmers"]
        results.append(
            {
                "benchmark_class": track["public_source_class"],
                "task": track["public_task"],
                "status": evaluation["status"],
                "coverage": evaluation["coverage"],
                "primary": {
                    "metric": primary["metric"],
                    "valucast_error": primary["valucast_error"],
                    "baseline_error": primary["competitor_error"],
                    "baseline_minus_valucast_error": primary[
                        "competitor_minus_valucast_error"
                    ],
                    "relative_improvement_pct": primary[
                        "relative_improvement_pct"
                    ],
                    "error_delta_ci_low": primary["error_delta_ci_low"],
                    "error_delta_ci_high": primary["error_delta_ci_high"],
                },
                "confirmers": {
                    "valucast_top_k_regret": confirmers[
                        "valucast_top_k_regret"
                    ],
                    "baseline_top_k_regret": confirmers[
                        "competitor_top_k_regret"
                    ],
                },
                "segments": [
                    {
                        "role": row["role"],
                        "resolved": row["resolved"],
                        "valucast_error": row["valucast_error"],
                        "baseline_error": row["competitor_error"],
                        "regression_pct": row["regression_pct"],
                    }
                    for row in evaluation.get("segments", [])
                ],
                "cohorts": [
                    {
                        "cohort_number": index,
                        "registered": row["registered"],
                        "resolved": row["resolved"],
                        "coverage": row["coverage"],
                        "valucast_error": row["valucast_error"],
                        "baseline_error": row["competitor_error"],
                        "regression_pct": row["regression_pct"],
                    }
                    for index, row in enumerate(
                        evaluation.get("cohorts", []), start=1
                    )
                ],
            }
        )
    payload = {
        "artifact": "valucast_competition_evidence",
        "protocol_version": private_artifact["protocol_version"],
        "generated_at": private_artifact["generated_at"],
        "results": results,
        "validation": {"public_claim_count": len(results)},
    }
    validate_public_artifact(payload, forbidden_identifiers)
    return payload
```

Create a private-identifier collector limited to registration identity fields:

```python
def _private_identifiers(source: dict) -> list[str]:
    keys = ("competitor", "competitor_url", "track", "cohort_id")
    return [
        str(registration[key])
        for registration in source.get("registrations", [])
        for key in keys
        if registration.get(key)
    ]
```

When `--write` is supplied, atomically write the full artifact to
`PRIVATE_ARTIFACT_PATH` and the sanitizer output to `PUBLIC_ARTIFACT_PATH`.
With current collecting cohorts, the public artifact must contain
`"results": []`.

Build both outputs from the same in-memory private registry in `main`:

```python
source = _load(PRIVATE_SOURCES_PATH)
payload = build_artifact(source=source)
public_payload = build_public_artifact(
    payload,
    forbidden_identifiers=_private_identifiers(source),
)
if args.write:
    _write(payload, PRIVATE_ARTIFACT_PATH)
    _write(public_payload, PUBLIC_ARTIFACT_PATH)
```

- [ ] **Step 6: Run the tests and deterministic build**

Run:

```powershell
python -m pytest tests/test_competition_proof.py -q
python -m ruff check prospects/competition_benchmark.py scripts/build_competition_benchmark.py tests/test_competition_proof.py
python scripts/build_competition_benchmark.py --write
$before = (Get-FileHash data/validation/valucast_competition_evidence.json -Algorithm SHA256).Hash
python scripts/build_competition_benchmark.py --write
$after = (Get-FileHash data/validation/valucast_competition_evidence.json -Algorithm SHA256).Hash
if ($before -ne $after) { throw "public artifact is not deterministic" }
```

Expected: tests and Ruff pass; both hashes match; the private artifact remains ignored; the public artifact has no results while all tracks are collecting.

- [ ] **Step 7: Commit the privacy boundary**

```powershell
git add .gitignore prospects/competition_benchmark.py scripts/build_competition_benchmark.py tests/test_competition_proof.py data/validation/valucast_competition_evidence.json
git commit -m "feat: isolate private competition evidence"
```

---

### Task 3: Lock production isolation and generic documentation

**Files:**
- Modify: `tests/test_competition_proof.py`
- Modify: `plans/032-competition-proof-lane.md`
- Modify: `plans/README.md`
- Modify: `docs/superpowers/specs/2026-07-19-competition-historical-replay-design.md`
- Modify: `docs/superpowers/plans/2026-07-19-competition-proof-lane.md`

**Interfaces:**
- Consumes: the private evaluator and sanitized public artifact from Tasks 1-2.
- Produces: an automated no-import production boundary and generic, source-anonymous public-repository documentation.

- [ ] **Step 1: Write the production-isolation test**

Add:

```python
from pathlib import Path


def test_production_model_paths_do_not_import_competition_evidence():
    production_paths = [
        Path("app.py"),
        Path("prospects/rank_v1.py"),
        Path("prospects/dynasty.py"),
        Path("prospects/buys.py"),
        Path("prospects/availability.py"),
        Path("prospects/shadow_promotion.py"),
    ]
    forbidden = (
        "competition_benchmark",
        "competition_benchmark_sources",
        "valucast_competition_evidence",
    )
    for path in production_paths:
        body = path.read_text(encoding="utf-8")
        assert not any(value in body for value in forbidden), path
```

- [ ] **Step 2: Run the isolation test**

Run:

```powershell
python -m pytest tests/test_competition_proof.py::test_production_model_paths_do_not_import_competition_evidence -q
```

Expected: PASS. If it fails, remove the dependency from the production path; do not weaken the test.

- [ ] **Step 3: Make repository documentation source-anonymous**

Rewrite Plan 032 track labels as:

```markdown
### Track A: Four-year prospect fantasy value versus a public prospect-board baseline

### Track B: Rest-of-season pitcher fantasy usefulness versus a public pitcher-skill baseline
```

The plan and index must retain dates, tasks, sample sizes, coverage, methods, losses, and claim states while removing individual names, handles, URLs, and branded metric names. The historical replay design must say `dated public preseason prospect boards`; its private registry remains the authority for source identity and capture hashes.

Add the approved industry claim floor and effect gate to Plan 032:

```markdown
- A narrow track may report statistical results at its registered exploratory sample, but no industry-standard superiority claim is authorized below 150 unique matched players.
- Superiority also requires at least 5% relative improvement and no role or completed cohort more than 5% worse on the primary metric.
- Public artifacts use anonymous source classes; named evidence remains private.
```

- [ ] **Step 4: Run the full verification gate**

Run fresh:

```powershell
python scripts/build_competition_benchmark.py --write
python -m pytest tests/test_competition_proof.py tests/test_forward_cohort.py tests/test_forward_scoreboard.py tests/test_prospect_rank_backtest.py -q
python -m ruff check prospects/competition_benchmark.py scripts/build_competition_benchmark.py tests/test_competition_proof.py
python -m pytest -q
git diff --check
git check-ignore data/private/competition/sources.json
git check-ignore data/private/competition/benchmark.json
```

Expected: the build exits zero, targeted tests pass, Ruff reports no errors, the full suite has zero failures, `git diff --check` is silent, and both private paths are printed by `git check-ignore`.

Inspect the public artifact directly:

```powershell
@'
import json
from pathlib import Path
p = json.loads(Path("data/validation/valucast_competition_evidence.json").read_text())
assert p["artifact"] == "valucast_competition_evidence"
assert p["results"] == []
assert p["validation"]["public_claim_count"] == 0
'@ | python -
```

Expected: exit zero. No browser test is needed because this phase intentionally adds no public consumer.

- [ ] **Step 5: Commit the isolation contract and documentation**

```powershell
git add tests/test_competition_proof.py plans/032-competition-proof-lane.md plans/README.md docs/superpowers/specs/2026-07-19-competition-historical-replay-design.md docs/superpowers/plans/2026-07-19-competition-proof-lane.md
git commit -m "docs: anonymize competition proof lane"
```

Before any future push, confirm `git log master..HEAD --name-only` contains no named private registry or row-level artifact. If unpublished earlier commits contain source identities, create a clean integration branch from `master` and cherry-pick only sanitized commits; do not push the unsafe history.

## Deferred Plans

- **Decision-value challenger:** register and test improvements to format-specific fantasy value after the proof foundation passes.
- **Hitter and pitcher skill challengers:** separate plans and claims; never combine roles to hide a loss.
- **Long-horizon prospect challenger:** begin only with a frozen four-year fantasy-value outcome contract.
- **Distribution:** add an anonymized proof surface only after `public_claim_count > 0` on untouched forward evidence.
