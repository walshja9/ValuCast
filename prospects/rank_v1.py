"""Candidate ValuCast prospect ranking built from ValuCast-owned signals.

This artifact is a bridge, not a production switch. It ranks the current public
prospect universe for review while keeping DD ranks, DD values, and public
source ranks out of the score.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospects.dynasty import ARTIFACT_PATH as DYNASTY_LAYER_PATH
from prospects.model import ARTIFACT_PATH as PROSPECT_MODEL_PATH

ROOT = Path(__file__).resolve().parents[1]
DD_FEED_PATH = ROOT / "data" / "dd" / "dd_dynasty_feed.json"
INPUT_CONTRACT_PATH = ROOT / "data" / "dd" / "prospect_model_inputs.json"
DD_ADAPTER_PATH = ROOT / "data" / "models" / "valucast_dd_7x7_prospect_adapter.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"

RANK_NAME = "ValuCast Prospect Rank v1 Candidate"
RANK_VERSION = "0.1.0"

PITCHER_POSITIONS = {"P", "SP", "RP"}
MODEL_COMPONENT_WEIGHTS = {
    "expected_outcome_score": 0.58,
    "expected_category_impact_score": 0.42,
}
SCORE_WEIGHTS = {
    "prospect_model_v0_6": {
        "model_score": 0.76,
        "universal_outcome_index": 0.15,
        "factual_investment_context": 0.06,
        "sample_reliability": 0.03,
    },
    "universal_fallback": {
        "universal_outcome_index": 0.76,
        "factual_investment_context": 0.14,
        "sample_reliability": 0.10,
    },
    "identity_only_fallback": {
        "base_score": 1.0,
        "factual_investment_context": 0.08,
        "sample_reliability": 0.06,
    },
}
FALLBACK_SCORE_CAP = 62.0
IDENTITY_ONLY_BASE_SCORE = 18.0
IDENTITY_ONLY_SCORE_CAP = 32.0
IDENTITY_ONLY_NEUTRAL_RELIABILITY = 10.0
NEUTRAL_CONTEXT_SCORE = 50.0
MIN_PUBLIC_COVERAGE_RATE = 0.98
MIN_TOP_200_UNIQUE_SCORE_COUNT = 120

PROHIBITED_SCORE_INPUTS = [
    "DD dynasty_rank",
    "DD dynasty_value",
    "DD prospect_rank",
    "DD value_history",
    "public or external prospect source_ranks",
    "DD trade-market behavior",
    "DD 7x7 adapter rank or score",
]


def _clean_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def infer_role(positions: list[str] | tuple[str, ...] | None) -> str:
    normalized = [str(position).upper() for position in positions or [] if position]
    if normalized and all(position in PITCHER_POSITIONS for position in normalized):
        return "pitcher"
    return "hitter"


def identity_key(mlbam_id: Any, role: str | None) -> tuple[str, str] | None:
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return str(mlbam_id), role


def _sample_size(row: dict, role: str) -> float:
    if role == "pitcher":
        return (
            _clean_float(row.get("innings_pitched"))
            or _clean_float(row.get("sample"))
            or _clean_float(row.get("ip"))
            or 0.0
        )
    return (
        _clean_float(row.get("plate_appearances"))
        or _clean_float(row.get("sample"))
        or _clean_float(row.get("pa"))
        or 0.0
    )


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _generated_date(payload: dict) -> str | None:
    return _date_part(payload.get("generated_at"))


def _model_lookup(prospect_model: dict) -> dict[tuple[str, str], dict]:
    lookup = {}
    for row in prospect_model.get("ranked") or []:
        key = identity_key(row.get("mlbam_id"), row.get("role"))
        if key:
            lookup[key] = row
    return lookup


def _layer_lookup(dynasty_layer: dict) -> dict[tuple[str, str], dict]:
    lookup = {}
    for row in dynasty_layer.get("profiles") or []:
        key = identity_key(row.get("mlbam_id"), row.get("role"))
        if key:
            lookup[key] = row
    return lookup


def _input_lookup(input_contract: dict) -> dict[tuple[str, str], dict]:
    lookup: dict[tuple[str, str], dict] = {}
    for role, bucket in (("hitter", "hitters"), ("pitcher", "pitchers")):
        for row in (input_contract.get("current") or {}).get(bucket) or []:
            key = identity_key(row.get("mlbam_id"), role)
            if not key:
                continue
            existing = lookup.get(key)
            if existing is None or _sample_size(row, role) > _sample_size(existing, role):
                merged = dict(row)
                if existing:
                    _fill_factual_context(merged, existing)
                lookup[key] = merged
            elif existing:
                _fill_factual_context(existing, row)
    return lookup


def _fill_factual_context(target: dict, source: dict) -> None:
    for key in (
        "draft_pick_number",
        "draft_record_known",
        "draft_round",
        "draft_year",
        "pick_value",
        "rule4_drafted",
        "school_type",
        "signing_bonus",
    ):
        if target.get(key) in (None, "") and source.get(key) not in (None, ""):
            target[key] = source[key]


def _adapter_lookup(adapter: dict | None) -> dict[tuple[str, str], dict]:
    if not adapter:
        return {}
    lookup = {}
    for role, result in (adapter.get("roles") or {}).items():
        for row in result.get("players") or []:
            key = identity_key(row.get("mlbam_id"), role)
            if key:
                lookup[key] = row
    return lookup


def _prospect_rows(dd_feed: dict) -> list[dict]:
    return [
        row
        for row in dd_feed.get("players") or []
        if row.get("player_type") == "prospect"
    ]


def _model_score(model_profile: dict | None) -> float | None:
    if not model_profile:
        return None
    outcome = _clean_float(model_profile.get("expected_outcome_score"))
    impact = _clean_float(model_profile.get("expected_category_impact_score"))
    if outcome is None and impact is None:
        return None
    if outcome is None:
        outcome = impact
    if impact is None:
        impact = outcome
    assert outcome is not None
    assert impact is not None
    return round(
        100.0
        * (
            MODEL_COMPONENT_WEIGHTS["expected_outcome_score"] * outcome
            + MODEL_COMPONENT_WEIGHTS["expected_category_impact_score"] * impact
        ),
        2,
    )


def _universal_outcome_index(layer_profile: dict | None) -> float:
    signal = (layer_profile or {}).get("dynasty_signal") or {}
    tier = _clean_float(signal.get("expected_factual_outcome_tier"))
    if tier is not None:
        return round(max(0.0, min(100.0, tier * 50.0)), 2)
    distribution = (layer_profile or {}).get("outcome_distribution") or {}
    role = _clean_float(distribution.get("role_probability")) or 0.0
    star = _clean_float(distribution.get("star_probability")) or 0.0
    return round(max(0.0, min(100.0, role * 50.0 + star * 100.0)), 2)


def _sample_reliability_score(
    layer_profile: dict | None,
    model_profile: dict | None,
) -> float:
    reliability = _clean_float((layer_profile or {}).get("sample_reliability"))
    if reliability is None:
        reliability = _clean_float((model_profile or {}).get("sample_reliability"))
    if reliability is None:
        return 45.0
    if reliability <= 1.0:
        return round(max(0.0, min(100.0, reliability * 100.0)), 2)
    return round(max(0.0, min(100.0, reliability)), 2)


def _input_sample_reliability_score(input_row: dict | None, role: str) -> float:
    if not input_row:
        return IDENTITY_ONLY_NEUTRAL_RELIABILITY
    sample = _sample_size(input_row, role)
    regression = 200.0 if role == "hitter" else 50.0
    if sample <= 0:
        return IDENTITY_ONLY_NEUTRAL_RELIABILITY
    return round(max(0.0, min(100.0, 100.0 * sample / (sample + regression))), 2)


def _factual_investment_score(input_row: dict | None) -> float | None:
    if not input_row:
        return None
    pieces = []
    draft_pick = _clean_float(input_row.get("draft_pick_number"))
    if draft_pick and draft_pick > 0:
        pieces.append(
            max(0.0, min(100.0, 100.0 - 100.0 * math.log(draft_pick) / math.log(615)))
        )
    bonus = _clean_float(input_row.get("signing_bonus"))
    if bonus and bonus > 0:
        pieces.append(
            max(
                0.0,
                min(
                    100.0,
                    100.0
                    * (math.log10(bonus) - 4.0)
                    / (math.log10(8_000_000) - 4.0),
                ),
            )
        )
    if not pieces:
        return None
    return round(max(pieces), 2)


def _identity_only_score_components(
    input_row: dict | None,
    role: str,
) -> tuple[float, str, dict]:
    investment_score = _factual_investment_score(input_row)
    reliability_score = _input_sample_reliability_score(input_row, role)
    weights = SCORE_WEIGHTS["identity_only_fallback"]
    score = (
        weights["base_score"] * IDENTITY_ONLY_BASE_SCORE
        + weights["factual_investment_context"]
        * (investment_score if investment_score is not None else NEUTRAL_CONTEXT_SCORE)
        + weights["sample_reliability"] * reliability_score
    )
    return (
        round(min(score, IDENTITY_ONLY_SCORE_CAP), 2),
        "identity_only_fallback",
        {
            "model_score": None,
            "universal_outcome_index": None,
            "factual_investment_context": _round(investment_score),
            "factual_investment_missing_uses_neutral": investment_score is None,
            "sample_reliability": _round(reliability_score),
            "identity_only_base_score": IDENTITY_ONLY_BASE_SCORE,
            "identity_only_score_cap": IDENTITY_ONLY_SCORE_CAP,
        },
    )


def _score_components(
    model_profile: dict | None,
    layer_profile: dict,
    input_row: dict | None,
) -> tuple[float, str, dict]:
    model_score = _model_score(model_profile)
    universal_score = _universal_outcome_index(layer_profile)
    investment_score = _factual_investment_score(input_row)
    reliability_score = _sample_reliability_score(layer_profile, model_profile)

    if model_score is not None:
        source = "prospect_model_v0_6"
        weights = SCORE_WEIGHTS[source]
        score = (
            weights["model_score"] * model_score
            + weights["universal_outcome_index"] * universal_score
            + weights["factual_investment_context"]
            * (investment_score if investment_score is not None else NEUTRAL_CONTEXT_SCORE)
            + weights["sample_reliability"] * reliability_score
        )
    else:
        source = "universal_fallback"
        weights = SCORE_WEIGHTS[source]
        uncapped = (
            weights["universal_outcome_index"] * universal_score
            + weights["factual_investment_context"]
            * (investment_score if investment_score is not None else NEUTRAL_CONTEXT_SCORE)
            + weights["sample_reliability"] * reliability_score
        )
        score = min(uncapped, FALLBACK_SCORE_CAP)

    components = {
        "model_score": _round(model_score),
        "universal_outcome_index": _round(universal_score),
        "factual_investment_context": _round(investment_score),
        "factual_investment_missing_uses_neutral": investment_score is None,
        "sample_reliability": _round(reliability_score),
    }
    if source == "universal_fallback":
        components["fallback_score_cap"] = FALLBACK_SCORE_CAP
    return round(score, 2), source, components


def _confidence(source: str, model_profile: dict | None, reliability: float | None) -> str:
    if source in {"universal_fallback", "identity_only_fallback"}:
        return "low"
    role_gate = (model_profile or {}).get("role_gate")
    impact_gate = (model_profile or {}).get("impact_gate")
    if role_gate == "active" and impact_gate == "active" and (reliability or 0.0) >= 45:
        return "high"
    return "medium"


def _drivers(model_profile: dict | None, layer_profile: dict) -> list[str]:
    values: list[str] = []
    for key in ("drivers", "impact_drivers"):
        current = (model_profile or {}).get(key)
        if isinstance(current, list):
            values.extend(str(item) for item in current[:4])
        elif isinstance(current, str):
            values.append(current)
    if values:
        return values[:6]
    signal = layer_profile.get("dynasty_signal") or {}
    return [
        f"role+ probability {signal.get('role_or_better_probability')}",
        f"star probability {signal.get('star_ceiling_probability')}",
    ]


def _context(dd_row: dict, adapter_row: dict | None) -> dict:
    context = {
        "dd_dynasty_rank": dd_row.get("dynasty_rank"),
        "dd_dynasty_value": dd_row.get("dynasty_value"),
        "dd_prospect_rank": dd_row.get("prospect_rank"),
        "source_ranks": dd_row.get("source_ranks"),
        "breakout_label": dd_row.get("breakout_label"),
        "breakout_rank_change": dd_row.get("breakout_rank_change"),
        "value_history_points": len(dd_row.get("value_history") or []),
    }
    if adapter_row:
        context["dd_adapter_context"] = {
            "adapter_score": adapter_row.get("adapter_score"),
            "adapter_rank": adapter_row.get("adapter_rank"),
            "role": adapter_row.get("role"),
        }
    return context


def _missing_sample(rows: list[dict], missing_keys: set[tuple[str, str]], limit: int = 15) -> list[dict]:
    missing = []
    for row in sorted(rows, key=lambda item: item.get("prospect_rank") or 9999):
        role = infer_role(row.get("positions"))
        key = identity_key(row.get("mlbam_id"), role)
        if key in missing_keys:
            missing.append(
                {
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "role": role,
                    "dd_prospect_rank": row.get("prospect_rank"),
                    "dd_dynasty_rank": row.get("dynasty_rank"),
                }
            )
        if len(missing) >= limit:
            break
    return missing


def _validation(
    dd_feed: dict,
    dynasty_layer: dict,
    input_contract: dict,
    prospect_rows: list[dict],
    board: list[dict],
    duplicate_keys: list[tuple[str, str]],
    missing_mlbam_count: int,
    unmatched_layer_keys: set[tuple[str, str]],
    identity_only_fallback_count: int,
) -> dict:
    feed_date = _generated_date(dd_feed)
    layer_date = _generated_date(dynasty_layer)
    input_date = _generated_date(input_contract)
    same_day = bool(feed_date and layer_date and input_date) and len(
        {feed_date, layer_date, input_date}
    ) == 1
    coverage_rate = round(len(board) / len(prospect_rows), 4) if prospect_rows else 0.0
    top_200_scores = {row["score"] for row in board[:200]}
    blockers = [
        "Prospect Rank v1 is a candidate shadow artifact; no public consumer is allowed yet.",
        "ValuCast still does not publish a complete canonical Dynasty/Prospects/Buys snapshot.",
    ]
    if coverage_rate < MIN_PUBLIC_COVERAGE_RATE:
        blockers.append(
            "Current ValuCast prospect-model coverage is below the public migration threshold."
        )
    if missing_mlbam_count:
        blockers.append("Some public prospect rows still lack MLBAM identity.")
    if duplicate_keys:
        blockers.append("Duplicate MLBAM+role identities exist in the prospect universe.")
    if len(top_200_scores) < MIN_TOP_200_UNIQUE_SCORE_COUNT:
        blockers.append("Top-200 score separation is not strong enough for publication.")
    if not same_day:
        blockers.append("Input artifacts were not generated on the same date.")

    return {
        "public_migration_ready": False,
        "ready_to_replace_dd_feed": False,
        "same_day_freshness": same_day,
        "generated_dates": {
            "dd_feed": feed_date,
            "dynasty_layer": layer_date,
            "prospect_input_contract": input_date,
        },
        "prospect_universe_count": len(prospect_rows),
        "ranked_count": len(board),
        "missing_mlbam_count": missing_mlbam_count,
        "unmatched_dynasty_layer_count": len(unmatched_layer_keys),
        "identity_only_fallback_count": identity_only_fallback_count,
        "coverage_rate": coverage_rate,
        "duplicate_identity_count": len(duplicate_keys),
        "duplicate_identities": [
            {"mlbam_id": mlbam_id, "role": role}
            for mlbam_id, role in duplicate_keys[:20]
        ],
        "top_200_unique_score_count": len(top_200_scores),
        "ranks_contiguous": [row["rank"] for row in board] == list(range(1, len(board) + 1)),
        "unmatched_sample": _missing_sample(prospect_rows, unmatched_layer_keys),
        "blockers": blockers,
    }


def build_prospect_rank_v1(
    dd_feed: dict,
    dynasty_layer: dict,
    prospect_model: dict,
    input_contract: dict,
    dd_adapter: dict | None = None,
) -> dict:
    model_by_key = _model_lookup(prospect_model)
    layer_by_key = _layer_lookup(dynasty_layer)
    input_by_key = _input_lookup(input_contract)
    adapter_by_key = _adapter_lookup(dd_adapter)

    rows = _prospect_rows(dd_feed)
    seen: set[tuple[str, str]] = set()
    duplicate_keys: list[tuple[str, str]] = []
    missing_mlbam_count = 0
    unmatched_layer_keys: set[tuple[str, str]] = set()
    identity_only_fallback_count = 0
    board = []

    for dd_row in rows:
        role = infer_role(dd_row.get("positions"))
        key = identity_key(dd_row.get("mlbam_id"), role)
        if key is None:
            missing_mlbam_count += 1
            continue
        if key in seen:
            duplicate_keys.append(key)
            continue
        seen.add(key)
        layer_profile = layer_by_key.get(key)
        model_profile = model_by_key.get(key)
        input_row = input_by_key.get(key)
        if layer_profile:
            score, source, components = _score_components(
                model_profile,
                layer_profile,
                input_row,
            )
        else:
            unmatched_layer_keys.add(key)
            identity_only_fallback_count += 1
            score, source, components = _identity_only_score_components(input_row, role)
        confidence = _confidence(
            source,
            model_profile,
            components.get("sample_reliability"),
        )
        board.append(
            {
                "mlbam_id": dd_row.get("mlbam_id"),
                "name": dd_row.get("name") or (layer_profile or {}).get("name"),
                "normalized_name": (layer_profile or {}).get("normalized_name"),
                "role": role,
                "positions": dd_row.get("positions"),
                "mlb_team": dd_row.get("mlb_team"),
                "age": dd_row.get("age")
                if dd_row.get("age") is not None
                else (layer_profile or {}).get("age"),
                "level": dd_row.get("level") or (layer_profile or {}).get("level"),
                "eta": dd_row.get("eta"),
                "score": score,
                "score_source": source,
                "confidence": confidence,
                "components": components,
                "dynasty_signal": (layer_profile or {}).get("dynasty_signal"),
                "drivers": _drivers(model_profile, layer_profile or {}),
                "context_only": _context(dd_row, adapter_by_key.get(key)),
            }
        )

    board.sort(
        key=lambda row: (
            -row["score"],
            row["score_source"] == "universal_fallback",
            str(row.get("role") or ""),
            str(row.get("name") or ""),
            int(row.get("mlbam_id") or 0),
        )
    )
    for rank, row in enumerate(board, 1):
        row["rank"] = rank

    validation = _validation(
        dd_feed,
        dynasty_layer,
        input_contract,
        rows,
        board,
        duplicate_keys,
        missing_mlbam_count,
        unmatched_layer_keys,
        identity_only_fallback_count,
    )
    coverage_repair_needed = (
        validation["coverage_rate"] < MIN_PUBLIC_COVERAGE_RATE
        or validation["missing_mlbam_count"] > 0
        or validation["duplicate_identity_count"] > 0
    )
    generated_at = (
        dynasty_layer.get("generated_at")
        or input_contract.get("generated_at")
        or dd_feed.get("generated_at")
    )
    return {
        "status": "candidate_shadow",
        "rank_name": RANK_NAME,
        "rank_version": RANK_VERSION,
        "generated_at": generated_at,
        "candidate_count": len(rows),
        "ranked_count": len(board),
        "rank_contract": {
            "purpose": (
                "Review a ValuCast-owned prospect ordering before it is allowed "
                "to influence any public ValuCast or DD surface."
            ),
            "score_range": [0.0, 100.0],
            "score_weights": SCORE_WEIGHTS,
            "model_component_weights": MODEL_COMPONENT_WEIGHTS,
            "fallback_score_cap": FALLBACK_SCORE_CAP,
            "identity_only_score_cap": IDENTITY_ONLY_SCORE_CAP,
            "dd_feed_usage": "Universe, identity, and display context only.",
            "context_only_fields": [
                "DD dynasty_rank",
                "DD dynasty_value",
                "DD prospect_rank",
                "source_ranks",
                "value_history",
                "DD adapter score/rank",
            ],
            "prohibited_score_inputs": PROHIBITED_SCORE_INPUTS,
            "external_rankings_used_for_score": False,
            "dd_values_used_for_score": False,
            "market_independent": True,
            "live_surface": False,
            "tie_policy": "Ranks are contiguous after deterministic non-score tiebreakers.",
        },
        "input_artifacts": {
            "dd_feed_generated_by": dd_feed.get("generated_by"),
            "dd_feed_source": dd_feed.get("source"),
            "dd_feed_schema_version": dd_feed.get("schema_version"),
            "prospect_model_version": prospect_model.get("model_version"),
            "dynasty_layer_version": dynasty_layer.get("layer_version"),
            "prospect_input_schema_version": input_contract.get("schema_version"),
            "dd_adapter_version": (dd_adapter or {}).get("adapter_version"),
        },
        "promotion": {
            "live_consumer": "blocked",
            "feeds_live_valucast_rank": False,
            "feeds_live_dd_value": False,
            "next_allowed_step": (
                "human_review_and_coverage_repair"
                if coverage_repair_needed
                else "human_review_and_canonical_snapshot_build"
            ),
            "reason": validation["blockers"][0],
        },
        "validation": validation,
        "limitations": [
            "Candidate only; the live ValuCast Prospects board is not switched by this artifact.",
            "DD feed rows provide the current review universe and card context, not score inputs.",
            "Identity-only fallback rows remain for prospects absent from the current ValuCast layer.",
            "Identity-only fallback rows have verified MLBAM identity but no eligible ValuCast model sample yet.",
            "Fallback-only lower-minors profiles are capped until the expanded model earns publication-grade evidence.",
        ],
        "board": board,
    }


def archive_rank(
    payload: dict,
    date_str: str,
    archive_dir: Path = ARCHIVE_DIR,
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "rank_version": payload["rank_version"],
        "generated_at": payload["generated_at"],
        "candidate_count": payload["candidate_count"],
        "ranked_count": payload["ranked_count"],
        "validation": payload["validation"],
        "board": payload["board"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run_prospect_rank_v1(
    dd_feed_path: Path = DD_FEED_PATH,
    dynasty_layer_path: Path = DYNASTY_LAYER_PATH,
    prospect_model_path: Path = PROSPECT_MODEL_PATH,
    input_contract_path: Path = INPUT_CONTRACT_PATH,
    dd_adapter_path: Path = DD_ADAPTER_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict:
    dd_feed = json.loads(dd_feed_path.read_text(encoding="utf-8"))
    dynasty_layer = json.loads(dynasty_layer_path.read_text(encoding="utf-8"))
    prospect_model = json.loads(prospect_model_path.read_text(encoding="utf-8"))
    input_contract = json.loads(input_contract_path.read_text(encoding="utf-8"))
    dd_adapter = (
        json.loads(dd_adapter_path.read_text(encoding="utf-8"))
        if dd_adapter_path.exists()
        else None
    )
    payload = build_prospect_rank_v1(
        dd_feed,
        dynasty_layer,
        prospect_model,
        input_contract,
        dd_adapter,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)

    generated_at = payload.get("generated_at")
    parsed_now = (
        datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if generated_at
        else datetime.now(timezone.utc)
    )
    if parsed_now.tzinfo is None:
        parsed_now = parsed_now.replace(tzinfo=timezone.utc)
    archive_path, archive_changed = archive_rank(
        payload,
        date_str=parsed_now.date().isoformat(),
        archive_dir=archive_dir,
    )
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "ranked_count": payload["ranked_count"],
        "candidate_count": payload["candidate_count"],
        "coverage_rate": payload["validation"]["coverage_rate"],
        "live_consumer": payload["promotion"]["live_consumer"],
    }
