"""Side artifact for observe-only pooled-line prospect shadows."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

from prospects.model import (
    ARTIFACT_PATH as PROSPECT_MODEL_PATH,
    POOLED_SHADOW_USAGE,
    POOLED_SHADOW_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_NAME = "valucast_pooled_shadow"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_pooled_shadow.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_pooled_shadow"
SHADOW_VERSION = POOLED_SHADOW_VERSION


def _load_optional(path: Path) -> tuple[dict, list[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except Exception as exc:  # noqa: BLE001
        return {}, [f"{path} unreadable: {exc}"]


def _num(value) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_policy() -> dict:
    return {
        "kind": "valucast_pooled_line_shadow",
        "feeds_model_score": False,
        "feeds_public_rank": False,
        "feeds_buy_score": False,
        "feeds_live_valucast_rank": False,
        "feeds_live_dd_value": False,
        "dd_values_used": False,
        "external_rankings_used": False,
        "market_values_used": False,
    }


def _shadow_row(row: dict) -> dict | None:
    shadow = row.get("pooled_shadow")
    if not isinstance(shadow, dict):
        return None
    return {
        "mlbam_id": row.get("mlbam_id"),
        "role": row.get("role"),
        "name": row.get("name"),
        "normalized_name": row.get("normalized_name"),
        "team": row.get("team"),
        "position": row.get("position"),
        "level": row.get("level"),
        "valucast_prospect_rank": row.get("valucast_prospect_rank"),
        "valucast_impact_rank": row.get("valucast_impact_rank"),
        **shadow,
    }


def _p90(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.90) - 1))
    return ordered[index]


def _largest_movers(shadows: list[dict]) -> list[dict]:
    rows = sorted(
        shadows,
        key=lambda row: (
            -abs(_num(row.get("delta")) or 0.0),
            row.get("valucast_prospect_rank") or 999999,
            str(row.get("name") or ""),
        ),
    )[:25]
    return [
        {
            "mlbam_id": row.get("mlbam_id"),
            "role": row.get("role"),
            "name": row.get("name"),
            "served_score": row.get("served_score"),
            "pooled_score": row.get("pooled_score"),
            "delta": row.get("delta"),
            "served_sample": row.get("served_sample"),
            "pooled_sample": row.get("pooled_sample"),
            "levels_pooled": row.get("levels_pooled"),
            "n_levels": row.get("n_levels"),
        }
        for row in rows
    ]


def build_pooled_shadow(
    *,
    model_path: Path = PROSPECT_MODEL_PATH,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    model_payload, blockers = _load_optional(model_path)
    ranked = model_payload.get("ranked") if isinstance(model_payload, dict) else None
    if ranked is None and not blockers:
        blockers.append(f"{model_path} missing ranked rows")
    if ranked is not None and not isinstance(ranked, list):
        blockers.append(f"{model_path} ranked must be a list")
        ranked = []
    ranked = ranked or []
    shadows = [
        shadow
        for shadow in (_shadow_row(row) for row in ranked if isinstance(row, dict))
        if shadow is not None
    ]
    abs_deltas = [abs(_num(row.get("delta")) or 0.0) for row in shadows]
    summary = {
        "scored_count": len(ranked),
        "shadowed_count": len(shadows),
        "multi_level_count": sum(1 for row in shadows if (row.get("n_levels") or 0) >= 2),
        "nontrivial_delta_count": sum(1 for value in abs_deltas if value >= 0.01),
        "median_abs_delta": round(median(abs_deltas), 4) if abs_deltas else 0.0,
        "p90_abs_delta": round(_p90(abs_deltas), 4),
        "largest_movers": _largest_movers(shadows),
    }
    return {
        "artifact": ARTIFACT_NAME,
        "shadow_version": SHADOW_VERSION,
        "generated_at": generated_at,
        "status": "blocked" if blockers else "candidate_ready",
        "source_policy": _source_policy(),
        "summary": summary,
        "shadows": shadows,
        "validation": {
            "ready": not blockers,
            "blockers": blockers,
        },
    }


def _write_json(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def archive_pooled_shadow(
    payload: dict, archive_dir: Path = ARCHIVE_DIR, date_str: str | None = None
) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    if date_str is None:
        generated_at = datetime.fromisoformat(
            str(payload["generated_at"]).replace("Z", "+00:00")
        )
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        date_str = generated_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    path = archive_dir / f"{date_str}.json"
    return _write_json(payload, path)


def run_pooled_shadow(
    *,
    model_path: Path = PROSPECT_MODEL_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    generated_at: str | None = None,
) -> dict:
    payload = build_pooled_shadow(model_path=model_path, generated_at=generated_at)
    path = _write_json(payload, artifact_path)
    archive_path = archive_pooled_shadow(payload, archive_dir)
    summary = payload["summary"]
    return {
        "artifact_path": str(path),
        "archive_path": str(archive_path),
        "status": payload["status"],
        "scored_count": summary["scored_count"],
        "shadowed_count": summary["shadowed_count"],
        "multi_level_count": summary["multi_level_count"],
        "nontrivial_delta_count": summary["nontrivial_delta_count"],
    }
