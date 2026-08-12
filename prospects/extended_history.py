"""Leak-free helpers for the isolated extended prospect-history protocol.

This module deliberately contains no file I/O.  Callers must provide the raw
MiLB candidate rows, MLB season outcomes, and draft facts explicitly so the
research contract cannot overwrite the production dataset by accident.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


LEVEL_CODE = {"A": 1, "A+": 2, "AA": 3, "AAA": 4}
MIN_SAMPLE = {"hitter": 250.0, "pitcher": 50.0}
MAX_AGE = 24.0
HITTER_REACHED_PA = 150.0
HITTER_STAR_PA = 450.0
HITTER_STAR_OPS = 0.800
PITCHER_REACHED_IP = 50.0
PITCHER_STAR_IP = 120.0
PITCHER_STAR_ERA = 3.75
DRAFT_FIELDS = (
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


class MissingOutcomeError(ValueError):
    """Raised when a selected candidate has no completed outcome lookup."""


class SeasonCanonicalizationError(ValueError):
    """Raised when team splits cannot prove one full-season aggregate row."""


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_innings(value: Any) -> float:
    """Convert baseball ``whole.outs`` or true-third decimals consistently."""
    number = _number(value)
    if number is None or number < 0:
        raise ValueError(f"invalid innings value: {value!r}")
    whole = math.floor(number)
    outs_text = str(value).strip().partition(".")[2]
    if not outs_text or not outs_text.strip("0"):
        return float(whole)
    if outs_text in {"1", "2"}:
        return whole + int(outs_text) / 3.0
    fraction = number - whole
    for outs, expected in ((1, 1 / 3), (2, 2 / 3)):
        if math.isclose(fraction, expected, abs_tol=0.001):
            return whole + outs / 3.0
    raise ValueError(f"invalid baseball innings value: {value!r}")


def _sample(record: Mapping[str, Any], role: str) -> float:
    if role == "hitter":
        return _number(record.get("plate_appearances")) or 0.0
    if role == "pitcher":
        value = record.get("innings_pitched")
        return parse_innings(value) if value is not None else 0.0
    return 0.0


def qualifies(record: Mapping[str, Any], role: str) -> bool:
    """Apply the frozen historical age, level, and opportunity screen."""
    age = _number(record.get("age"))
    return bool(
        role in MIN_SAMPLE
        and record.get("role", role) == role
        and str(record.get("level") or "").upper() in LEVEL_CODE
        and record.get("mlbam_id")
        and age is not None
        and age <= MAX_AGE
        and _sample(record, role) >= MIN_SAMPLE[role]
    )


def select_earliest_candidates(rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Select earliest qualifying season and its highest-level row per role.

    Hitter and pitcher identities remain separate so a two-way player may
    contribute one observation for each role.  Duplicate rows at the selected
    season and level resolve to the larger role-specific sample.
    """
    eligible = [
        copy.deepcopy(dict(row))
        for row in rows
        if str(row.get("role") or "") in MIN_SAMPLE
        and qualifies(row, str(row.get("role")))
    ]
    eligible.sort(
        key=lambda row: (
            int(row["cohort_year"]),
            -LEVEL_CODE[str(row["level"]).upper()],
            -_sample(row, str(row["role"])),
            int(row["mlbam_id"]),
            str(row["role"]),
        )
    )
    selected: dict[tuple[int, str], dict] = {}
    for row in eligible:
        row["level"] = str(row["level"]).upper()
        selected.setdefault((int(row["mlbam_id"]), str(row["role"])), row)
    return sorted(
        selected.values(),
        key=lambda row: (
            int(row["cohort_year"]),
            int(row["mlbam_id"]),
            str(row["role"]),
        ),
    )


def _season_ip(season: Mapping[str, Any]) -> float:
    value = season.get("ip", season.get("innings_pitched"))
    return parse_innings(value) if value is not None else 0.0


def canonicalize_mlb_seasons(
    seasons: Iterable[Mapping[str, Any]], role: str
) -> list[dict]:
    """Return exactly one proven aggregate line per MLB season.

    MLB StatsAPI year-by-year responses can contain team splits followed by a
    full-season aggregate.  The aggregate's PA/IP equals the sum of every other
    line for that year.  Ties select the final matching row, which is the API's
    aggregate ordering; a duplicate year without a provable total fails closed.
    """
    if role not in {"hitter", "pitcher"}:
        raise SeasonCanonicalizationError("role must be hitter or pitcher")
    grouped: dict[int, list[dict]] = defaultdict(list)
    for source in seasons:
        if not isinstance(source, Mapping):
            raise SeasonCanonicalizationError("MLB season rows must be mappings")
        row = copy.deepcopy(dict(source))
        try:
            year = int(row["year"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SeasonCanonicalizationError("MLB season year is invalid") from exc
        if year <= 0:
            raise SeasonCanonicalizationError("MLB season year is invalid")
        grouped[year].append(row)

    canonical = []
    for year, year_rows in sorted(grouped.items()):
        if len(year_rows) == 1:
            canonical.append(year_rows[0])
            continue
        samples = [
            (
                (_number(row.get("pa")) or 0.0)
                if role == "hitter"
                else _season_ip(row)
            )
            for row in year_rows
        ]
        aggregates = [
            index
            for index, sample in enumerate(samples)
            if math.isclose(
                sample,
                sum(samples) - sample,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        ]
        if not aggregates:
            raise SeasonCanonicalizationError(
                f"no full-season aggregate for {role} season {year}"
            )
        canonical.append(year_rows[aggregates[-1]])
    return canonical


def outcome_label(
    seasons: Iterable[Mapping[str, Any]],
    role: str,
    cohort_year: int,
    *,
    horizon_years: int = 4,
) -> str:
    """Return the frozen outcome using only years +1 through +horizon."""
    if horizon_years < 1:
        raise ValueError("horizon_years must be positive")
    cohort_year = int(cohort_year)
    post = [
        row
        for row in canonicalize_mlb_seasons(seasons, role)
        if cohort_year < int(row.get("year") or 0) <= cohort_year + horizon_years
    ]
    if role == "hitter":
        reached = any((_number(row.get("pa")) or 0.0) >= HITTER_REACHED_PA for row in post)
        if not reached:
            return "bust"
        return (
            "star"
            if any(
                (_number(row.get("pa")) or 0.0) >= HITTER_STAR_PA
                and (_number(row.get("ops")) or 0.0) >= HITTER_STAR_OPS
                for row in post
            )
            else "role"
        )
    if role == "pitcher":
        reached = any(_season_ip(row) >= PITCHER_REACHED_IP for row in post)
        if not reached:
            return "bust"
        return (
            "star"
            if any(
                _season_ip(row) >= PITCHER_STAR_IP
                and (era := _number(row.get("era"))) is not None
                and era <= PITCHER_STAR_ERA
                for row in post
            )
            else "role"
        )
    raise ValueError("role must be hitter or pitcher")


def draft_for_cohort(fact: Mapping[str, Any], cohort_year: int) -> dict:
    """Return a copy with facts from a future draft masked at the cutoff."""
    result = copy.deepcopy(dict(fact))
    draft_year = _number(result.get("draft_year"))
    if draft_year is None or int(draft_year) <= int(cohort_year):
        return result
    result.update(
        {
            "rule4_drafted": False,
            "draft_year": None,
            "draft_pick_number": None,
            "draft_round": None,
            "signing_bonus": None,
            "pick_value": None,
            "school_type": None,
        }
    )
    return result


def build_labeled_rows(
    candidates: Iterable[Mapping[str, Any]],
    mlb_seasons: Mapping[str, list[dict]],
    draft_facts: Mapping[str, Mapping[str, Any]],
    *,
    horizon_years: int = 4,
) -> list[dict]:
    """Join selected candidates to complete, horizon-limited labels."""
    rows = []
    missing = []
    for candidate in candidates:
        role = str(candidate["role"])
        mlbam_id = int(candidate["mlbam_id"])
        key = f"{mlbam_id}_{role}"
        if key not in mlb_seasons:
            missing.append(key)
            continue
        cohort_year = int(candidate["cohort_year"])
        draft = draft_for_cohort(draft_facts.get(str(mlbam_id), {}), cohort_year)
        rows.append(
            {
                **copy.deepcopy(dict(candidate)),
                **{field: draft.get(field) for field in DRAFT_FIELDS},
                "outcome": outcome_label(
                    mlb_seasons[key],
                    role,
                    cohort_year,
                    horizon_years=horizon_years,
                ),
            }
        )
    if missing:
        raise MissingOutcomeError(
            "missing completed outcome requests: " + ", ".join(sorted(missing))
        )
    return rows


def validate_identity_parity(
    candidates: Iterable[Mapping[str, Any]],
    committed: Iterable[Mapping[str, Any]],
    *,
    cohort_year: int,
) -> dict:
    """Compare a regenerated cohort with the committed identity-role set."""
    year = int(cohort_year)

    def identities(rows: Iterable[Mapping[str, Any]]) -> set[tuple[int, str]]:
        return {
            (int(row["mlbam_id"]), str(row["role"]))
            for row in rows
            if int(row.get("cohort_year", year)) == year
        }

    candidate_ids = identities(candidates)
    committed_ids = identities(committed)

    def display(values: set[tuple[int, str]]) -> list[dict]:
        return [
            {"mlbam_id": mlbam_id, "role": role}
            for mlbam_id, role in sorted(values)
        ]

    extra = display(candidate_ids - committed_ids)
    missing = display(committed_ids - candidate_ids)
    return {
        "status": "ready" if not extra and not missing else "mismatch",
        "cohort_year": year,
        "candidate_count": len(candidate_ids),
        "committed_count": len(committed_ids),
        "extra": extra,
        "missing": missing,
    }
