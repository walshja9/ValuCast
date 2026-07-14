"""Calibration report for ValuCast Prospect Peak Projection V2 visuals.

This artifact is a review layer only. It groups the current peak-projection
output by role, level, risk, and confidence so we can tune the model by bucket
instead of by single-player vibes.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PEAK_PATH = ROOT / "data" / "models" / "valucast_prospect_peak_projection_v1.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_peak_projection_calibration.json"

ARTIFACT_NAME = "valucast_prospect_peak_projection_calibration"
CALIBRATION_VERSION = "0.1.0"


def _num(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _level_band(level: str | None) -> str:
    value = str(level or "").upper()
    if value == "MLB":
        return "mlb"
    if value in {"AAA", "AA"}:
        return "upper_minors"
    if value in {"A+", "A"}:
        return "lower_minors"
    if value:
        return "complex_or_unknown"
    return "unknown"


def _bucket_key(row: dict) -> tuple[str, str, str, str]:
    return (
        str(row.get("role") or "unknown"),
        _level_band(row.get("level")),
        str(row.get("risk_band") or "unknown"),
        str(row.get("confidence") or "unknown"),
    )


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _bucket_row(key: tuple[str, str, str, str], rows: list[dict]) -> dict:
    current_scores = [_num(row.get("rank_v1_score")) for row in rows]
    peak_scores = [_num(row.get("peak_score")) for row in rows]
    deltas = [
        peak - current
        for peak, current in zip(peak_scores, current_scores, strict=False)
        if peak is not None and current is not None
    ]
    high_delta = [row for row in rows if (_num(row.get("peak_score")) or 0) - (_num(row.get("rank_v1_score")) or 0) >= 10]
    negative_delta = [row for row in rows if (_num(row.get("peak_score")) or 0) - (_num(row.get("rank_v1_score")) or 0) < 0]
    big_negative_delta = [row for row in rows if (_num(row.get("peak_score")) or 0) - (_num(row.get("rank_v1_score")) or 0) <= -10]
    role, level_band, risk, confidence = key
    return {
        "role": role,
        "level_band": level_band,
        "risk": risk,
        "confidence": confidence,
        "count": len(rows),
        "avg_current_score": _avg([v for v in current_scores if v is not None]),
        "avg_peak_score": _avg([v for v in peak_scores if v is not None]),
        "avg_delta": _avg(deltas),
        "high_delta_count": len(high_delta),
        "negative_delta_count": len(negative_delta),
        "big_negative_delta_count": len(big_negative_delta),
        "sample_players": [
            {
                "name": str(row.get("name") or ""),
                "rank": row.get("rank_v1_rank"),
                "current": _num(row.get("rank_v1_score")),
                "peak": _num(row.get("peak_score")),
            }
            for row in rows[:5]
        ],
    }


def _watch_items(bucket_rows: list[dict]) -> list[dict]:
    items = []
    for row in bucket_rows:
        count = int(row.get("count") or 0)
        avg_delta = _num(row.get("avg_delta")) or 0.0
        if count < 8:
            continue
        if avg_delta >= 8.0:
            label = "peak_aggressive"
        elif avg_delta <= -8.0:
            label = "peak_conservative"
        elif row.get("risk") == "high" and (_num(row.get("avg_peak_score")) or 0) >= 52:
            label = "high_risk_peak_watch"
        else:
            continue
        items.append(
            {
                "watch": label,
                "role": row["role"],
                "level_band": row["level_band"],
                "risk": row["risk"],
                "confidence": row["confidence"],
                "count": count,
                "avg_delta": row.get("avg_delta"),
                "avg_peak_score": row.get("avg_peak_score"),
            }
        )
    return items


def build_peak_calibration_report(
    peak_payload: dict,
    *,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    projections = [row for row in peak_payload.get("projections") or [] if isinstance(row, dict)]
    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in projections:
        grouped[_bucket_key(row)].append(row)
    buckets = [_bucket_row(key, rows) for key, rows in sorted(grouped.items())]
    buckets.sort(key=lambda row: (-int(row["count"]), row["role"], row["level_band"]))
    blockers = []
    if not projections:
        blockers.append("Peak calibration has no projection rows.")
    if not buckets:
        blockers.append("Peak calibration has no bucket rows.")
    missing_card_v2 = sum(1 for row in projections if not isinstance(row.get("card_v2"), dict))
    if missing_card_v2:
        blockers.append("Some peak projection rows are missing Card V2 context.")
    watch_items = _watch_items(buckets)
    return {
        "artifact": ARTIFACT_NAME,
        "calibration_version": CALIBRATION_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "source_policy": {
            "kind": "peak_projection_bucket_review",
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used_for_score": False,
            "public_scouting_grades_used": False,
            "feeds_live_rank": False,
            "feeds_live_value": False,
        },
        "input_artifacts": {
            "peak_projection_version": peak_payload.get("projection_version"),
            "peak_projection_generated_at": peak_payload.get("generated_at"),
        },
        "summary": {
            "projection_count": len(projections),
            "bucket_count": len(buckets),
            "watch_item_count": len(watch_items),
            "missing_card_v2_count": missing_card_v2,
        },
        "validation": {
            "ready_for_review": not blockers,
            "blockers": blockers,
        },
        "watch_items": watch_items,
        "buckets": buckets,
    }


def run_peak_calibration_report(
    *,
    peak_path: Path = PEAK_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    peak_payload = json.loads(peak_path.read_text(encoding="utf-8"))
    payload = build_peak_calibration_report(peak_payload)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "ready_for_review": payload["validation"]["ready_for_review"],
        "bucket_count": payload["summary"]["bucket_count"],
        "watch_item_count": payload["summary"]["watch_item_count"],
    }
