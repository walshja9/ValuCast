"""Adversarial failure report for the ValuCast front-office track."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospects.forward_validation import ARTIFACT_PATH as FORWARD_VALIDATION_PATH
from prospects.model_v07 import ARTIFACT_PATH as MODEL_V07_PATH
from prospects.outcome_backtest import ARTIFACT_PATH as OUTCOME_BACKTEST_PATH
from prospects.rank_v1 import ARTIFACT_PATH as RANK_V1_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_front_office_failures.json"

REPORT_VERSION = "0.1.0"
MAX_FRONT_OFFICE_RISKS = 25
MAX_V07_DISAGREEMENTS = 25


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _clean_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _components(row: dict) -> dict:
    value = row.get("components")
    return value if isinstance(value, dict) else {}


def _context(components: dict, key: str) -> dict:
    value = components.get(key)
    return value if isinstance(value, dict) else {}


def _risk_score(row: dict) -> tuple[float, list[str]]:
    components = _components(row)
    availability = _context(components, "availability")
    uncertainty = _context(components, "uncertainty")
    reasons = []
    score = 0.0

    rank = _clean_int(row.get("rank")) or 999999
    if rank <= 50:
        score += 3.0
    elif rank <= 100:
        score += 1.0

    availability_status = str(availability.get("status") or "")
    if availability_status and availability_status not in {"available", "clear"}:
        score += 3.0
        reasons.append(f"availability={availability_status}")
    risk_discount = _clean_float(components.get("availability_risk_discount")) or 0.0
    if risk_discount > 0:
        score += min(3.0, risk_discount * 20.0)
        reasons.append(f"risk_discount={risk_discount:.3f}")

    uncertainty_band = str(uncertainty.get("band") or "")
    if uncertainty_band in {"moderate", "wide"}:
        score += 2.0 if uncertainty_band == "moderate" else 3.0
        reasons.append(f"uncertainty={uncertainty_band}")

    source = str(row.get("score_source") or "")
    if source in {"universal_fallback", "identity_only_fallback"}:
        score += 3.0
        reasons.append(f"score_source={source}")
    elif source == "prospect_pedigree_v0_7":
        score += 1.5
        reasons.append("pedigree_score_source")

    factual = _context(components, "factual_current_context")
    skill_band = str(factual.get("skill_band") or "")
    if skill_band in {"thin", "limited", "low_impact"}:
        score += 2.0
        reasons.append(f"skill_band={skill_band}")

    return round(score, 4), reasons


def _front_office_risks(rank_payload: dict) -> list[dict]:
    rows = []
    for row in rank_payload.get("board") or []:
        risk, reasons = _risk_score(row)
        if not reasons:
            continue
        rows.append(
            {
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "level": row.get("level"),
                "rank": row.get("rank"),
                "score": row.get("score"),
                "risk_score": risk,
                "reasons": reasons,
            }
        )
    rows.sort(
        key=lambda item: (
            -(item["risk_score"] or 0.0),
            _clean_int(item.get("rank")) or 999999,
            str(item.get("name") or ""),
        )
    )
    return rows[:MAX_FRONT_OFFICE_RISKS]


def _v07_disagreements(model_v07: dict) -> list[dict]:
    rows = []
    for row in model_v07.get("candidates") or []:
        delta = _clean_float(row.get("v0_7_delta_vs_rank_v1"))
        if delta is None:
            continue
        rows.append(
            {
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "level": row.get("level"),
                "rank_v1_rank": row.get("rank_v1_rank"),
                "rank_v1_score": row.get("rank_v1_score"),
                "v0_7_shadow_score": row.get("v0_7_shadow_score"),
                "v0_7_delta_vs_rank_v1": delta,
                "score_source": row.get("score_source"),
                "availability_status": (row.get("candidate_features") or {}).get(
                    "availability_status"
                ),
            }
        )
    rows.sort(
        key=lambda item: (
            -abs(item["v0_7_delta_vs_rank_v1"]),
            _clean_int(item.get("rank_v1_rank")) or 999999,
            str(item.get("name") or ""),
        )
    )
    return rows[:MAX_V07_DISAGREEMENTS]


def build_front_office_failures(
    forward_validation: dict,
    outcome_backtest: dict,
    model_v07: dict,
    rank_payload: dict,
    generated_at: str | None = None,
) -> dict:
    generated = generated_at or rank_payload.get("generated_at") or datetime.now(
        timezone.utc
    ).isoformat()
    outcome_track = outcome_backtest.get("front_office_track") or {}
    latest_rank = forward_validation.get("latest_rank_comparison") or {}
    latest_buy = forward_validation.get("latest_buy_comparison") or {}
    front_office_risks = _front_office_risks(rank_payload)
    v07_disagreements = _v07_disagreements(model_v07)
    blocking_findings = []
    for reason in outcome_track.get("cap_reasons") or []:
        blocking_findings.append({"kind": "front_office_cap", "message": reason})
    if (forward_validation.get("metrics") or {}).get("rank_comparison_count", 0) < 7:
        blocking_findings.append(
            {
                "kind": "forward_history",
                "message": "Fewer than seven rank archive comparisons are available.",
            }
        )
    return {
        "artifact": "valucast_front_office_failures",
        "report_version": REPORT_VERSION,
        "generated_at": generated,
        "status": "watchlist_active",
        "source_policy": {
            "kind": "observe_only_front_office_failure_report",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "summary": {
            "blocking_finding_count": len(blocking_findings),
            "front_office_risk_count": len(front_office_risks),
            "v0_7_disagreement_count": len(v07_disagreements),
            "latest_rank_bucket_count": latest_rank.get("bucket_count"),
            "latest_buy_retention_rate": latest_buy.get("retention_rate"),
        },
        "blocking_findings": blocking_findings,
        "forward_archive_thresholds": forward_validation.get("evidence_status"),
        "latest_rank_bucket_watchlist": latest_rank.get("buckets", [])[:8],
        "latest_buy_largest_movers": latest_buy.get("largest_movers", [])[:15],
        "front_office_risks": front_office_risks,
        "v0_7_disagreements": v07_disagreements,
    }


def write_front_office_failures(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_front_office_failures(
    forward_validation_path: Path = FORWARD_VALIDATION_PATH,
    outcome_backtest_path: Path = OUTCOME_BACKTEST_PATH,
    model_v07_path: Path = MODEL_V07_PATH,
    rank_path: Path = RANK_V1_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_front_office_failures(
        _load(forward_validation_path),
        _load(outcome_backtest_path),
        _load(model_v07_path),
        _load(rank_path),
    )
    path = write_front_office_failures(payload, artifact_path)
    summary = payload["summary"]
    return {
        "artifact_path": str(path),
        "status": payload["status"],
        "blocking_finding_count": summary["blocking_finding_count"],
        "front_office_risk_count": summary["front_office_risk_count"],
        "v0_7_disagreement_count": summary["v0_7_disagreement_count"],
    }
