"""Monitoring artifact for ValuCast-owned prospect Buys v1."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.buys import ARTIFACT_PATH as BUY_PATH
from prospects.forward_validation import ARTIFACT_PATH as FORWARD_VALIDATION_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_buys_monitor.json"

MONITOR_NAME = "ValuCast Prospect Buys v1 Monitor"
MONITOR_VERSION = "0.1.0"
MIN_BUY_COMPARISONS_FOR_REVIEW = 7
MIN_OBSERVATION_SPAN_DAYS_FOR_REVIEW = 14
MIN_TOP40_RETENTION_RATE = 0.45
LOCKED_BUY_SIGNAL_VERSION = "1.0.0"


def _latest_buy_comparison(forward_validation: dict) -> dict:
    comparison = forward_validation.get("latest_buy_comparison")
    return comparison if isinstance(comparison, dict) else {}


def _monitor_status(blockers: list[str], review_ready: bool) -> str:
    if blockers:
        return "blocked"
    if review_ready:
        return "review_ready"
    return "collecting"


def build_buys_monitor(
    buy_payload: dict,
    forward_validation: dict,
    generated_at: str | None = None,
) -> dict:
    generated = generated_at or buy_payload.get("generated_at") or datetime.now(
        timezone.utc
    ).isoformat()
    buy_validation = buy_payload.get("validation") or {}
    promotion = buy_payload.get("promotion") or {}
    forward_metrics = forward_validation.get("metrics") or {}
    latest_buy = _latest_buy_comparison(forward_validation)

    buy_comparisons = int(forward_metrics.get("buy_comparison_count") or 0)
    span_days = int(forward_metrics.get("observation_span_days") or 0)
    retention_rate = latest_buy.get("retention_rate")
    review_ready = (
        buy_comparisons >= MIN_BUY_COMPARISONS_FOR_REVIEW
        and span_days >= MIN_OBSERVATION_SPAN_DAYS_FOR_REVIEW
    )

    blockers = []
    if buy_payload.get("signal_version") != LOCKED_BUY_SIGNAL_VERSION:
        blockers.append("ValuCast Buys monitor requires locked v1 buy signals.")
    if buy_validation.get("ready_for_live_consumers") is not True:
        blockers.append("ValuCast Buys artifact is not ready for live consumers.")
    if promotion.get("feeds_live_buys") is not True:
        blockers.append("ValuCast Buys promotion is not feeding live buys.")
    if (
        isinstance(retention_rate, (int, float))
        and retention_rate < MIN_TOP40_RETENTION_RATE
    ):
        blockers.append("ValuCast Buys top-40 retention is below monitor threshold.")

    status = _monitor_status(blockers, review_ready)
    next_action = (
        "investigate_buy_signal_quality"
        if blockers
        else (
            "review_bucket_movement_before_next_calibration"
            if review_ready
            else "collect_more_valucast_owned_buy_observations"
        )
    )

    return {
        "artifact": "valucast_prospect_buys_monitor",
        "monitor_name": MONITOR_NAME,
        "monitor_version": MONITOR_VERSION,
        "generated_at": generated,
        "status": status,
        "source_policy": {
            "kind": "observe_only_valucast_buy_monitor",
            "feeds_model_score": False,
            "feeds_buy_score": False,
            "feeds_public_rank": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "monitor_contract": {
            "monitors_live_buys_v1": True,
            "mutates_buy_scores": False,
            "uses_valucast_archives_only": True,
            "minimum_buy_comparisons_for_review": MIN_BUY_COMPARISONS_FOR_REVIEW,
            "minimum_observation_span_days_for_review": (
                MIN_OBSERVATION_SPAN_DAYS_FOR_REVIEW
            ),
        },
        "input_artifacts": {
            "buy_signal_version": buy_payload.get("signal_version"),
            "buy_generated_at": buy_payload.get("generated_at"),
            "forward_validation_status": forward_validation.get("status"),
            "forward_validation_report_version": forward_validation.get(
                "report_version"
            ),
        },
        "monitoring": {
            "feeds_live_buys": promotion.get("feeds_live_buys") is True,
            "ready_for_live_consumers": (
                buy_validation.get("ready_for_live_consumers") is True
            ),
            "buy_comparison_count": buy_comparisons,
            "observation_span_days": span_days,
            "latest_top40_retention_rate": retention_rate,
            "latest_top40_new_count": latest_buy.get("new_top_count"),
            "latest_top40_exited_count": latest_buy.get("exited_top_count"),
            "review_ready": review_ready,
            "next_action": next_action,
        },
        "validation": {
            "ready_for_monitoring": not blockers,
            "blockers": blockers,
            "min_top40_retention_rate": MIN_TOP40_RETENTION_RATE,
        },
        "recommendations": forward_validation.get("recommendations") or [],
    }


def write_buys_monitor(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_buys_monitor(
    buy_path: Path = BUY_PATH,
    forward_validation_path: Path = FORWARD_VALIDATION_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    buy_payload = json.loads(buy_path.read_text(encoding="utf-8"))
    forward_validation = json.loads(forward_validation_path.read_text(encoding="utf-8"))
    payload = build_buys_monitor(buy_payload, forward_validation)
    path = write_buys_monitor(payload, artifact_path)
    monitoring = payload["monitoring"]
    return {
        "artifact_path": str(path),
        "status": payload["status"],
        "ready_for_monitoring": payload["validation"]["ready_for_monitoring"],
        "buy_comparison_count": monitoring["buy_comparison_count"],
        "observation_span_days": monitoring["observation_span_days"],
    }
