"""MiLB current-stat freshness audit for ValuCast prospect cards.

This audit is intentionally separate from ranking. It watches whether the
visible prospect-card stat context is current enough to publish.
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INPUTS_PATH = ROOT / "data" / "prospects" / "prospect_model_inputs.json"
RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
PUBLIC_SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_milb_stat_freshness_audit.json"

AUDIT_VERSION = "0.1.0"
TOP50_N = 50
TOP200_N = 200
MAX_TOP50_HISTORY_FALLBACK_COUNT = 0
MAX_TOP50_STAT_CONTEXT_MISMATCH_COUNT = 0
MAX_TOP200_HISTORY_FALLBACK_COUNT = 10
MAX_CURRENT_ROW_STALE_FETCH_COUNT = 0


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


def _parse_date(value: Any) -> date | None:
    text = _date_part(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


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


def _current_rows(inputs: dict) -> list[dict]:
    current = inputs.get("current") or {}
    rows = []
    for role_key in ("hitters", "pitchers"):
        for row in current.get(role_key) or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _rank_rows(rank_payload: dict, limit: int) -> list[dict]:
    rows = list(rank_payload.get("board") or [])
    rows.sort(
        key=lambda row: (
            _clean_int(row.get("rank")) or 999999,
            str(row.get("name") or ""),
        )
    )
    ranked = [row for row in rows if (_clean_int(row.get("rank")) or 999999) <= limit]
    return ranked if ranked else rows[:limit]


def _components(row: dict) -> dict:
    value = row.get("components")
    return value if isinstance(value, dict) else {}


def _factual_context(row: dict) -> dict:
    value = _components(row).get("factual_current_context")
    return value if isinstance(value, dict) else {}


def _public_prospects(public_snapshot: dict | None, limit: int) -> list[dict]:
    if not public_snapshot:
        return []
    rows = [
        row
        for row in public_snapshot.get("players") or []
        if isinstance(row, dict) and row.get("player_type") == "prospect"
    ]
    rows.sort(
        key=lambda row: (
            _clean_int(row.get("prospect_rank")) or 999999,
            _clean_int(row.get("rank")) or 999999,
            str(row.get("name") or ""),
        )
    )
    return rows[:limit]


def _history_fallbacks(rank_payload: dict, limit: int) -> list[dict]:
    rows = []
    for row in _rank_rows(rank_payload, limit):
        factual = _factual_context(row)
        if factual.get("source_kind") == "current_season":
            continue
        availability = _components(row).get("availability") or {}
        rows.append(
            {
                "rank": row.get("rank"),
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "level": row.get("level"),
                "score": row.get("score"),
                "score_source": row.get("score_source"),
                "source_kind": factual.get("source_kind") or "missing",
                "sample": factual.get("sample"),
                "sample_unit": factual.get("sample_unit"),
                "sample_season": factual.get("sample_season"),
                "sample_fetched_date": availability.get("sample_fetched_date"),
            }
        )
    return rows


def _stale_current_rows(inputs: dict) -> list[dict]:
    expected = _parse_date(inputs.get("generated_at"))
    if expected is None:
        return []
    stale = []
    default_fetched = (inputs.get("current") or {}).get("fetched_date")
    for row in _current_rows(inputs):
        if row.get("source_kind") != "current_season":
            continue
        fetched = _parse_date(row.get("sample_fetched_date") or default_fetched)
        if fetched is None or fetched < expected:
            stale.append(
                {
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "role": row.get("role"),
                    "level": row.get("level"),
                    "source_kind": row.get("source_kind"),
                    "sample_season": row.get("sample_season"),
                    "sample_fetched_date": row.get("sample_fetched_date")
                    or default_fetched,
                }
            )
    return stale


def _targeted_refresh_rows(inputs: dict) -> list[dict]:
    expected = _parse_date(inputs.get("generated_at"))
    if expected is None:
        return []
    targeted = []
    default_fetched = (inputs.get("current") or {}).get("fetched_date")
    for row in _current_rows(inputs):
        fetched = _parse_date(row.get("sample_fetched_date") or default_fetched)
        if fetched is None or fetched <= expected:
            continue
        targeted.append(
            {
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "level": row.get("level"),
                "sample_fetched_date": row.get("sample_fetched_date"),
                "source_kind": row.get("source_kind"),
            }
        )
    targeted.sort(key=lambda row: (row.get("sample_fetched_date") or "", row.get("name") or ""))
    return targeted


def _stat_context_mismatches(public_snapshot: dict | None, limit: int) -> list[dict]:
    mismatches = []
    for row in _public_prospects(public_snapshot, limit):
        components = row.get("components") if isinstance(row.get("components"), dict) else {}
        factual = components.get("factual_current_context")
        if not isinstance(factual, dict) or factual.get("source_kind") != "current_season":
            continue
        context = row.get("context") if isinstance(row.get("context"), dict) else {}
        factual_sample = _clean_float(factual.get("sample"))
        context_sample = _clean_float(context.get("stat_line_sample"))
        factual_season = _clean_int(factual.get("sample_season"))
        context_season = _clean_int(context.get("stat_line_sample_season"))
        sample_matches = (
            factual_sample is None
            or context_sample is None
            or round(factual_sample, 1) == round(context_sample, 1)
        )
        season_matches = (
            factual_season is None
            or context_season is None
            or factual_season == context_season
        )
        if (
            context.get("stat_line_source") == "valucast_input_contract"
            and context.get("stat_line_source_kind") == "current_season"
            and sample_matches
            and season_matches
        ):
            continue
        mismatches.append(
            {
                "rank": row.get("prospect_rank") or row.get("rank"),
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "factual_sample": factual.get("sample"),
                "stat_line_sample": context.get("stat_line_sample"),
                "stat_line_source_kind": context.get("stat_line_source_kind"),
            }
        )
    return mismatches


def build_milb_stat_freshness_audit(
    inputs: dict,
    rank_payload: dict,
    public_snapshot: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    generated = generated_at or inputs.get("generated_at") or datetime.now(
        timezone.utc
    ).isoformat()
    current_rows = _current_rows(inputs)
    current_season_rows = [
        row for row in current_rows if row.get("source_kind") == "current_season"
    ]
    history_rows = [
        row for row in current_rows if row.get("source_kind") == "latest_milb_history"
    ]
    stale_current_rows = _stale_current_rows(inputs)
    targeted_refresh_rows = _targeted_refresh_rows(inputs)
    top50_history = _history_fallbacks(rank_payload, TOP50_N)
    top200_history = _history_fallbacks(rank_payload, TOP200_N)
    top50_mismatches = _stat_context_mismatches(public_snapshot, TOP50_N)

    blockers = []
    if len(stale_current_rows) > MAX_CURRENT_ROW_STALE_FETCH_COUNT:
        blockers.append("current-season MiLB rows have stale sample_fetched_date values")
    if len(top50_history) > MAX_TOP50_HISTORY_FALLBACK_COUNT:
        blockers.append("top-50 prospect card context uses latest_milb_history fallback")
    if len(top50_mismatches) > MAX_TOP50_STAT_CONTEXT_MISMATCH_COUNT:
        blockers.append("top-50 prospect stat_line context is stale or mismatched")
    if len(top200_history) > MAX_TOP200_HISTORY_FALLBACK_COUNT:
        blockers.append("top-200 prospect board has too many MiLB history fallbacks")

    return {
        "artifact": "valucast_milb_stat_freshness_audit",
        "audit_version": AUDIT_VERSION,
        "generated_at": generated,
        "status": "candidate_ready" if not blockers else "blocked",
        "source_policy": {
            "kind": "display_stat_freshness_audit",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "criteria": {
            "top50_n": TOP50_N,
            "top200_n": TOP200_N,
            "max_current_row_stale_fetch_count": MAX_CURRENT_ROW_STALE_FETCH_COUNT,
            "max_top50_history_fallback_count": MAX_TOP50_HISTORY_FALLBACK_COUNT,
            "max_top50_stat_context_mismatch_count": MAX_TOP50_STAT_CONTEXT_MISMATCH_COUNT,
            "max_top200_history_fallback_count": MAX_TOP200_HISTORY_FALLBACK_COUNT,
        },
        "metrics": {
            "current_row_count": len(current_rows),
            "current_season_row_count": len(current_season_rows),
            "latest_milb_history_row_count": len(history_rows),
            "targeted_row_refresh_count": len(targeted_refresh_rows),
            "current_row_stale_fetch_count": len(stale_current_rows),
            "top50_history_fallback_count": len(top50_history),
            "top50_stat_context_mismatch_count": len(top50_mismatches),
            "top200_history_fallback_count": len(top200_history),
            "expected_input_date": _date_part(inputs.get("generated_at")),
            "current_default_fetched_date": (inputs.get("current") or {}).get(
                "fetched_date"
            ),
        },
        "blockers": blockers,
        "samples": {
            "targeted_row_refreshes": targeted_refresh_rows[:20],
            "stale_current_rows": stale_current_rows[:20],
            "top50_history_fallbacks": top50_history[:20],
            "top50_stat_context_mismatches": top50_mismatches[:20],
            "top200_history_fallbacks": top200_history[:20],
        },
        "interpretation": (
            "This artifact audits visible MiLB stat freshness only; it does not feed "
            "ValuCast ranks, values, or buy scores."
        ),
    }


def write_milb_stat_freshness_audit(
    payload: dict,
    path: Path = ARTIFACT_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_milb_stat_freshness_audit(
    inputs_path: Path = INPUTS_PATH,
    rank_path: Path = RANK_PATH,
    public_snapshot_path: Path = PUBLIC_SNAPSHOT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    public_snapshot = _load(public_snapshot_path) if public_snapshot_path.exists() else None
    payload = build_milb_stat_freshness_audit(
        _load(inputs_path),
        _load(rank_path),
        public_snapshot=public_snapshot,
    )
    path = write_milb_stat_freshness_audit(payload, artifact_path)
    metrics = payload["metrics"]
    return {
        "artifact_path": str(path),
        "status": payload["status"],
        "blocker_count": len(payload["blockers"]),
        "current_row_count": metrics["current_row_count"],
        "top50_history_fallback_count": metrics["top50_history_fallback_count"],
        "top200_history_fallback_count": metrics["top200_history_fallback_count"],
        "targeted_row_refresh_count": metrics["targeted_row_refresh_count"],
    }
