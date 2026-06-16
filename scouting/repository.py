"""Build a deterministic ValuCast scouting report repository.

The repository stores the same stat-grounded read used on player cards, keyed by
MLBAM identity. It is intentionally deterministic for this first pass; a future
LLM writer can consume this artifact as grounding, but cannot replace the facts.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from web.public_snapshot_store import PublicSnapshotStore
from web import prospect_percentiles

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_scouting_reports.json"

ARTIFACT_NAME = "valucast_scouting_report_repository"
REPOSITORY_VERSION = "0.1.0"
DEFAULT_MAX_PROSPECT_RANK = 300


def _report_status(text: str | None) -> str:
    if not text:
        return "missing"
    lowered = text.lower()
    if "no current performance sample" in lowered:
        return "thin_sample"
    if "injured" in lowered or "availability risk" in lowered:
        return "availability_context"
    return "stat_grounded"


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _row_report(row) -> dict:
    text = prospect_percentiles.identity_line(row, {}) or ""
    peak = row.peak_projection_summary if row.has_peak_projection else None
    return {
        "id": row.id,
        "mlbam_id": str(row.mlbam_id),
        "name": row.name,
        "role": row.role,
        "team": row.team,
        "positions": list(row.positions or []),
        "player_type": row.player_type,
        "prospect_rank": row.prospect_rank,
        "dynasty_value": row.dynasty_value,
        "confidence": row.confidence,
        "level": row.level,
        "age": row.age,
        "report": text,
        "report_status": _report_status(text),
        "peak_summary": peak,
        "source_fields": {
            "stat_line_source": row.context.get("stat_line_source"),
            "stat_line_sample": row.context.get("stat_line_sample"),
            "stat_line_sample_unit": row.context.get("stat_line_sample_unit"),
            "stat_line_sample_season": row.context.get("stat_line_sample_season"),
            "score_source": row.value_source,
            "peak_projection": row.has_peak_projection,
        },
        "usage": "scouting_repository_context_not_live_rank_or_value",
    }


def build_scouting_repository(
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    generated_at: str | None = None,
    max_prospect_rank: int = DEFAULT_MAX_PROSPECT_RANK,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    store = PublicSnapshotStore(snapshot_path)
    if not store.is_available:
        rows = []
    else:
        rows = [
            row
            for row in store.get_all()
            if row.is_prospect
            and row.prospect_rank is not None
            and row.prospect_rank <= max_prospect_rank
        ]
    reports = [_row_report(row) for row in rows]
    identity_keys = [(row["mlbam_id"], row["role"]) for row in reports]
    duplicate_identity_count = len(identity_keys) - len(set(identity_keys))
    missing_report_count = sum(1 for row in reports if not row.get("report"))
    top100_count = sum(
        1 for row in reports if row.get("prospect_rank") is not None and row["prospect_rank"] <= 100
    )
    blockers = []
    if not reports:
        blockers.append("Scouting repository has no reports.")
    if duplicate_identity_count:
        blockers.append("Scouting repository has duplicate MLBAM+role reports.")
    if top100_count < min(100, len(reports)):
        blockers.append("Scouting repository does not cover the visible top 100 prospects.")
    return {
        "artifact": ARTIFACT_NAME,
        "repository_version": REPOSITORY_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "source_policy": {
            "kind": "valucast_scouting_report_repository",
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used_for_report": False,
            "market_values_used_for_report": False,
            "llm_generated": False,
            "feeds_live_rank": False,
            "feeds_live_value": False,
        },
        "input_artifacts": {
            "public_snapshot_path": _display_path(snapshot_path),
            "public_snapshot_generated_at": store.generated_at,
            "public_snapshot_schema_version": store.schema_version,
        },
        "summary": {
            "report_count": len(reports),
            "top100_report_count": top100_count,
            "missing_report_count": missing_report_count,
            "max_prospect_rank": max_prospect_rank,
        },
        "validation": {
            "ready_for_repository": not blockers,
            "report_count": len(reports),
            "duplicate_identity_count": duplicate_identity_count,
            "missing_report_count": missing_report_count,
            "blockers": blockers,
        },
        "reports": reports,
    }


def run_scouting_repository(
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_scouting_repository(snapshot_path=snapshot_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "ready_for_repository": payload["validation"]["ready_for_repository"],
        "report_count": payload["validation"]["report_count"],
    }
