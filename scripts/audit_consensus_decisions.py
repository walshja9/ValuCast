"""Audit matured Ahead-of-the-Curve decisions at their claim-time state.

Internal validation only. This module never feeds scoring, ranking, value,
publication, or public surfaces.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.ahead_of_consensus import _divergence_row  # noqa: E402


DEFAULT_SCORECARD_PATH = (
    ROOT / "data" / "models" / "valucast_ahead_of_consensus_scorecard.json"
)
DEFAULT_ARCHIVE_DIR = (
    ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
)
DEFAULT_OUTPUT_PATH = (
    ROOT / "data" / "validation" / "valucast_consensus_decision_error_audit.json"
)

DECIDED_STATUSES = frozenset(
    {"open_toward", "closed_caught_up", "open_away", "retired_we_backed_off"}
)
WIN_STATUSES = frozenset({"open_toward", "closed_caught_up"})
MATURITY_DAYS = 14
MIN_REPORTING_N = 10
MIN_CANDIDATE_N = 20


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def age_bin(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "missing"
    if number <= 19:
        return "19_or_younger"
    if number <= 21:
        return "20_21"
    if number <= 23:
        return "22_23"
    return "24_or_older"


def level_bin(value: Any) -> str:
    level = str(value or "").strip().upper()
    if level in {"ACL", "DSL", "FCL", "RK", "ROK", "ROOKIE", "CPX"}:
        return "complex_rookie"
    if level in {"A", "A+"}:
        return "a_a_plus"
    if level == "AA":
        return "aa"
    if level == "AAA":
        return "aaa"
    return "other_missing"


def confidence_bin(value: Any) -> str:
    confidence = str(value or "").strip().lower()
    return confidence if confidence in {"low", "medium", "high"} else "other_missing"


def reliability_bin(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "missing"
    if number < 25:
        return "below_25"
    if number < 50:
        return "25_49_99"
    return "50_plus"


def sample_bin(role: str, value: Any) -> str:
    number = _number(value)
    if number is None:
        return "missing"
    if role == "hitter":
        if number < 100:
            return "below_100_pa"
        if number < 200:
            return "100_199_pa"
        if number < 400:
            return "200_399_pa"
        return "400_plus_pa"
    if role == "pitcher":
        if number < 20:
            return "below_20_ip"
        if number < 50:
            return "20_49_99_ip"
        if number < 100:
            return "50_99_99_ip"
        return "100_plus_ip"
    return "missing"


def gap_bin(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "missing"
    if number < 50:
        return "25_49"
    if number < 100:
        return "50_99"
    if number < 200:
        return "100_199"
    return "200_plus"


def rank_bin(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "missing"
    if number <= 50:
        return "1_50"
    if number <= 100:
        return "51_100"
    if number <= 250:
        return "101_250"
    return "251_plus"


def coverage_bin(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "missing"
    if number <= 2:
        return "2"
    if number <= 4:
        return "3_4"
    return "5_plus"


def availability_bin(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status == "available":
        return "available"
    if any(token in status for token in ("thin", "limited", "rehab", "return")):
        return "limited"
    if any(
        token in status
        for token in ("injur", "inactive", "stale", "absent", "missing", "unavailable")
    ):
        return "unavailable"
    return "other_missing"


def wilson_interval(wins: int, n: int) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    z = NormalDist().inv_cdf(0.975)
    rate = wins / n
    denominator = 1 + (z * z / n)
    centre = rate + (z * z / (2 * n))
    margin = z * math.sqrt((rate * (1 - rate) / n) + (z * z / (4 * n * n)))
    return (
        round((centre - margin) / denominator, 3),
        round((centre + margin) / denominator, 3),
    )


def _evidence_status(n: int) -> str:
    if n < MIN_REPORTING_N:
        return "insufficient"
    if n < MIN_CANDIDATE_N:
        return "descriptive_only"
    return "eligible_for_exploratory_review"


def _outcome(status: str) -> str:
    if status in WIN_STATUSES:
        return "win"
    if status == "open_away":
        return "moved_away"
    if status == "retired_we_backed_off":
        return "retracted"
    raise ValueError(f"unsupported decided status: {status}")


def _segment_stats(records: list[dict]) -> dict:
    counts = Counter(record["outcome"] for record in records)
    n = len(records)
    wins = counts["win"]
    moved_away = counts["moved_away"]
    retracted = counts["retracted"]
    lower, upper = wilson_interval(wins, n)
    return {
        "n": n,
        "wins": wins,
        "moved_away": moved_away,
        "retracted": retracted,
        "win_rate": round(wins / n, 3) if n else None,
        "moved_away_rate": round(moved_away / n, 3) if n else None,
        "retraction_rate": round(retracted / n, 3) if n else None,
        "win_rate_wilson_95": {"lower": lower, "upper": upper},
        "evidence_status": _evidence_status(n),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity_key(row: dict) -> str | None:
    mlbam_id = row.get("mlbam_id")
    role = str(row.get("role") or "").lower()
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return f"{mlbam_id}_{role}"


def _role_from_identity_key(identity_key: str) -> str | None:
    _, separator, role = identity_key.rpartition("_")
    return role if separator and role in {"hitter", "pitcher"} else None


def _load_archive(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: dict[str, dict] = {}
    for row in payload.get("board") or []:
        if not isinstance(row, dict):
            continue
        key = _identity_key(row)
        if not key:
            continue
        if key in rows:
            raise ValueError(f"duplicate identity in claim-time archive {path.name}: {key}")
        rows[key] = row
    return rows


def _matured_decisions(scorecard: dict) -> list[dict]:
    return [
        call
        for call in scorecard.get("calls") or []
        if isinstance(call, dict)
        and call.get("status") in DECIDED_STATUSES
        and (_number(call.get("days_tracked")) or 0) >= MATURITY_DAYS
    ]


def _dimension_rows(records: list[dict], field: str) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[record[field]].append(record)
    return [
        {"segment": segment, **_segment_stats(grouped[segment])}
        for segment in sorted(grouped)
    ]


def _validate_summary(scorecard: dict, records: list[dict]) -> None:
    summary = scorecard.get("summary") or {}
    expected_n = int(summary.get("decided_count", -1))
    expected_wins = int(summary.get("wins", -1))
    actual = _segment_stats(records)
    if actual["n"] != expected_n or actual["wins"] != expected_wins:
        raise ValueError(
            "audit cohort does not reconcile with frozen scorecard summary: "
            f"expected n={expected_n}, wins={expected_wins}; "
            f"got n={actual['n']}, wins={actual['wins']}"
        )
    expected_rate = _number(summary.get("decided_rate"))
    if expected_rate is None or actual["win_rate"] != round(expected_rate, 3):
        raise ValueError(
            "audit decided rate does not reconcile with frozen scorecard summary: "
            f"expected {expected_rate}; got {actual['win_rate']}"
        )


def build_audit(
    *,
    scorecard_path: Path = DEFAULT_SCORECARD_PATH,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    generated_at: str | None = None,
) -> dict:
    scorecard_path = Path(scorecard_path)
    archive_dir = Path(archive_dir)
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    decisions = _matured_decisions(scorecard)
    archive_cache: dict[str, dict[str, dict]] = {}
    archive_paths: dict[str, Path] = {}
    joined: list[tuple[dict, dict, int]] = []
    join_errors: list[str] = []

    for call in decisions:
        claim_date = str(call.get("ahead_since") or "")
        identity_key = str(call.get("identity_key") or "")
        path = archive_dir / f"{claim_date}.json"
        if not claim_date or not path.exists():
            join_errors.append(f"missing archive for {identity_key} on {claim_date or 'missing date'}")
            continue
        if claim_date not in archive_cache:
            archive_cache[claim_date] = _load_archive(path)
            archive_paths[claim_date] = path
        row = archive_cache[claim_date].get(identity_key)
        expected_role = _role_from_identity_key(identity_key)
        if row is None or expected_role is None or row.get("role") != expected_role:
            join_errors.append(f"missing exact claim-time join for {identity_key} on {claim_date}")
            continue
        divergence = _divergence_row(row)
        if divergence is None or divergence.get("consensus_rank") is None:
            join_errors.append(f"missing claim-time consensus for {identity_key} on {claim_date}")
            continue
        if int(divergence["consensus_rank"]) != int(call.get("consensus_then")):
            join_errors.append(f"claim-time consensus mismatch for {identity_key} on {claim_date}")
            continue
        joined.append((call, row, int(divergence["board_count"])))

    if join_errors or len(joined) != len(decisions):
        detail = "; ".join(join_errors[:5])
        raise ValueError(
            "exact claim-time join failed: "
            f"joined {len(joined)} of {len(decisions)} decisions"
            + (f"; {detail}" if detail else "")
        )

    score_source_counts = Counter(str(row.get("score_source") or "") for _, row, _ in joined)
    records: list[dict] = []
    for call, row, board_count in joined:
        components = row.get("components") if isinstance(row.get("components"), dict) else {}
        availability = (
            components.get("availability")
            if isinstance(components.get("availability"), dict)
            else {}
        )
        context = row.get("context_only") if isinstance(row.get("context_only"), dict) else {}
        raw_source = str(row.get("score_source") or "")
        score_source = (
            raw_source
            if raw_source and score_source_counts[raw_source] >= MIN_REPORTING_N
            else "other_missing"
        )
        records.append(
            {
                "outcome": _outcome(str(call["status"])),
                "role": str(row["role"]),
                "level": level_bin(row.get("level")),
                "age": age_bin(row.get("age")),
                "confidence": confidence_bin(row.get("confidence")),
                "sample_reliability": reliability_bin(components.get("sample_reliability")),
                "current_sample": sample_bin(str(row["role"]), context.get("stat_line_sample")),
                "initial_gap": gap_bin(call.get("initial_gap")),
                "consensus_rank": rank_bin(call.get("consensus_then")),
                "board_coverage": coverage_bin(board_count),
                "availability": availability_bin(availability.get("status")),
                "score_source": score_source,
            }
        )

    _validate_summary(scorecard, records)
    dimension_fields = (
        "role",
        "level",
        "age",
        "confidence",
        "sample_reliability",
        "current_sample",
        "initial_gap",
        "consensus_rank",
        "board_coverage",
        "availability",
        "score_source",
    )
    dimensions = {field: _dimension_rows(records, field) for field in dimension_fields}
    for field, rows in dimensions.items():
        if sum(row["n"] for row in rows) != len(records):
            raise ValueError(f"dimension {field} does not reconcile with audit cohort")

    source_generated_at = str(scorecard.get("generated_at") or "")
    as_of = source_generated_at[:10] if len(source_generated_at) >= 10 else None
    manifest = [
        {"date": claim_date, "sha256": _sha256(archive_paths[claim_date])}
        for claim_date in sorted(archive_paths)
    ]
    manifest_sha256 = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    summary = scorecard.get("summary") or {}

    return {
        "artifact": "valucast_consensus_decision_error_audit",
        "schema_version": "1.0.0",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "as_of": as_of,
        "scope": {
            "kind": "matured_ahead_of_consensus_decisions",
            "minimum_days_tracked": MATURITY_DAYS,
            "decided_statuses": sorted(DECIDED_STATUSES),
            "claim_time_evidence_only": True,
        },
        "source_hashes": {
            "scorecard_sha256": _sha256(scorecard_path),
            "claim_archive_manifest_sha256": manifest_sha256,
            "claim_archive_count": len(manifest),
        },
        "quality": {
            "expected_decided_count": int(summary["decided_count"]),
            "joined_decided_count": len(records),
            "join_errors": [],
            "ready": True,
        },
        "overall": _segment_stats(records),
        "matched_control_context": {
            "control_lift": summary.get("control_lift"),
            "control_matured_n": (summary.get("control_matured_rates") or {}).get("n"),
            "control_toward_rate": (summary.get("control_matured_rates") or {}).get(
                "toward_rate"
            ),
            "segment_level_controls_reconstructed": False,
        },
        "dimensions": dimensions,
        "thresholds": {
            "minimum_reporting_n": MIN_REPORTING_N,
            "minimum_candidate_review_n": MIN_CANDIDATE_N,
            "interval": "two_sided_wilson_95",
        },
        "research_disposition": {
            "status": "exploratory_error_audit_only",
            "existing_registrations_checked_first": [
                "development_density",
                "position_value_x",
                "post_2026_prospect_challenger_epoch",
            ],
            "new_challenger_authorized": False,
            "fresh_untouched_cohort_required_for_post_audit_hypotheses": True,
        },
        "boundaries": {
            "feeds_model_score": False,
            "feeds_rank_or_value": False,
            "feeds_publication": False,
            "public_surface": False,
            "authorizes_new_claim": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD_PATH)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    payload = build_audit(scorecard_path=args.scorecard, archive_dir=args.archive_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {args.output} "
        f"({payload['overall']['n']} decisions, {payload['overall']['wins']} wins)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
