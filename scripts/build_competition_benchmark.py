"""Build the dark, comparison-only Plan 032 competition benchmark artifact."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import hashlib
import json
from math import isfinite
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.competition_benchmark import (  # noqa: E402
    MINIMUM_INDUSTRY_CLAIM_PLAYERS,
    _claim_decision,
    append_cohort,
    build_cohort,
    build_track,
)

PRIVATE_DIR = ROOT / "data" / "private" / "competition"
PRIVATE_SOURCES_PATH = PRIVATE_DIR / "sources.json"
PRIVATE_ARTIFACT_PATH = PRIVATE_DIR / "benchmark.json"
PUBLIC_ARTIFACT_PATH = (
    ROOT / "data" / "validation" / "valucast_competition_evidence.json"
)

_IDENTITY_TOKEN_STOPWORDS = {
    "baseline",
    "benchmark",
    "board",
    "competition",
    "cohort",
    "data",
    "error",
    "four",
    "leading",
    "pitcher",
    "prospect",
    "public",
    "rank",
    "rate",
    "regret",
    "source",
    "track",
    "value",
    "year",
}
_APPROVED_PUBLIC_METRICS = {"forward_rate_error", "realized_value_regret"}
_APPROVED_BENCHMARK_CLASSES = {
    "leading_public_prospect_boards",
    "public_pitcher_skill_benchmarks",
}
_APPROVED_PROTOCOL_VERSIONS = {"032-v1", "proof-v1"}
_APPROVED_PUBLIC_ROLES = {"hitter", "pitcher"}
_APPROVED_PUBLIC_TASKS = {
    "forward pitcher-skill rate error",
    "four-year prospect-selection regret",
}
_COVERAGE_DECIMAL_PLACES = 4
_PRIVATE_EVALUATION_STATUSES = {
    "collecting",
    "no_significant_difference",
    "research_only",
    "validated_superiority",
    "validated_underperformance",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _checked_path(relative: str, expected_hash: str) -> Path:
    path = ROOT / relative
    actual = _sha256(path)
    if actual != expected_hash.upper():
        raise ValueError(f"source drift for {relative}: expected {expected_hash}, got {actual}")
    return path


def _prospect_board_rows(registration: dict) -> tuple[list[dict], list[dict], dict]:
    valucast_path = _checked_path(
        registration["valucast_path"], registration["valucast_sha256"]
    )
    competitor_path = _checked_path(
        registration["competitor_path"], registration["competitor_sha256"]
    )
    valucast = _load(valucast_path)
    competitor = _load(competitor_path)
    valucast_rows = [
        {"mlbam_id": row.get("mlbam_id"), "name": row.get("name"), "rank": row.get("rank")}
        for row in valucast.get("board") or []
    ]
    competitor_rows = [
        {
            "mlbam_id": mlbam_id,
            "name": row.get("name"),
            "rank": row.get("rank"),
        }
        for mlbam_id, row in (competitor.get("players_by_mlbam") or {}).items()
    ]
    sources = {
        "valucast": {
            "path": registration["valucast_path"],
            "sha256": registration["valucast_sha256"],
            "metric": "Prospect Rank v1 served rank",
        },
        "competitor": {
            "name": registration["competitor"],
            "url": registration["competitor_url"],
            "path": registration["competitor_path"],
            "sha256": registration["competitor_sha256"],
            "metric": "published prospect-board rank",
        },
    }
    return valucast_rows, competitor_rows, sources


def _pitcher_skill_rows(registration: dict) -> tuple[list[dict], list[dict], dict]:
    valucast_path = _checked_path(
        registration["valucast_path"], registration["valucast_sha256"]
    )
    valucast = _load(valucast_path)
    competitor_rows = registration["competitor_rows"]
    competitor_ids = {str(row["mlbam_id"]) for row in competitor_rows}
    matched = [
        row
        for row in valucast.get("players") or []
        if str(row.get("mlbam_id") or "") in competitor_ids
    ]
    metric_rows = []
    for row in matched:
        metric = (row.get("value_by_preset") or {}).get("7x7")
        if isinstance(metric, (int, float)):
            metric_rows.append((row, float(metric)))
    metric_rows.sort(key=lambda pair: (-pair[1], str(pair[0]["mlbam_id"])))
    valucast_rows = [
        {
            "mlbam_id": row["mlbam_id"],
            "name": row["name"],
            "rank": rank,
        }
        for rank, (row, _) in enumerate(metric_rows, start=1)
    ]
    sources = {
        "outcome_start": registration["outcome_start"],
        "valucast": {
            "path": registration["valucast_path"],
            "sha256": registration["valucast_sha256"],
            "metric": "ValuCast 7x7 Value order within the published cohort",
        },
        "competitor": {
            "name": registration["competitor"],
            "url": registration["competitor_url"],
            "observed_at": registration["source_observed_at"],
            "screenshot_sha256": registration["source_screenshot_sha256"],
            "note": registration["source_note"],
            "metric": "published pitcher-skill order",
        },
    }
    return valucast_rows, competitor_rows, sources


def _outcomes(source: dict) -> dict:
    path = ROOT / source["outcome_file"]
    return _load(path) if path.exists() else {}


def build_artifact(
    existing: dict | None = None,
    source: dict | None = None,
) -> dict:
    source = source if source is not None else _load(PRIVATE_SOURCES_PATH)
    outcomes = _outcomes(source)
    if existing is None and PRIVATE_ARTIFACT_PATH.exists():
        existing = _load(PRIVATE_ARTIFACT_PATH)
    metadata_fields = (
        "competitor",
        "task",
        "public_source_class",
        "public_task",
        "criteria",
    )
    registry_tracks = {}
    registry_cohorts = {}
    for registration in source["registrations"]:
        metadata = {field: registration[field] for field in metadata_fields}
        prior = registry_tracks.setdefault(registration["track"], metadata)
        if prior != metadata:
            raise ValueError("competition track registry mismatch")
        registry_cohorts.setdefault(registration["track"], set()).add(
            registration["cohort_id"]
        )

    track_data = {}
    for key, persisted in ((existing or {}).get("tracks") or {}).items():
        track = {
            field: deepcopy(persisted.get(field)) for field in metadata_fields
        } | {"cohorts": {}}
        for cohort in persisted.get("cohorts") or []:
            if cohort.get("cohort_id") not in registry_cohorts.get(key, set()):
                raise ValueError("unregistered cohort in persisted competition track")
            append_cohort(track, cohort)
        if key not in registry_tracks or any(
            track[field] != registry_tracks[key][field] for field in metadata_fields
        ):
            raise ValueError("competition track registry mismatch")
        track_data[key] = track
    builders = {
        "prospect_board_rank": _prospect_board_rows,
        "pitcher_skill_rank": _pitcher_skill_rows,
    }
    for registration in source["registrations"]:
        try:
            row_builder = builders[registration["kind"]]
        except KeyError as exc:
            raise ValueError(
                f"unsupported competition registration {registration['kind']}"
            ) from exc
        valucast_rows, competitor_rows, sources = row_builder(registration)
        cohort = build_cohort(
            cohort_id=registration["cohort_id"],
            registered_at=registration["registered_at"],
            track=registration["track"],
            valucast_rows=valucast_rows,
            competitor_rows=competitor_rows,
            sources=sources,
        )
        track = track_data.setdefault(
            registration["track"],
            {
                "competitor": registration["competitor"],
                "task": registration["task"],
                "public_source_class": registration["public_source_class"],
                "public_task": registration["public_task"],
                "criteria": deepcopy(registration["criteria"]),
                "cohorts": {},
            },
        )
        existing_cohort = track["cohorts"].get(registration["cohort_id"])
        if existing_cohort is not None and existing_cohort != cohort:
            raise ValueError("registry cohort mismatch")
        append_cohort(track, cohort)

    tracks = {}
    for key, track in sorted(track_data.items()):
        cohorts = [track["cohorts"][cohort_id] for cohort_id in sorted(track["cohorts"])]
        tracks[key] = {
            "competitor": track["competitor"],
            "task": track["task"],
            "public_source_class": track["public_source_class"],
            "public_task": track["public_task"],
            "criteria": track["criteria"],
            "cohorts": cohorts,
            "evaluation": build_track(
                cohorts, (outcomes.get(key) or {}), track["criteria"]
            ),
        }

    claim_count = sum(
        track["evaluation"]["claim_authorized"] for track in tracks.values()
    )
    return {
        "artifact": "valucast_competition_benchmark",
        "protocol_version": source["protocol_version"],
        "generated_at": source["registered_at"],
        "purpose": "Direct, outcome-grounded ValuCast comparisons on identical players and horizons.",
        "source_policy": {
            "comparison_only": True,
            "feeds_live_rank": False,
            "feeds_live_value": False,
            "feeds_role_watch": False,
            "feeds_pitcher_cap": False,
            "feeds_publication": False,
        },
        "tracks": tracks,
        "validation": {
            "ready": bool(tracks),
            "claim_authorized_count": claim_count,
            "track_count": len(tracks),
        },
    }


def validate_public_artifact(
    payload: dict,
    forbidden_identifiers: list[str],
) -> None:
    def normalize(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()

    def strings(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str):
                    yield normalize(key)
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
        elif isinstance(value, str):
            yield normalize(value)

    terms = set()
    for identifier in forbidden_identifiers:
        normalized = normalize(identifier)
        if not normalized:
            continue
        terms.add(normalized)
        terms.update(
            token
            for token in re.findall(r"[^\W_]+", normalized)
            if len(token) >= 4
            and any(character.isalpha() for character in token)
            and token not in _IDENTITY_TOKEN_STOPWORDS
        )
    leaked = any(
        (
            re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text)
            if len(term) <= 3
            else term in text
        )
        for text in strings(payload)
        for term in terms
    )
    if leaked:
        raise ValueError("private identity leak")

    def fail() -> None:
        raise ValueError("public artifact schema")

    def exact_dict(value, keys: set[str]) -> None:
        if type(value) is not dict or set(value) != keys:
            fail()

    def exact_list(value) -> None:
        if type(value) is not list:
            fail()

    def integer(value, *, positive: bool = False) -> None:
        if type(value) is not int or value < int(positive):
            fail()

    def number(value) -> None:
        if type(value) is int:
            return
        if type(value) is not float or not isfinite(value):
            fail()

    def ratio(value) -> None:
        number(value)
        if not 0.0 <= value <= 1.0:
            fail()

    def coverage_rate(registered, resolved, value) -> None:
        integer(registered)
        integer(resolved)
        ratio(value)
        if resolved > registered:
            fail()
        expected = (
            round(resolved / registered, _COVERAGE_DECIMAL_PLACES)
            if registered
            else 0.0
        )
        if value != expected:
            fail()

    def label(value, allowed: set[str]) -> None:
        if type(value) is not str or value not in allowed:
            fail()

    exact_dict(
        payload,
        {"artifact", "protocol_version", "generated_at", "results", "validation"},
    )
    label(payload["artifact"], {"valucast_competition_evidence"})
    label(payload["protocol_version"], _APPROVED_PROTOCOL_VERSIONS)
    generated_at = payload["generated_at"]
    if type(generated_at) is not str or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", generated_at
    ):
        fail()
    try:
        date.fromisoformat(generated_at)
    except ValueError:
        fail()

    exact_list(payload["results"])
    exact_dict(payload["validation"], {"public_claim_count"})
    integer(payload["validation"]["public_claim_count"])

    for result in payload["results"]:
        exact_dict(
            result,
            {
                "benchmark_class",
                "task",
                "status",
                "coverage",
                "primary",
                "confirmers",
                "segments",
                "cohorts",
            },
        )
        label(result["benchmark_class"], _APPROVED_BENCHMARK_CLASSES)
        label(result["task"], _APPROVED_PUBLIC_TASKS)
        label(result["status"], {"validated_superiority"})

        coverage = result["coverage"]
        exact_dict(coverage, {"registered", "resolved", "rate"})
        coverage_rate(
            coverage["registered"], coverage["resolved"], coverage["rate"]
        )

        primary = result["primary"]
        exact_dict(
            primary,
            {
                "metric",
                "valucast_error",
                "baseline_error",
                "baseline_minus_valucast_error",
                "relative_improvement_pct",
                "error_delta_ci_low",
                "error_delta_ci_high",
            },
        )
        label(primary["metric"], _APPROVED_PUBLIC_METRICS)
        for key in (
            "valucast_error",
            "baseline_error",
            "baseline_minus_valucast_error",
            "relative_improvement_pct",
            "error_delta_ci_low",
            "error_delta_ci_high",
        ):
            number(primary[key])

        confirmers = result["confirmers"]
        exact_dict(
            confirmers,
            {"valucast_top_k_regret", "baseline_top_k_regret"},
        )
        number(confirmers["valucast_top_k_regret"])
        number(confirmers["baseline_top_k_regret"])

        exact_list(result["segments"])
        for segment in result["segments"]:
            exact_dict(
                segment,
                {
                    "role",
                    "resolved",
                    "valucast_error",
                    "baseline_error",
                    "regression_pct",
                },
            )
            label(segment["role"], _APPROVED_PUBLIC_ROLES)
            integer(segment["resolved"])
            number(segment["valucast_error"])
            number(segment["baseline_error"])
            number(segment["regression_pct"])

        exact_list(result["cohorts"])
        for index, cohort in enumerate(result["cohorts"], start=1):
            exact_dict(
                cohort,
                {
                    "cohort_number",
                    "registered",
                    "resolved",
                    "coverage",
                    "valucast_error",
                    "baseline_error",
                    "regression_pct",
                },
            )
            integer(cohort["cohort_number"], positive=True)
            if cohort["cohort_number"] != index:
                fail()
            coverage_rate(
                cohort["registered"], cohort["resolved"], cohort["coverage"]
            )
            number(cohort["valucast_error"])
            number(cohort["baseline_error"])
            number(cohort["regression_pct"])

    if payload["validation"]["public_claim_count"] != len(payload["results"]):
        fail()


def _revalidate_authorized_evaluation(evaluation: dict) -> None:
    def fail() -> None:
        raise ValueError("invalid authorized evidence")

    def integer(value) -> int:
        if type(value) is not int or value < 0:
            fail()
        return value

    def number(value) -> float:
        if type(value) not in (int, float) or not isfinite(value):
            fail()
        return float(value)

    def rate(registered, resolved, value) -> float:
        registered = integer(registered)
        resolved = integer(resolved)
        value = number(value)
        if resolved > registered or not 0.0 <= value <= 1.0:
            fail()
        expected = (
            round(resolved / registered, _COVERAGE_DECIMAL_PLACES)
            if registered
            else 0.0
        )
        if value != expected:
            fail()
        return value

    if (
        evaluation.get("status") != "validated_superiority"
        or evaluation.get("statistical_status") != "validated_superiority"
        or evaluation.get("claim_authorized") is not True
    ):
        fail()
    criteria = evaluation.get("criteria")
    coverage = evaluation.get("coverage")
    primary = evaluation.get("primary")
    confirmers = evaluation.get("confirmers")
    cohorts = evaluation.get("cohorts")
    segments = evaluation.get("segments")
    if any(
        type(value) is not expected
        for value, expected in (
            (criteria, dict),
            (coverage, dict),
            (primary, dict),
            (confirmers, dict),
            (cohorts, list),
            (segments, list),
        )
    ):
        fail()

    minimum_cohorts = criteria.get("minimum_cohorts")
    minimum_players = criteria.get("minimum_unique_players")
    minimum_coverage = criteria.get("minimum_outcome_coverage")
    minimum_improvement = criteria.get("minimum_relative_improvement_pct", 5.0)
    if type(minimum_cohorts) is not int or minimum_cohorts < 0:
        fail()
    if type(minimum_players) is not int or minimum_players < 0:
        fail()
    minimum_coverage = number(minimum_coverage)
    minimum_improvement = number(minimum_improvement)
    if not 0.0 <= minimum_coverage <= 1.0 or minimum_improvement < 0.0:
        fail()
    required_cohorts = max(3, minimum_cohorts)
    required_players = max(MINIMUM_INDUSTRY_CLAIM_PLAYERS, minimum_players)
    required_coverage = max(0.90, minimum_coverage)

    registered = integer(coverage.get("registered"))
    resolved = integer(coverage.get("resolved"))
    completed = integer(coverage.get("completed_cohorts"))
    unique_players = integer(coverage.get("unique_players"))
    overall_rate = rate(registered, resolved, coverage.get("rate"))
    if unique_players > resolved:
        fail()

    cohort_regressions = []
    cohort_registered = cohort_resolved = 0
    for cohort in cohorts:
        if type(cohort) is not dict:
            fail()
        row_registered = integer(cohort.get("registered"))
        row_resolved = integer(cohort.get("resolved"))
        row_rate = rate(row_registered, row_resolved, cohort.get("coverage"))
        if row_registered == 0 or row_rate < required_coverage:
            fail()
        cohort_registered += row_registered
        cohort_resolved += row_resolved
        number(cohort.get("valucast_error"))
        number(cohort.get("competitor_error"))
        cohort_regressions.append(number(cohort.get("regression_pct")))
    if (
        completed != len(cohorts)
        or completed < required_cohorts
        or cohort_registered != registered
        or cohort_resolved != resolved
    ):
        fail()

    segment_regressions = []
    segment_resolved = 0
    roles = set()
    for segment in segments:
        if type(segment) is not dict or segment.get("role") not in _APPROVED_PUBLIC_ROLES:
            fail()
        roles.add(segment["role"])
        segment_resolved += integer(segment.get("resolved"))
        number(segment.get("valucast_error"))
        number(segment.get("competitor_error"))
        segment_regressions.append(number(segment.get("regression_pct")))
    if not segment_regressions or len(roles) != len(segments) or segment_resolved != resolved:
        fail()

    if primary.get("metric") not in _APPROVED_PUBLIC_METRICS:
        fail()
    for key in (
        "valucast_error",
        "competitor_error",
        "competitor_minus_valucast_error",
        "relative_improvement_pct",
        "error_delta_ci_low",
        "error_delta_ci_high",
    ):
        number(primary.get(key))
    valucast_top_k = number(confirmers.get("valucast_top_k_regret"))
    competitor_top_k = number(confirmers.get("competitor_top_k_regret"))

    evidence_ready = (
        unique_players >= required_players
        and completed >= required_cohorts
        and overall_rate >= required_coverage
    )
    decision = _claim_decision(
        evidence_ready=evidence_ready,
        ci_low=primary["error_delta_ci_low"],
        ci_high=primary["error_delta_ci_high"],
        relative_improvement_pct=primary["relative_improvement_pct"],
        cohort_regressions=cohort_regressions,
        segment_regressions=segment_regressions,
        top_k_non_regression=valucast_top_k <= competitor_top_k,
        claim_eligible=True,
        criteria=criteria,
    )
    if decision != (
        "validated_superiority",
        True,
        "validated_superiority",
    ):
        fail()


def build_public_artifact(
    private_artifact: dict,
    forbidden_identifiers: list[str],
) -> dict:
    results = []
    for track in private_artifact.get("tracks", {}).values():
        if not isinstance(track, dict) or not isinstance(
            track.get("evaluation"), dict
        ):
            raise ValueError("invalid authorization state")
        evaluation = track["evaluation"]
        authorized = evaluation.get("claim_authorized")
        status = evaluation.get("status")
        if type(authorized) is not bool or status not in _PRIVATE_EVALUATION_STATUSES:
            raise ValueError("invalid authorization state")
        if authorized is False:
            if status == "validated_superiority":
                raise ValueError("invalid authorization state")
            continue
        if status != "validated_superiority":
            raise ValueError("invalid authorization state")
        primary = evaluation.get("primary")
        if not isinstance(primary, dict) or primary.get(
            "metric"
        ) not in _APPROVED_PUBLIC_METRICS:
            raise ValueError("invalid authorized primary")
        try:
            _revalidate_authorized_evaluation(evaluation)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid authorized evidence") from exc
        try:
            coverage = evaluation["coverage"]
            confirmers = evaluation["confirmers"]
            result = {
                "benchmark_class": track["public_source_class"],
                "task": track["public_task"],
                "status": status,
                "coverage": {
                    "registered": coverage["registered"],
                    "resolved": coverage["resolved"],
                    "rate": coverage["rate"],
                },
                "primary": {
                    "metric": primary["metric"],
                    "valucast_error": primary["valucast_error"],
                    "baseline_error": primary["competitor_error"],
                    "baseline_minus_valucast_error": primary[
                        "competitor_minus_valucast_error"
                    ],
                    "relative_improvement_pct": primary[
                        "relative_improvement_pct"
                    ],
                    "error_delta_ci_low": primary["error_delta_ci_low"],
                    "error_delta_ci_high": primary["error_delta_ci_high"],
                },
                "confirmers": {
                    "valucast_top_k_regret": confirmers[
                        "valucast_top_k_regret"
                    ],
                    "baseline_top_k_regret": confirmers[
                        "competitor_top_k_regret"
                    ],
                },
                "segments": [
                    {
                        "role": row["role"],
                        "resolved": row["resolved"],
                        "valucast_error": row["valucast_error"],
                        "baseline_error": row["competitor_error"],
                        "regression_pct": row["regression_pct"],
                    }
                    for row in evaluation.get("segments", [])
                ],
                "cohorts": [
                    {
                        "cohort_number": index,
                        "registered": row["registered"],
                        "resolved": row["resolved"],
                        "coverage": row["coverage"],
                        "valucast_error": row["valucast_error"],
                        "baseline_error": row["competitor_error"],
                        "regression_pct": row["regression_pct"],
                    }
                    for index, row in enumerate(
                        evaluation.get("cohorts", []), start=1
                    )
                ],
            }
        except (KeyError, TypeError) as exc:
            raise ValueError("malformed authorized evidence") from exc
        results.append(result)
    payload = {
        "artifact": "valucast_competition_evidence",
        "protocol_version": private_artifact["protocol_version"],
        "generated_at": private_artifact["generated_at"],
        "results": results,
        "validation": {"public_claim_count": len(results)},
    }
    validate_public_artifact(payload, forbidden_identifiers)
    return payload


def _private_identifiers(source: dict) -> list[str]:
    keys = ("competitor", "competitor_url", "track", "cohort_id")
    return [
        str(registration[key])
        for registration in source.get("registrations", [])
        for key in keys
        if registration.get(key)
    ]


def _write(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    source = _load(PRIVATE_SOURCES_PATH)
    payload = build_artifact(source=source)
    public_payload = build_public_artifact(
        payload,
        forbidden_identifiers=_private_identifiers(source),
    )
    if args.write:
        _write(payload, PRIVATE_ARTIFACT_PATH)
        _write(public_payload, PUBLIC_ARTIFACT_PATH)
        print(f"wrote {PRIVATE_ARTIFACT_PATH}")
        print(f"wrote {PUBLIC_ARTIFACT_PATH}")
    print(
        " ".join(
            f"{key}={track['evaluation']['status']}"
            for key, track in payload["tracks"].items()
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
