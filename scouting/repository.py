"""Build the ValuCast scouting report repository.

The repository stores a stat-grounded read keyed by MLBAM identity. When the
optional LLM writer is enabled and passes the voice guard, its text becomes the
published read; the deterministic stat read remains the fallback.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scouting import report_generator
from scouting.voice import handedness_problems
from web.public_snapshot_store import PublicSnapshotStore
from web import prospect_percentiles

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_scouting_reports.json"
RECENT_SIGNAL_PATH = ROOT / "data" / "models" / "valucast_recent_signal_report.json"
CARD_DATA_AUDIT_PATH = ROOT / "data" / "models" / "valucast_prospect_card_data_audit.json"
LLM_CACHE_PATH = ROOT / "data" / "models" / "valucast_scouting_llm_cache.json"

ARTIFACT_NAME = "valucast_scouting_report_repository"
REPOSITORY_VERSION = "0.1.0"
DEFAULT_MAX_PROSPECT_RANK = 500


def _report_status(text: str | None) -> str:
    if not text:
        return "missing"
    lowered = text.lower()
    if "no current performance sample" in lowered:
        return "thin_sample"
    if "injured" in lowered or "availability risk" in lowered:
        return "availability_context"
    return "stat_grounded"


def _valid_llm_text(report: dict) -> str | None:
    llm = report.get("report_llm")
    if not isinstance(llm, dict):
        return None
    if llm.get("valid") is not True:
        return None
    text = str(llm.get("text") or "").strip()
    handedness = handedness_problems(text, report)
    if handedness:
        llm["valid"] = False
        llm["hard_ok"] = False
        llm["handedness_problems"] = handedness
        problems = llm.get("problems")
        if isinstance(problems, dict):
            problems["handedness_problems"] = handedness
        else:
            llm["problems"] = {"handedness_problems": handedness}
        return None
    return text or None


def _publish_report_fields(reports: list[dict]) -> dict:
    """Set the public report text with guarded row-level LLM fallback."""
    llm_count = 0
    deterministic_count = 0
    for report in reports:
        llm_text = _valid_llm_text(report)
        if llm_text:
            report["published_report"] = llm_text
            report["published_report_source"] = "llm"
            llm_count += 1
        else:
            report["published_report"] = str(report.get("report") or "").strip()
            report["published_report_source"] = "deterministic"
            deterministic_count += 1
    return {
        "llm_published_report_count": llm_count,
        "deterministic_published_report_count": deterministic_count,
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_optional(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _identity_key(row) -> str | None:
    if row.mlbam_id in (None, "") or row.role in (None, ""):
        return None
    return f"{row.mlbam_id}_{str(row.role).lower()}"


def _hand_code(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("code") or value.get("description") or value.get("side")
    text = str(value or "").strip().upper()
    if text in {"L", "LEFT"} or text.startswith("LEFT "):
        return "L"
    if text in {"R", "RIGHT"} or text.startswith("RIGHT "):
        return "R"
    return None


def _index_rows(payload: dict, rows_key: str) -> dict[str, dict]:
    indexed = {}
    for raw in payload.get(rows_key) or []:
        if not isinstance(raw, dict):
            continue
        key = raw.get("identity_key")
        if not key and raw.get("mlbam_id") not in (None, "") and raw.get("role"):
            key = f"{raw['mlbam_id']}_{str(raw['role']).lower()}"
        if key and key not in indexed:
            indexed[str(key)] = raw
    return indexed


def _row_report(row, recent_signal: dict | None = None, card_data: dict | None = None) -> dict:
    text = prospect_percentiles.identity_line(row, {}) or ""
    peak = row.peak_projection_summary if row.has_peak_projection else None
    bats = _hand_code(
        getattr(row, "bats", None)
        or row.context.get("bats")
        or row.metadata.get("bats")
    )
    throws = _hand_code(
        getattr(row, "throws", None)
        or row.context.get("throws")
        or row.metadata.get("throws")
    )
    recent_context = None
    if recent_signal:
        recent_context = {
            "movement_label": recent_signal.get("movement_label"),
            "score_delta_3d": recent_signal.get("score_delta_3d"),
            "rank_delta_3d": recent_signal.get("rank_delta_3d"),
            "buy_rank": recent_signal.get("buy_rank"),
            "buy_score": recent_signal.get("buy_score"),
            "buy_reason": recent_signal.get("buy_reason"),
            "usage": recent_signal.get("usage"),
        }
    card_context = None
    if card_data:
        card_context = {
            "status": card_data.get("status"),
            "problems": list(card_data.get("problems") or []),
            "card_level": card_data.get("card_level"),
            "sample": card_data.get("sample"),
            "sample_unit": card_data.get("sample_unit"),
            "stat_line_source_kind": card_data.get("stat_line_source_kind"),
        }
    return {
        "id": row.id,
        "identity_key": _identity_key(row),
        "mlbam_id": str(row.mlbam_id),
        "name": row.name,
        "role": row.role,
        "bats": bats,
        "throws": throws,
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
        "recent_signal": recent_context,
        "card_data_status": card_context,
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


def _llm_enabled() -> bool:
    return os.environ.get("VALUCAST_SCOUTING_LLM", "").strip().lower() in ("1", "true", "yes", "on")


def _llm_grounding(row, percentiles: dict, pool_label: str | None) -> dict:
    """Source-tagged, ValuCast-owned facts for the LLM read. No DD values/ranks, no
    external rankings, no market values — only what the card already owns."""
    grounding = {
        "name": row.name,
        "role": row.role,
        "bats": _hand_code(getattr(row, "bats", None) or row.context.get("bats")),
        "throws": _hand_code(getattr(row, "throws", None) or row.context.get("throws")),
        "positions": list(row.positions or []),
        "team": row.team,
        "level": row.level,
        "age": row.age,
        "prospect_rank": row.prospect_rank,
        "current_minor_league_line": row.stat_line or None,
        "mlb_equivalent_translation": row.stat_line_translated or None,
        "best_single_level_line": row.best_single_level_stat_line or None,
        "current_skill_percentiles": percentiles or None,
        "percentile_pool": pool_label,
        "peak_projection": row.peak_projection_summary if row.has_peak_projection else None,
        "availability": row.availability_context or None,
        "sample_context": {
            "sample": row.context.get("stat_line_sample"),
            "sample_unit": row.context.get("stat_line_sample_unit"),
            "season": row.context.get("stat_line_sample_season"),
            "source_kind": row.context.get("stat_line_source_kind"),
        },
    }
    return {key: value for key, value in grounding.items() if value not in (None, {}, [])}


def _save_llm_cache(entries: dict) -> None:
    LLM_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"artifact": "valucast_scouting_llm_cache", "entries": entries}
    tmp = LLM_CACHE_PATH.with_suffix(LLM_CACHE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, LLM_CACHE_PATH)


def _attach_llm_reports(rows, reports, store) -> dict:
    """Attach `report_llm` to each report when available.

    Grounding-hash cached so only changed reports re-call the API. Offline / no
    key -> no calls, reports unchanged.
    """
    client = report_generator.default_client()
    if client is None:
        return {"enabled": True, "available": False, "generated": 0, "reused": 0, "flagged": 0}
    pool = prospect_percentiles.build_pool(store.get_all())
    cache = _load_optional(LLM_CACHE_PATH)
    entries = cache.get("entries") if isinstance(cache.get("entries"), dict) else {}
    generated = reused = flagged = 0
    fresh: dict = {}
    for row, report in zip(rows, reports):
        key = report.get("identity_key")
        if not key:
            continue
        percentiles = prospect_percentiles.card_percentiles(pool, row)
        grounding = _llm_grounding(row, percentiles, prospect_percentiles.pool_label(row))
        digest = report_generator.grounding_hash(grounding)
        cached = entries.get(key)
        if (
            isinstance(cached, dict)
            and cached.get("hash") == digest
            and cached.get("valid") is True
        ):
            result = cached
            reused += 1
        else:
            try:
                gen = report_generator.generate_report(grounding, client=client)
            except Exception:  # noqa: BLE001 - one bad call must not fail the daily build
                continue
            if gen is None:
                continue
            result = {
                "hash": digest, "text": gen["text"], "model": gen["model"],
                "valid": gen["valid"], "hard_ok": gen["hard_ok"], "problems": gen["problems"],
            }
            generated += 1
        fresh[key] = result
        if not result.get("valid"):
            flagged += 1
        report["report_llm"] = {
            "text": result["text"], "model": result["model"],
            "valid": result["valid"], "hard_ok": result.get("hard_ok"),
            "problems": result.get("problems"),
            "handedness_problems": (result.get("problems") or {}).get("handedness_problems"),
        }
    _save_llm_cache(fresh)
    return {
        "enabled": True, "available": True, "generated": generated,
        "reused": reused, "flagged": flagged, "report_count": len(fresh),
    }


def build_scouting_repository(
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    recent_signal_path: Path = RECENT_SIGNAL_PATH,
    card_data_audit_path: Path = CARD_DATA_AUDIT_PATH,
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
    recent_payload = _load_optional(recent_signal_path)
    card_audit_payload = _load_optional(card_data_audit_path)
    recent_index = _index_rows(recent_payload, "signals")
    card_index = _index_rows(card_audit_payload, "cards")
    reports = [
        _row_report(
            row,
            recent_signal=recent_index.get(_identity_key(row) or ""),
            card_data=card_index.get(_identity_key(row) or ""),
        )
        for row in rows
    ]
    llm_shadow = {"enabled": False, "available": False, "generated": 0, "reused": 0, "flagged": 0}
    if _llm_enabled():
        llm_shadow = _attach_llm_reports(rows, reports, store)
    publish_summary = _publish_report_fields(reports)
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
            "recent_signal_used_for_context": bool(recent_index),
            "card_data_audit_used_for_context": bool(card_index),
            "llm_generated": publish_summary["llm_published_report_count"] > 0,
            "llm_generated_for_report_text_only": publish_summary["llm_published_report_count"] > 0,
            "llm_shadow_enabled": False,
            "feeds_live_rank": False,
            "feeds_live_value": False,
        },
        "input_artifacts": {
            "public_snapshot_path": _display_path(snapshot_path),
            "public_snapshot_generated_at": store.generated_at,
            "public_snapshot_schema_version": store.schema_version,
            "recent_signal_path": _display_path(recent_signal_path),
            "recent_signal_generated_at": recent_payload.get("generated_at"),
            "card_data_audit_path": _display_path(card_data_audit_path),
            "card_data_audit_generated_at": card_audit_payload.get("generated_at"),
        },
        "summary": {
            "report_count": len(reports),
            "top100_report_count": top100_count,
            "missing_report_count": missing_report_count,
            "max_prospect_rank": max_prospect_rank,
            "llm_shadow": llm_shadow,
            **publish_summary,
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
    recent_signal_path: Path = RECENT_SIGNAL_PATH,
    card_data_audit_path: Path = CARD_DATA_AUDIT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        recent_signal_path=recent_signal_path,
        card_data_audit_path=card_data_audit_path,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "ready_for_repository": payload["validation"]["ready_for_repository"],
        "report_count": payload["validation"]["report_count"],
    }
