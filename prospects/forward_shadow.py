"""Forward shadow tracking for ValuCast prospect outcome and dynasty signals.

Forward observation measures archive integrity and prediction stability after
fresh factual input updates. It is not realized-outcome accuracy evidence and
cannot promote a live consumer.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median

from prospects.dynasty import (
    ARCHIVE_DIR as DYNASTY_ARCHIVE_DIR,
    ARTIFACT_PATH as DYNASTY_ARTIFACT_PATH,
    BACKTEST_PATH as DYNASTY_BACKTEST_PATH,
    run_layer,
)
from prospects.dynasty_backtest import run_backtest
from prospects.index import (
    ARCHIVE_DIR as INDEX_ARCHIVE_DIR,
    ARTIFACT_PATH as INDEX_ARTIFACT_PATH,
    BACKTEST_PATH as INDEX_BACKTEST_PATH,
    run_index,
)
from prospects.index_backtest import run_backtest as run_index_backtest
from prospects.model import INPUT_PATH
from prospects.universal import (
    ARCHIVE_DIR as UNIVERSAL_ARCHIVE_DIR,
    ARTIFACT_PATH as UNIVERSAL_ARTIFACT_PATH,
    load_input_contract,
    run_model,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_forward_shadow.json"
RUN_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_forward_shadow"

TRACKER_NAME = "ValuCast Prospect Forward Shadow Tracker"
TRACKER_VERSION = "0.1.0"
MIN_OBSERVATIONS = 30
MIN_OBSERVATION_SPAN_DAYS = 60
MIN_OVERLAP_RATE = 0.70
SIGNAL_FIELDS = (
    "bust_risk",
    "role_or_better_probability",
    "star_ceiling_probability",
    "expected_factual_outcome_tier",
    "outcome_uncertainty",
)


def input_fingerprint(path: Path = INPUT_PATH) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(payload: dict, path: Path, *, compact: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if compact
        else json.dumps(payload, indent=2, sort_keys=True)
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _portable_output(result: dict) -> dict:
    return {
        key: value
        for key, value in result.items()
        if not key.endswith("_path")
    }


def _archive_paths(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.glob("*.json")
        if path.stem.count("-") == 2
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _latest_manifest(run_archive_dir: Path = RUN_ARCHIVE_DIR) -> dict | None:
    paths = _archive_paths(run_archive_dir)
    return _load_json(paths[-1]) if paths else None


def should_run(
    fingerprint: str,
    run_archive_dir: Path = RUN_ARCHIVE_DIR,
    *,
    input_generated_at: str | None = None,
    force: bool = False,
) -> tuple[bool, str]:
    if force:
        return True, "forced"
    latest = _latest_manifest(run_archive_dir)
    if latest and latest.get("input_fingerprint") == fingerprint:
        return False, "unchanged_input"
    latest_generated_at = ((latest or {}).get("input_contract") or {}).get(
        "generated_at"
    )
    if latest_generated_at and input_generated_at:
        latest_time = _parse_timestamp(latest_generated_at)
        input_time = _parse_timestamp(input_generated_at)
        if input_time < latest_time:
            return False, "stale_input_contract"
    return True, "fresh_input"


def _profile_index(snapshot: dict) -> tuple[dict[tuple[int, str], dict], dict]:
    index = {}
    duplicate_count = 0
    invalid_count = 0
    for profile in snapshot.get("profiles") or []:
        mlbam_id = profile.get("mlbam_id")
        role = profile.get("role")
        signal = profile.get("dynasty_signal") or {}
        if (
            not isinstance(mlbam_id, int)
            or role not in {"hitter", "pitcher"}
            or any(
                not isinstance(signal.get(field), (int, float))
                or isinstance(signal.get(field), bool)
                for field in SIGNAL_FIELDS
            )
        ):
            invalid_count += 1
            continue
        key = (mlbam_id, role)
        if key in index:
            duplicate_count += 1
            continue
        index[key] = profile
    candidate_count_matches = snapshot.get("candidate_count") == len(
        snapshot.get("profiles") or []
    )
    return index, {
        "duplicate_identity_count": duplicate_count,
        "invalid_profile_count": invalid_count,
        "candidate_count_matches_profiles": candidate_count_matches,
    }


def _index_board(snapshot: dict) -> tuple[dict[tuple[int, str], dict], dict]:
    index = {}
    duplicate_count = 0
    invalid_count = 0
    ordering_valid = True
    previous_score = None
    previous_rank = 0
    for position, row in enumerate(snapshot.get("board") or [], 1):
        mlbam_id = row.get("mlbam_id")
        role = row.get("role")
        score = row.get("universal_prospect_index")
        rank = row.get("universal_rank")
        if (
            not isinstance(mlbam_id, int)
            or role not in {"hitter", "pitcher"}
            or not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not isinstance(rank, int)
            or isinstance(rank, bool)
            or rank < 1
        ):
            invalid_count += 1
            continue
        expected_rank = (
            previous_rank if previous_score is not None and score == previous_score else position
        )
        if (
            (previous_score is not None and score > previous_score)
            or rank != expected_rank
        ):
            ordering_valid = False
        previous_score = score
        previous_rank = rank
        key = (mlbam_id, role)
        if key in index:
            duplicate_count += 1
            continue
        index[key] = row
    return index, {
        "duplicate_identity_count": duplicate_count,
        "invalid_profile_count": invalid_count,
        "candidate_count_matches_board": snapshot.get("candidate_count")
        == len(snapshot.get("board") or []),
        "rank_ordering_valid": ordering_valid,
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index]


def _movement_summary(values: list[float]) -> dict:
    return {
        "median_absolute_change": round(median(values), 6) if values else None,
        "p90_absolute_change": (
            round(_percentile(values, 0.90), 6) if values else None
        ),
        "max_absolute_change": round(max(values), 6) if values else None,
    }


def compare_snapshots(previous: dict, current: dict) -> dict:
    previous_index, previous_integrity = _profile_index(previous)
    current_index, current_integrity = _profile_index(current)
    overlap = sorted(set(previous_index) & set(current_index))
    denominator = min(len(previous_index), len(current_index))
    overlap_rate = len(overlap) / denominator if denominator else None
    movement = {
        field: _movement_summary(
            [
                abs(
                    float(current_index[key]["dynasty_signal"][field])
                    - float(previous_index[key]["dynasty_signal"][field])
                )
                for key in overlap
            ]
        )
        for field in SIGNAL_FIELDS
    }
    tier_movers = sorted(
        (
            {
                "mlbam_id": key[0],
                "role": key[1],
                "name": current_index[key].get("name"),
                "previous_expected_factual_outcome_tier": previous_index[key][
                    "dynasty_signal"
                ]["expected_factual_outcome_tier"],
                "current_expected_factual_outcome_tier": current_index[key][
                    "dynasty_signal"
                ]["expected_factual_outcome_tier"],
                "absolute_change": round(
                    abs(
                        float(
                            current_index[key]["dynasty_signal"][
                                "expected_factual_outcome_tier"
                            ]
                        )
                        - float(
                            previous_index[key]["dynasty_signal"][
                                "expected_factual_outcome_tier"
                            ]
                        )
                    ),
                    6,
                ),
            }
            for key in overlap
        ),
        key=lambda row: (-row["absolute_change"], row["role"], row["mlbam_id"]),
    )[:25]
    return {
        "previous_date": previous.get("date"),
        "current_date": current.get("date"),
        "previous_candidate_count": len(previous_index),
        "current_candidate_count": len(current_index),
        "overlap_count": len(overlap),
        "overlap_rate": round(overlap_rate, 6) if overlap_rate is not None else None,
        "new_identity_count": len(set(current_index) - set(previous_index)),
        "exited_identity_count": len(set(previous_index) - set(current_index)),
        "integrity": {
            "previous": previous_integrity,
            "current": current_integrity,
        },
        "signal_movement": movement,
        "largest_expected_tier_movers": tier_movers,
    }


def compare_index_snapshots(previous: dict, current: dict) -> dict:
    previous_index, previous_integrity = _index_board(previous)
    current_index, current_integrity = _index_board(current)
    overlap = sorted(set(previous_index) & set(current_index))
    denominator = min(len(previous_index), len(current_index))
    overlap_rate = len(overlap) / denominator if denominator else None
    score_changes = [
        abs(
            float(current_index[key]["universal_prospect_index"])
            - float(previous_index[key]["universal_prospect_index"])
        )
        for key in overlap
    ]
    rank_changes = [
        abs(
            int(current_index[key]["universal_rank"])
            - int(previous_index[key]["universal_rank"])
        )
        for key in overlap
    ]
    movers = sorted(
        (
            {
                "mlbam_id": key[0],
                "role": key[1],
                "name": current_index[key].get("name"),
                "previous_rank": previous_index[key]["universal_rank"],
                "current_rank": current_index[key]["universal_rank"],
                "absolute_rank_change": abs(
                    int(current_index[key]["universal_rank"])
                    - int(previous_index[key]["universal_rank"])
                ),
                "previous_index": previous_index[key]["universal_prospect_index"],
                "current_index": current_index[key]["universal_prospect_index"],
                "absolute_index_change": round(
                    abs(
                        float(current_index[key]["universal_prospect_index"])
                        - float(previous_index[key]["universal_prospect_index"])
                    ),
                    6,
                ),
            }
            for key in overlap
        ),
        key=lambda row: (
            -row["absolute_rank_change"],
            -row["absolute_index_change"],
            row["role"],
            row["mlbam_id"],
        ),
    )[:25]
    return {
        "previous_date": previous.get("date"),
        "current_date": current.get("date"),
        "previous_candidate_count": len(previous_index),
        "current_candidate_count": len(current_index),
        "overlap_count": len(overlap),
        "overlap_rate": round(overlap_rate, 6) if overlap_rate is not None else None,
        "new_identity_count": len(set(current_index) - set(previous_index)),
        "exited_identity_count": len(set(previous_index) - set(current_index)),
        "integrity": {
            "previous": previous_integrity,
            "current": current_integrity,
        },
        "index_movement": _movement_summary(score_changes),
        "rank_movement": _movement_summary(rank_changes),
        "largest_rank_movers": movers,
    }


def _observation_span_days(manifests: list[dict]) -> int:
    if len(manifests) < 2:
        return 0
    first = date.fromisoformat(manifests[0]["date"])
    last = date.fromisoformat(manifests[-1]["date"])
    return (last - first).days


def build_report(
    run_archive_dir: Path = RUN_ARCHIVE_DIR,
    dynasty_archive_dir: Path = DYNASTY_ARCHIVE_DIR,
    index_archive_dir: Path = INDEX_ARCHIVE_DIR,
) -> dict:
    manifests = [_load_json(path) for path in _archive_paths(run_archive_dir)]
    manifest_by_date = {
        manifest["date"]: manifest
        for manifest in manifests
        if manifest.get("status") == "completed"
    }
    snapshots = []
    missing_snapshot_dates = []
    index_snapshots = []
    missing_index_snapshot_dates = []
    for date_str in sorted(manifest_by_date):
        path = dynasty_archive_dir / f"{date_str}.json"
        if path.exists():
            snapshots.append(_load_json(path))
        else:
            missing_snapshot_dates.append(date_str)
        index_path = index_archive_dir / f"{date_str}.json"
        if index_path.exists():
            index_snapshots.append(_load_json(index_path))
        else:
            missing_index_snapshot_dates.append(date_str)

    comparisons = [
        compare_snapshots(previous, current)
        for previous, current in zip(snapshots, snapshots[1:])
    ]
    index_comparisons = [
        compare_index_snapshots(previous, current)
        for previous, current in zip(index_snapshots, index_snapshots[1:])
    ]
    snapshot_integrity = [_profile_index(snapshot)[1] for snapshot in snapshots]
    index_snapshot_integrity = [
        _index_board(snapshot)[1] for snapshot in index_snapshots
    ]
    duplicate_count = sum(item["duplicate_identity_count"] for item in snapshot_integrity)
    invalid_count = sum(item["invalid_profile_count"] for item in snapshot_integrity)
    candidate_mismatch_count = sum(
        not item["candidate_count_matches_profiles"] for item in snapshot_integrity
    )
    index_duplicate_count = sum(
        item["duplicate_identity_count"] for item in index_snapshot_integrity
    )
    index_invalid_count = sum(
        item["invalid_profile_count"] for item in index_snapshot_integrity
    )
    index_candidate_mismatch_count = sum(
        not item["candidate_count_matches_board"] for item in index_snapshot_integrity
    )
    index_ordering_failure_count = sum(
        not item["rank_ordering_valid"] for item in index_snapshot_integrity
    )
    overlap_rates = [
        comparison["overlap_rate"]
        for comparison in comparisons
        if comparison["overlap_rate"] is not None
    ]
    minimum_overlap_rate = min(overlap_rates) if overlap_rates else None
    index_overlap_rates = [
        comparison["overlap_rate"]
        for comparison in index_comparisons
        if comparison["overlap_rate"] is not None
    ]
    minimum_index_overlap_rate = (
        min(index_overlap_rates) if index_overlap_rates else None
    )
    span_days = _observation_span_days(
        [manifest_by_date[date_str] for date_str in sorted(manifest_by_date)]
    )
    integrity_ok = not (
        missing_snapshot_dates
        or missing_index_snapshot_dates
        or duplicate_count
        or invalid_count
        or candidate_mismatch_count
        or index_duplicate_count
        or index_invalid_count
        or index_candidate_mismatch_count
        or index_ordering_failure_count
    )
    enough_observations = len(snapshots) >= MIN_OBSERVATIONS
    enough_span = span_days >= MIN_OBSERVATION_SPAN_DAYS
    overlap_ok = (
        minimum_overlap_rate is not None and minimum_overlap_rate >= MIN_OVERLAP_RATE
    )
    index_overlap_ok = (
        minimum_index_overlap_rate is not None
        and minimum_index_overlap_rate >= MIN_OVERLAP_RATE
    )
    review_ready = (
        integrity_ok
        and enough_observations
        and enough_span
        and overlap_ok
        and index_overlap_ok
    )
    status = (
        "blocked_integrity"
        if not integrity_ok
        else "review_ready"
        if review_ready
        else "collecting"
    )
    generated_at = manifests[-1].get("completed_at") if manifests else None
    return {
        "status": status,
        "tracker_name": TRACKER_NAME,
        "tracker_version": TRACKER_VERSION,
        "generated_at": generated_at,
        "observation_contract": {
            "purpose": "Measure forward archive integrity and prediction stability.",
            "is_outcome_accuracy_evidence": False,
            "minimum_observations": MIN_OBSERVATIONS,
            "minimum_observation_span_days": MIN_OBSERVATION_SPAN_DAYS,
            "minimum_overlap_rate": MIN_OVERLAP_RATE,
            "review_ready_means": (
                "Enough structurally sound forward observations exist for a human "
                "consumer-design review; it never authorizes live use."
            ),
        },
        "summary": {
            "completed_observation_count": len(snapshots),
            "observation_span_days": span_days,
            "comparison_count": len(comparisons),
            "index_comparison_count": len(index_comparisons),
            "minimum_overlap_rate": (
                round(minimum_overlap_rate, 6)
                if minimum_overlap_rate is not None
                else None
            ),
            "minimum_index_overlap_rate": (
                round(minimum_index_overlap_rate, 6)
                if minimum_index_overlap_rate is not None
                else None
            ),
            "latest_observation_date": snapshots[-1]["date"] if snapshots else None,
        },
        "integrity": {
            "status": "active" if integrity_ok else "blocked",
            "missing_snapshot_dates": missing_snapshot_dates,
            "missing_index_snapshot_dates": missing_index_snapshot_dates,
            "duplicate_identity_count": duplicate_count,
            "invalid_profile_count": invalid_count,
            "candidate_count_mismatch_count": candidate_mismatch_count,
            "index_duplicate_identity_count": index_duplicate_count,
            "index_invalid_profile_count": index_invalid_count,
            "index_candidate_count_mismatch_count": index_candidate_mismatch_count,
            "index_rank_ordering_failure_count": index_ordering_failure_count,
        },
        "readiness_checks": {
            "enough_observations": enough_observations,
            "enough_observation_span": enough_span,
            "overlap_guard": overlap_ok,
            "index_overlap_guard": index_overlap_ok,
            "integrity_guard": integrity_ok,
        },
        "latest_comparison": comparisons[-1] if comparisons else None,
        "latest_index_comparison": (
            index_comparisons[-1] if index_comparisons else None
        ),
        "comparisons": comparisons,
        "index_comparisons": index_comparisons,
        "promotion": {
            "forward_observation_status": status,
            "next_allowed_step": (
                "human_consumer_design_review" if review_ready else "continue_collection"
            ),
            "live_consumer": "blocked",
            "feeds_live_dd_value": False,
            "feeds_live_valucast_rank": False,
        },
    }


def write_report(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    return _write_json(payload, path)


def run_pipeline(
    *,
    input_path: Path = INPUT_PATH,
    universal_artifact_path: Path = UNIVERSAL_ARTIFACT_PATH,
    universal_archive_dir: Path = UNIVERSAL_ARCHIVE_DIR,
    dynasty_backtest_path: Path = DYNASTY_BACKTEST_PATH,
    dynasty_artifact_path: Path = DYNASTY_ARTIFACT_PATH,
    dynasty_archive_dir: Path = DYNASTY_ARCHIVE_DIR,
    index_backtest_path: Path = INDEX_BACKTEST_PATH,
    index_artifact_path: Path = INDEX_ARTIFACT_PATH,
    index_archive_dir: Path = INDEX_ARCHIVE_DIR,
    run_archive_dir: Path = RUN_ARCHIVE_DIR,
    report_path: Path = ARTIFACT_PATH,
    now: str | None = None,
    force: bool = False,
) -> dict:
    contract = load_input_contract(input_path)
    contract_generated_at = contract.get("generated_at")
    if not contract_generated_at and now is None:
        raise ValueError("Forward shadow automation requires input generated_at")
    observation_now = (
        now
        or contract_generated_at
        or datetime.now(timezone.utc).isoformat()
    )
    parsed_observation = _parse_timestamp(observation_now)
    date_str = parsed_observation.date().isoformat()
    fingerprint = input_fingerprint(input_path)
    run_allowed, reason = should_run(
        fingerprint,
        run_archive_dir,
        input_generated_at=contract_generated_at,
        force=force,
    )
    if not run_allowed:
        if reason == "stale_input_contract":
            raise ValueError("Refusing stale factual input contract")
        report = build_report(run_archive_dir, dynasty_archive_dir, index_archive_dir)
        write_report(report, report_path)
        return {
            "status": "skipped",
            "reason": reason,
            "date": date_str,
            "input_fingerprint": fingerprint,
            "report_path": str(report_path),
            "forward_observation_status": report["status"],
        }

    universal = run_model(
        input_path=input_path,
        artifact_path=universal_artifact_path,
        archive_dir=universal_archive_dir,
        now=observation_now,
    )
    dynasty_backtest = run_backtest(
        input_path=input_path,
        artifact_path=dynasty_backtest_path,
        now=observation_now,
    )
    index_backtest = run_index_backtest(
        input_path=input_path,
        dynasty_backtest_path=dynasty_backtest_path,
        artifact_path=index_backtest_path,
        now=observation_now,
    )
    dynasty = run_layer(
        universal_path=universal_artifact_path,
        backtest_path=dynasty_backtest_path,
        artifact_path=dynasty_artifact_path,
        archive_dir=dynasty_archive_dir,
    )
    index = run_index(
        universal_path=universal_artifact_path,
        backtest_path=index_backtest_path,
        artifact_path=index_artifact_path,
        archive_dir=index_archive_dir,
    )
    manifest = {
        "status": "completed",
        "date": date_str,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "tracker_version": TRACKER_VERSION,
        "input_fingerprint": fingerprint,
        "input_contract": {
            "schema_version": contract.get("schema_version"),
            "generated_at": contract.get("generated_at"),
            "fetched_date": (contract.get("current") or {}).get("fetched_date"),
            "source_policy": contract.get("source_policy"),
        },
        "outputs": {
            "universal_model": _portable_output(universal),
            "dynasty_backtest": _portable_output(dynasty_backtest),
            "dynasty_layer": _portable_output(dynasty),
            "universal_index_backtest": _portable_output(index_backtest),
            "universal_index": _portable_output(index),
        },
        "promotion": {
            "live_consumer": "blocked",
            "feeds_live_dd_value": False,
            "feeds_live_valucast_rank": False,
        },
    }
    manifest_path = _write_json(
        manifest,
        run_archive_dir / f"{date_str}.json",
        compact=True,
    )
    report = build_report(run_archive_dir, dynasty_archive_dir, index_archive_dir)
    write_report(report, report_path)
    return {
        "status": "completed",
        "reason": reason,
        "date": date_str,
        "input_fingerprint": fingerprint,
        "manifest_path": str(manifest_path),
        "report_path": str(report_path),
        "forward_observation_status": report["status"],
        "universal_candidates": universal["candidates"],
        "dynasty_candidates": dynasty["candidate_count"],
        "dynasty_research_gate": dynasty["research_gate"],
        "universal_index_candidates": index["candidate_count"],
        "universal_index_research_gate": index["research_gate"],
    }
