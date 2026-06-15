"""Front-office readiness report for ValuCast."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.buys_monitor import ARTIFACT_PATH as BUYS_MONITOR_PATH
from prospects.outcome_backtest import ARTIFACT_PATH as OUTCOME_BACKTEST_PATH
from prospects.raw_data_independence import ARTIFACT_PATH as RAW_INDEPENDENCE_PATH
from quality.valucast_governor import ARTIFACT_PATH as QUALITY_GOVERNOR_PATH

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
MODEL_V07_PATH = ROOT / "data" / "models" / "valucast_prospect_model_v0_7.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_front_office_report.json"

REPORT_VERSION = "0.1.0"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _grade_from_score(score: int) -> str:
    if score >= 97:
        return "A+"
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


def _pillar(name: str, score: int, status: str, evidence: dict) -> dict:
    return {
        "name": name,
        "score": score,
        "grade": _grade_from_score(score),
        "status": status,
        "evidence": evidence,
    }


def build_front_office_report(
    public_snapshot: dict,
    quality_governor: dict,
    outcome_backtest: dict,
    model_v07: dict,
    raw_independence: dict,
    buys_monitor: dict,
    generated_at: str | None = None,
) -> dict:
    generated = generated_at or public_snapshot.get("generated_at") or datetime.now(
        timezone.utc
    ).isoformat()
    snapshot_validation = public_snapshot.get("validation") or {}
    outcome_track = outcome_backtest.get("front_office_track") or {}
    v07_validation = model_v07.get("validation") or {}
    raw_validation = raw_independence.get("validation") or {}
    raw_score = float(
        (raw_independence.get("independence") or {}).get("direct_raw_ownership_score")
        or 0.0
    )
    buys_monitoring = buys_monitor.get("monitoring") or {}
    governor_ready = quality_governor.get("ready_for_public_snapshot") is True
    public_ready = snapshot_validation.get("ready_for_live_consumers") is True

    pillars = [
        _pillar(
            "Product readiness",
            95 if public_ready and governor_ready else 78,
            "public_ready" if public_ready and governor_ready else "needs_work",
            {
                "public_snapshot_ready": public_ready,
                "quality_governor_ready": governor_ready,
                "row_count": public_snapshot.get("row_count"),
                "surface_readiness": snapshot_validation.get("surface_readiness"),
            },
        ),
        _pillar(
            "Data pipeline readiness",
            92 if snapshot_validation.get("same_day_freshness") else 72,
            "same_day_fresh" if snapshot_validation.get("same_day_freshness") else "stale",
            {
                "same_day_freshness": snapshot_validation.get("same_day_freshness"),
                "required_fields_complete": snapshot_validation.get(
                    "required_fields_complete"
                ),
                "duplicate_identity_count": snapshot_validation.get(
                    "duplicate_identity_count"
                ),
            },
        ),
        _pillar(
            "Independence",
            88 if raw_validation.get("ready_for_current_publication") else 70,
            (
                "boundary_hardened"
                if raw_validation.get("ready_for_current_publication")
                else "blocked"
            ),
            {
                "direct_raw_ownership_score": raw_score,
                "raw_data_independence_complete": raw_validation.get(
                    "raw_data_independence_complete"
                ),
                "last_external_trust_boundary": (
                    raw_independence.get("independence") or {}
                ).get("last_external_trust_boundary"),
            },
        ),
        _pillar(
            "Prospect credibility",
            90
            if outcome_backtest.get("status") == "evidence_ready"
            and v07_validation.get("ready_for_backtest")
            else 78,
            (
                "historical_evidence_ready"
                if outcome_backtest.get("status") == "evidence_ready"
                else "needs_more_evidence"
            ),
            {
                "outcome_grade": outcome_track.get("grade"),
                "outcome_score": outcome_track.get("score"),
                "v07_ready_for_backtest": v07_validation.get("ready_for_backtest"),
                "v07_top200_factual_context_coverage": v07_validation.get(
                    "top200_factual_context_coverage"
                ),
            },
        ),
        _pillar(
            "MLB front-office track",
            int(outcome_track.get("score") or 0),
            "in_progress",
            {
                "current_grade": outcome_track.get("grade"),
                "target_grade": outcome_track.get("target_grade"),
                "limitations": outcome_track.get("interpretation"),
                "buys_monitor_status": buys_monitor.get("status"),
                "buy_comparison_count": buys_monitoring.get("buy_comparison_count"),
                "observation_span_days": buys_monitoring.get("observation_span_days"),
            },
        ),
    ]
    overall_score = round(sum(pillar["score"] for pillar in pillars) / len(pillars))
    return {
        "artifact": "valucast_front_office_report",
        "report_version": REPORT_VERSION,
        "generated_at": generated,
        "status": "front_office_track_active",
        "overall": {
            "score": overall_score,
            "grade": _grade_from_score(overall_score),
            "target": "A+ product/pipeline/independence/prospect credibility; B front-office track.",
        },
        "source_policy": {
            "kind": "readiness_report",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "pillars": pillars,
        "next_build_order": [
            "Expand realized outcome backtests by bucket and cohort.",
            "Train/compare Prospect Model v0.7 against v0.6 by bucket.",
            "Promote uncertainty bands into every prospect explanation.",
            "Move DD-hosted factual input production into ValuCast-owned raw jobs.",
            "Keep the front-office report public and fail-loud when evidence regresses.",
        ],
    }


def write_front_office_report(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_front_office_report(
    public_snapshot_path: Path = PUBLIC_SNAPSHOT_PATH,
    quality_governor_path: Path = QUALITY_GOVERNOR_PATH,
    outcome_backtest_path: Path = OUTCOME_BACKTEST_PATH,
    model_v07_path: Path = MODEL_V07_PATH,
    raw_independence_path: Path = RAW_INDEPENDENCE_PATH,
    buys_monitor_path: Path = BUYS_MONITOR_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_front_office_report(
        _load(public_snapshot_path),
        _load(quality_governor_path),
        _load(outcome_backtest_path),
        _load(model_v07_path),
        _load(raw_independence_path),
        _load(buys_monitor_path),
    )
    path = write_front_office_report(payload, artifact_path)
    return {
        "artifact_path": str(path),
        "grade": payload["overall"]["grade"],
        "score": payload["overall"]["score"],
        "status": payload["status"],
    }
