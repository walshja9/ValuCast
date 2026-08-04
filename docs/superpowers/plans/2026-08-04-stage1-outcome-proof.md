# Stage 1 Outcome Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one reproducible, research-only Stage 1 scorecard covering outcome ordering, contributor discrimination, historical evidence bands, and frozen disagreement funnels.

**Architecture:** Reuse the committed out-of-fold outcome, reliability, dynasty-backtest, and Ahead-of-Consensus artifacts. One pure module computes and validates the aggregate payload and renders Markdown; one CLI loads the four inputs and writes one JSON artifact plus one report. Nothing is wired into production or daily workflows.

**Tech Stack:** Python 3.10+, stdlib JSON/hashlib/statistics, NumPy, SciPy, pytest.

## Global Constraints

- Evaluation and reporting only: no score, rank, value, cap, Role Watch, buy signal, pitcher-veto, or publication change.
- Preserve the model freeze and failed-decay flag.
- Use only committed out-of-fold predictions; never substitute today's model or today's rank.
- `contributor = Role or Star` inside the fixed four-year outcome horizon.
- Report hitters and pitchers separately before any combined row.
- Evidence bands are within-role equal-count deciles, not probabilities or public player grades.
- Existing forward cohort `2026-07-16` remains untouched and unsliced.
- Plan 034 and Plan 035 remain unspent.
- Retrospective evidence never authorizes a public superiority claim.
- No new dependency, workflow, serving route, template, or public artifact.

## File Map

- Create `prospects/stage1_outcome_proof.py`: metrics, evidence bands, disagreement funnel, validation, and Markdown rendering.
- Create `scripts/build_stage1_outcome_proof.py`: load/hash inputs and write outputs.
- Create `tests/test_stage1_outcome_proof.py`: unit, drift, provenance, and production-isolation contracts.
- Create `data/validation/valucast_stage1_outcome_proof.json`: committed aggregate research artifact.
- Create `docs/stage1-outcome-proof.md`: generated human-readable report from the same payload.

---

### Task 1: Historical ordering and contributor metrics

**Files:**
- Create: `prospects/stage1_outcome_proof.py`
- Create: `tests/test_stage1_outcome_proof.py`

**Interfaces:**
- Consumes: OOF rows with `mlbam_id`, `role`, `test_cohort`, `model_prediction`, `prior_prediction`, `neighbor_prediction`, and `target`.
- Produces: `build_role_metrics(rows: list[dict], *, seed: int, resamples: int) -> dict`.

- [ ] **Step 1: Write the failing metric tests**

```python
import json
from pathlib import Path

import pytest

from prospects.stage1_outcome_proof import (
    auc,
    build_role_metrics,
)


def _row(player, cohort, target, model, prior, neighbor, role="hitter"):
    return {
        "mlbam_id": str(player),
        "role": role,
        "test_cohort": cohort,
        "train_cohort_max": cohort - 1,
        "model_prediction": model,
        "prior_prediction": prior,
        "neighbor_prediction": neighbor,
        "target": target,
    }


def test_auc_is_tie_correct_and_requires_both_classes():
    assert auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert auc([0.5, 0.5], [0, 1]) == 0.5
    assert auc([0.1, 0.2], [0, 0]) is None


def test_role_metrics_are_outcome_ordered_and_seeded():
    rows = [
        _row(1, 2018, 0.0, 0.1, 0.9, 0.8),
        _row(2, 2018, 0.5, 0.5, 0.5, 0.5),
        _row(3, 2019, 1.0, 0.9, 0.1, 0.2),
        _row(4, 2019, 0.0, 0.1, 0.9, 0.8),
    ]
    first = build_role_metrics(rows, seed=34041, resamples=100)
    second = build_role_metrics(list(reversed(rows)), seed=34041, resamples=100)
    assert first == second
    assert first["sample_size"] == 4
    assert first["cohort_count"] == 2
    assert first["contributor_base_rate"] == 0.5
    assert first["metrics"]["roc_auc"]["model"]["point"] == 1.0
    assert first["metrics"]["spearman_rho"]["model"]["point"] == 1.0
    assert first["metrics"]["kendall_tau_b"]["model"]["point"] == 1.0
    assert first["metrics"]["roc_auc"]["level_age_prior"]["point"] == 0.0
    assert set(first["cohorts"]) == {"2018", "2019"}
    assert first["metrics"]["roc_auc"]["model_minus_baseline"]["level_age_prior"]["historical_support"] is False
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_stage1_outcome_proof.py -q`

Expected: collection fails because `prospects.stage1_outcome_proof` does not exist.

- [ ] **Step 3: Implement the minimal metric core**

```python
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from scipy.stats import kendalltau, rankdata, spearmanr

BOOTSTRAP_SEED = 34041
BOOTSTRAP_RESAMPLES = 10_000
ROLES = ("hitter", "pitcher")
PREDICTIONS = {
    "model": "model_prediction",
    "level_age_prior": "prior_prediction",
    "historical_neighbors_25": "neighbor_prediction",
}


def _round(value):
    return None if value is None or not math.isfinite(float(value)) else round(float(value), 6)


def auc(scores: list[float], outcomes: list[int]) -> float | None:
    positives = sum(outcomes)
    negatives = len(outcomes) - positives
    if not positives or not negatives:
        return None
    ranks = rankdata(np.asarray(scores, dtype=float), method="average")
    positive_rank_sum = sum(rank for rank, outcome in zip(ranks, outcomes) if outcome)
    return float((positive_rank_sum - positives * (positives + 1) / 2) / (positives * negatives))


def _metric(name: str, predictions: list[float], targets: list[float]) -> float | None:
    if name == "roc_auc":
        return auc(predictions, [int(target > 0.0) for target in targets])
    result = (
        spearmanr(predictions, targets).statistic
        if name == "spearman_rho"
        else kendalltau(predictions, targets, variant="b").statistic
    )
    return None if result is None or not math.isfinite(float(result)) else float(result)


def _draw_indices(rows: list[dict], rng: np.random.Generator) -> list[int]:
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        groups[str(row["mlbam_id"])].append(index)
    ordered = [groups[key] for key in sorted(groups)]
    picks = rng.integers(0, len(ordered), len(ordered))
    return [index for pick in picks for index in ordered[int(pick)]]


def _interval(draws: list[float]) -> dict:
    if not draws:
        return {"low": None, "high": None}
    low, high = np.percentile(np.asarray(draws, dtype=float), [2.5, 97.5])
    return {"low": _round(low), "high": _round(high)}


def build_role_metrics(rows: list[dict], *, seed: int, resamples: int) -> dict:
    rows = sorted(rows, key=lambda row: (int(row["test_cohort"]), str(row["mlbam_id"])))
    targets = [float(row["target"]) for row in rows]
    points = {
        metric: {
            label: _metric(metric, [float(row[key]) for row in rows], targets)
            for label, key in PREDICTIONS.items()
        }
        for metric in ("spearman_rho", "kendall_tau_b", "roc_auc")
    }
    draws = {
        metric: {label: [] for label in PREDICTIONS}
        for metric in points
    }
    deltas = {
        metric: {label: [] for label in PREDICTIONS if label != "model"}
        for metric in points
    }
    rng = np.random.default_rng(seed)
    for _ in range(resamples):
        indices = _draw_indices(rows, rng)
        sample = [rows[index] for index in indices]
        sample_targets = [float(row["target"]) for row in sample]
        for metric in points:
            sampled = {
                label: _metric(metric, [float(row[key]) for row in sample], sample_targets)
                for label, key in PREDICTIONS.items()
            }
            for label, value in sampled.items():
                if value is not None:
                    draws[metric][label].append(value)
            for label in deltas[metric]:
                if sampled["model"] is not None and sampled[label] is not None:
                    deltas[metric][label].append(sampled["model"] - sampled[label])
    metrics = {}
    for metric, values in points.items():
        metrics[metric] = {
            label: {"point": _round(point), **_interval(draws[metric][label])}
            for label, point in values.items()
        }
        metrics[metric]["model_minus_baseline"] = {
            label: {
                "point": _round(values["model"] - values[label]),
                **_interval(deltas[metric][label]),
            }
            for label in deltas[metric]
        }
        for comparison in metrics[metric]["model_minus_baseline"].values():
            comparison["historical_support"] = bool(
                len(rows) >= 250
                and len({int(row["test_cohort"]) for row in rows}) >= 3
                and comparison["low"] is not None
                and comparison["low"] > 0.0
            )
            comparison["evidence_status"] = (
                "supported_retrospective" if comparison["historical_support"] else "descriptive"
            )
    cohorts = {}
    for cohort in sorted({int(row["test_cohort"]) for row in rows}):
        cohort_rows = [row for row in rows if int(row["test_cohort"]) == cohort]
        cohort_targets = [float(row["target"]) for row in cohort_rows]
        cohorts[str(cohort)] = {
            "sample_size": len(cohort_rows),
            "contributor_base_rate": _round(
                sum(target > 0.0 for target in cohort_targets) / len(cohort_rows)
            ),
            "metrics": {
                metric: {
                    label: _round(
                        _metric(
                            metric,
                            [float(row[key]) for row in cohort_rows],
                            cohort_targets,
                        )
                    )
                    for label, key in PREDICTIONS.items()
                }
                for metric in points
            },
        }
    return {
        "sample_size": len(rows),
        "cohort_count": len({int(row["test_cohort"]) for row in rows}),
        "contributor_base_rate": _round(sum(target > 0.0 for target in targets) / len(rows)),
        "metrics": metrics,
        "cohorts": cohorts,
        "bootstrap": {"seed": seed, "resamples": resamples, "cluster": "mlbam_id"},
    }
```

- [ ] **Step 4: Run the metric tests**

Run: `python -m pytest tests/test_stage1_outcome_proof.py -q`

Expected: all current tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add prospects/stage1_outcome_proof.py tests/test_stage1_outcome_proof.py
git commit -m "feat: compute Stage 1 outcome proof metrics"
```

---

### Task 2: Evidence bands, disagreement funnel, and fail-closed payload

**Files:**
- Modify: `prospects/stage1_outcome_proof.py`
- Modify: `tests/test_stage1_outcome_proof.py`

**Interfaces:**
- Consumes: validated OOF and reliability payloads, dynasty-backtest metadata, and Ahead-of-Consensus calls.
- Produces: `build_stage1_outcome_proof(...) -> dict`, `validate_stage1_outcome_proof(payload: dict) -> list[str]`, and `render_markdown(payload: dict) -> str`.

- [ ] **Step 1: Add failing evidence-band and funnel tests**

```python
from prospects.stage1_outcome_proof import (
    build_disagreement_funnel,
    build_evidence_bands,
    build_stage1_outcome_proof,
    render_markdown,
    validate_stage1_outcome_proof,
)


def test_evidence_bands_cover_rows_once_and_match_reliability_counts():
    rows = [
        _row(index, 2018 + index % 2, [0.0, 0.5, 1.0][index % 3], index / 20, 0.2, 0.3)
        for index in range(20)
    ]
    reliability = {
        "bins": [
            {
                "decile": decile + 1,
                "count": 2,
                "predicted_score_min": (2 * decile) / 20,
                "predicted_score_max": (2 * decile + 1) / 20,
                "reached_role_or_better_freq": sum(
                    [0.0, 0.5, 1.0][index % 3] > 0.0
                    for index in (2 * decile, 2 * decile + 1)
                ) / 2,
            }
            for decile in range(10)
        ]
    }
    bands = build_evidence_bands(rows, reliability)
    assert len(bands) == 10
    assert sum(band["sample_size"] for band in bands) == 20
    assert all(sum(band["outcome_counts"].values()) == band["sample_size"] for band in bands)


def test_disagreement_funnel_is_role_split_and_whole_funnel():
    scorecard = {
        "calls": [
            {"identity_key": "1_hitter", "initial_gap": 30, "status": "open_toward", "bucket": "toward"},
            {"identity_key": "2_hitter", "initial_gap": 120, "status": "retired_we_backed_off", "bucket": None},
            {"identity_key": "3_pitcher", "initial_gap": 220, "status": "closed_caught_up", "bucket": "toward"},
            {"identity_key": "4_pitcher", "initial_gap": 60, "status": "left_universe", "bucket": None},
        ]
    }
    funnel = build_disagreement_funnel(scorecard)
    assert funnel["roles"]["hitter"]["total"] == 2
    assert funnel["roles"]["pitcher"]["total"] == 2
    assert funnel["roles"]["hitter"]["bins"]["100_199"]["retracted"] == 1
    assert funnel["roles"]["pitcher"]["bins"]["200_plus"]["resolved"] == 1
    assert funnel["overall"]["total"] == 4


@pytest.mark.parametrize(
    "call",
    [
        {"identity_key": "1_hitter", "initial_gap": 24, "status": "open_toward", "bucket": "toward"},
        {"identity_key": "1_hitter", "initial_gap": 30, "status": "unknown", "bucket": None},
    ],
)
def test_disagreement_funnel_fails_closed_on_non_registered_rows(call):
    with pytest.raises(ValueError):
        build_disagreement_funnel({"calls": [call]})


def test_disagreement_funnel_uses_frozen_gap_not_current_ranks():
    call = {
        "identity_key": "1_hitter",
        "initial_gap": 120,
        "status": "open_toward",
        "bucket": "toward",
        "valucast_now": 1,
        "consensus_now": 1,
    }
    baseline = build_disagreement_funnel({"calls": [call]})
    call.update(valucast_now=9999, consensus_now=-9999)
    assert build_disagreement_funnel({"calls": [call]}) == baseline


def test_payload_is_research_only_and_renders_from_one_source():
    root = Path(__file__).resolve().parents[1]
    paths = {
        "oof": root / "data/models/valucast_outcome_oof_scores.json",
        "reliability": root / "data/models/valucast_probability_reliability.json",
        "backtest": root / "data/models/valucast_prospect_dynasty_backtest.json",
        "scorecard": root / "data/models/valucast_ahead_of_consensus_scorecard.json",
    }
    inputs = {
        key: json.loads(path.read_text(encoding="utf-8"))
        for key, path in paths.items()
    }
    payload = build_stage1_outcome_proof(
        oof_payload=inputs["oof"],
        reliability_payload=inputs["reliability"],
        backtest_payload=inputs["backtest"],
        scorecard_payload=inputs["scorecard"],
        sources={
            key: {"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": "a" * 64}
            for key, path in paths.items()
        },
        generated_at=max(str(item.get("generated_at") or "") for item in inputs.values()),
        seed=34041,
        resamples=10,
    )
    assert validate_stage1_outcome_proof(payload) == []
    assert payload["policy"]["public_superiority_authorized"] is False
    assert payload["policy"]["feeds_model_score"] is False
    report = render_markdown(payload)
    assert "Contributor discrimination" in report
    assert "Level/age prior" in report
    assert "Historical neighbors (25)" in report
    assert "Closed-cohort detail" in report
    assert "100-199" in report
    assert "Public superiority authorized: **No**" in report


def test_validator_rejects_any_public_authorization():
    payload = {
        "artifact": "valucast_stage1_outcome_proof",
        "schema_version": "1.0.0",
        "status": "research_only",
        "sources": {
            key: {"path": f"data/{key}.json", "sha256": "a" * 64}
            for key in ("oof", "reliability", "backtest", "scorecard")
        },
        "historical": {"roles": {}},
        "disagreements": {},
        "policy": {"public_superiority_authorized": True},
    }
    assert "retrospective evidence cannot authorize public superiority" in validate_stage1_outcome_proof(payload)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_stage1_outcome_proof.py -q`

Expected: imports for the new functions fail.

- [ ] **Step 3: Add evidence bands and the disagreement funnel**

```python
import json

from prospects.probability_reliability import _wilson_interval
from scripts.audit_consensus_decisions import gap_bin

FUNNEL_STATUSES = {
    "open": {"open_toward", "open_flat", "open_away"},
    "resolved": {"closed_caught_up", "resolved_called_up_or_graduated"},
    "censored": {"left_universe"},
    "retracted": {"retired_we_backed_off"},
}


def _evidence_label(sample_size: int) -> str:
    if sample_size < 10:
        return "insufficient"
    if sample_size < 20:
        return "descriptive"
    return "observed"


def build_evidence_bands(rows: list[dict], reliability_role: dict) -> list[dict]:
    ordered = sorted(rows, key=lambda row: (float(row["model_prediction"]), str(row["mlbam_id"])))
    expected = reliability_role.get("bins") or []
    bands = []
    for decile in range(10):
        start = decile * len(ordered) // 10
        stop = (decile + 1) * len(ordered) // 10
        chunk = ordered[start:stop]
        counts = {
            "bust": sum(float(row["target"]) == 0.0 for row in chunk),
            "role": sum(float(row["target"]) == 0.5 for row in chunk),
            "star": sum(float(row["target"]) == 1.0 for row in chunk),
        }
        contributors = counts["role"] + counts["star"]
        actual = {
            "count": len(chunk),
            "predicted_score_min": _round(chunk[0]["model_prediction"]),
            "predicted_score_max": _round(chunk[-1]["model_prediction"]),
            "reached_role_or_better_freq": _round(contributors / len(chunk)),
        }
        expected_values = {
            key: _round(expected[decile][key]) if key != "count" else int(expected[decile][key])
            for key in actual
        } if decile < len(expected) else None
        if actual != expected_values:
            raise ValueError(f"reliability decile {decile + 1} does not reconcile")
        bands.append({
            "decile": decile + 1,
            "sample_size": len(chunk),
            "score_min": _round(chunk[0]["model_prediction"]),
            "score_max": _round(chunk[-1]["model_prediction"]),
            "outcome_counts": counts,
            "outcome_shares": {key: _round(value / len(chunk)) for key, value in counts.items()},
            "contributor_rate": _round(contributors / len(chunk)),
            "contributor_wilson95": _wilson_interval(contributors, len(chunk)),
            "evidence_label": _evidence_label(len(chunk)),
        })
    return bands


def _role(identity_key: str) -> str:
    role = identity_key.rsplit("_", 1)[-1]
    if role not in ROLES:
        raise ValueError(f"invalid disagreement identity role: {identity_key}")
    return role


def _empty_funnel() -> dict:
    return {
        "total": 0,
        "open": 0,
        "resolved": 0,
        "censored": 0,
        "retracted": 0,
        "moved_toward": 0,
        "moved_away": 0,
    }


def build_disagreement_funnel(scorecard: dict) -> dict:
    output = {"overall": {**_empty_funnel(), "bins": {}}, "roles": {}}
    for role in ROLES:
        output["roles"][role] = {**_empty_funnel(), "bins": {}}
    for call in scorecard.get("calls") or []:
        role = _role(str(call["identity_key"]))
        if float(call["initial_gap"]) < 25:
            raise ValueError("disagreement call is below the frozen 25-rank gap floor")
        band = gap_bin(call["initial_gap"])
        if band == "missing":
            raise ValueError("disagreement call is missing its frozen initial gap")
        for target in (output["overall"], output["roles"][role]):
            target["total"] += 1
            cell = target["bins"].setdefault(band, _empty_funnel())
            cell["total"] += 1
            lifecycle = [label for label, statuses in FUNNEL_STATUSES.items() if call["status"] in statuses]
            if len(lifecycle) != 1:
                raise ValueError(f"unclassified disagreement status: {call['status']}")
            target[lifecycle[0]] += 1
            cell[lifecycle[0]] += 1
            if call.get("bucket") == "toward":
                target["moved_toward"] += 1
                cell["moved_toward"] += 1
            if call.get("bucket") == "away":
                target["moved_away"] += 1
                cell["moved_away"] += 1
    for summary in (output["overall"], *output["roles"].values()):
        for cell in (summary, *summary["bins"].values()):
            if sum(cell[key] for key in FUNNEL_STATUSES) != cell["total"]:
                raise ValueError("disagreement lifecycle does not partition its population")
            cell["evidence_label"] = _evidence_label(cell["total"])
    return output
```

- [ ] **Step 4: Add the aggregate builder, validator, and Markdown renderer**

```python
SCHEMA_VERSION = "1.0.0"


def build_stage1_outcome_proof(
    *,
    oof_payload: dict,
    reliability_payload: dict,
    backtest_payload: dict,
    scorecard_payload: dict,
    sources: dict[str, dict[str, str]],
    generated_at: str,
    seed: int = BOOTSTRAP_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict:
    from prospects.outcome_oof import validate_outcome_oof_artifact
    from prospects.probability_reliability import validate_probability_reliability

    oof_problems = validate_outcome_oof_artifact(oof_payload)
    reliability_problems = validate_probability_reliability(reliability_payload)
    if oof_problems or reliability_problems:
        raise ValueError("invalid Stage 1 evidence: " + "; ".join(oof_problems + reliability_problems))
    calls = scorecard_payload.get("calls") or []
    identities = [str(call.get("identity_key") or "") for call in calls]
    source_policy = scorecard_payload.get("source_policy") or {}
    if (
        scorecard_payload.get("artifact") != "valucast_ahead_of_consensus_scorecard"
        or source_policy.get("inputs") != "valucast_prospect_rank_v1_dated_archive"
        or not identities
        or len(identities) != len(set(identities))
    ):
        raise ValueError("disagreement evidence is not an exact claim-time archive join")
    rows = oof_payload["rows"]
    roles = {}
    for role in ROLES:
        role_rows = [row for row in rows if row["role"] == role]
        roles[role] = {
            **build_role_metrics(role_rows, seed=seed, resamples=resamples),
            "evidence_bands": build_evidence_bands(role_rows, reliability_payload["roles"][role]),
        }
    payload = {
        "artifact": "valucast_stage1_outcome_proof",
        "schema_version": SCHEMA_VERSION,
        "status": "research_only",
        "generated_at": generated_at,
        "versions": {
            "stage1_model": backtest_payload["universal_model_version"],
            "backtest": backtest_payload["backtest_version"],
            "reliability_schema": reliability_payload["schema_version"],
            "rank_calibration": "not_applicable_to_oof_stage1_scores",
            "outcome_contract": "four_year_bust_role_star_v1",
        },
        "sources": sources,
        "evaluation": {
            "mature_through_cohort": max(int(row["test_cohort"]) for row in rows),
            "closed_cohorts": sorted({int(row["test_cohort"]) for row in rows}),
            "historical_rows": len(rows),
            "historical_censored_rows": 0,
        },
        "outcome_contract": {
            "horizon_years": 4,
            "contributor": "role_or_star",
            "targets": {"bust": 0.0, "role": 0.5, "star": 1.0},
        },
        "historical": {"roles": roles},
        "disagreements": build_disagreement_funnel(scorecard_payload),
        "claim_policy": {
            "minimum_closed_cohorts": 3,
            "minimum_matched_role_n": 250,
            "delta_interval_must_exclude_zero": True,
            "retrospective_only": True,
        },
        "policy": {
            "public_superiority_authorized": False,
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_value": False,
            "feeds_buy_score": False,
            "feeds_role_watch": False,
            "feeds_pitcher_publication": False,
        },
        "validation": {"problems": []},
    }
    problems = validate_stage1_outcome_proof(payload)
    if problems:
        raise ValueError("Stage 1 proof failed validation: " + "; ".join(problems))
    return payload


def validate_stage1_outcome_proof(payload: dict) -> list[str]:
    problems = []
    if payload.get("artifact") != "valucast_stage1_outcome_proof":
        problems.append("artifact name is invalid")
    if payload.get("status") != "research_only":
        problems.append("status must be research_only")
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is invalid")
    roles = ((payload.get("historical") or {}).get("roles") or {})
    if set(roles) != set(ROLES):
        problems.append("historical roles must be hitter and pitcher")
    for role, summary in roles.items():
        if sum(band["sample_size"] for band in summary.get("evidence_bands") or []) != summary.get("sample_size"):
            problems.append(f"{role} evidence bands do not reconcile")
        if len(summary.get("cohorts") or {}) != summary.get("cohort_count"):
            problems.append(f"{role} cohort detail does not reconcile")
    evaluation = payload.get("evaluation") or {}
    if roles and sum(int(summary.get("sample_size", 0)) for summary in roles.values()) != evaluation.get("historical_rows"):
        problems.append("hitter and pitcher samples do not reconcile to the matched population")
    disagreements = payload.get("disagreements") or {}
    scopes = [disagreements.get("overall") or {}, *((disagreements.get("roles") or {}).values())]
    for scope in scopes:
        for cell in [scope, *((scope.get("bins") or {}).values())]:
            if cell and sum(int(cell.get(key, 0)) for key in FUNNEL_STATUSES) != int(cell.get("total", 0)):
                problems.append("disagreement lifecycle does not partition its population")
    sources = payload.get("sources") or {}
    if set(sources) != {"oof", "reliability", "backtest", "scorecard"}:
        problems.append("source hashes are incomplete")
    if any(
        not isinstance(value, dict)
        or not value.get("path")
        or not isinstance(value.get("sha256"), str)
        or len(value["sha256"]) != 64
        for value in sources.values()
    ):
        problems.append("sources must include paths and SHA-256 digests")
    policy = payload.get("policy") or {}
    if policy.get("public_superiority_authorized") is not False:
        problems.append("retrospective evidence cannot authorize public superiority")
    for key in (
        "feeds_model_score", "feeds_public_rank", "feeds_value", "feeds_buy_score",
        "feeds_role_watch", "feeds_pitcher_publication",
    ):
        if policy.get(key) is not False:
            problems.append(f"policy.{key} must be false")
    serialized = json.dumps(payload, sort_keys=True).lower()
    for forbidden in ("source_ranks", "public_source_consensus", "fangraphs", "mlb pipeline", "eephus", "efv", "wag"):
        if forbidden in serialized:
            problems.append(f"forbidden public-comparison token present: {forbidden}")
    return problems


def _estimate(cell: dict) -> str:
    if cell.get("point") is None:
        return "n/a"
    if cell.get("low") is None or cell.get("high") is None:
        return f"{cell['point']:.3f}"
    return f"{cell['point']:.3f} [{cell['low']:.3f}, {cell['high']:.3f}]"


def _point(value) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_markdown(payload: dict) -> str:
    lines = [
        "# ValuCast Stage 1 Outcome Proof",
        "",
        f"**Generated:** {payload['generated_at']}",
        f"**Stage 1 model:** {payload['versions']['stage1_model']}",
        f"**Backtest:** {payload['versions']['backtest']}",
        f"**Mature through cohort:** {payload['evaluation']['mature_through_cohort']}",
        f"**Bootstrap:** {payload['historical']['roles']['hitter']['bootstrap']['resamples']:,} player-clustered resamples; seed {payload['historical']['roles']['hitter']['bootstrap']['seed']}",
        "**Status:** Research-only retrospective evidence",
        "Public superiority authorized: **No**",
        "",
        "Contributor means a factual Role or Star outcome within the fixed four-year horizon. All historical rows are mature; open, censored, and retracted claim-time disagreements remain visible in their full funnel. These ordinal outcomes are not realized WAR.",
        "",
        "## Contributor discrimination and ordering",
        "",
        "### Closed-cohort detail",
        "",
        "| Role | Cohort | N | Contributor rate | Spearman | Kendall tau-b | ROC AUC |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for role in ROLES:
        for cohort, row in payload["historical"]["roles"][role]["cohorts"].items():
            lines.append(
                f"| {role.title()} | {cohort} | {row['sample_size']} | {row['contributor_base_rate']:.1%} | "
                f"{_point(row['metrics']['spearman_rho']['model'])} | "
                f"{_point(row['metrics']['kendall_tau_b']['model'])} | "
                f"{_point(row['metrics']['roc_auc']['model'])} |"
            )
    lines.extend([
        "",
        "### Pooled role results",
        "",
        "Each estimate is followed by its 95% player-cluster bootstrap interval. Baseline deltas remain descriptive unless their evidence status is `supported_retrospective`.",
        "",
        "| Role | Metric | ValuCast | Level/age prior | Historical neighbors (25) | vs prior | Evidence | vs neighbors | Evidence |",
        "|---|---|---:|---:|---:|---:|:---:|---:|:---:|",
    ])
    for role in ROLES:
        summary = payload["historical"]["roles"][role]
        metrics = summary["metrics"]
        for metric, label in (("spearman_rho", "Spearman rho"), ("kendall_tau_b", "Kendall tau-b"), ("roc_auc", "ROC AUC")):
            row = metrics[metric]
            prior_delta = row["model_minus_baseline"]["level_age_prior"]
            neighbor_delta = row["model_minus_baseline"]["historical_neighbors_25"]
            lines.append(
                f"| {role.title()} (n={summary['sample_size']}, {summary['cohort_count']} cohorts) | {label} | "
                f"{_estimate(row['model'])} | {_estimate(row['level_age_prior'])} | "
                f"{_estimate(row['historical_neighbors_25'])} | {_estimate(prior_delta)} | "
                f"{prior_delta['evidence_status']} | {_estimate(neighbor_delta)} | "
                f"{neighbor_delta['evidence_status']} |"
            )
    lines.extend([
        "",
        "## Stage 1 evidence bands",
        "",
        "Bands are within-role score deciles, not probabilities or public player grades.",
    ])
    for role in ROLES:
        lines.extend(["", f"### {role.title()}s", "", "| Decile | N | Score range | Bust | Role | Star | Contributor | 95% CI | Evidence |", "|---:|---:|---:|---:|---:|---:|---:|---:|---|"])
        for band in payload["historical"]["roles"][role]["evidence_bands"]:
            shares = band["outcome_shares"]
            interval = band["contributor_wilson95"]
            lines.append(
                f"| {band['decile']} | {band['sample_size']} | {band['score_min']:.3f}-{band['score_max']:.3f} | {shares['bust']:.1%} | "
                f"{shares['role']:.1%} | {shares['star']:.1%} | {band['contributor_rate']:.1%} | "
                f"{interval['low']:.1%}-{interval['high']:.1%} | {band['evidence_label']} |"
            )
    lines.extend([
        "",
        "## Frozen disagreements",
        "",
        "Initial-gap bins use frozen claim-time ranks. Open, resolved, censored, and retracted calls remain in the denominator.",
    ])
    gap_labels = {"25_49": "25-49", "50_99": "50-99", "100_199": "100-199", "200_plus": "200+"}
    lines.extend(["", "| Scope | Initial gap | Total | Open | Resolved | Censored | Retracted | Toward | Away | Evidence |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"])
    scopes = [("Overall", payload["disagreements"]["overall"])] + [
        (role.title(), payload["disagreements"]["roles"][role]) for role in ROLES
    ]
    for scope_label, scope in scopes:
        for key, gap_label in gap_labels.items():
            cell = scope["bins"].get(key, {**_empty_funnel(), "evidence_label": "insufficient"})
            lines.append(
                f"| {scope_label} | {gap_label} | {cell['total']} | {cell['open']} | {cell['resolved']} | "
                f"{cell['censored']} | {cell['retracted']} | {cell['moved_toward']} | {cell['moved_away']} | "
                f"{cell['evidence_label']} |"
            )
    lines.extend([
        "",
        "## Provenance",
        "",
        "| Input | Path | SHA-256 |",
        "|---|---|---|",
    ])
    for name, source in sorted(payload["sources"].items()):
        lines.append(f"| {name} | `{source['path']}` | `{source['sha256']}` |")
    lines.extend([
        "",
        "## Boundaries",
        "",
        "This report feeds no model score, rank, value, buy signal, Role Watch output, or pitcher publication decision.",
        "It does not claim WAR accuracy, probability calibration, or public superiority.",
        "",
    ])
    return "\n".join(lines)
```

- [ ] **Step 5: Run Task 2 tests**

Run: `python -m pytest tests/test_stage1_outcome_proof.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add prospects/stage1_outcome_proof.py tests/test_stage1_outcome_proof.py
git commit -m "feat: add Stage 1 evidence bands and disagreement funnel"
```

---

### Task 3: Reproducible CLI and committed research outputs

**Files:**
- Create: `scripts/build_stage1_outcome_proof.py`
- Modify: `tests/test_stage1_outcome_proof.py`
- Create: `data/validation/valucast_stage1_outcome_proof.json`
- Create: `docs/stage1-outcome-proof.md`

**Interfaces:**
- Consumes: the four committed source artifacts named in `INPUTS`.
- Produces: deterministic JSON and Markdown when source hashes are unchanged.

- [ ] **Step 1: Add failing CLI and drift-safe committed-artifact tests**

```python
import json
from pathlib import Path

import pytest

from prospects.stage1_outcome_proof import (
    render_markdown,
    validate_stage1_outcome_proof,
)
from scripts.build_stage1_outcome_proof import INPUTS, OUTPUT_JSON, OUTPUT_REPORT, _sha, run


def test_cli_writes_json_and_markdown(tmp_path):
    output_json = tmp_path / "proof.json"
    output_report = tmp_path / "proof.md"
    payload = run(output_json=output_json, output_report=output_report, resamples=100)
    assert json.loads(output_json.read_text(encoding="utf-8")) == payload
    assert output_report.read_text(encoding="utf-8") == render_markdown(payload)


def test_source_hash_is_line_ending_neutral(tmp_path):
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{\n  "ok": true\n}\n')
    crlf.write_bytes(b'{\r\n  "ok": true\r\n}\r\n')
    assert _sha(lf) == _sha(crlf)


def test_committed_inputs_rebuild_deterministically():
    first = run(write=False, resamples=10)
    second = run(write=False, resamples=10)
    assert first == second


def test_committed_outputs_validate_when_sources_match():
    committed = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
    current_hashes = {key: _sha(path) for key, path in INPUTS.items()}
    recorded_hashes = {key: value["sha256"] for key, value in committed["sources"].items()}
    if current_hashes != recorded_hashes:
        pytest.skip("daily source artifact advanced beyond this research snapshot")
    assert validate_stage1_outcome_proof(committed) == []
    assert render_markdown(committed) == OUTPUT_REPORT.read_text(encoding="utf-8")


def test_proof_module_and_artifact_have_no_production_importers():
    root = Path(__file__).resolve().parents[1]
    candidates = [
        path for path in root.rglob("*.py")
        if "tests" not in path.parts
        and "scripts" not in path.parts
        and path.name != "stage1_outcome_proof.py"
    ]
    for folder in (root / "templates", root / "static", root / ".github"):
        candidates.extend(
            path for path in folder.rglob("*")
            if path.suffix in {".html", ".js", ".yml", ".yaml"}
        )
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        assert "stage1_outcome_proof" not in text
        assert "valucast_stage1_outcome_proof" not in text
```

- [ ] **Step 2: Run the tests and verify the CLI import fails**

Run: `python -m pytest tests/test_stage1_outcome_proof.py -q`

Expected: collection fails because `scripts.build_stage1_outcome_proof` does not exist.

- [ ] **Step 3: Implement the CLI**

```python
"""Build the research-only Stage 1 outcome proof artifact and report."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from prospects.stage1_outcome_proof import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    build_stage1_outcome_proof,
    render_markdown,
)

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "oof": ROOT / "data/models/valucast_outcome_oof_scores.json",
    "reliability": ROOT / "data/models/valucast_probability_reliability.json",
    "backtest": ROOT / "data/models/valucast_prospect_dynasty_backtest.json",
    "scorecard": ROOT / "data/models/valucast_ahead_of_consensus_scorecard.json",
}
OUTPUT_JSON = ROOT / "data/validation/valucast_stage1_outcome_proof.json"
OUTPUT_REPORT = ROOT / "docs/stage1-outcome-proof.md"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def run(
    *,
    output_json: Path = OUTPUT_JSON,
    output_report: Path = OUTPUT_REPORT,
    seed: int = BOOTSTRAP_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
    write: bool = True,
) -> dict:
    inputs = {key: _load(path) for key, path in INPUTS.items()}
    generated_at = max(str(payload.get("generated_at") or "") for payload in inputs.values())
    payload = build_stage1_outcome_proof(
        oof_payload=inputs["oof"],
        reliability_payload=inputs["reliability"],
        backtest_payload=inputs["backtest"],
        scorecard_payload=inputs["scorecard"],
        sources={
            key: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha(path),
            }
            for key, path in INPUTS.items()
        },
        generated_at=generated_at,
        seed=seed,
        resamples=resamples,
    )
    if write:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_report.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        output_report.write_text(render_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--resamples", type=int, default=BOOTSTRAP_RESAMPLES)
    args = parser.parse_args()
    payload = run(seed=args.seed, resamples=args.resamples)
    print(f"wrote {OUTPUT_JSON} ({sum(role['sample_size'] for role in payload['historical']['roles'].values())} OOF rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Build the committed outputs**

Run: `python scripts/build_stage1_outcome_proof.py`

Expected: prints `wrote ...valucast_stage1_outcome_proof.json (2901 OOF rows)` and creates both outputs.

- [ ] **Step 5: Run the focused suite**

Run: `python -m pytest tests/test_stage1_outcome_proof.py tests/test_probability_reliability.py tests/test_consensus_decision_error_audit.py -q`

Expected: all tests pass.

- [ ] **Step 6: Inspect the generated boundaries and counts**

Run:

```powershell
@'
import json
p=json.load(open('data/validation/valucast_stage1_outcome_proof.json', encoding='utf-8'))
print(p['status'], p['policy'])
print({role: row['sample_size'] for role, row in p['historical']['roles'].items()})
print({role: row['cohort_count'] for role, row in p['historical']['roles'].items()})
print(p['disagreements']['overall']['total'])
'@ | python -
```

Expected: `research_only`; every policy flag is false; role samples sum to 2,901; each role has at least three cohorts; disagreement total matches the source scorecard call count.

- [ ] **Step 7: Commit Task 3**

```powershell
git add scripts/build_stage1_outcome_proof.py tests/test_stage1_outcome_proof.py data/validation/valucast_stage1_outcome_proof.json docs/stage1-outcome-proof.md
git commit -m "feat: publish research-only Stage 1 proof artifact"
```

---

### Task 4: Final regression and review gate

**Files:**
- Verify only; no planned source changes.

**Interfaces:**
- Consumes: all Task 1-3 commits.
- Produces: a reviewable branch with no production behavior change.

- [ ] **Step 1: Run the focused evidence tests**

Run: `python -m pytest tests/test_stage1_outcome_proof.py tests/test_probability_reliability.py tests/test_consensus_decision_error_audit.py tests/test_forward_cohort.py tests/test_forward_scoreboard.py -q`

Expected: all tests pass.

- [ ] **Step 2: Run the complete suite**

Run: `python -m pytest -q`

Expected: at least the baseline `3186 passed, 3 skipped, 18 subtests passed`, plus the new tests; no failures.

- [ ] **Step 3: Verify the diff is research-only**

Run:

```powershell
git diff --name-only 5b9a1d65..HEAD
rg -n "stage1_outcome_proof" app.py templates static .github prospects/rank_v1.py prospects/buy_score.py
git diff --check 5b9a1d65..HEAD
```

Expected: only the five planned files plus the approved design/plan documents appear; the production-import search returns no matches; `git diff --check` returns clean.

- [ ] **Step 4: Review the generated report before any public-surface proposal**

Check `docs/stage1-outcome-proof.md` for:

- hitter and pitcher rows shown separately;
- cohort sizes and intervals present;
- no competitor names, 20-80 grades, or per-player probabilities;
- no public-superiority authorization; and
- no claim that ordinal outcomes are realized WAR.

Expected: all five checks pass. Any public page is a separate owner-approved project.

- [ ] **Step 5: Commit only if verification required a plan correction**

```powershell
git status --short
```

Expected: clean. If a documentation-only correction was necessary, commit only that correction with `git commit -m "docs: clarify Stage 1 proof boundaries"`.
