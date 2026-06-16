"""Daily pipeline observability artifact for ValuCast public data."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_pipeline_observability.json"

PUBLIC_SNAPSHOT = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
DD_FEED = ROOT / "data" / "dd" / "dd_dynasty_feed.json"
PROSPECT_INPUTS = ROOT / "data" / "prospects" / "prospect_model_inputs.json"
MLB_TRACK_RECORD = ROOT / "data" / "models" / "valucast_mlb_track_record.json"
MLB_AVAILABILITY = ROOT / "data" / "models" / "valucast_mlb_availability.json"
MLB_ROSTER_STATUS = ROOT / "data" / "models" / "valucast_mlb_roster_status.json"
MLB_DYNASTY_LAYER = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
PROSPECT_RANK = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
PROSPECT_AVAILABILITY = ROOT / "data" / "models" / "valucast_prospect_availability.json"
PROSPECT_COVERAGE_AUDIT = ROOT / "data" / "models" / "valucast_prospect_coverage_audit.json"
PROSPECT_CALIBRATION = ROOT / "data" / "models" / "valucast_prospect_calibration_report.json"
PROSPECT_MODEL_V07 = ROOT / "data" / "models" / "valucast_prospect_model_v0_7.json"
MILB_STAT_FRESHNESS = ROOT / "data" / "models" / "valucast_milb_stat_freshness_audit.json"
PROSPECT_CARD_DATA_AUDIT = ROOT / "data" / "models" / "valucast_prospect_card_data_audit.json"
RECENT_SIGNAL_REPORT = ROOT / "data" / "models" / "valucast_recent_signal_report.json"
QUALITY_GOVERNOR = ROOT / "data" / "models" / "valucast_quality_governor.json"
VALUCAST_BUYS = ROOT / "data" / "models" / "valucast_prospect_buys.json"
VALUCAST_BUYS_MONITOR = ROOT / "data" / "models" / "valucast_prospect_buys_monitor.json"
FRONT_OFFICE_FAILURES = ROOT / "data" / "models" / "valucast_front_office_failures.json"
REDRAFT_METADATA = ROOT / "data" / "projections" / "metadata.json"
STATCAST_PERCENTILES = ROOT / "data" / "statcast" / "percentiles.json"

OBSERVABILITY_VERSION = "0.1.0"

DATED_ARTIFACTS: tuple[tuple[Path, str, str], ...] = (
    (PUBLIC_SNAPSHOT, "generated_at", "public_snapshot"),
    (DD_FEED, "generated_at", "dd_feed"),
    (PROSPECT_INPUTS, "generated_at", "prospect_inputs"),
    (MLB_TRACK_RECORD, "generated_at", "mlb_track_record"),
    (MLB_AVAILABILITY, "generated_at", "mlb_availability"),
    (MLB_ROSTER_STATUS, "generated_at", "mlb_roster_status"),
    (MLB_DYNASTY_LAYER, "generated_at", "mlb_dynasty_layer"),
    (PROSPECT_RANK, "generated_at", "prospect_rank_v1"),
    (PROSPECT_AVAILABILITY, "generated_at", "prospect_availability"),
    (PROSPECT_COVERAGE_AUDIT, "generated_at", "prospect_coverage_audit"),
    (PROSPECT_CALIBRATION, "generated_at", "prospect_calibration_report"),
    (PROSPECT_MODEL_V07, "generated_at", "prospect_model_v0_7"),
    (MILB_STAT_FRESHNESS, "generated_at", "milb_stat_freshness_audit"),
    (PROSPECT_CARD_DATA_AUDIT, "generated_at", "prospect_card_data_audit"),
    (RECENT_SIGNAL_REPORT, "generated_at", "recent_signal_report"),
    (QUALITY_GOVERNOR, "generated_at", "quality_governor"),
    (VALUCAST_BUYS, "generated_at", "prospect_buys"),
    (VALUCAST_BUYS_MONITOR, "generated_at", "prospect_buys_monitor"),
    (FRONT_OFFICE_FAILURES, "generated_at", "front_office_failures"),
    (REDRAFT_METADATA, "as_of", "redraft_metadata"),
    (STATCAST_PERCENTILES, "as_of", "statcast_percentiles"),
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _expected_date(public_snapshot: dict | None, expected_date: str | None) -> str:
    if expected_date:
        return expected_date
    if public_snapshot and public_snapshot.get("generated_at"):
        return _date_part(public_snapshot.get("generated_at")) or ""
    return datetime.now(timezone.utc).date().isoformat()


def _artifact_status(path: Path, field: str, label: str, expected_date: str) -> dict:
    try:
        display_path = str(path.relative_to(ROOT))
    except ValueError:
        display_path = str(path)
    try:
        payload = _load(path)
    except Exception as exc:  # noqa: BLE001
        return {
            "label": label,
            "path": display_path,
            "field": field,
            "date": None,
            "matches_expected_date": False,
            "problem": f"unreadable: {exc}",
        }
    actual_value = payload.get(field)
    actual_date = _date_part(actual_value)
    return {
        "label": label,
        "path": display_path,
        "field": field,
        "value": actual_value,
        "date": actual_date,
        "matches_expected_date": actual_date == expected_date,
    }


def _targeted_row_refreshes(prospect_inputs: dict | None, expected_date: str) -> list[dict]:
    if not prospect_inputs:
        return []
    rows = []
    current = prospect_inputs.get("current") or {}
    default_fetched_date = current.get("fetched_date")
    for role_key in ("hitters", "pitchers"):
        for row in current.get(role_key) or []:
            if not isinstance(row, dict):
                continue
            fetched = _date_part(row.get("sample_fetched_date") or default_fetched_date)
            if fetched and fetched > expected_date:
                rows.append(
                    {
                        "name": row.get("name"),
                        "mlbam_id": row.get("mlbam_id"),
                        "role": row.get("role"),
                        "level": row.get("level"),
                        "sample_fetched_date": fetched,
                    }
                )
    rows.sort(key=lambda row: (row.get("sample_fetched_date") or "", row.get("name") or ""))
    return rows


def build_pipeline_observability(
    public_snapshot: dict | None,
    prospect_inputs: dict | None,
    expected_date: str | None = None,
    generated_at: str | None = None,
) -> dict:
    expected = _expected_date(public_snapshot, expected_date)
    generated = generated_at or (
        public_snapshot or {}
    ).get("generated_at") or datetime.now(timezone.utc).isoformat()
    artifacts = [
        _artifact_status(path, field, label, expected)
        for path, field, label in DATED_ARTIFACTS
    ]
    mismatches = [
        item
        for item in artifacts
        if not item.get("matches_expected_date") and not item.get("problem")
    ]
    missing_or_unreadable = [item for item in artifacts if item.get("problem")]
    targeted = _targeted_row_refreshes(prospect_inputs, expected)
    ready = not mismatches and not missing_or_unreadable
    return {
        "artifact": "valucast_pipeline_observability",
        "observability_version": OBSERVABILITY_VERSION,
        "generated_at": generated,
        "status": "candidate_ready" if ready else "blocked",
        "expected_date": expected,
        "schedule": {
            "workflow": ".github/workflows/daily-public-data.yml",
            "cron_utc": "30 13 * * *",
            "local_time_daylight": "9:30 AM ET",
            "local_time_standard": "8:30 AM ET",
            "upstream_dependency": "DD VPS nightly starts around 7:00 AM ET",
        },
        "source_policy": {
            "kind": "pipeline_observability",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "validation": {
            "ready_for_daily_publication": ready,
            "artifact_count": len(artifacts),
            "date_mismatch_count": len(mismatches),
            "missing_or_unreadable_count": len(missing_or_unreadable),
            "targeted_row_refresh_count": len(targeted),
        },
        "artifacts": artifacts,
        "date_mismatches": mismatches,
        "missing_or_unreadable": missing_or_unreadable,
        "targeted_row_refreshes": targeted[:25],
        "interpretation": (
            "This artifact explains daily pipeline freshness and timing. It is "
            "observe-only and never feeds ValuCast ranks, values, or buy scores."
        ),
    }


def write_pipeline_observability(
    payload: dict,
    path: Path = ARTIFACT_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_pipeline_observability(
    public_snapshot_path: Path = PUBLIC_SNAPSHOT,
    prospect_inputs_path: Path = PROSPECT_INPUTS,
    artifact_path: Path = ARTIFACT_PATH,
    expected_date: str | None = None,
) -> dict:
    public_snapshot = _load(public_snapshot_path) if public_snapshot_path.exists() else None
    prospect_inputs = _load(prospect_inputs_path) if prospect_inputs_path.exists() else None
    payload = build_pipeline_observability(
        public_snapshot,
        prospect_inputs,
        expected_date=expected_date,
    )
    path = write_pipeline_observability(payload, artifact_path)
    validation = payload["validation"]
    return {
        "artifact_path": str(path),
        "status": payload["status"],
        "ready_for_daily_publication": validation["ready_for_daily_publication"],
        "date_mismatch_count": validation["date_mismatch_count"],
        "missing_or_unreadable_count": validation["missing_or_unreadable_count"],
        "targeted_row_refresh_count": validation["targeted_row_refresh_count"],
    }
