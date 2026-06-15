"""Unified outcome evidence for ValuCast prospect work."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospects.adapter_backtest import ARTIFACT_PATH as ADAPTER_BACKTEST_PATH
from prospects.dynasty_backtest import ARTIFACT_PATH as DYNASTY_BACKTEST_PATH
from prospects.forward_validation import ARTIFACT_PATH as FORWARD_VALIDATION_PATH
from prospects.model import ARTIFACT_PATH as PROSPECT_MODEL_PATH
from prospects.model_v07 import ARTIFACT_PATH as MODEL_V07_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_outcome_backtest.json"

REPORT_NAME = "ValuCast Prospect Outcome Evidence"
REPORT_VERSION = "0.1.0"
MIN_REALIZED_OUTCOME_SAMPLE = 2_000
MIN_BUCKET_COHORT_COUNT = 8
MIN_BUCKET_COHORT_PASS_RATE = 0.75


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _status_from_gate(gate: dict | None) -> str:
    return str((gate or {}).get("status") or "missing")


def _role_samples(payload: dict) -> int:
    return sum(int(role.get("sample_size") or 0) for role in (payload.get("roles") or {}).values())


def _role_gates(payload: dict) -> dict:
    return {
        role: result.get("role_research_gate")
        for role, result in (payload.get("roles") or {}).items()
    }


def _role_metric_rows(payload: dict) -> list[dict]:
    rows = []
    for role, result in (payload.get("roles") or {}).items():
        rows.append(
            {
                "role": role,
                "research_gate": result.get("role_research_gate"),
                "sample_size": result.get("sample_size"),
                "fold_count": result.get("fold_count"),
                "candidate_rank_concordance": result.get("candidate_rank_concordance"),
                "baseline_rank_concordance": result.get("baseline_rank_concordance"),
                "candidate_multiclass_brier": result.get("candidate_multiclass_brier"),
                "baseline_multiclass_brier": result.get("baseline_multiclass_brier"),
                "candidate_top_quartile_precision": result.get(
                    "candidate_top_quartile_precision"
                ),
                "baseline_top_quartile_precision": result.get(
                    "baseline_top_quartile_precision"
                ),
            }
        )
    return rows


def _better_or_equal(candidate, baseline, *, lower_is_better: bool) -> bool:
    if candidate is None or baseline is None:
        return False
    return candidate <= baseline if lower_is_better else candidate >= baseline


def _cohort_rows(layer: str, payload: dict) -> list[dict]:
    rows = []
    for role, result in (payload.get("roles") or {}).items():
        for fold in result.get("folds") or []:
            if layer == "dynasty":
                primary_passed = _better_or_equal(
                    fold.get("candidate_multiclass_brier"),
                    fold.get("baseline_multiclass_brier"),
                    lower_is_better=True,
                )
                secondary_passed = _better_or_equal(
                    fold.get("candidate_rank_concordance"),
                    fold.get("baseline_rank_concordance"),
                    lower_is_better=False,
                )
                metrics = {
                    "candidate_multiclass_brier": fold.get(
                        "candidate_multiclass_brier"
                    ),
                    "baseline_multiclass_brier": fold.get(
                        "baseline_multiclass_brier"
                    ),
                    "candidate_rank_concordance": fold.get(
                        "candidate_rank_concordance"
                    ),
                    "baseline_rank_concordance": fold.get(
                        "baseline_rank_concordance"
                    ),
                }
            else:
                primary_passed = _better_or_equal(
                    fold.get("candidate_rank_concordance"),
                    fold.get("baseline_rank_concordance"),
                    lower_is_better=False,
                )
                secondary_passed = _better_or_equal(
                    fold.get("candidate_top_quartile_precision"),
                    fold.get("baseline_top_quartile_precision"),
                    lower_is_better=False,
                )
                metrics = {
                    "candidate_rank_concordance": fold.get(
                        "candidate_rank_concordance"
                    ),
                    "baseline_rank_concordance": fold.get(
                        "baseline_rank_concordance"
                    ),
                    "candidate_top_quartile_precision": fold.get(
                        "candidate_top_quartile_precision"
                    ),
                    "baseline_top_quartile_precision": fold.get(
                        "baseline_top_quartile_precision"
                    ),
                }
            rows.append(
                {
                    "bucket": f"{layer}|{role}|cohort_{fold.get('test_cohort')}",
                    "layer": layer,
                    "role": role,
                    "test_cohort": fold.get("test_cohort"),
                    "sample_size": fold.get("sample_size"),
                    "primary_non_regression": primary_passed,
                    "secondary_non_regression": secondary_passed,
                    "passed": primary_passed and secondary_passed,
                    "metrics": metrics,
                }
            )
    return rows


def _bucket_cohort_evidence(dynasty_backtest: dict, adapter_backtest: dict) -> dict:
    rows = _cohort_rows("dynasty", dynasty_backtest) + _cohort_rows(
        "adapter", adapter_backtest
    )
    passed = sum(1 for row in rows if row["passed"])
    total = len(rows)
    pass_rate = round(passed / total, 4) if total else 0.0
    by_role = {}
    for role in sorted({row["role"] for row in rows}):
        role_rows = [row for row in rows if row["role"] == role]
        role_passed = sum(1 for row in role_rows if row["passed"])
        by_role[role] = {
            "bucket_count": len(role_rows),
            "passed_count": role_passed,
            "pass_rate": round(role_passed / len(role_rows), 4) if role_rows else 0.0,
        }
    ready = (
        total >= MIN_BUCKET_COHORT_COUNT
        and pass_rate >= MIN_BUCKET_COHORT_PASS_RATE
        and all(summary["pass_rate"] >= MIN_BUCKET_COHORT_PASS_RATE for summary in by_role.values())
    )
    return {
        "status": "ready" if ready else "collecting",
        "bucket_definition": "validation_layer|role|test_cohort",
        "minimum_bucket_count": MIN_BUCKET_COHORT_COUNT,
        "minimum_pass_rate": MIN_BUCKET_COHORT_PASS_RATE,
        "bucket_count": total,
        "passed_count": passed,
        "pass_rate": pass_rate,
        "by_role": by_role,
        "buckets": rows,
    }


def _grade(score: int) -> str:
    if score >= 93:
        return "A"
    if score >= 90:
        return "A-"
    if score >= 87:
        return "B+"
    if score >= 83:
        return "B"
    if score >= 80:
        return "B-"
    if score >= 75:
        return "C+"
    if score >= 70:
        return "C"
    return "Incomplete"


def build_outcome_backtest(
    prospect_model: dict,
    dynasty_backtest: dict,
    adapter_backtest: dict,
    forward_validation: dict,
    model_v07: dict,
    generated_at: str | None = None,
) -> dict:
    generated = (
        generated_at
        or model_v07.get("generated_at")
        or forward_validation.get("generated_at")
        or dynasty_backtest.get("generated_at")
        or adapter_backtest.get("generated_at")
        or prospect_model.get("generated_at")
        or datetime.now(timezone.utc).isoformat()
    )
    model_board_gate = _status_from_gate(prospect_model.get("board_gate"))
    model_impact_gate = _status_from_gate(prospect_model.get("impact_board_gate"))
    dynasty_gate = (dynasty_backtest.get("promotion") or {}).get(
        "dynasty_layer_research_gate"
    )
    adapter_gate = (adapter_backtest.get("promotion") or {}).get(
        "adapter_research_gate"
    )
    forward_status = forward_validation.get("status")
    forward_evidence_status = forward_validation.get("evidence_status") or {}
    v07_validation = model_v07.get("validation") or {}
    bucket_cohort = _bucket_cohort_evidence(dynasty_backtest, adapter_backtest)
    bucket_cohort_ready = bucket_cohort["status"] == "ready"

    realized_samples = max(_role_samples(dynasty_backtest), _role_samples(adapter_backtest))
    raw_score = 0
    raw_score += 25 if dynasty_gate == "active" else 0
    raw_score += 20 if adapter_gate == "active" else 0
    raw_score += 15 if model_impact_gate == "active" else 0
    raw_score += 10 if model_board_gate == "active" else 4 if model_board_gate == "fallback" else 0
    raw_score += 10 if realized_samples >= MIN_REALIZED_OUTCOME_SAMPLE else 0
    raw_score += 10 if v07_validation.get("ready_for_backtest") is True else 0
    raw_score += 5 if forward_status == "review_ready" else 2 if forward_status == "collecting" else 0
    raw_score += 5 if not v07_validation.get("blockers") else 0
    raw_score = min(raw_score, 100)

    blockers = []
    evidence_gates = []
    if dynasty_gate != "active":
        blockers.append("Universal dynasty outcome distribution has not passed both roles.")
    if adapter_gate != "active":
        blockers.append("League adapter outcome backtest has not passed both roles.")
    if model_board_gate != "active":
        evidence_gates.append(
            {
                "kind": "ordinal_bridge",
                "message": "Ordinal bridge outcome gate is not active yet.",
                "current": model_board_gate,
                "required": "active",
            }
        )
    if forward_status != "review_ready":
        evidence_gates.append(
            {
                "kind": "forward_archives",
                "message": "Forward archives are still collecting; no live-outcome stability review yet.",
                "current": forward_status,
                "required": "review_ready",
            }
        )

    score_cap = 100
    cap_reasons = []
    if model_board_gate != "active":
        score_cap = min(score_cap, 87 if bucket_cohort_ready else 84)
        cap_reasons.append(
            "Ordinal bridge is still partial; bucket/cohort evidence caps the grade."
        )
    if forward_status != "review_ready":
        score_cap = min(score_cap, 87 if bucket_cohort_ready else 84)
        cap_reasons.append("Forward observations are not review-ready yet.")
    score = min(raw_score, score_cap)

    return {
        "artifact": "valucast_prospect_outcome_backtest",
        "report_name": REPORT_NAME,
        "report_version": REPORT_VERSION,
        "generated_at": generated,
        "status": "evidence_ready" if dynasty_gate == "active" and adapter_gate == "active" else "needs_work",
        "source_policy": {
            "kind": "realized_outcome_and_observe_only_evidence",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "front_office_track": {
            "score": score,
            "uncapped_score": raw_score,
            "score_cap": score_cap if score_cap < 100 else None,
            "cap_reasons": cap_reasons,
            "grade": _grade(score),
            "target_grade": "A-",
            "forward_supported_grade": forward_evidence_status.get(
                "current_supported_grade"
            ),
            "forward_next_target_grade": forward_evidence_status.get(
                "next_target_grade"
            ),
            "forward_thresholds": forward_evidence_status.get("thresholds"),
            "interpretation": (
                "Strong public-model evidence with real historical outcome support; "
                "not a club-grade system because proprietary scouting, medical, "
                "player-development, and tracking data are not present."
            ),
        },
        "evidence": {
            "ordinal_bridge_walk_forward": {
                "status": "partial" if model_board_gate == "fallback" else model_board_gate,
                "board_gate": prospect_model.get("board_gate"),
                "impact_board_gate": prospect_model.get("impact_board_gate"),
                "candidate_count": prospect_model.get("candidate_count"),
            },
            "dynasty_fixed_horizon": {
                "status": dynasty_gate,
                "sample_size": _role_samples(dynasty_backtest),
                "role_gates": _role_gates(dynasty_backtest),
                "roles": _role_metric_rows(dynasty_backtest),
                "promotion": dynasty_backtest.get("promotion"),
            },
            "adapter_fixed_horizon": {
                "status": adapter_gate,
                "sample_size": _role_samples(adapter_backtest),
                "role_gates": _role_gates(adapter_backtest),
                "roles": _role_metric_rows(adapter_backtest),
                "promotion": adapter_backtest.get("promotion"),
            },
            "forward_observation": {
                "status": forward_status,
                "is_realized_outcome_accuracy_evidence": False,
                "metrics": forward_validation.get("metrics"),
                "recommendations": forward_validation.get("recommendations") or [],
            },
            "model_v07_readiness": {
                "status": model_v07.get("status"),
                "model_version": model_v07.get("model_version"),
                "validation": v07_validation,
            },
            "bucket_cohort": bucket_cohort,
        },
        "validation": {
            "realized_outcome_sample_size": realized_samples,
            "minimum_realized_outcome_sample_size": MIN_REALIZED_OUTCOME_SAMPLE,
            "realized_evidence_ready": dynasty_gate == "active" and adapter_gate == "active",
            "bucket_cohort_evidence_ready": bucket_cohort_ready,
            "forward_evidence_ready": forward_status == "review_ready",
            "evidence_gates": evidence_gates,
            "blockers": blockers,
        },
        "generated_dates": {
            "prospect_model": _date_part(prospect_model.get("generated_at")),
            "dynasty_backtest": _date_part(dynasty_backtest.get("generated_at")),
            "adapter_backtest": _date_part(adapter_backtest.get("generated_at")),
            "forward_validation": _date_part(forward_validation.get("generated_at")),
            "model_v07": _date_part(model_v07.get("generated_at")),
        },
    }


def write_outcome_backtest(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_outcome_backtest(
    prospect_model_path: Path = PROSPECT_MODEL_PATH,
    dynasty_backtest_path: Path = DYNASTY_BACKTEST_PATH,
    adapter_backtest_path: Path = ADAPTER_BACKTEST_PATH,
    forward_validation_path: Path = FORWARD_VALIDATION_PATH,
    model_v07_path: Path = MODEL_V07_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_outcome_backtest(
        _load(prospect_model_path),
        _load(dynasty_backtest_path),
        _load(adapter_backtest_path),
        _load(forward_validation_path),
        _load(model_v07_path),
    )
    path = write_outcome_backtest(payload, artifact_path)
    return {
        "artifact_path": str(path),
        "status": payload["status"],
        "front_office_grade": payload["front_office_track"]["grade"],
        "front_office_score": payload["front_office_track"]["score"],
        "blocker_count": len(payload["validation"]["blockers"]),
        "evidence_gate_count": len(payload["validation"]["evidence_gates"]),
    }
