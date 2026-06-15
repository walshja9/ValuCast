"""Bucket-level forward validation for ValuCast prospect boards.

This report is observe-only. It compares dated ValuCast-owned archives and
summarizes whether buckets are holding, rising, or falling across refreshes.
It does not use DD values, public rankings, market values, or realized MLB
outcomes, and it must not feed model scoring.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from prospects.buys import ARCHIVE_DIR as BUY_ARCHIVE_DIR
from prospects.rank_v1 import ARCHIVE_DIR as RANK_ARCHIVE_DIR

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_forward_validation.json"

REPORT_NAME = "ValuCast Prospect Forward Validation Report"
REPORT_VERSION = "0.1.0"

MIN_REVIEW_COMPARISONS = 7
MIN_REVIEW_SPAN_DAYS = 14
GRADE_THRESHOLDS = {
    "A-": {
        "minimum_rank_comparisons": 7,
        "minimum_buy_comparisons": 7,
        "minimum_span_days": 14,
        "minimum_buy_retention_rate": 0.45,
    },
    "A": {
        "minimum_rank_comparisons": 14,
        "minimum_buy_comparisons": 14,
        "minimum_span_days": 30,
        "minimum_buy_retention_rate": 0.55,
    },
    "A+": {
        "minimum_rank_comparisons": 30,
        "minimum_buy_comparisons": 30,
        "minimum_span_days": 60,
        "minimum_buy_retention_rate": 0.60,
    },
}
TOP_BUY_BOARD_SIZE = 40
LOWER_LEVELS = {"DSL", "CPX", "ROK", "A", "A+"}
UPPER_LEVELS = {"AA", "AAA", "MLB"}


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


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _archive_paths(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.glob("*.json")
        if path.stem.count("-") == 2
    )


def _load_archive_payloads(directory: Path) -> list[dict]:
    payloads = []
    for path in _archive_paths(directory):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        payload.setdefault("date", path.stem)
        payloads.append(payload)
    payloads.sort(key=lambda payload: str(payload.get("date") or ""))
    return payloads


def _identity_key(row: dict) -> tuple[str, str] | None:
    mlbam_id = row.get("mlbam_id")
    role = row.get("role")
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return str(mlbam_id), role


def _availability(row: dict) -> dict:
    components = row.get("components")
    components = components if isinstance(components, dict) else {}
    availability = components.get("availability")
    return availability if isinstance(availability, dict) else {}


def _availability_status(row: dict) -> str:
    return str(_availability(row).get("status") or "missing")


def _level(row: dict) -> str:
    return str(row.get("level") or "unknown").strip().upper() or "unknown"


def _level_band(row: dict) -> str:
    level = _level(row)
    if level in LOWER_LEVELS:
        return "lower_minors"
    if level in UPPER_LEVELS:
        return "upper_level"
    return "unknown_level"


def _role(row: dict) -> str:
    role = str(row.get("role") or "").strip().lower()
    return role if role in {"hitter", "pitcher"} else "unknown"


def _score_source(row: dict) -> str:
    return str(row.get("score_source") or "unknown_source")


def _evidence_bucket(row: dict) -> str:
    status = _availability_status(row)
    if status == "thin_current_sample":
        return "thin_current_sample"
    if status == "available":
        return "active_sample"
    if status in {"missing", ""}:
        return "missing_availability"
    return status


def _bucket_id(row: dict) -> str:
    return "|".join(
        [
            _role(row),
            _level_band(row),
            _score_source(row),
            _evidence_bucket(row),
        ]
    )


def _row_index(payload: dict) -> dict[tuple[str, str], dict]:
    index = {}
    for row in payload.get("board") or []:
        key = _identity_key(row)
        if key and key not in index:
            index[key] = row
    return index


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def _entry(row: dict, previous: dict | None = None) -> dict:
    rank = _clean_int(row.get("rank"))
    prev_rank = _clean_int((previous or {}).get("rank"))
    score = _clean_float(row.get("score"))
    prev_score = _clean_float((previous or {}).get("score"))
    return {
        "mlbam_id": row.get("mlbam_id"),
        "name": row.get("name"),
        "role": row.get("role"),
        "level": row.get("level"),
        "score_source": row.get("score_source"),
        "availability_status": _availability_status(row),
        "previous_rank": prev_rank,
        "current_rank": rank,
        "rank_change": None if rank is None or prev_rank is None else rank - prev_rank,
        "previous_score": prev_score,
        "current_score": score,
        "score_change": (
            None
            if score is None or prev_score is None
            else round(score - prev_score, 4)
        ),
    }


def _bucket_summary(
    bucket: str,
    current_rows: list[dict],
    previous_by_key: dict[tuple[str, str], dict],
) -> dict:
    rank_changes = []
    score_changes = []
    overlap_rows = []
    for row in current_rows:
        key = _identity_key(row)
        previous = previous_by_key.get(key) if key else None
        if not previous:
            continue
        rank = _clean_int(row.get("rank"))
        prev_rank = _clean_int(previous.get("rank"))
        score = _clean_float(row.get("score"))
        prev_score = _clean_float(previous.get("score"))
        if rank is not None and prev_rank is not None:
            rank_changes.append(float(rank - prev_rank))
        if score is not None and prev_score is not None:
            score_changes.append(score - prev_score)
        overlap_rows.append((row, previous))

    representative = current_rows[0] if current_rows else {}
    movers = sorted(
        (
            _entry(row, previous)
            for row, previous in overlap_rows
        ),
        key=lambda item: (
            -abs(item.get("rank_change") or 0),
            item.get("current_rank") or 999999,
            str(item.get("name") or ""),
        ),
    )[:10]
    return {
        "bucket": bucket,
        "role": _role(representative),
        "level_band": _level_band(representative),
        "score_source": _score_source(representative),
        "evidence_bucket": _evidence_bucket(representative),
        "current_count": len(current_rows),
        "current_top50_count": sum(
            1 for row in current_rows if (_clean_int(row.get("rank")) or 999999) <= 50
        ),
        "overlap_count": len(overlap_rows),
        "average_rank_change": _avg(rank_changes),
        "median_rank_change": _median(rank_changes),
        "average_absolute_rank_change": _avg([abs(value) for value in rank_changes]),
        "moved_up_count": sum(1 for value in rank_changes if value < 0),
        "moved_down_count": sum(1 for value in rank_changes if value > 0),
        "stable_rank_count": sum(1 for value in rank_changes if value == 0),
        "average_score_change": _avg(score_changes),
        "median_score_change": _median(score_changes),
        "largest_movers": movers,
    }


def compare_rank_archives(previous: dict, current: dict) -> dict:
    previous_by_key = _row_index(previous)
    current_by_key = _row_index(current)
    grouped: dict[str, list[dict]] = {}
    for row in current_by_key.values():
        grouped.setdefault(_bucket_id(row), []).append(row)
    summaries = [
        _bucket_summary(bucket, rows, previous_by_key)
        for bucket, rows in grouped.items()
    ]
    summaries.sort(
        key=lambda item: (
            item["current_top50_count"] == 0,
            item["current_top50_count"] * -1,
            item["bucket"],
        )
    )
    overlap = set(previous_by_key) & set(current_by_key)
    return {
        "previous_date": previous.get("date"),
        "current_date": current.get("date"),
        "previous_count": len(previous_by_key),
        "current_count": len(current_by_key),
        "overlap_count": len(overlap),
        "new_identity_count": len(set(current_by_key) - set(previous_by_key)),
        "exited_identity_count": len(set(previous_by_key) - set(current_by_key)),
        "bucket_count": len(summaries),
        "buckets": summaries,
    }


def _top_buy_keys(payload: dict, limit: int = TOP_BUY_BOARD_SIZE) -> dict[tuple[str, str], dict]:
    rows = sorted(
        payload.get("board") or [],
        key=lambda row: _clean_int(row.get("rank")) or 999999,
    )[:limit]
    return {key: row for row in rows if (key := _identity_key(row))}


def compare_buy_archives(previous: dict, current: dict) -> dict:
    previous_top = _top_buy_keys(previous)
    current_top = _top_buy_keys(current)
    overlap = sorted(set(previous_top) & set(current_top))
    rank_changes = []
    score_changes = []
    movers = []
    for key in overlap:
        row = current_top[key]
        previous_row = previous_top[key]
        rank = _clean_int(row.get("rank"))
        prev_rank = _clean_int(previous_row.get("rank"))
        score = _clean_float(row.get("score"))
        prev_score = _clean_float(previous_row.get("score"))
        if rank is not None and prev_rank is not None:
            rank_changes.append(float(rank - prev_rank))
        if score is not None and prev_score is not None:
            score_changes.append(score - prev_score)
        movers.append(_entry(row, previous_row))
    movers.sort(
        key=lambda item: (
            -abs(item.get("rank_change") or 0),
            item.get("current_rank") or 999999,
            str(item.get("name") or ""),
        )
    )
    return {
        "previous_date": previous.get("date"),
        "current_date": current.get("date"),
        "board_size": TOP_BUY_BOARD_SIZE,
        "previous_top_count": len(previous_top),
        "current_top_count": len(current_top),
        "retained_top_count": len(overlap),
        "retention_rate": round(len(overlap) / TOP_BUY_BOARD_SIZE, 4)
        if TOP_BUY_BOARD_SIZE
        else None,
        "new_top_count": len(set(current_top) - set(previous_top)),
        "exited_top_count": len(set(previous_top) - set(current_top)),
        "average_rank_change": _avg(rank_changes),
        "average_absolute_rank_change": _avg([abs(value) for value in rank_changes]),
        "average_score_change": _avg(score_changes),
        "largest_movers": movers[:15],
    }


def _span_days(payloads: list[dict]) -> int:
    dates = [date for payload in payloads if (date := _date_part(payload.get("date")))]
    if len(dates) < 2:
        return 0
    first = datetime.fromisoformat(dates[0]).date()
    last = datetime.fromisoformat(dates[-1]).date()
    return max(0, (last - first).days)


def _recommendations(rank_comparisons: list[dict], buy_comparisons: list[dict]) -> list[str]:
    recommendations = []
    latest = rank_comparisons[-1] if rank_comparisons else None
    if latest:
        watched = [
            bucket
            for bucket in latest.get("buckets") or []
            if bucket.get("current_top50_count", 0) > 0
            and bucket.get("evidence_bucket") in {"thin_current_sample", "injured"}
        ]
        if watched:
            recommendations.append(
                "Review top-50 availability-risk buckets before changing individual names."
            )
    latest_buy = buy_comparisons[-1] if buy_comparisons else None
    if latest_buy and (latest_buy.get("retention_rate") or 0.0) < 0.5:
        recommendations.append(
            "Buy top-40 retention is low; keep monitoring before tuning the buy-window curve."
        )
    if not recommendations:
        recommendations.append(
            "No bucket-level forward movement requires a scoring change yet; keep collecting archives."
        )
    return recommendations


def _evidence_status(
    rank_comparisons: list[dict],
    buy_comparisons: list[dict],
    span_days: int,
) -> dict:
    latest_buy = buy_comparisons[-1] if buy_comparisons else {}
    retention_rate = latest_buy.get("retention_rate")
    grades = {}
    achieved = None
    for grade, thresholds in GRADE_THRESHOLDS.items():
        missing = []
        if len(rank_comparisons) < thresholds["minimum_rank_comparisons"]:
            missing.append(
                {
                    "metric": "rank_comparison_count",
                    "current": len(rank_comparisons),
                    "required": thresholds["minimum_rank_comparisons"],
                }
            )
        if len(buy_comparisons) < thresholds["minimum_buy_comparisons"]:
            missing.append(
                {
                    "metric": "buy_comparison_count",
                    "current": len(buy_comparisons),
                    "required": thresholds["minimum_buy_comparisons"],
                }
            )
        if span_days < thresholds["minimum_span_days"]:
            missing.append(
                {
                    "metric": "observation_span_days",
                    "current": span_days,
                    "required": thresholds["minimum_span_days"],
                }
            )
        if retention_rate is None or retention_rate < thresholds["minimum_buy_retention_rate"]:
            missing.append(
                {
                    "metric": "latest_top40_buy_retention_rate",
                    "current": retention_rate,
                    "required": thresholds["minimum_buy_retention_rate"],
                }
            )
        passed = not missing
        if passed:
            achieved = grade
        grades[grade] = {
            "passed": passed,
            "missing": missing,
            **thresholds,
        }
    return {
        "status": "review_ready" if grades["A-"]["passed"] else "collecting",
        "current_supported_grade": achieved,
        "next_target_grade": (
            "A-"
            if achieved is None
            else "A"
            if achieved == "A-"
            else "A+"
            if achieved == "A"
            else None
        ),
        "thresholds": grades,
    }


def build_forward_validation_report(
    rank_payloads: list[dict],
    buy_payloads: list[dict] | None = None,
    generated_at: str | None = None,
) -> dict:
    buy_payloads = buy_payloads or []
    rank_comparisons = [
        compare_rank_archives(previous, current)
        for previous, current in zip(rank_payloads, rank_payloads[1:])
    ]
    buy_comparisons = [
        compare_buy_archives(previous, current)
        for previous, current in zip(buy_payloads, buy_payloads[1:])
    ]
    span_days = _span_days(rank_payloads)
    evidence_status = _evidence_status(
        rank_comparisons,
        buy_comparisons,
        span_days,
    )
    review_ready = evidence_status["status"] == "review_ready"
    status = "review_ready" if review_ready else "collecting"
    latest_rank = rank_payloads[-1] if rank_payloads else {}
    latest_buy = buy_payloads[-1] if buy_payloads else {}
    return {
        "artifact": "valucast_prospect_forward_validation",
        "report_name": REPORT_NAME,
        "report_version": REPORT_VERSION,
        "generated_at": generated_at
        or latest_rank.get("generated_at")
        or datetime.now(timezone.utc).isoformat(),
        "status": status,
        "source_policy": {
            "kind": "observe_only_forward_bucket_validation",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "observation_contract": {
            "is_realized_outcome_accuracy_evidence": False,
            "uses_valucast_archives_only": True,
            "minimum_review_comparisons": MIN_REVIEW_COMPARISONS,
            "minimum_review_span_days": MIN_REVIEW_SPAN_DAYS,
            "bucket_shape": "role|level_band|score_source|availability_status",
            "grade_thresholds": GRADE_THRESHOLDS,
        },
        "input_artifacts": {
            "rank_archive_count": len(rank_payloads),
            "buy_archive_count": len(buy_payloads),
            "latest_rank_date": latest_rank.get("date"),
            "latest_rank_version": latest_rank.get("rank_version"),
            "latest_buy_date": latest_buy.get("date"),
            "latest_buy_signal_version": latest_buy.get("signal_version"),
        },
        "metrics": {
            "rank_comparison_count": len(rank_comparisons),
            "buy_comparison_count": len(buy_comparisons),
            "observation_span_days": span_days,
            "latest_rank_bucket_count": (
                rank_comparisons[-1].get("bucket_count") if rank_comparisons else 0
            ),
        },
        "latest_rank_comparison": rank_comparisons[-1] if rank_comparisons else None,
        "latest_buy_comparison": buy_comparisons[-1] if buy_comparisons else None,
        "evidence_status": evidence_status,
        "rank_comparisons": rank_comparisons,
        "buy_comparisons": buy_comparisons,
        "recommendations": _recommendations(rank_comparisons, buy_comparisons),
    }


def write_forward_validation_report(
    payload: dict,
    path: Path = ARTIFACT_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_forward_validation_report(
    rank_archive_dir: Path = RANK_ARCHIVE_DIR,
    buy_archive_dir: Path = BUY_ARCHIVE_DIR,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_forward_validation_report(
        _load_archive_payloads(rank_archive_dir),
        _load_archive_payloads(buy_archive_dir),
    )
    path = write_forward_validation_report(payload, artifact_path)
    metrics = payload.get("metrics") or {}
    return {
        "artifact_path": str(path),
        "status": payload["status"],
        "rank_comparison_count": metrics.get("rank_comparison_count"),
        "buy_comparison_count": metrics.get("buy_comparison_count"),
        "observation_span_days": metrics.get("observation_span_days"),
    }
