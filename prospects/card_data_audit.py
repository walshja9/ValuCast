"""Prospect-card data integrity audit for ValuCast.

This artifact watches the public prospect card contract: identity, team/level,
current stat context, graduation state, split-level labels, and peak/scouting
coverage. It does not feed rankings, values, buys, or model training.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web.public_snapshot_store import PublicSnapshotStore

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
FRESHNESS_AUDIT_PATH = ROOT / "data" / "models" / "valucast_milb_stat_freshness_audit.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_card_data_audit.json"

ARTIFACT_NAME = "valucast_prospect_card_data_audit"
AUDIT_VERSION = "0.1.0"
TOP50_N = 50
TOP200_N = 200


def _load_optional(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _identity_key(row) -> str | None:
    if row.mlbam_id in (None, "") or row.role in (None, ""):
        return None
    return f"{row.mlbam_id}_{str(row.role).lower()}"


def _status(blockers: list[str]) -> str:
    return "blocked" if blockers else "candidate_ready"


def _is_active_callup_bridge(row) -> bool:
    context = row.context if isinstance(row.context, dict) else {}
    graduation_context = context.get("graduation_context")
    if not isinstance(graduation_context, dict):
        graduation_context = {}
    metadata = row.metadata if isinstance(row.metadata, dict) else {}
    return (
        metadata.get("active_mlb_callup_bridge") is True
        or graduation_context.get("surface") == "active_mlb_roster_bridge"
    )


def _row_status(row) -> tuple[str, list[str]]:
    problems: list[str] = []
    active_callup_bridge = _is_active_callup_bridge(row)
    if not _identity_key(row):
        problems.append("missing identity")
    if row.team in (None, ""):
        problems.append("missing team")
    if row.age is None:
        problems.append("missing age")
    if not (row.card_level_label or row.level):
        problems.append("missing level")
    if not active_callup_bridge and (row.card_level_label == "MLB" or row.has_graduated):
        problems.append("graduated or MLB-level prospect")
    if not row.stat_line:
        problems.append("missing stat line")
    context = row.context if isinstance(row.context, dict) else {}
    if not context.get("stat_line_source_kind"):
        problems.append("missing stat context source")
    if not row.has_peak_projection:
        problems.append("missing peak projection")
    return ("ready" if not problems else "watch"), problems


def _card_row(row) -> dict[str, Any]:
    status, problems = _row_status(row)
    context = row.context if isinstance(row.context, dict) else {}
    return {
        "identity_key": _identity_key(row),
        "id": row.id,
        "mlbam_id": str(row.mlbam_id) if row.mlbam_id not in (None, "") else None,
        "role": row.role,
        "name": row.name,
        "team": row.team,
        "positions": list(row.positions or ()),
        "age": row.age,
        "prospect_rank": row.prospect_rank,
        "value": row.dynasty_value,
        "level": row.level,
        "card_level": row.card_level_label,
        "stat_line_level": context.get("stat_line_level"),
        "sample": context.get("stat_line_sample"),
        "sample_unit": context.get("stat_line_sample_unit"),
        "sample_season": context.get("stat_line_sample_season"),
        "stat_line_source_kind": context.get("stat_line_source_kind"),
        "has_stat_line": bool(row.stat_line),
        "has_split_level_sample": row.has_split_level_sample,
        "has_peak_projection": row.has_peak_projection,
        "has_graduated": row.has_graduated,
        "active_mlb_callup_bridge": _is_active_callup_bridge(row),
        "status": status,
        "problems": problems,
    }


def build_prospect_card_data_audit(
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    freshness_audit_path: Path = FRESHNESS_AUDIT_PATH,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    store = PublicSnapshotStore(snapshot_path)
    rows = []
    if store.is_available:
        rows = [
            row
            for row in store.get_all()
            if row.is_prospect and row.prospect_rank is not None
        ]
    rows.sort(key=lambda row: (row.prospect_rank or 999999, row.name))
    top50 = [row for row in rows if (row.prospect_rank or 999999) <= TOP50_N]
    top200 = [row for row in rows if (row.prospect_rank or 999999) <= TOP200_N]
    cards = [_card_row(row) for row in top200]

    identity_keys = [key for key in (_identity_key(row) for row in rows) if key]
    duplicate_identity_count = len(identity_keys) - len(set(identity_keys))
    top50_watch = [row for row in cards if (row.get("prospect_rank") or 999999) <= TOP50_N and row["status"] != "ready"]
    top200_watch = [row for row in cards if row["status"] != "ready"]
    freshness = _load_optional(freshness_audit_path)
    freshness_metrics = freshness.get("metrics") if isinstance(freshness.get("metrics"), dict) else {}

    blockers: list[str] = []
    if not rows:
        blockers.append("No prospect rows are available in the public snapshot.")
    if duplicate_identity_count:
        blockers.append("Duplicate MLBAM+role identities are present in the prospect card pool.")
    active_top50 = [
        row for row in top50
        if (row.card_level_label == "MLB" or row.has_graduated)
        and not _is_active_callup_bridge(row)
    ]
    if active_top50:
        blockers.append("Top-50 prospect cards include graduated or MLB-level players.")
    critical_top50 = [
        row for row in top50_watch
        if any(
            problem in {"missing identity", "missing team", "missing age", "missing level", "missing stat line", "missing stat context source"}
            for problem in row["problems"]
        )
    ]
    if critical_top50:
        blockers.append("Top-50 prospect cards are missing required identity or stat context.")
    if int(freshness_metrics.get("top50_history_fallback_count") or 0) > 0:
        blockers.append("Top-50 cards still rely on MiLB history fallback stat context.")
    if int(freshness_metrics.get("top50_stat_context_mismatch_count") or 0) > 0:
        blockers.append("Top-50 card stat context does not match the model's factual sample.")

    metrics = {
        "prospect_count": len(rows),
        "top50_count": len(top50),
        "top200_count": len(top200),
        "top50_watch_count": len(top50_watch),
        "top200_watch_count": len(top200_watch),
        "duplicate_identity_count": duplicate_identity_count,
        "missing_identity_count": sum(1 for row in cards if not row.get("identity_key")),
        "missing_team_count": sum(1 for row in cards if not row.get("team")),
        "missing_age_count": sum(1 for row in cards if row.get("age") is None),
        "missing_level_count": sum(1 for row in cards if not row.get("card_level")),
        "missing_stat_line_count": sum(1 for row in cards if not row.get("has_stat_line")),
        "missing_peak_projection_count": sum(1 for row in cards if not row.get("has_peak_projection")),
        "split_level_sample_count": sum(1 for row in cards if row.get("has_split_level_sample")),
        "active_mlb_level_count": sum(1 for row in cards if row.get("has_graduated") or row.get("card_level") == "MLB"),
        "freshness_top50_history_fallback_count": int(freshness_metrics.get("top50_history_fallback_count") or 0),
        "freshness_top50_stat_context_mismatch_count": int(freshness_metrics.get("top50_stat_context_mismatch_count") or 0),
    }
    return {
        "artifact": ARTIFACT_NAME,
        "audit_version": AUDIT_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "status": _status(blockers),
        "source_policy": {
            "kind": "valucast_prospect_card_data_audit",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "input_artifacts": {
            "public_snapshot_path": str(snapshot_path.relative_to(ROOT)) if snapshot_path.is_absolute() and ROOT in snapshot_path.parents else str(snapshot_path),
            "public_snapshot_generated_at": store.generated_at,
            "milb_stat_freshness_status": freshness.get("status"),
            "milb_stat_freshness_generated_at": freshness.get("generated_at"),
        },
        "metrics": metrics,
        "validation": {
            "ready_for_cards": not blockers,
            "blockers": blockers,
        },
        "samples": {
            "watch_top50": top50_watch[:15],
            "watch_top200": top200_watch[:25],
        },
        "cards": cards,
    }


def run_prospect_card_data_audit(
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    freshness_audit_path: Path = FRESHNESS_AUDIT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_prospect_card_data_audit(
        snapshot_path=snapshot_path,
        freshness_audit_path=freshness_audit_path,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "status": payload["status"],
        "ready_for_cards": payload["validation"]["ready_for_cards"],
        "top200_count": payload["metrics"]["top200_count"],
        "top200_watch_count": payload["metrics"]["top200_watch_count"],
    }
