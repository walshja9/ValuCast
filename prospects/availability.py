"""Availability and current-sample risk layer for ValuCast prospects.

This layer uses only ValuCast-owned factual inputs from the prospect training
contract plus optional manually verified status overrides. It must not consume
DD ranks, DD values, public prospect rankings, or market behavior.
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from mlb.availability import availability_lookup as mlb_availability_lookup
from mlb.roster_status import active_roster_lookup
from prospects.input_contract import VALUCAST_INPUT_PATH

ROOT = Path(__file__).resolve().parents[1]
INPUT_CONTRACT_PATH = VALUCAST_INPUT_PATH
OVERRIDES_PATH = ROOT / "data" / "manual" / "prospect_availability_overrides.json"
MLB_AVAILABILITY_PATH = ROOT / "data" / "models" / "valucast_mlb_availability.json"
MLB_ROSTER_STATUS_PATH = ROOT / "data" / "models" / "valucast_mlb_roster_status.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_availability.json"

ARTIFACT_NAME = "valucast_prospect_availability"
ARTIFACT_VERSION = "0.5.0"

MAX_RISK_DISCOUNT = 0.12
SEVERE_IL_DISCOUNT = 0.30
SHORT_IL_DISCOUNT = 0.12
MAX_IL_RISK_DISCOUNT = 0.40
SEVERE_IL_KEYWORDS = (
    "surgery",
    "tommy john",
    "ucl",
    "acl",
    "achilles",
    "labrum",
    "tear",
    "season-ending",
    "season ending",
)
STALE_MODERATE_DAYS = 14
STALE_HIGH_DAYS = 28
UPPER_LEVELS = {"AA", "AAA", "MLB"}
LEVEL_ORDER = {
    "DSL": 1,
    "CPX": 2,
    "ROK": 2,
    "R": 2,
    "A": 3,
    "A+": 4,
    "HIGH-A": 4,
    "AA": 5,
    "AAA": 6,
    "MLB": 7,
}
LEVEL_ETA_HINTS = {
    "MLB": "now",
    "AAA": "near_term",
    "AA": "one_to_two_years",
    "A+": "two_to_three_years",
    "A": "two_to_three_years",
    "ROK": "long_range",
    "CPX": "long_range",
}
EXPLICIT_STATUS_DISCOUNTS = {
    "injured": MAX_RISK_DISCOUNT,
    "il": MAX_RISK_DISCOUNT,
    "inactive": 0.10,
    "restricted": 0.10,
    "rehab": 0.08,
}
ROSTER_STATUS_MAP = {
    "inj res": "injured",
    "injured reserve": "injured",
    "il": "injured",
    "injured": "injured",
    "out": "injured",
}


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


def _clean_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


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


def _level_key(level: Any) -> str:
    text = str(level or "").strip().upper()
    return {
        "HIGH A": "A+",
        "HIGH-A": "A+",
        "HI-A": "A+",
        "SINGLE-A": "A",
        "LOW A": "A",
        "LOW-A": "A",
        "ROOKIE": "ROK",
        "COMPLEX": "CPX",
    }.get(text, text)


def _level_rank(level: Any) -> int:
    return LEVEL_ORDER.get(_level_key(level), 0)


def eta_window(row: dict | None) -> str:
    if not isinstance(row, dict):
        return "unknown"
    eta = row.get("eta")
    if eta not in (None, ""):
        return str(eta)
    return LEVEL_ETA_HINTS.get(_level_key(row.get("level")), "unknown")


# Compact, table-friendly labels for the level-derived ETA windows (the precise
# integer ETA is rendered as the year itself; this only labels the fallback).
_ETA_WINDOW_LABELS = {
    "now": "~now",
    "near_term": "~1 yr",
    "one_to_two_years": "~1-2 yr",
    "two_to_three_years": "~2-3 yr",
    "long_range": "~3+ yr",
}


def eta_window_label(window: Any) -> str | None:
    if window in (None, "", "unknown"):
        return None
    return _ETA_WINDOW_LABELS.get(str(window), "approx. " + str(window).replace("_", " "))


def identity_key(mlbam_id: Any, role: str | None) -> tuple[str, str] | None:
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return str(mlbam_id), role


def _sample_value(row: dict, role: str) -> float:
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


def _best_display_row(rows: list[dict], role: str) -> dict:
    return max(
        rows,
        key=lambda row: (
            _level_rank(row.get("level")),
            _sample_value(row, role),
            str(row.get("sample_fetched_date") or ""),
        ),
    )


def _sample_season(row: dict) -> float:
    return _clean_float(row.get("sample_season")) or 0.0


def _active_sample_rows(rows: list[dict]) -> list[dict]:
    seasons = [_sample_season(row) for row in rows]
    valid_seasons = [season for season in seasons if season > 0]
    if not valid_seasons:
        return rows
    latest = max(valid_seasons)
    return [row for row in rows if _sample_season(row) == latest]


def _latest_sample_date(rows: list[dict]) -> str | None:
    dates = [_parse_date(row.get("sample_fetched_date")) for row in rows]
    valid_dates = [value for value in dates if value is not None]
    if not valid_dates:
        return None
    return max(valid_dates).isoformat()


def _current_rows(input_contract: dict) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    current = input_contract.get("current") or {}
    for role, bucket in (("hitter", "hitters"), ("pitcher", "pitchers")):
        for row in current.get(bucket) or []:
            key = identity_key(row.get("mlbam_id"), role)
            if key:
                rows.append((role, row))
    return rows


def _override_entries(overrides: dict | list[dict] | None) -> dict[tuple[str, str], dict]:
    if not overrides:
        return {}
    if isinstance(overrides, list):
        entries = overrides
    elif isinstance(overrides, dict):
        entries = (
            overrides.get("overrides")
            or overrides.get("players")
            or overrides.get("availability")
            or []
        )
        if isinstance(entries, dict):
            entries = list(entries.values())
    else:
        entries = []

    lookup: dict[tuple[str, str], dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = identity_key(entry.get("mlbam_id"), entry.get("role"))
        if key:
            lookup[key] = entry
    return lookup


def _staleness_days(rows: list[dict], generated_at: str | None) -> int | None:
    sample_date = _parse_date(_latest_sample_date(rows))
    generated_date = _parse_date(generated_at)
    if sample_date is None or generated_date is None:
        return None
    return max(0, (generated_date - sample_date).days)


def _sample_signal(
    role: str,
    total_sample: float,
    display_row: dict,
    highest_level: str,
) -> tuple[float, list[str]]:
    signals: list[str] = []
    discount = 0.0
    upper_level = highest_level in UPPER_LEVELS
    if role == "pitcher":
        starts = _clean_int(display_row.get("games_started")) or 0
        is_starter = bool(display_row.get("is_starter")) or starts >= 3
        if is_starter:
            if total_sample < 30.0:
                discount = max(discount, 0.06)
                signals.append("thin_starter_workload_under_30_ip")
            elif upper_level and total_sample < 45.0:
                discount = max(discount, 0.03)
                signals.append("limited_upper_level_starter_workload_under_45_ip")
        elif total_sample < 12.0:
            discount = max(discount, 0.04)
            signals.append("thin_pitcher_workload_under_12_ip")
    elif upper_level:
        if total_sample < 100.0:
            discount = max(discount, 0.05)
            signals.append("thin_upper_level_hitter_sample_under_100_pa")
        elif total_sample < 150.0:
            discount = max(discount, 0.03)
            signals.append("limited_upper_level_hitter_sample_under_150_pa")
    return discount, signals


def _staleness_signal(
    role: str,
    rows: list[dict],
    generated_at: str | None,
) -> tuple[float, list[str], int | None]:
    days = _staleness_days(rows, generated_at)
    signals: list[str] = []
    discount = 0.0
    years = max(
        (
            _clean_int(row.get("sample_staleness_years")) or 0
            for row in rows
        ),
        default=0,
    )
    if years > 0:
        discount = max(discount, 0.10 if role == "pitcher" else 0.08)
        signals.append("prior_season_sample")
    if days is not None and days >= STALE_HIGH_DAYS:
        discount = max(discount, 0.08 if role == "pitcher" else 0.06)
        signals.append("sample_stale_28_plus_days")
    elif days is not None and days >= STALE_MODERATE_DAYS:
        discount = max(discount, 0.04 if role == "pitcher" else 0.03)
        signals.append("sample_stale_14_plus_days")
    return discount, signals, days


def _status_discount(role: str, status: str | None, explicit: float | None = None) -> float:
    if explicit is not None:
        discount = explicit
    else:
        discount = EXPLICIT_STATUS_DISCOUNTS.get(status or "", 0.0)
        if role == "hitter" and discount == MAX_RISK_DISCOUNT:
            discount = 0.08
    return discount


def _override_signal(role: str, override: dict | None) -> tuple[float, list[str], str | None, str | None]:
    if not override:
        return 0.0, [], None, None
    status = str(override.get("status") or "").strip().lower() or None
    note = override.get("note")
    explicit = _clean_float(override.get("risk_discount"))
    discount = _status_discount(role, status, explicit)
    signals = ["manual_status_override"] if status else []
    return discount, signals, status, str(note) if note not in (None, "") else None


def _il_severity_discount(list_type: str, description: str) -> float:
    text = f"{list_type} {description}".lower()
    if (
        "60-day" in text
        or "60 day" in text
        or any(k in text for k in SEVERE_IL_KEYWORDS)
    ):
        return SEVERE_IL_DISCOUNT
    return SHORT_IL_DISCOUNT


def _official_availability_signal(
    mlbam_id: str,
    role: str,
    il_lookup: dict | None,
) -> tuple[float, list[str], str | None, str | None]:
    profile = (il_lookup or {}).get(str(mlbam_id)) or (il_lookup or {}).get(mlbam_id)
    if not profile:
        return 0.0, [], None, None
    status = str(profile.get("status") or "").strip().lower()
    if status == "available":
        return 0.0, [], status, None
    if status == "rehab" and profile.get("active_injury_risk") is True:
        return (
            _status_discount(role, status),
            ["official_mlb_rehab_override"],
            status,
            str(profile.get("description") or "Official MLB rehab assignment."),
        )
    if status != "injured" or profile.get("active_injury_risk") is not True:
        return 0.0, [], None, None
    list_type = str(profile.get("list_type") or "")
    description = str(profile.get("description") or "")
    discount = _il_severity_discount(list_type, description)
    note = description.strip()
    if not note:
        team = profile.get("team") or "MLB"
        name = profile.get("name") or f"MLBAM {mlbam_id}"
        list_type = profile.get("list_type") or "IL"
        effective_date = profile.get("effective_date") or "unknown date"
        note = f"{team} placed {name} on the {list_type} ({effective_date})"
    return discount, ["official_mlb_il_override"], "injured", note


def _row_status(row: dict) -> str | None:
    status = str(row.get("availability_status") or "").strip().lower()
    if status:
        return ROSTER_STATUS_MAP.get(status, status)
    roster_status = str(row.get("roster_status") or "").strip().lower()
    if roster_status:
        return ROSTER_STATUS_MAP.get(roster_status)
    return None


def _upstream_status_signal(role: str, rows: list[dict]) -> tuple[float, list[str], str | None, str | None]:
    candidates = []
    for row in rows:
        status = _row_status(row)
        if status not in EXPLICIT_STATUS_DISCOUNTS:
            continue
        candidates.append((status, row))
    if not candidates:
        return 0.0, [], None, None
    status, row = candidates[0]
    note = row.get("availability_note")
    roster_status = row.get("roster_status")
    source = row.get("availability_source") or "upstream_factual_status"
    if not note and roster_status:
        note = f"Upstream factual roster status is {roster_status}."
    return (
        _status_discount(role, status),
        [f"{source}_override"],
        status,
        str(note) if note not in (None, "") else None,
    )


def _risk_level(discount: float) -> str:
    if discount >= 0.08:
        return "high"
    if discount >= 0.03:
        return "medium"
    if discount > 0:
        return "low"
    return "clear"


def _status(signals: list[str], override_status: str | None) -> str:
    if override_status:
        return override_status
    if any(signal.startswith("sample_stale") or signal == "prior_season_sample" for signal in signals):
        return "stale_or_inactive"
    if signals:
        return "thin_current_sample"
    return "available"


def _risk_basis(
    sample_discount: float,
    stale_discount: float,
    upstream_discount: float,
    il_discount: float,
    override_discount: float,
    il_status: str | None = None,
) -> str:
    discounts = {
        "manual_override": override_discount,
        "official_mlb_rehab" if il_status == "rehab" else "official_mlb_il": il_discount,
        "upstream_factual_status": upstream_discount,
        "sample_staleness": stale_discount,
        "current_sample_size": sample_discount,
    }
    basis, discount = max(discounts.items(), key=lambda item: item[1])
    return basis if discount > 0 else "none"


def _profile(
    key: tuple[str, str],
    rows: list[dict],
    generated_at: str | None,
    override: dict | None,
    il_lookup: dict | None = None,
    active_roster_ids: set[str] | None = None,
) -> dict:
    mlbam_id, role = key
    active_mlb_roster = str(mlbam_id) in (active_roster_ids or set())
    active_rows = _active_sample_rows(rows)
    display_row = _best_display_row(active_rows, role)
    total_sample = sum(_sample_value(row, role) for row in active_rows)
    highest_level = _level_key(display_row.get("level"))

    sample_discount, sample_signals = _sample_signal(
        role,
        total_sample,
        display_row,
        highest_level,
    )
    stale_discount, stale_signals, stale_days = _staleness_signal(
        role,
        active_rows,
        generated_at,
    )
    upstream_discount, upstream_signals, upstream_status, upstream_note = (
        _upstream_status_signal(role, active_rows)
    )
    il_discount, il_signals, il_status, il_note = _official_availability_signal(
        mlbam_id,
        role,
        il_lookup,
    )
    override_discount, override_signals, override_status, override_note = _override_signal(
        role,
        override,
    )
    override_present = override_discount > 0.0 or bool(override_status)
    if override_present or active_mlb_roster:
        il_discount, il_signals, il_status, il_note = 0.0, [], None, None
    if override_present or active_mlb_roster or il_status:
        upstream_discount, upstream_signals, upstream_status, upstream_note = (
            0.0,
            [],
            None,
            None,
        )
    if il_status == "available":
        il_status = None
    override_age = _clean_int((override or {}).get("age"))
    signals = list(
        dict.fromkeys(
            sample_signals
            + stale_signals
            + upstream_signals
            + il_signals
            + override_signals
        )
    )
    risk_discount = max(
        min(
            MAX_RISK_DISCOUNT,
            max(
                0.0,
                sample_discount,
                stale_discount,
                upstream_discount,
            ),
        ),
        min(MAX_IL_RISK_DISCOUNT, il_discount),
        min(MAX_IL_RISK_DISCOUNT, override_discount),
    )
    risk_basis = _risk_basis(
        sample_discount,
        stale_discount,
        upstream_discount,
        il_discount,
        override_discount,
        il_status,
    )
    if risk_basis in {"official_mlb_il", "official_mlb_rehab"}:
        signals = il_signals
    official_profile = (il_lookup or {}).get(str(mlbam_id)) or (il_lookup or {}).get(
        mlbam_id
    )
    status_source = (
        "manual_override"
        if override_present
        else "active_mlb_roster"
        if active_mlb_roster
        else "official_mlb_transactions"
        if official_profile
        else "upstream_factual_status"
        if upstream_status
        else "current_sample"
    )
    known_evidence = bool(
        _latest_sample_date(active_rows)
        or override_present
        or active_mlb_roster
        or official_profile
        or upstream_status
    )
    evidence_state = (
        "unknown"
        if not known_evidence
        else "known_available"
        if risk_basis == "none"
        else "known_limited"
        if risk_basis
        in {"current_sample_size", "sample_staleness", "official_mlb_rehab"}
        else "known_unavailable"
    )
    return {
        "mlbam_id": _clean_int(mlbam_id) or mlbam_id,
        "role": role,
        "name": display_row.get("name"),
        "normalized_name": display_row.get("normalized_name"),
        "age": override_age if override_age is not None else display_row.get("age"),
        "level": display_row.get("level"),
        "team": display_row.get("team"),
        "sample": _round(total_sample, 3),
        "sample_unit": "IP" if role == "pitcher" else "PA",
        "sample_fetched_date": _latest_sample_date(active_rows),
        "sample_staleness_days": stale_days,
        "source_kind": display_row.get("source_kind"),
        "risk_discount": round(risk_discount, 4),
        "risk_basis": risk_basis,
        "risk_level": _risk_level(risk_discount),
        "status": _status(signals, override_status or il_status or upstream_status),
        "availability_note": override_note or il_note or upstream_note or (
            "; ".join(signals).replace("_", " ") if signals else "Current sample is active."
        ),
        "signals": signals,
        "row_count": len(rows),
        "active_row_count": len(active_rows),
        "evidence_state": evidence_state,
        "evidence_provenance": {
            "generated_at": generated_at,
            "status_source": status_source,
            "selected_level": display_row.get("level"),
            "selected_sample": _round(_sample_value(display_row, role), 3),
            "selected_sample_unit": "IP" if role == "pitcher" else "PA",
            "selected_sample_fetched_date": _date_part(
                display_row.get("sample_fetched_date")
            ),
            "active_row_count": len(active_rows),
            "adjustment_reason": risk_basis,
        },
        "present": True,
        "active_mlb_roster": active_mlb_roster,
    }


def availability_lookup(payload: dict | None) -> dict[tuple[str, str], dict]:
    lookup: dict[tuple[str, str], dict] = {}
    for row in (payload or {}).get("profiles") or []:
        key = identity_key(row.get("mlbam_id"), row.get("role"))
        if key:
            lookup[key] = row
    return lookup


def apply_availability_adjustment(
    score: float,
    components: dict,
    availability_profile: dict | None,
) -> tuple[float, dict]:
    if not availability_profile:
        return score, components
    discount = _clean_float(availability_profile.get("risk_discount")) or 0.0
    basis = str(availability_profile.get("risk_basis") or "")
    ceiling = (
        MAX_IL_RISK_DISCOUNT
        if basis in {"official_mlb_il", "manual_override"}
        else MAX_RISK_DISCOUNT
    )
    discount = max(0.0, min(ceiling, discount))
    adjusted_score = round(max(0.0, score * (1.0 - discount)), 2)
    next_components = dict(components)
    next_components["score_before_availability_adjustment"] = round(score, 2)
    next_components["availability_risk_discount"] = round(discount, 4)
    next_components["availability_adjusted"] = discount > 0
    next_components["availability"] = {
        "present": True,
        "status": availability_profile.get("status"),
        "risk_level": availability_profile.get("risk_level"),
        "risk_discount": round(discount, 4),
        "risk_basis": availability_profile.get("risk_basis"),
        "note": availability_profile.get("availability_note"),
        "level": availability_profile.get("level"),
        "signals": list(availability_profile.get("signals") or []),
        "sample": availability_profile.get("sample"),
        "sample_unit": availability_profile.get("sample_unit"),
        "sample_fetched_date": availability_profile.get("sample_fetched_date"),
        "sample_staleness_days": availability_profile.get("sample_staleness_days"),
    }
    return adjusted_score, next_components


def _count_by(profiles: list[dict], field: str) -> dict[str, int]:
    counts = Counter(str(row.get(field) or "missing") for row in profiles)
    return {key: counts[key] for key in sorted(counts)}


def _signal_counts(profiles: list[dict]) -> dict[str, int]:
    counts = Counter(str(signal) for row in profiles for signal in row.get("signals") or [])
    return {key: counts[key] for key in sorted(counts)}


def _risk_entry(row: dict) -> dict:
    return {
        "mlbam_id": row.get("mlbam_id"),
        "name": row.get("name"),
        "role": row.get("role"),
        "level": row.get("level"),
        "team": row.get("team"),
        "sample": row.get("sample"),
        "sample_unit": row.get("sample_unit"),
        "status": row.get("status"),
        "risk_level": row.get("risk_level"),
        "risk_discount": row.get("risk_discount"),
        "risk_basis": row.get("risk_basis"),
        "signals": row.get("signals") or [],
        "availability_note": row.get("availability_note"),
    }


def _risk_summary(profiles: list[dict]) -> dict:
    risk_profiles = [
        row for row in profiles if (_clean_float(row.get("risk_discount")) or 0.0) > 0
    ]
    top_risk = sorted(
        risk_profiles,
        key=lambda row: (
            -(_clean_float(row.get("risk_discount")) or 0.0),
            str(row.get("role") or ""),
            str(row.get("name") or ""),
            str(row.get("mlbam_id") or ""),
        ),
    )[:25]
    return {
        "profile_count": len(profiles),
        "risk_profile_count": len(risk_profiles),
        "status_counts": _count_by(profiles, "status"),
        "risk_level_counts": _count_by(profiles, "risk_level"),
        "risk_basis_counts": _count_by(profiles, "risk_basis"),
        "signal_counts": _signal_counts(profiles),
        "top_risk_profiles": [_risk_entry(row) for row in top_risk],
    }


def build_prospect_availability(
    input_contract: dict,
    overrides: dict | list[dict] | None = None,
    generated_at: str | None = None,
    il_lookup: dict | None = None,
    active_roster_ids: set[str] | None = None,
) -> dict:
    generated_at = generated_at or input_contract.get("generated_at") or datetime.now(
        timezone.utc
    ).isoformat()
    grouped: dict[tuple[str, str], list[dict]] = {}
    for role, row in _current_rows(input_contract):
        key = identity_key(row.get("mlbam_id"), role)
        if key:
            grouped.setdefault(key, []).append(row)

    override_by_key = _override_entries(overrides)
    profiles = [
        _profile(
            key,
            rows,
            generated_at,
            override_by_key.get(key),
            il_lookup or {},
            active_roster_ids or set(),
        )
        for key, rows in sorted(
            grouped.items(),
            key=lambda item: (
                item[0][1],
                str(_best_display_row(item[1], item[0][1]).get("name") or ""),
                item[0][0],
            ),
        )
    ]
    profiles.sort(
        key=lambda row: (
            str(row.get("role") or ""),
            str(row.get("name") or ""),
            str(row.get("mlbam_id") or ""),
        )
    )
    risk_profiles = [row for row in profiles if (row.get("risk_discount") or 0.0) > 0]
    summary = _risk_summary(profiles)
    return {
        "artifact": ARTIFACT_NAME,
        "artifact_version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "profile_count": len(profiles),
        "risk_profile_count": len(risk_profiles),
        "max_risk_discount": MAX_RISK_DISCOUNT,
        "source_policy": {
            "kind": "valucast_factual_availability_layer",
            "source_artifact": "prospect_model_inputs",
            "manual_overrides_allowed": True,
            "dd_factual_roster_status_allowed": True,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "thresholds": {
            "stale_moderate_days": STALE_MODERATE_DAYS,
            "stale_high_days": STALE_HIGH_DAYS,
            "upper_levels": sorted(UPPER_LEVELS),
            "max_risk_discount": MAX_RISK_DISCOUNT,
        },
        "summary": summary,
        "validation": {
            "current_identity_count": len(profiles),
            "duplicate_level_rows_collapsed": sum(
                max(0, len(rows) - 1) for rows in grouped.values()
            ),
            "risk_profile_count": len(risk_profiles),
            "manual_override_count": len(override_by_key),
            "upstream_status_count": sum(
                1
                for row in profiles
                if "fantrax_roster_status_override" in (row.get("signals") or [])
            ),
            "unmatched_manual_override_count": len(
                set(override_by_key).difference(grouped)
            ),
        },
        "profiles": profiles,
    }


def _load_optional(path: Path | None) -> dict | list[dict] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_prospect_availability(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_prospect_availability(
    input_contract_path: Path = INPUT_CONTRACT_PATH,
    overrides_path: Path | None = OVERRIDES_PATH,
    mlb_availability_path: Path | None = MLB_AVAILABILITY_PATH,
    mlb_roster_status_path: Path | None = MLB_ROSTER_STATUS_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    input_contract = json.loads(input_contract_path.read_text(encoding="utf-8"))
    overrides = _load_optional(overrides_path)
    raw_mlb_availability = _load_optional(mlb_availability_path)
    raw_profiles = (
        raw_mlb_availability.get("profiles")
        if isinstance(raw_mlb_availability, dict)
        else None
    )
    il_lookup = (
        mlb_availability_lookup({"profiles": raw_profiles}) if raw_profiles else {}
    )
    raw_roster_status = _load_optional(mlb_roster_status_path)
    active_roster_ids = set(
        active_roster_lookup(
            raw_roster_status if isinstance(raw_roster_status, dict) else {}
        )
    )
    payload = build_prospect_availability(
        input_contract,
        overrides=overrides,
        il_lookup=il_lookup,
        active_roster_ids=active_roster_ids,
    )
    path = write_prospect_availability(payload, artifact_path)
    return {
        "artifact_path": str(path),
        "profile_count": payload["profile_count"],
        "risk_profile_count": payload["risk_profile_count"],
        "manual_override_count": payload["validation"]["manual_override_count"],
    }
