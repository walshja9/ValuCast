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
from scouting.mlb_read import build_mlb_scouting_read, stat_line_stats
from scouting.voice import handedness_problems, sample_context_stale, validate_report_text
from web.statcast_store import StatcastStore
from web.public_snapshot_store import PublicSnapshotStore
from web import prospect_percentiles

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_scouting_reports.json"
RECENT_SIGNAL_PATH = ROOT / "data" / "models" / "valucast_recent_signal_report.json"
CARD_DATA_AUDIT_PATH = ROOT / "data" / "models" / "valucast_prospect_card_data_audit.json"
LLM_CACHE_PATH = ROOT / "data" / "models" / "valucast_scouting_llm_cache.json"
DEFAULT_LLM_MAX_GENERATE = 25

ARTIFACT_NAME = "valucast_scouting_report_repository"
REPOSITORY_VERSION = "0.1.0"
DEFAULT_MAX_PROSPECT_RANK = 500
DEFAULT_MAX_DYNASTY_RANK = 500


class ScoutingRepositorySentinelError(RuntimeError):
    """Raised when a generated repository fails a semantic sentinel and must not
    publish (e.g. the no-sample read contradicts a real current stat line)."""


def _report_status(text: str | None) -> str:
    if not text:
        return "missing"
    lowered = text.lower()
    if "no current performance sample" in lowered:
        return "thin_sample"
    if "injured" in lowered or "availability risk" in lowered:
        return "availability_context"
    return "stat_grounded"


# Lead sentence emitted by web.prospect_percentiles._no_sample_report for a
# genuinely sample-less prospect (see the f"No current performance sample is
# available for this {descriptor}." templates there). This exact prefix is the
# unambiguous marker of the no-evidence read; it is never produced for a player
# whose current line has real rate values. Keep this string in sync with the
# generator template if it ever changes.
_NO_SAMPLE_MARKER = "No current performance sample is available"


def _no_sample_template_in(text: str | None) -> bool:
    return bool(text) and _NO_SAMPLE_MARKER in text


def _stat_line_has_values(row) -> bool:
    """True when the prospect's current stat_line carries at least one readable
    hitter/pitcher rate metric (real performance sample), using the SAME rule the
    read logic uses (prospect_percentiles._has_stat_values). A sample-only dict
    ({"pa": 40}) or empty/None line is NOT a performance sample."""
    return prospect_percentiles._has_stat_values(getattr(row, "stat_line", None))


def _no_sample_contradiction(row, report: dict) -> bool:
    """A prospect report uses the no-sample template while the player HAS a real
    current stat line. This is always a bug: the read claims no evidence exists
    for a player who has non-empty PA/IP + rate values (e.g. Ronny Hernandez 90
    PA .329/.456/.671). Gates the build so the bad artifact cannot publish."""
    if getattr(row, "is_prospect", True) is False:
        return False
    return _no_sample_template_in(report.get("report")) and _stat_line_has_values(row)


def _no_sample_contradictions(rows, reports) -> list[str]:
    """Names of prospects whose no-sample read contradicts a real stat line."""
    offenders: list[str] = []
    for row, report in zip(rows, reports):
        if _no_sample_contradiction(row, report):
            offenders.append(str(report.get("name") or getattr(row, "name", "") or "unknown"))
    return offenders


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


def _statcast_grounding_groups(display_groups) -> list[dict]:
    groups = []
    for group in display_groups or ():
        if not isinstance(group, dict):
            continue
        metrics = []
        for metric in group.get("metrics") or ():
            if not isinstance(metric, dict):
                continue
            pct = metric.get("pct")
            if not isinstance(pct, (int, float)):
                continue
            item = {
                "label": str(metric.get("label") or "").strip(),
                "pct": int(max(0, min(100, pct))),
                "raw": metric.get("raw") if isinstance(metric.get("raw"), (int, float)) else None,
                "display": metric.get("display"),
            }
            if item["label"]:
                metrics.append(item)
        if metrics:
            groups.append({
                "label": str(group.get("label") or "").strip(),
                "metrics": metrics,
            })
    return groups


def _mlb_row_report(row, statcast_groups: list[dict] | None = None) -> dict:
    stats = stat_line_stats(row.stat_line)
    groups = _statcast_grounding_groups(statcast_groups)
    text = build_mlb_scouting_read(row, groups, stats)
    source = row.stat_line.get("source") if isinstance(row.stat_line, dict) else None
    return {
        "id": row.id,
        "identity_key": _identity_key(row),
        "mlbam_id": str(row.mlbam_id),
        "name": row.name,
        "role": row.role,
        "team": row.team,
        "positions": list(row.positions or []),
        "player_type": row.player_type,
        "prospect_rank": None,
        "confidence": row.confidence,
        "level": row.level,
        "age": row.age,
        "report": text,
        "report_status": _report_status(text),
        "peak_summary": None,
        "recent_signal": None,
        "card_data_status": None,
        "statcast_groups": groups,
        "stat_line_stats": stats,
        "source_fields": {
            "stat_line_source": source or "valucast_current_projection",
            "stat_line_label": "projection",
            "statcast_percentiles": bool(groups),
        },
        "usage": "scouting_repository_context_not_live_rank_or_value",
    }


# Rate stats carry false precision off the raw runtime line (e.g. 14.597 K/9). Round
# them in the grounding before the LLM sees them so a model read cannot echo the
# spurious decimals: 1 decimal for per-9 / ERA / WHIP, whole number for percentages.
_RATE_ROUND_1DP = ("k_per_9", "bb_per_9", "era", "whip")
_RATE_ROUND_WHOLE = ("k_pct", "bb_pct", "k_bb_pct")


def _round_grounding_rates(line: dict) -> dict:
    rounded = dict(line)
    for key in _RATE_ROUND_1DP:
        value = rounded.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            rounded[key] = round(float(value), 1)
    for key in _RATE_ROUND_WHOLE:
        value = rounded.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            rounded[key] = round(float(value))
    return rounded


def _card_display_line_grounding(
    line: dict | None,
    is_best: bool,
    source_kind: str | None = None,
) -> dict | None:
    if not isinstance(line, dict) or not line:
        return None
    return {
        **_round_grounding_rates(line),
        "usage": "the line shown on the card skill bars",
        "source_kind": source_kind
        or ("best_single_level_stat_line" if is_best else "current_minor_league_line"),
    }


def _line_sample_context(
    row,
    line: dict | None,
    level: str | None,
    is_best: bool,
    source_kind: str | None = None,
) -> dict | None:
    if not isinstance(line, dict) or not line:
        return None
    is_pitcher = any(key in line for key in ("era", "whip", "k_per_9", "bb_per_9", "k_bb_pct"))
    sample = line.get("ip" if is_pitcher else "pa")
    if sample is None:
        sample = line.get("sample")
    sample_unit = line.get("sample_unit") or ("IP" if is_pitcher else "PA")
    context = row.context if isinstance(getattr(row, "context", None), dict) else {}
    # A combined multi-level line's sample spans every level it pooled. Ground the level
    # as the combined label (and expose the levels) so a generated report never claims
    # "235 PA in Triple-A" when only part of that sample was at Triple-A.
    sample_levels = [lv for lv in (line.get("levels") or []) if lv]
    if len(sample_levels) > 1:
        level_value = line.get("level_label") or "+".join(str(lv) for lv in sample_levels)
    else:
        level_value = level or line.get("level") or row.level
    return {
        "sample": sample,
        "sample_unit": sample_unit,
        "season": line.get("season") or context.get("stat_line_sample_season"),
        "level": level_value,
        "levels": sample_levels or None,
        "source_kind": source_kind
        or ("best_single_level_stat_line" if is_best else context.get("stat_line_source_kind")),
    }


def _mlb_equivalent_translation_grounding(translated: dict | None) -> dict | None:
    if not isinstance(translated, dict) or not translated:
        return None
    grounding = {
        key: value
        for key, value in translated.items()
        if key != "stats" and value not in (None, {}, [], "")
    }
    grounding["usage"] = (
        "MLB-equivalent context only; lead with card_display_line for displayed MiLB values"
    )
    stats = []
    for stat in translated.get("stats") or ():
        if not isinstance(stat, dict):
            continue
        item = {
            key: stat.get(key)
            for key in ("key", "label", "fmt", "mlb", "mlb_avg")
            if stat.get(key) not in (None, {}, [], "")
        }
        if item:
            stats.append(item)
    if stats:
        grounding["stats"] = stats
    return grounding or None


def _row_report(
    row,
    recent_signal: dict | None = None,
    card_data: dict | None = None,
    statcast_groups: list[dict] | None = None,
) -> dict:
    if getattr(row, "is_prospect", True) is False:
        return _mlb_row_report(row, statcast_groups=statcast_groups)
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


def _llm_generation_limit() -> int | None:
    raw = os.environ.get("VALUCAST_SCOUTING_LLM_MAX_GENERATE")
    if raw is None or raw.strip() == "":
        return DEFAULT_LLM_MAX_GENERATE
    value = raw.strip().lower()
    if value in {"all", "none", "unbounded", "unlimited"}:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return DEFAULT_LLM_MAX_GENERATE


def _env_optional_int(name: str, default: int) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in {"all", "none", "unbounded", "unlimited"}:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return default


def _llm_grounding(
    row,
    percentiles: dict,
    pool_label: str | None,
    recent_signal: dict | None = None,
    statcast_groups: list[dict] | None = None,
) -> dict:
    """Source-tagged, ValuCast-owned facts for the LLM read. No DD values/ranks, no
    external rankings, no market values — only what the card already owns."""
    if getattr(row, "is_prospect", True) is False:
        stat_line = row.stat_line if isinstance(row.stat_line, dict) else {}
        source = stat_line.get("source")
        grounding = {
            "name": row.name,
            "role": row.role,
            "positions": list(row.positions or []),
            "team": row.team,
            "player_type": row.player_type,
            "age": row.age,
            "confidence": row.confidence,
            "statcast_groups": statcast_groups or None,
            "stat_line_stats": {
                "label": "projection",
                "source": source or "valucast_current_projection",
                "stats": stat_line_stats(row.stat_line),
            },
        }
        return {key: value for key, value in grounding.items() if value not in (None, {}, [])}
    peak_detail = None
    if row.has_peak_projection:
        peak_detail = {key: value for key, value in {
            "role_ceiling": getattr(row, "peak_role_label", None),
            "floor": getattr(row, "peak_floor_label", None),
            "eta": getattr(row, "peak_eta_label", None),
            "trajectory_vs_current": getattr(row, "peak_trajectory_label", None),
            "skill_shape": getattr(row, "peak_shape_items", None),
            "role_probabilities": getattr(row, "peak_role_probability_items", None),
        }.items() if value not in (None, {}, [], "")} or None
    rank_movement = None
    if recent_signal and recent_signal.get("movement_label"):
        rank_movement = {key: value for key, value in {
            "direction": recent_signal.get("movement_label"),
            "score_delta_3d": recent_signal.get("score_delta_3d"),
            "rank_delta_3d": recent_signal.get("rank_delta_3d"),
        }.items() if value not in (None, "")} or None
    card_selection = prospect_percentiles.card_line(row)
    card_stat_line, card_level, card_line_is_best = card_selection
    card_source_kind = (
        card_selection.source_kind
        if card_selection.is_combined or card_selection.is_best
        else None
    )
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
        "card_display_line": _card_display_line_grounding(
            card_stat_line,
            card_line_is_best,
            card_source_kind,
        ),
        "mlb_equivalent_translation": _mlb_equivalent_translation_grounding(row.stat_line_translated),
        "current_skill_percentiles": percentiles or None,
        "percentile_pool": pool_label,
        "peak_projection": row.peak_projection_summary if row.has_peak_projection else None,
        "peak_projection_detail": peak_detail,
        "valucast_rank_movement": rank_movement,
        "availability": row.availability_context or None,
        "sample_context": _line_sample_context(
            row,
            card_stat_line,
            card_level,
            card_line_is_best,
            card_source_kind,
        ),
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
    generation_limit = _llm_generation_limit()
    client = report_generator.default_client()
    if client is None:
        return {
            "enabled": True,
            "available": False,
            "generated": 0,
            "reused": 0,
            "reused_stale": 0,
            "flagged": 0,
            "errored": 0,
            "skipped_due_to_budget": 0,
            "generation_limit": generation_limit,
        }
    pool = prospect_percentiles.build_pool(store.get_all())
    cache = _load_optional(LLM_CACHE_PATH)
    entries = cache.get("entries") if isinstance(cache.get("entries"), dict) else {}
    generated = reused = reused_stale = flagged = errored = skipped_due_to_budget = 0
    fresh: dict = dict(entries)
    for row, report in zip(rows, reports):
        key = report.get("identity_key")
        if not key:
            continue
        if row.is_prospect:
            percentiles = prospect_percentiles.card_percentiles(pool, row)
            grounding = _llm_grounding(row, percentiles, prospect_percentiles.pool_label(row),
                                       recent_signal=report.get("recent_signal"))
        else:
            grounding = _llm_grounding(
                row,
                {},
                None,
                recent_signal=report.get("recent_signal"),
                statcast_groups=report.get("statcast_groups") or [],
            )
        digest = report_generator.grounding_hash(grounding)
        cached = entries.get(key)
        result = None
        current_model = report_generator.DEFAULT_MODEL
        # Reuse only when the grounding AND the model both match the current build — so a
        # model/prompt swap forces regeneration instead of serving the old model's prose.
        if (
            isinstance(cached, dict)
            and cached.get("hash") == digest
            and cached.get("valid") is True
            and cached.get("model") == current_model
        ):
            result = cached
            reused += 1
        elif (
            isinstance(cached, dict)
            and cached.get("valid") is True
            and cached.get("text")
            and cached.get("model") == current_model
        ):
            guard = validate_report_text(cached["text"], grounding)
            # unsupported_numbers() alone lets a stale report through when the player's
            # sample grew (e.g. into a multi-level pooled line): every number the old
            # text cites still individually appears somewhere in the new grounding's
            # per-level breakdown, so nothing looks "unsupported" even though the text
            # now silently describes a narrower, outdated slice of the season as the
            # whole thing. sample_context_stale() closes that gap.
            if guard["ok"] and not sample_context_stale(cached["text"], grounding):
                result = {
                    **cached,
                    "hash": digest,
                    "valid": True,
                    "hard_ok": guard["hard_ok"],
                    "problems": guard,
                    "reused_against_updated_grounding": True,
                }
                reused_stale += 1
        if result is None:
            # Attempts (success or failure) count against the budget, not just successes —
            # otherwise a run of API errors (rate limit, outage) never trips the cutoff and
            # retries every eligible row instead of stopping at generation_limit calls.
            if generation_limit is not None and generated + errored >= generation_limit:
                skipped_due_to_budget += 1
                continue
            try:
                gen = report_generator.generate_report(grounding, client=client)
            except Exception:  # noqa: BLE001 - one bad call must not fail the daily build
                errored += 1
                continue
            if gen is None:
                errored += 1
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
        "reused": reused, "reused_stale": reused_stale, "flagged": flagged,
        "errored": errored, "skipped_due_to_budget": skipped_due_to_budget,
        "generation_limit": generation_limit, "report_count": len(fresh),
    }


def build_scouting_repository(
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    recent_signal_path: Path = RECENT_SIGNAL_PATH,
    card_data_audit_path: Path = CARD_DATA_AUDIT_PATH,
    generated_at: str | None = None,
    max_prospect_rank: int = DEFAULT_MAX_PROSPECT_RANK,
    max_dynasty_rank: int | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    if max_dynasty_rank is None:
        max_dynasty_rank = _env_optional_int(
            "VALUCAST_SCOUTING_MAX_DYNASTY_RANK",
            DEFAULT_MAX_DYNASTY_RANK,
        )
    store = PublicSnapshotStore(snapshot_path)
    if not store.is_available:
        rows = []
    else:
        rows = []
        for row in store.get_all():
            if (
                row.is_prospect
                and row.prospect_rank is not None
                and row.prospect_rank <= max_prospect_rank
            ):
                rows.append(row)
            elif (
                not row.is_prospect
                and row.mlbam_id not in (None, "")
                and row.stat_line
                and (
                    max_dynasty_rank is None
                    or row.dynasty_rank <= max_dynasty_rank
                )
            ):
                rows.append(row)
    recent_payload = _load_optional(recent_signal_path)
    card_audit_payload = _load_optional(card_data_audit_path)
    recent_index = _index_rows(recent_payload, "signals")
    card_index = _index_rows(card_audit_payload, "cards")
    statcast_store = StatcastStore()
    statcast_by_key = {
        _identity_key(row): _statcast_grounding_groups(
            statcast_store.display_groups(
                row.mlbam_id,
                prefer_pitching=str(row.role or "").lower() == "pitcher",
            )
        )
        for row in rows
        if not row.is_prospect and _identity_key(row)
    }
    reports = [
        _row_report(
            row,
            recent_signal=recent_index.get(_identity_key(row) or ""),
            card_data=card_index.get(_identity_key(row) or ""),
            statcast_groups=statcast_by_key.get(_identity_key(row) or ""),
        )
        for row in rows
    ]
    llm_shadow = {
        "enabled": False,
        "available": False,
        "generated": 0,
        "reused": 0,
        "reused_stale": 0,
        "flagged": 0,
        "errored": 0,
        "skipped_due_to_budget": 0,
        "generation_limit": None,
    }
    if _llm_enabled():
        llm_shadow = _attach_llm_reports(rows, reports, store)
    publish_summary = _publish_report_fields(reports)
    identity_keys = [(row["mlbam_id"], row["role"]) for row in reports]
    duplicate_identity_count = len(identity_keys) - len(set(identity_keys))
    missing_report_count = sum(1 for row in reports if not row.get("report"))
    prospect_report_count = sum(1 for row in reports if row.get("player_type") == "prospect")
    mlb_report_count = sum(1 for row in reports if row.get("player_type") != "prospect")
    top100_count = sum(
        1
        for row in reports
        if row.get("player_type") == "prospect"
        and row.get("prospect_rank") is not None
        and row["prospect_rank"] <= 100
    )
    no_sample_contradictions = _no_sample_contradictions(rows, reports)
    blockers = []
    if not reports:
        blockers.append("Scouting repository has no reports.")
    if duplicate_identity_count:
        blockers.append("Scouting repository has duplicate MLBAM+role reports.")
    if top100_count < min(100, prospect_report_count):
        blockers.append("Scouting repository does not cover the visible top 100 prospects.")
    if no_sample_contradictions:
        preview = ", ".join(no_sample_contradictions[:10])
        if len(no_sample_contradictions) > 10:
            preview += f", +{len(no_sample_contradictions) - 10} more"
        blockers.append(
            "Scouting repository emits the no-sample read for "
            f"{len(no_sample_contradictions)} prospect(s) with a real stat line: {preview}."
        )
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
            "max_dynasty_rank": max_dynasty_rank,
            "prospect_report_count": prospect_report_count,
            "mlb_report_count": mlb_report_count,
            "llm_shadow": llm_shadow,
            **publish_summary,
        },
        "validation": {
            "ready_for_repository": not blockers,
            "report_count": len(reports),
            "duplicate_identity_count": duplicate_identity_count,
            "missing_report_count": missing_report_count,
            "no_sample_contradiction_count": len(no_sample_contradictions),
            "no_sample_contradiction_players": no_sample_contradictions,
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
    # Fail loud BEFORE writing: a no-sample read for a player who has a real
    # current stat line is always a bug, and a stale/contradictory artifact must
    # never publish over a good one. Tolerance is zero — the gate only fires on
    # this unambiguous contradiction, never on legitimately sample-less players.
    offenders = payload["validation"].get("no_sample_contradiction_players") or []
    if offenders:
        preview = ", ".join(offenders[:25])
        if len(offenders) > 25:
            preview += f", +{len(offenders) - 25} more"
        raise ScoutingRepositorySentinelError(
            f"{len(offenders)} scouting report(s) claim 'no current performance sample' "
            f"for a prospect with a real stat line; refusing to publish: {preview}."
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
