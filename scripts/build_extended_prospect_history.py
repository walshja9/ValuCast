"""Build the isolated extended prospect-history research contract.

The default mode is deliberately outcome-blind.  It replays registered raw
MiLB StatsAPI receipts into exact tracked checkpoints, proves 2014 identity
parity against the committed contract, and writes a separate prepared artifact
plus source hashes.
It also projects the tracked draft-fact cache down to the exact candidate ID
set.  This command has no outcome-reading mode; the registered sealed runner is
the only executable path allowed to acquire labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.extended_history import (  # noqa: E402
    select_earliest_candidates,
    validate_identity_parity,
)


RESEARCH_DIR = ROOT / "data" / "research" / "extended_prospect_history"
PRODUCTION_CONTRACT = ROOT / "data" / "prospects" / "prospect_model_inputs.json"
DEFAULT_PARITY_CONTRACT = RESEARCH_DIR / "parity-2014-identities.json"
DEFAULT_CHECKPOINT_DIR = RESEARCH_DIR / "checkpoints"
DEFAULT_MILB_RESPONSE_DIR = RESEARCH_DIR / "milb-source-responses"
DEFAULT_PREPARED_OUTPUT = RESEARCH_DIR / "prepared.json"
DEFAULT_PREPARE_MANIFEST = RESEARCH_DIR / "prepared-source-manifest.json"
DEFAULT_DRAFT_SOURCE = ROOT / "data" / "prospects" / "raw" / "mlb_draft_facts_cache.json"
DEFAULT_DRAFT_SUPPLEMENT = RESEARCH_DIR / "draft-facts-supplement.json"
DEFAULT_DRAFT_OUTPUT = RESEARCH_DIR / "draft-facts.json"
DEFAULT_COHORT_YEARS = tuple([*range(2009, 2020), 2021, 2022])
PARITY_YEAR = 2014
MILB_STATS_ENDPOINT = "https://statsapi.mlb.com/api/v1/stats"
MILB_SPORT_LEVELS = {11: "AAA", 12: "AA", 13: "A+", 14: "A"}
DRAFT_FACT_FIELDS = (
    "draft_record_known",
    "rule4_drafted",
    "draft_year",
    "draft_pick_number",
    "draft_round",
    "signing_bonus",
    "pick_value",
    "school_type",
    "bats",
    "throws",
)

def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _atomic_write_json(path: Path, payload: Any) -> Path:
    """Write one complete JSON file and publish it with ``os.replace``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _logical_path(path: Path, *, repository_root: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path(repository_root).resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"source/output is outside repository root: {path}") from exc


def _source(
    kind: str,
    path: Path,
    *,
    repository_root: Path,
    **details: Any,
) -> dict:
    resolved = Path(path).resolve()
    return {
        "kind": kind,
        "path": _logical_path(resolved, repository_root=repository_root),
        "sha256": _sha256(resolved),
        **details,
    }


_PARITY_FORBIDDEN_KEYS = frozenset(
    {"outcome", "outcome_label", "historical_mlb_seasons", "mlb_seasons"}
)


def _parity_contains_forbidden_content(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in _PARITY_FORBIDDEN_KEYS
            or _parity_contains_forbidden_content(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_parity_contains_forbidden_content(child) for child in value)
    return False


def _identity_parity_rows(payload: Any, *, source: Path) -> list[dict]:
    if _parity_contains_forbidden_content(payload):
        raise ValueError(f"{source} is not an identity-only parity artifact")
    if (
        not isinstance(payload, Mapping)
        or set(payload)
        != {
            "artifact",
            "schema_version",
            "cohort_year",
            "identity_count",
            "source_policy",
            "rows",
        }
        or payload.get("artifact")
        != "valucast_extended_history_2014_identity_parity"
        or payload.get("schema_version") != 1
        or payload.get("cohort_year") != PARITY_YEAR
    ):
        raise ValueError(f"{source} is not an identity-only parity artifact")
    policy = payload.get("source_policy")
    if policy != {
        "identity_fields_only": True,
        "outcomes_read": False,
        "mlb_seasons_read": False,
    }:
        raise ValueError(f"{source} is not an identity-only parity artifact")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError(f"{source} is not an identity-only parity artifact")
    rows = []
    identities = set()
    for value in raw_rows:
        if not isinstance(value, Mapping) or set(value) != {"mlbam_id", "role"}:
            raise ValueError(f"{source} is not an identity-only parity artifact")
        mlbam_id = value.get("mlbam_id")
        role = value.get("role")
        if (
            not isinstance(mlbam_id, int)
            or isinstance(mlbam_id, bool)
            or mlbam_id <= 0
            or role not in {"hitter", "pitcher"}
        ):
            raise ValueError(f"{source} is not an identity-only parity artifact")
        identity = (mlbam_id, role)
        if identity in identities:
            raise ValueError(f"{source} contains a duplicate parity identity")
        identities.add(identity)
        rows.append({"mlbam_id": mlbam_id, "role": role})
    if payload.get("identity_count") != len(rows):
        raise ValueError(f"{source} identity count does not match its rows")
    return rows


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _guard_destinations(
    output: Path,
    manifest_path: Path,
    draft_output: Path,
    *,
    parity_contract: Path,
    other_sources: Iterable[Path] = (),
) -> None:
    destinations = (Path(output), Path(manifest_path), Path(draft_output))
    protected_contracts = (Path(PRODUCTION_CONTRACT), Path(parity_contract))
    for destination in destinations:
        if any(_same_path(destination, protected) for protected in protected_contracts):
            raise ValueError(f"refusing to overwrite protected contract with {destination}")
    if any(
        _same_path(left, right)
        for index, left in enumerate(destinations)
        for right in destinations[index + 1 :]
    ):
        raise ValueError("prepared, manifest, and draft outputs must use different paths")
    for source in other_sources:
        if any(_same_path(destination, Path(source)) for destination in destinations):
            raise ValueError(f"refusing to overwrite source input {source}")


def _row_year(row: Mapping[str, Any], *, source: Path) -> int:
    try:
        return int(row["cohort_year"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{source} contains a row without a valid cohort_year") from exc


def _milb_query(year: int) -> dict[str, Any]:
    return {
        "stats": "season",
        "season": int(year),
        "sportIds": "11,12,13,14",
        "group": "hitting,pitching",
        "playerPool": "ALL",
        "limit": 10000,
    }


def _stats_number(value: Any, default: float | None = None) -> float | None:
    if value in (None, "", "-.--", ".---"):
        return default
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _stats_int(value: Any, default: int = 0) -> int:
    number = _stats_number(value)
    return default if number is None else int(round(number))


def _stats_rate(value: Any, *, digits: int = 3) -> float | None:
    number = _stats_number(value)
    return None if number is None else round(number, digits)


def _stats_innings(value: Any) -> float:
    text = str(value or "0").split()[0]
    whole, separator, fraction = text.partition(".")
    try:
        whole_value = int(whole)
        outs = int(fraction[:1] or 0) if separator else 0
    except ValueError as exc:
        raise ValueError(f"invalid StatsAPI innings value: {value!r}") from exc
    if whole_value < 0 or outs not in {0, 1, 2}:
        raise ValueError(f"invalid StatsAPI innings value: {value!r}")
    return whole_value + outs / 3.0


def _stats_pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100.0, 1) if denominator else 0.0


def _normalize_player_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("-", " ")
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _milb_base_row(split: Mapping[str, Any], role: str, year: int) -> dict[str, Any]:
    player = split.get("player") or {}
    stat = split.get("stat") or {}
    sport = split.get("sport") or {}
    try:
        sport_id = int(sport["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("MiLB StatsAPI split has an invalid sport ID") from exc
    if sport_id not in MILB_SPORT_LEVELS:
        raise ValueError(f"MiLB StatsAPI split has unregistered sport ID: {sport_id}")
    try:
        split_year = int(split["season"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("MiLB StatsAPI split has an invalid season") from exc
    if split_year != int(year):
        raise ValueError("MiLB StatsAPI split is outside the registered cohort")
    mlbam_id = _stats_int(player.get("id"))
    if mlbam_id <= 0:
        raise ValueError("MiLB StatsAPI split has an invalid player ID")
    name = str(player.get("fullName") or "")
    age_value = _stats_number(stat.get("age"))
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        "normalized_name": _normalize_player_name(name),
        "team": str((split.get("team") or {}).get("name") or ""),
        "level": MILB_SPORT_LEVELS[sport_id],
        "sport_id": sport_id,
        "role": role,
        "age": None if age_value is None else int(round(age_value)),
        "position": str((split.get("position") or {}).get("abbreviation") or ""),
        "cohort_year": int(year),
    }


def _milb_hitter_row(split: Mapping[str, Any], year: int) -> dict[str, Any]:
    stat = split.get("stat") or {}
    at_bats = _stats_int(stat.get("atBats"))
    hits = _stats_int(stat.get("hits"))
    home_runs = _stats_int(stat.get("homeRuns"))
    strikeouts = _stats_int(stat.get("strikeOuts"))
    walks = _stats_int(stat.get("baseOnBalls"))
    plate_appearances = _stats_int(stat.get("plateAppearances"))
    sac_flies = _stats_int(stat.get("sacFlies"))
    avg = _stats_rate(stat.get("avg"))
    slg = _stats_rate(stat.get("slg"))
    babip_denominator = at_bats - strikeouts - home_runs + sac_flies
    return {
        **_milb_base_row(split, "hitter", year),
        "plate_appearances": plate_appearances,
        "at_bats": at_bats,
        "hits": hits,
        "home_runs": home_runs,
        "strikeouts": strikeouts,
        "walks": walks,
        "doubles": _stats_int(stat.get("doubles")),
        "triples": _stats_int(stat.get("triples")),
        "stolen_bases": _stats_int(stat.get("stolenBases")),
        "rbi": _stats_int(stat.get("rbi")),
        "runs": _stats_int(stat.get("runs")),
        "games_played": _stats_int(stat.get("gamesPlayed")),
        "sac_flies": sac_flies,
        "avg": avg,
        "obp": _stats_rate(stat.get("obp")),
        "slg": slg,
        "ops": _stats_rate(stat.get("ops")),
        "iso": round(slg - avg, 3) if slg is not None and avg is not None else None,
        "k_pct": _stats_pct(strikeouts, plate_appearances),
        "bb_pct": _stats_pct(walks, plate_appearances),
        "babip": (
            round((hits - home_runs) / babip_denominator, 3)
            if babip_denominator > 0
            else 0.0
        ),
    }


def _milb_pitcher_row(split: Mapping[str, Any], year: int) -> dict[str, Any]:
    stat = split.get("stat") or {}
    innings = _stats_innings(stat.get("inningsPitched"))
    strikeouts = _stats_int(stat.get("strikeOuts"))
    walks = _stats_int(stat.get("baseOnBalls"))
    batters_faced = _stats_int(stat.get("battersFaced"))
    games_started = _stats_int(stat.get("gamesStarted"))
    games_played = _stats_int(stat.get("gamesPlayed") or stat.get("gamesPitched"))
    hits = _stats_int(stat.get("hits"))
    earned_runs = _stats_int(stat.get("earnedRuns"))
    return {
        **_milb_base_row(split, "pitcher", year),
        "innings_pitched": round(innings, 3),
        "strikeouts": strikeouts,
        "walks": walks,
        "batters_faced": batters_faced,
        "games_played": games_played,
        "games_started": games_started,
        "wins": _stats_int(stat.get("wins")),
        "losses": _stats_int(stat.get("losses")),
        "hits": hits,
        "home_runs": _stats_int(stat.get("homeRuns")),
        "earned_runs": earned_runs,
        "runs": _stats_int(stat.get("runs")),
        "era": _stats_rate(stat.get("era"), digits=2) or 0.0,
        "whip": _stats_rate(stat.get("whip"), digits=2) or 0.0,
        "k_per_9": round(9 * strikeouts / innings, 2) if innings else 0.0,
        "bb_per_9": round(9 * walks / innings, 2) if innings else 0.0,
        "k_bb_pct": _stats_pct(strikeouts - walks, batters_faced),
        "is_starter": (
            games_started / games_played > 0.4 if games_played else False
        ),
    }


def parse_milb_stats_response(payload: Any, *, year: int) -> list[dict]:
    """Replay one registered, outcome-blind MiLB season response."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("stats"), list):
        raise ValueError("MiLB StatsAPI response is invalid")
    if _parity_contains_forbidden_content(payload):
        raise ValueError("MiLB StatsAPI response contains outcome-bearing content")
    groups: dict[str, Mapping[str, Any]] = {}
    for group in payload["stats"]:
        if not isinstance(group, Mapping):
            raise ValueError("MiLB StatsAPI response contains an invalid group")
        group_name = (group.get("group") or {}).get("displayName")
        stats_type = (group.get("type") or {}).get("displayName")
        if group_name not in {"hitting", "pitching"} or stats_type != "season":
            raise ValueError("MiLB StatsAPI response group contract is invalid")
        if group_name in groups or not isinstance(group.get("splits"), list):
            raise ValueError("MiLB StatsAPI response group contract is invalid")
        groups[group_name] = group
    if set(groups) != {"hitting", "pitching"}:
        raise ValueError("MiLB StatsAPI response must contain both registered groups")
    rows = []
    for group_name in ("hitting", "pitching"):
        parser = _milb_hitter_row if group_name == "hitting" else _milb_pitcher_row
        splits = groups[group_name]["splits"]
        for split in splits:
            if not isinstance(split, Mapping):
                raise ValueError("MiLB StatsAPI response contains an invalid split")
            sport = split.get("sport")
            if not isinstance(sport, Mapping):
                raise ValueError("MiLB StatsAPI split has an invalid sport")
            sport_id = _stats_int(sport.get("id"))
            if sport_id not in MILB_SPORT_LEVELS:
                raise ValueError(
                    f"MiLB StatsAPI split has unregistered sport ID: {sport_id}"
                )
        for sport_id in MILB_SPORT_LEVELS:
            rows.extend(
                parser(split, int(year))
                for split in splits
                if _stats_int((split.get("sport") or {}).get("id")) == sport_id
            )
    return rows


def _rows_sha256(rows: list[dict]) -> str:
    return hashlib.sha256(_json_bytes(rows)).hexdigest()


def build_milb_checkpoint(
    *,
    year: int,
    rows: list[dict],
    response_path: Path,
    response_sha256: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Create the exact tracked checkpoint wrapper for a replayed response."""
    return {
        "artifact": "valucast_extended_history_milb_checkpoint",
        "schema_version": 2,
        "cohort_year": int(year),
        "source_receipt": {
            "endpoint": MILB_STATS_ENDPOINT,
            "query": _milb_query(year),
            "status": 200,
            "response_path": _logical_path(
                response_path, repository_root=repository_root
            ),
            "response_sha256": response_sha256,
        },
        "row_count": len(rows),
        "rows_sha256": _rows_sha256(rows),
        "rows": rows,
    }


def _checkpoint_rows(
    payload: Any,
    *,
    year: int,
    source: Path,
    response_dir: Path,
    repository_root: Path,
) -> tuple[list[dict], Path, dict[str, Any]]:
    required = {
        "artifact",
        "schema_version",
        "cohort_year",
        "source_receipt",
        "row_count",
        "rows_sha256",
        "rows",
    }
    if (
        not isinstance(payload, Mapping)
        or set(payload) != required
        or payload.get("artifact") != "valucast_extended_history_milb_checkpoint"
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 2
        or type(payload.get("cohort_year")) is not int
        or payload.get("cohort_year") != int(year)
        or type(payload.get("row_count")) is not int
        or payload.get("row_count", -1) < 0
        or not isinstance(payload.get("rows_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", payload.get("rows_sha256", "")) is None
    ):
        raise ValueError(f"{source} checkpoint schema is invalid")
    receipt = payload.get("source_receipt")
    if not isinstance(receipt, Mapping) or set(receipt) != {
        "endpoint",
        "query",
        "status",
        "response_path",
        "response_sha256",
    }:
        raise ValueError(f"{source} source receipt schema is invalid")
    expected_response = Path(response_dir) / f"milb-{year}.json"
    expected_logical_path = _logical_path(
        expected_response, repository_root=repository_root
    )
    if (
        receipt.get("endpoint") != MILB_STATS_ENDPOINT
        or receipt.get("query") != _milb_query(year)
        or type(receipt.get("status")) is not int
        or receipt.get("status") != 200
        or receipt.get("response_path") != expected_logical_path
    ):
        raise ValueError(f"{source} source receipt contract drift")
    response_sha = receipt.get("response_sha256")
    try:
        actual_response_sha = _sha256(expected_response)
    except OSError as exc:
        raise ValueError(f"{source} source response is unreadable") from exc
    if (
        not isinstance(response_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", response_sha) is None
        or response_sha != actual_response_sha
    ):
        raise ValueError(f"{source} source response hash mismatch")
    try:
        response_payload = _read_json(expected_response)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source} source response is unreadable") from exc
    rebuilt = parse_milb_stats_response(response_payload, year=year)
    stored_rows = payload.get("rows")
    if (
        not isinstance(stored_rows, list)
        or payload.get("row_count") != len(rebuilt)
        or payload.get("rows_sha256") != _rows_sha256(rebuilt)
        or stored_rows != rebuilt
    ):
        raise ValueError(f"{source} parser output mismatch")
    return rebuilt, expected_response, dict(receipt)


def _load_milb_rows(
    *,
    cohort_years: Iterable[int],
    checkpoint_dir: Path,
    response_dir: Path,
    repository_root: Path,
) -> tuple[list[dict], list[dict]]:
    years = sorted({int(year) for year in cohort_years})
    if not years:
        raise ValueError("at least one cohort year is required")
    if PARITY_YEAR not in years:
        raise ValueError("the 2014 parity cohort is required before older data is accepted")

    rows: list[dict] = []
    checkpoint_sources: list[dict] = []
    response_sources: list[dict] = []
    checkpoint_dir = Path(checkpoint_dir)
    response_dir = Path(response_dir)
    for year in years:
        checkpoint = checkpoint_dir / f"milb-{year}.json"
        try:
            checkpoint_payload = _read_json(checkpoint)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"missing or unreadable MiLB checkpoint for cohort {year}") from exc
        fetched_rows, response_path, receipt = _checkpoint_rows(
            checkpoint_payload,
            year=year,
            source=checkpoint,
            response_dir=response_dir,
            repository_root=repository_root,
        )
        rows.extend(fetched_rows)
        checkpoint_sources.append(
            _source(
                "milb_checkpoint",
                checkpoint,
                repository_root=repository_root,
                origin="tracked_checkpoint",
                cohort_year=year,
            )
        )
        response_sources.append(
            _source(
                "milb_statsapi_response",
                response_path,
                repository_root=repository_root,
                origin="registered_raw_response",
                cohort_year=year,
                endpoint=receipt["endpoint"],
                query=receipt["query"],
                status=receipt["status"],
            )
        )
    return rows, [*checkpoint_sources, *response_sources]


def _integer(value: Any, *, field: str, player_id: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"draft fact {player_id} has invalid {field}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"draft fact {player_id} has invalid {field}") from exc
    if str(value).strip() not in {str(number), f"{number}.0"} or number <= 0:
        raise ValueError(f"draft fact {player_id} has invalid {field}")
    return number


def _nonnegative_float(value: Any, *, field: str, player_id: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"draft fact {player_id} has invalid {field}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"draft fact {player_id} has invalid {field}") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"draft fact {player_id} has invalid {field}")
    return number


def _optional_string(
    value: Any,
    *,
    field: str,
    player_id: str,
    allowed: set[str] | None = None,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"draft fact {player_id} has invalid {field}")
    normalized = value.strip()
    if allowed is not None and normalized not in allowed:
        raise ValueError(f"draft fact {player_id} has invalid {field}")
    return normalized


def _normalize_draft_fact(player_id: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"draft fact {player_id} is not an object")
    unknown = set(value) - set(DRAFT_FACT_FIELDS)
    if unknown:
        raise ValueError(f"draft fact {player_id} has unknown fields: {sorted(unknown)}")
    known = value.get("draft_record_known")
    drafted = value.get("rule4_drafted")
    if not isinstance(known, bool) or not isinstance(drafted, bool):
        raise ValueError(f"draft fact {player_id} has invalid boolean fields")
    year = _integer(value.get("draft_year"), field="draft_year", player_id=player_id)
    pick = _integer(
        value.get("draft_pick_number"),
        field="draft_pick_number",
        player_id=player_id,
    )
    round_value = _optional_string(
        value.get("draft_round"), field="draft_round", player_id=player_id
    )
    signing_bonus = _nonnegative_float(
        value.get("signing_bonus"), field="signing_bonus", player_id=player_id
    )
    pick_value = _nonnegative_float(
        value.get("pick_value"), field="pick_value", player_id=player_id
    )
    school_type = _optional_string(
        value.get("school_type"),
        field="school_type",
        player_id=player_id,
        allowed={"college", "high_school"},
    )
    bats = _optional_string(
        value.get("bats"),
        field="bats",
        player_id=player_id,
        allowed={"L", "R", "S"},
    )
    throws = _optional_string(
        value.get("throws"),
        field="throws",
        player_id=player_id,
        allowed={"L", "R", "S"},
    )
    if known is not True:
        raise ValueError(f"draft fact {player_id} is not a completed factual lookup")
    if bats is None or throws is None:
        raise ValueError(f"draft fact {player_id} is missing handedness")
    if drafted and (year is None or pick is None or round_value is None):
        raise ValueError(f"draft fact {player_id} has incomplete drafted fields")
    if not drafted and any(
        item is not None
        for item in (pick, round_value, signing_bonus, pick_value, school_type)
    ):
        raise ValueError(f"draft fact {player_id} has draft fields while undrafted")
    if not drafted:
        # StatsAPI occasionally exposes impossible person.draftYear values for
        # players with no Rule 4 draft record (notably 1979 for MLBAM 564653,
        # born in 1990).  Preserve the raw receipt, but never promote that
        # anomalous person field into the model-ready factual contract.
        year = None
    return {
        "draft_record_known": known,
        "rule4_drafted": drafted,
        "draft_year": year,
        "draft_pick_number": pick,
        "draft_round": round_value,
        "signing_bonus": signing_bonus,
        "pick_value": pick_value,
        "school_type": school_type,
        "bats": bats,
        "throws": throws,
    }


def build_candidate_draft_facts(
    candidates: Iterable[Mapping[str, Any]],
    source_cache: Any,
    supplemental_facts: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Project a complete tracked source cache to the exact candidate ID set."""
    if not isinstance(source_cache, Mapping):
        raise ValueError("draft fact source must be a JSON object")
    candidate_ids = sorted({str(int(row["mlbam_id"])) for row in candidates}, key=int)
    missing = [player_id for player_id in candidate_ids if player_id not in source_cache]
    supplement = {} if supplemental_facts is None else supplemental_facts
    if not isinstance(supplement, Mapping):
        raise ValueError("draft fact supplement must contain a facts object")
    if set(supplement) != set(missing):
        raise ValueError(
            "draft fact supplement must exactly cover IDs missing from the base cache: "
            f"missing_count={len(missing)} supplement_count={len(supplement)}"
        )
    merged = {**source_cache, **supplement}
    return {
        player_id: _normalize_draft_fact(player_id, merged[player_id])
        for player_id in candidate_ids
    }


def _identity_set_sha256(values: Iterable[str]) -> str:
    encoded = "".join(f"{value}\n" for value in sorted(values, key=int)).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _draft_fact_from_statsapi(
    player_id: str,
    *,
    person: Mapping[str, Any],
    pick: Mapping[str, Any] | None,
) -> dict[str, Any]:
    bats = (person.get("batSide") or {}).get("code")
    throws = (person.get("pitchHand") or {}).get("code")
    if bats not in {"L", "R", "S"} or throws not in {"L", "R", "S"}:
        raise ValueError(f"StatsAPI person response lacks handedness: {player_id}")
    if pick is None:
        return {
            "draft_record_known": True,
            "rule4_drafted": False,
            "draft_year": None,
            "draft_pick_number": None,
            "draft_round": None,
            "signing_bonus": None,
            "pick_value": None,
            "school_type": None,
            "bats": bats,
            "throws": throws,
        }
    school_class = (pick.get("school") or {}).get("schoolClass")
    school_type = (
        None
        if school_class is None
        else "high_school"
        if school_class == "HS"
        else "college"
    )
    return {
        "draft_record_known": True,
        "rule4_drafted": True,
        "draft_year": int(pick["year"]),
        "draft_pick_number": int(pick["pickNumber"]),
        "draft_round": str(pick["pickRound"]),
        "signing_bonus": None,
        "pick_value": None,
        "school_type": school_type,
        "bats": bats,
        "throws": throws,
    }


def _audit_supplement_responses(
    *,
    receipts: list[Any],
    missing_ids: set[str],
    repository_root: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict]]:
    draft_picks: dict[str, dict[str, Any]] = {}
    people: dict[str, dict[str, Any]] = {}
    draft_years: set[int] = set()
    queried_people: set[str] = set()
    sources = []
    root = repository_root.resolve()
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise ValueError("draft fact supplement receipt is invalid")
        endpoint = receipt.get("endpoint")
        query = receipt.get("query")
        fetched_at = receipt.get("fetched_at")
        response_path_value = receipt.get("response_path")
        declared_sha = receipt.get("response_sha256")
        if (
            not isinstance(endpoint, str)
            or not isinstance(query, Mapping)
            or not isinstance(fetched_at, str)
            or not fetched_at
            or not isinstance(response_path_value, str)
            or Path(response_path_value).is_absolute()
        ):
            raise ValueError("draft fact supplement receipt metadata is invalid")
        response_path = (root / response_path_value).resolve()
        try:
            response_path.relative_to(root)
        except ValueError as exc:
            raise ValueError("draft response path escapes repository root") from exc
        if not response_path.is_file() or _sha256(response_path) != declared_sha:
            raise ValueError("draft fact supplement raw response hash mismatch")
        payload = _read_json(response_path)
        if endpoint.startswith("https://statsapi.mlb.com/api/v1/draft/"):
            if query:
                raise ValueError("draft endpoint receipt must have an empty query")
            try:
                year = int(endpoint.rsplit("/", 1)[1])
            except ValueError as exc:
                raise ValueError("draft endpoint receipt year is invalid") from exc
            if not 2002 <= year <= 2012 or year in draft_years:
                raise ValueError("draft endpoint receipt set is invalid")
            draft_years.add(year)
            drafts = payload.get("drafts") if isinstance(payload, Mapping) else None
            rounds = drafts.get("rounds") if isinstance(drafts, Mapping) else None
            if not isinstance(rounds, list):
                raise ValueError("draft StatsAPI response is invalid")
            for round_record in rounds:
                for pick in (round_record or {}).get("picks") or []:
                    person = pick.get("person") or {}
                    player_id = str(person.get("id") or "")
                    if player_id not in missing_ids:
                        continue
                    choice = (int(pick["year"]), int(pick["pickNumber"]))
                    prior = draft_picks.get(player_id)
                    if prior is None or choice >= (
                        int(prior["year"]),
                        int(prior["pickNumber"]),
                    ):
                        draft_picks[player_id] = dict(pick)
        elif endpoint == "https://statsapi.mlb.com/api/v1/people":
            if set(query) != {"personIds"} or not isinstance(
                query.get("personIds"), str
            ):
                raise ValueError("people endpoint receipt query is invalid")
            requested = set(query["personIds"].split(","))
            response_people = payload.get("people") if isinstance(payload, Mapping) else None
            if not isinstance(response_people, list):
                raise ValueError("people StatsAPI response is invalid")
            returned = {str(person.get("id") or "") for person in response_people}
            if returned != requested or not returned <= missing_ids:
                raise ValueError("people endpoint response identity mismatch")
            if queried_people & returned:
                raise ValueError("people endpoint receipts overlap")
            queried_people.update(returned)
            people.update({str(person["id"]): dict(person) for person in response_people})
        else:
            raise ValueError("supplement receipt endpoint is not draft/people factual data")
        sources.append(
            _source(
                "draft_facts_statsapi_response",
                response_path,
                repository_root=repository_root,
                endpoint=endpoint,
                query=dict(query),
                fetched_at=fetched_at,
            )
        )
    if draft_years != set(range(2002, 2013)):
        raise ValueError("draft supplement must bind every registered draft year")
    undrafted = missing_ids - set(draft_picks)
    if queried_people != undrafted:
        raise ValueError("people receipts must exactly cover undrafted candidate IDs")
    rebuilt = {}
    for player_id in sorted(missing_ids, key=int):
        pick = draft_picks.get(player_id)
        person = (pick or {}).get("person") or people.get(player_id)
        if not isinstance(person, Mapping):
            raise ValueError(f"missing StatsAPI person fact: {player_id}")
        rebuilt[player_id] = _draft_fact_from_statsapi(
            player_id,
            person=person,
            pick=pick,
        )
    return rebuilt, sources


def _load_draft_inputs(
    *,
    candidates: list[dict],
    draft_source: Path,
    draft_supplement: Path,
    repository_root: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict]]:
    base = _read_json(draft_source)
    if not isinstance(base, Mapping):
        raise ValueError("tracked draft fact source must contain a JSON object")
    candidate_ids = {str(int(row["mlbam_id"])) for row in candidates}
    missing = sorted(candidate_ids - set(base), key=int)
    supplemental_facts: Mapping[str, Any] = {}
    sources = [
        _source(
            "draft_facts_base",
            draft_source,
            repository_root=repository_root,
            candidate_covered_count=len(candidate_ids & set(base)),
        )
    ]
    if missing:
        supplement = _read_json(draft_supplement)
        if (
            not isinstance(supplement, Mapping)
            or supplement.get("artifact")
            != "valucast_extended_history_draft_fact_supplement"
            or supplement.get("schema_version") != 1
        ):
            raise ValueError("draft fact supplement contract is invalid")
        supplemental_facts = supplement.get("facts")
        if not isinstance(supplemental_facts, Mapping):
            raise ValueError("draft fact supplement is missing facts")
        if supplement.get("candidate_ids_sha256") != _identity_set_sha256(missing):
            raise ValueError("draft fact supplement candidate identity hash mismatch")
        supplemental_drafted = sum(
            fact.get("rule4_drafted") is True
            for fact in supplemental_facts.values()
            if isinstance(fact, Mapping)
        )
        if (
            supplement.get("candidate_count") != len(missing)
            or supplement.get("drafted_count") != supplemental_drafted
            or supplement.get("people_only_count")
            != len(missing) - supplemental_drafted
            or supplement.get("draft_years") != list(range(2002, 2013))
        ):
            raise ValueError("draft fact supplement audit counts are invalid")
        receipts = supplement.get("receipts")
        if not isinstance(receipts, list) or not receipts:
            raise ValueError("draft fact supplement has no source receipts")
        sources.append(
            _source(
                "draft_facts_supplement",
                draft_supplement,
                repository_root=repository_root,
                candidate_count=len(supplemental_facts),
            )
        )
        rebuilt, raw_sources = _audit_supplement_responses(
            receipts=receipts,
            missing_ids=set(missing),
            repository_root=repository_root,
        )
        normalized_declared = {
            player_id: _normalize_draft_fact(player_id, fact)
            for player_id, fact in supplemental_facts.items()
        }
        if normalized_declared != rebuilt:
            raise ValueError("draft supplement facts do not match raw StatsAPI responses")
        sources.extend(raw_sources)
    facts = build_candidate_draft_facts(candidates, base, supplemental_facts)
    return facts, sources


def _manifest(
    *,
    mode: str,
    sources: list[dict],
    output: Path,
    draft_output: Path,
    repository_root: Path,
    identity_parity: Mapping[str, Any],
) -> dict:
    return {
        "artifact": "valucast_extended_prospect_history_source_manifest",
        "schema_version": 2,
        "mode": mode,
        "sources": sources,
        "output": {
            "path": _logical_path(output, repository_root=repository_root),
            "sha256": _sha256(output),
        },
        "draft_facts_output": {
            "path": _logical_path(draft_output, repository_root=repository_root),
            "sha256": _sha256(draft_output),
        },
        "identity_parity": dict(identity_parity),
    }


def prepare_history(
    *,
    cohort_years: Iterable[int],
    parity_contract: Path = DEFAULT_PARITY_CONTRACT,
    checkpoint_dir: Path = DEFAULT_CHECKPOINT_DIR,
    response_dir: Path = DEFAULT_MILB_RESPONSE_DIR,
    output: Path = DEFAULT_PREPARED_OUTPUT,
    manifest_path: Path = DEFAULT_PREPARE_MANIFEST,
    draft_source: Path = DEFAULT_DRAFT_SOURCE,
    draft_supplement: Path = DEFAULT_DRAFT_SUPPLEMENT,
    draft_output: Path = DEFAULT_DRAFT_OUTPUT,
    repository_root: Path = ROOT,
) -> dict:
    """Build an outcome-blind candidate contract after exact 2014 parity."""
    parity_contract = Path(parity_contract)
    checkpoint_dir = Path(checkpoint_dir)
    response_dir = Path(response_dir)
    output = Path(output)
    manifest_path = Path(manifest_path)
    draft_source = Path(draft_source)
    draft_supplement = Path(draft_supplement)
    draft_output = Path(draft_output)
    repository_root = Path(repository_root)
    _guard_destinations(
        output,
        manifest_path,
        draft_output,
        parity_contract=parity_contract,
        other_sources=(
            checkpoint_dir,
            response_dir,
            draft_source,
            draft_supplement,
        ),
    )

    raw_rows, sources = _load_milb_rows(
        cohort_years=cohort_years,
        checkpoint_dir=checkpoint_dir,
        response_dir=response_dir,
        repository_root=repository_root,
    )
    parity_rows = _identity_parity_rows(
        _read_json(parity_contract), source=parity_contract
    )
    sources.append(
        _source(
            "identity_parity_contract",
            parity_contract,
            repository_root=repository_root,
        )
    )

    parity_candidates = select_earliest_candidates(
        row for row in raw_rows if _row_year(row, source=Path("MiLB input")) == PARITY_YEAR
    )
    parity = validate_identity_parity(
        parity_candidates,
        parity_rows,
        cohort_year=PARITY_YEAR,
    )
    if parity["status"] != "ready":
        raise ValueError(
            "2014 identity parity mismatch: "
            f"extra={len(parity['extra'])} missing={len(parity['missing'])}"
        )

    candidates = select_earliest_candidates(raw_rows)
    for candidate in candidates:
        # A prepared contract cannot smuggle a pre-computed label past the sealed gate.
        candidate.pop("outcome", None)
    years = sorted({int(row["cohort_year"]) for row in candidates})
    draft_facts, draft_sources = _load_draft_inputs(
        candidates=candidates,
        draft_source=draft_source,
        draft_supplement=draft_supplement,
        repository_root=repository_root,
    )
    sources.extend(draft_sources)
    payload = {
        "artifact": "valucast_extended_prospect_history_prepared",
        "schema_version": 2,
        "mode": "prepare_only",
        "source_policy": {
            "separate_research_contract": True,
            "production_contract_overwritten": False,
            "outcomes_read": False,
            "labels_scored": False,
        },
        "cohort_years": years,
        "candidate_count": len(candidates),
        "identity_parity": parity,
        "rows": candidates,
    }
    _atomic_write_json(output, payload)
    _atomic_write_json(draft_output, draft_facts)
    _atomic_write_json(
        manifest_path,
        _manifest(
            mode="prepare_only",
            sources=sources,
            output=output,
            draft_output=draft_output,
            repository_root=repository_root,
            identity_parity=parity,
        ),
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="prepare candidates and parity evidence without reading outcomes (default)",
    )
    parser.add_argument("--cohort-year", action="append", type=int, dest="cohort_years")
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument(
        "--milb-response-dir", type=Path, default=DEFAULT_MILB_RESPONSE_DIR
    )
    parser.add_argument(
        "--parity-contract", type=Path, default=DEFAULT_PARITY_CONTRACT
    )
    parser.add_argument("--draft-source", type=Path, default=DEFAULT_DRAFT_SOURCE)
    parser.add_argument("--draft-supplement", type=Path, default=DEFAULT_DRAFT_SUPPLEMENT)
    parser.add_argument("--draft-output", type=Path, default=DEFAULT_DRAFT_OUTPUT)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    output = args.output or DEFAULT_PREPARED_OUTPUT
    manifest = args.manifest or DEFAULT_PREPARE_MANIFEST
    payload = prepare_history(
        cohort_years=args.cohort_years or DEFAULT_COHORT_YEARS,
        parity_contract=args.parity_contract,
        checkpoint_dir=args.checkpoint_dir,
        response_dir=args.milb_response_dir,
        output=output,
        manifest_path=manifest,
        draft_source=args.draft_source,
        draft_supplement=args.draft_supplement,
        draft_output=args.draft_output,
        repository_root=args.repository_root,
    )
    print(
        "extended prospect history prepared: "
        f"candidates={payload['candidate_count']} parity=ready -> {output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
