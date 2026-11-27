"""Prospect target definitions for the legacy correction and Rank v2."""
from __future__ import annotations

import hashlib
import json
import math
import re

OUTCOME_SCORE = {"bust": 0.0, "role": 0.5, "star": 1.0}
TARGET_NAME = "four_year_bust_role_star_v2"
HORIZON_YEARS = 4
_MISSING_RATE_MARKERS = {None, "", "-", "-.--", ".---"}

_ROW_FIELDS = {
    "age", "at_bats", "avg", "babip", "bats", "batters_faced", "bb_pct",
    "bb_per_9", "cohort_year", "doubles", "draft_pick_number",
    "draft_record_known", "draft_round", "draft_year", "earned_runs", "era",
    "games_played", "games_started", "hits", "home_runs", "innings_pitched",
    "is_starter", "iso", "k_bb_pct", "k_pct", "k_per_9", "level", "losses",
    "mlbam_id", "name", "normalized_name", "obp", "ops", "outcome",
    "pick_value", "pitches", "plate_appearances", "position", "rbi", "role",
    "rule4_drafted", "runs", "sac_flies", "school_type", "signing_bonus",
    "slg", "sport_id", "stolen_bases", "strikeouts", "strikes", "team",
    "throws", "triples", "walks", "whip", "wins",
}
_SEASON_FIELDS = {
    "hitter": {"year", "pa", "ab", "r", "hr", "rbi", "sb", "avg", "ops", "so"},
    "pitcher": {"year", "ip", "era", "whip", "so", "sv", "hld", "l", "k_bb", "qs"},
}


def canonical_sha256(payload) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _number(value, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _optional_number(value, field: str) -> float | None:
    return None if value in _MISSING_RATE_MARKERS else _number(value, field)


def _horizon(cohort_year: int, seasons: list[dict]) -> list[dict]:
    return [
        season
        for season in seasons
        if cohort_year < int(season["year"]) <= cohort_year + HORIZON_YEARS
    ]


def parse_baseball_innings(value) -> float:
    text = str(value).strip()
    if not re.fullmatch(r"\d+(?:\.[012])?", text):
        raise ValueError("inningsPitched must use whole innings or .0/.1/.2")
    whole, _, fraction = text.partition(".")
    return int(whole) + (int(fraction or 0) / 3.0)


def parse_year_by_year_response(payload: dict, role: str) -> tuple[list[dict], bool]:
    if role not in {"hitter", "pitcher"}:
        raise ValueError(f"unsupported role {role!r}")
    stats = payload.get("stats") if isinstance(payload, dict) else None
    if not isinstance(stats, list) or not stats:
        raise ValueError("stats must be a non-empty list")
    splits = []
    for group in stats:
        if not isinstance(group, dict) or not isinstance(group.get("splits"), list):
            raise ValueError("splits must be a list")
        splits.extend(group["splits"])

    seasons = []
    for split in splits:
        if not isinstance(split, dict):
            raise ValueError("split must be an object")
        if str((split.get("sport") or {}).get("id")) != "1":
            continue
        try:
            year = int(split["season"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("season must be an integer") from error
        stat = split.get("stat")
        if not isinstance(stat, dict):
            raise ValueError("stat must be an object")
        if role == "hitter":
            pa = _number(stat.get("plateAppearances"), "plateAppearances")
            ops = _optional_number(stat.get("ops"), "ops")
            if pa >= 450 and ops is None:
                raise ValueError("OPS required at the Star threshold")
            seasons.append({
                "year": year,
                "pa": int(pa),
                "ab": int(_number(stat.get("atBats", 0), "atBats")),
                "r": int(_number(stat.get("runs", 0), "runs")),
                "hr": int(_number(stat.get("homeRuns", 0), "homeRuns")),
                "rbi": int(_number(stat.get("rbi", 0), "rbi")),
                "sb": int(_number(stat.get("stolenBases", 0), "stolenBases")),
                "avg": _optional_number(stat.get("avg"), "avg"),
                "ops": ops,
                "so": int(_number(stat.get("strikeOuts", 0), "strikeOuts")),
            })
        else:
            ip = parse_baseball_innings(stat.get("inningsPitched"))
            era = _optional_number(stat.get("era"), "era")
            if ip >= 120 and era is None:
                raise ValueError("ERA required at the Star threshold")
            seasons.append({
                "year": year,
                "ip": ip,
                "era": era,
                "whip": _optional_number(stat.get("whip"), "whip"),
                "so": int(_number(stat.get("strikeOuts", 0), "strikeOuts")),
                "sv": int(_number(stat.get("saves", 0), "saves")),
                "hld": int(_number(stat.get("holds", 0), "holds")),
                "l": int(_number(stat.get("losses", 0), "losses")),
                "k_bb": _optional_number(
                    stat.get("strikeoutWalkRatio"), "strikeoutWalkRatio"
                ),
                "qs": None,
            })
    seasons.sort(key=lambda row: row["year"])
    return seasons, not seasons


def validate_no_debut_response(payload: dict, mlbam_id: int) -> bool:
    people = payload.get("people") if isinstance(payload, dict) else None
    if not isinstance(people, list):
        raise ValueError("people must be a list")
    person = next(
        (
            row for row in people
            if isinstance(row, dict) and str(row.get("id")) == str(int(mlbam_id))
        ),
        None,
    )
    if person is None:
        raise ValueError("matching person is required")
    if person.get("mlbDebutDate") not in (None, ""):
        raise ValueError("player already debuted")
    return True


def validate_opposite_role_response(
    people_payload: dict,
    opposite_stats_payload: dict,
    mlbam_id: int,
    requested_role: str,
) -> bool:
    people = people_payload.get("people") if isinstance(people_payload, dict) else None
    if not isinstance(people, list):
        raise ValueError("people must be a list")
    person = next(
        (
            row for row in people
            if isinstance(row, dict) and str(row.get("id")) == str(int(mlbam_id))
        ),
        None,
    )
    if person is None:
        raise ValueError("matching person is required")
    position_type = str((person.get("primaryPosition") or {}).get("type") or "")
    if requested_role == "hitter":
        opposite_role = "pitcher"
        position_matches = position_type == "Pitcher"
    elif requested_role == "pitcher":
        opposite_role = "hitter"
        position_matches = position_type not in {"", "Pitcher", "Two-Way Player"}
    else:
        raise ValueError(f"unsupported role {requested_role!r}")
    if not position_matches:
        raise ValueError("opposite-role primary position is required")
    seasons, _ = parse_year_by_year_response(opposite_stats_payload, opposite_role)
    if not seasons:
        raise ValueError("opposite-role MLB stats are required")
    return True


def _unexpected(mapping, allowed: set[str], path: str) -> list[str]:
    if not isinstance(mapping, dict):
        return [f"{path} must be an object"]
    return [f"unexpected field {path}.{key}" for key in sorted(set(mapping) - allowed)]


def _policy_errors(policy: dict, *, confirmation: bool) -> list[str]:
    allowed = {
        "kind", "candidate_input_allowlist", "contains_provisional_2022_target",
        "feeds_live_rank", "feeds_value",
    }
    if confirmation:
        allowed.add("contains_post_cohort_mlb_facts")
    errors = _unexpected(policy, allowed, "source_policy")
    if not isinstance(policy, dict):
        return errors
    expected = {
        "kind": "factual_only",
        "candidate_input_allowlist": True,
        "contains_provisional_2022_target": False,
        "feeds_live_rank": False,
        "feeds_value": False,
    }
    if confirmation:
        expected["contains_post_cohort_mlb_facts"] = False
    for key, value in expected.items():
        actual = policy.get(key)
        if type(actual) is not type(value) or actual != value:
            errors.append(f"source_policy.{key} must be {value!r}")
    return errors


def _source_hash_errors(source_hashes) -> list[str]:
    allowed = {"universal_dataset", "milb_card_history"}
    errors = _unexpected(source_hashes, allowed, "source_hashes")
    if not isinstance(source_hashes, dict):
        return errors
    for key in allowed:
        value = source_hashes.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            errors.append(f"source_hashes.{key} must be a SHA-256")
    return errors


def _row_errors(rows, *, confirmation: bool) -> list[str]:
    if not isinstance(rows, list):
        return ["rows must be a list"]
    errors = []
    allowed = _ROW_FIELDS - ({"outcome"} if confirmation else set())
    for index, row in enumerate(rows):
        path = f"rows[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{path} must be an object")
            continue
        for key in sorted(set(row) - allowed):
            if confirmation and key in {"outcome", "target", "historical_mlb_seasons"}:
                errors.append(f"forbidden field {path}.{key}")
            else:
                errors.append(f"unexpected field {path}.{key}")
        role = row.get("role")
        if role not in {"hitter", "pitcher"}:
            errors.append(f"{path}.role must be hitter or pitcher")
        if confirmation:
            if row.get("cohort_year") != 2022:
                errors.append(f"{path}.cohort_year must be 2022")
        else:
            if not isinstance(row.get("cohort_year"), int) or row["cohort_year"] > 2021:
                errors.append(f"{path}.cohort_year must be at most 2021")
            if row.get("outcome") not in OUTCOME_SCORE:
                errors.append(f"{path}.outcome is invalid")
        if role == "pitcher":
            pitches, strikes = row.get("pitches"), row.get("strikes")
            if (
                not isinstance(pitches, (int, float))
                or not isinstance(strikes, (int, float))
                or pitches <= 0
                or not 0 <= strikes <= pitches
            ):
                errors.append(f"{path} has invalid pitches/strikes")
    return errors


def validate_development_contract(payload: dict) -> list[str]:
    allowed = {
        "schema_version", "generated_at", "target", "cohort_max", "mature_through",
        "historical", "historical_mlb_seasons", "acquisition_by_cohort_identity",
        "source_hashes", "source_policy",
    }
    errors = _unexpected(payload, allowed, "payload")
    if not isinstance(payload, dict):
        return errors
    if payload.get("schema_version") != "prospect_v2_development_contract_v1":
        errors.append("schema_version must be prospect_v2_development_contract_v1")
    if payload.get("target") != TARGET_NAME:
        errors.append(f"target must be {TARGET_NAME}")
    if payload.get("cohort_max") != 2021 or payload.get("mature_through") != 2021:
        errors.append("development cohort boundary must be 2021")
    historical = payload.get("historical")
    errors.extend(_unexpected(historical, {"rows"}, "historical"))
    rows = historical.get("rows") if isinstance(historical, dict) else None
    errors.extend(_row_errors(rows, confirmation=False))
    if isinstance(rows, list) and len(rows) != 5984:
        errors.append("development row count must be 5984")
    if isinstance(rows, list):
        role_counts = {
            role: sum(row.get("role") == role for row in rows if isinstance(row, dict))
            for role in ("hitter", "pitcher")
        }
        if role_counts != {"hitter": 2922, "pitcher": 3062}:
            errors.append(f"development role counts are invalid: {role_counts}")
    seasons_by_key = payload.get("historical_mlb_seasons")
    expected_keys = {
        f"{int(row['mlbam_id'])}_{row['role']}"
        for row in rows or []
        if isinstance(row, dict) and row.get("mlbam_id") is not None
        and row.get("role") in {"hitter", "pitcher"}
    }
    if isinstance(rows, list) and len(expected_keys) != len(rows):
        errors.append("development identities must be unique")
    if not isinstance(seasons_by_key, dict):
        errors.append("historical_mlb_seasons must be an object")
    else:
        if set(seasons_by_key) != expected_keys:
            errors.append("historical_mlb_seasons keys must equal development identities")
        for key, seasons in seasons_by_key.items():
            role = "hitter" if key.endswith("_hitter") else "pitcher" if key.endswith("_pitcher") else None
            if role is None or not isinstance(seasons, list):
                errors.append(f"historical_mlb_seasons.{key} is invalid")
                continue
            for index, season in enumerate(seasons):
                errors.extend(_unexpected(season, _SEASON_FIELDS[role], f"historical_mlb_seasons.{key}[{index}]"))
    acquisitions = payload.get("acquisition_by_cohort_identity")
    if not isinstance(acquisitions, dict):
        errors.append("acquisition_by_cohort_identity must be an object")
    elif set(acquisitions) != expected_keys:
        errors.append("acquisition keys must equal development identities")
    elif isinstance(acquisitions, dict):
        acquisition_fields = {
            "url", "acquired_at", "raw_response_sha256", "structural_validation",
            "valid_empty", "empty_attestation",
        }
        for key, acquisition in acquisitions.items():
            errors.extend(_unexpected(acquisition, acquisition_fields, f"acquisition_by_cohort_identity.{key}"))
            if isinstance(acquisition, dict) and acquisition.get("structural_validation") != "passed":
                errors.append(f"acquisition_by_cohort_identity.{key}.structural_validation must be passed")
            if isinstance(acquisition, dict) and not re.fullmatch(
                r"[0-9a-f]{64}", str(acquisition.get("raw_response_sha256") or "")
            ):
                errors.append(f"acquisition_by_cohort_identity.{key}.raw_response_sha256 must be a SHA-256")
            attestation = acquisition.get("empty_attestation") if isinstance(acquisition, dict) else None
            if attestation is not None:
                errors.extend(_unexpected(
                    attestation,
                    {"url", "raw_response_sha256", "basis"},
                    f"acquisition_by_cohort_identity.{key}.empty_attestation",
                ))
    if isinstance(rows, list) and isinstance(seasons_by_key, dict):
        for row in rows:
            if not isinstance(row, dict) or row.get("role") not in {"hitter", "pitcher"}:
                continue
            key = f"{int(row['mlbam_id'])}_{row['role']}"
            seasons = seasons_by_key.get(key)
            if isinstance(seasons, list):
                try:
                    derived = derive_four_year_outcome(
                        row["role"], int(row["cohort_year"]), seasons
                    )
                except (KeyError, TypeError, ValueError) as error:
                    errors.append(f"{key}: target derivation failed: {error}")
                else:
                    if row.get("outcome") != derived:
                        errors.append(f"{key}: outcome does not match frozen seasons")
    errors.extend(_source_hash_errors(payload.get("source_hashes")))
    errors.extend(_policy_errors(payload.get("source_policy"), confirmation=False))
    return errors


def validate_confirmation_manifest(payload: dict) -> list[str]:
    allowed = {
        "schema_version", "generated_at", "target_cohort", "rows", "source_hashes",
        "source_policy",
    }
    errors = _unexpected(payload, allowed, "payload")
    if not isinstance(payload, dict):
        return errors
    if payload.get("schema_version") != "prospect_2022_confirmation_manifest_v1":
        errors.append("schema_version must be prospect_2022_confirmation_manifest_v1")
    if payload.get("target_cohort") != 2022:
        errors.append("target_cohort must be 2022")
    rows = payload.get("rows")
    errors.extend(_row_errors(rows, confirmation=True))
    if isinstance(rows, list) and len(rows) != 772:
        errors.append("confirmation row count must be 772")
    if isinstance(rows, list):
        role_counts = {
            role: sum(row.get("role") == role for row in rows if isinstance(row, dict))
            for role in ("hitter", "pitcher")
        }
        if role_counts != {"hitter": 385, "pitcher": 387}:
            errors.append(f"confirmation role counts are invalid: {role_counts}")
        identities = {
            (row.get("mlbam_id"), row.get("role"))
            for row in rows if isinstance(row, dict)
        }
        if len(identities) != len(rows):
            errors.append("confirmation identities must be unique")
    errors.extend(_source_hash_errors(payload.get("source_hashes")))
    errors.extend(_policy_errors(payload.get("source_policy"), confirmation=True))
    return errors


def derive_four_year_outcome(role: str, cohort_year: int, seasons: list[dict]) -> str:
    eligible = _horizon(int(cohort_year), seasons)
    if role == "hitter":
        if any(
            _number(season.get("pa"), "pa") >= 450
            and _number(season.get("ops"), "ops") >= 0.800
            for season in eligible
        ):
            return "star"
        return (
            "role"
            if any(_number(season.get("pa"), "pa") >= 300 for season in eligible)
            else "bust"
        )
    if role == "pitcher":
        if any(
            _number(season.get("ip"), "ip") >= 120
            and _number(season.get("era"), "era") <= 3.75
            for season in eligible
        ):
            return "star"
        return (
            "role"
            if any(_number(season.get("ip"), "ip") >= 50 for season in eligible)
            else "bust"
        )
    raise ValueError(f"unsupported role {role!r}")


def derive_legacy_outcome(role: str, seasons: list[dict]) -> str:
    if role == "hitter":
        if not any(_number(season.get("pa"), "pa") >= 150 for season in seasons):
            return "bust"
        peaks = [season for season in seasons if _number(season.get("pa"), "pa") >= 300]
        peak = max(peaks, key=lambda season: _number(season.get("ops"), "ops"), default=None)
        return (
            "star"
            if peak
            and _number(peak.get("pa"), "pa") >= 450
            and _number(peak.get("ops"), "ops") >= 0.800
            else "role"
        )
    if role == "pitcher":
        if not any(_number(season.get("ip"), "ip") >= 50 for season in seasons):
            return "bust"
        peaks = [season for season in seasons if _number(season.get("ip"), "ip") >= 80]
        peak = min(peaks, key=lambda season: _number(season.get("era"), "era"), default=None)
        return (
            "star"
            if peak
            and _number(peak.get("ip"), "ip") >= 120
            and _number(peak.get("era"), "era") <= 3.75
            else "role"
        )
    raise ValueError(f"unsupported role {role!r}")
