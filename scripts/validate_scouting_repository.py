"""Validate the ValuCast scouting report repository."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scouting.repository import ARTIFACT_NAME, ARTIFACT_PATH, REPOSITORY_VERSION  # noqa: E402
from scouting.voice import handedness_problems  # noqa: E402

PROHIBITED_REPORT_PHRASES = (
    "display-only",
    "artifact",
    "dd-backed",
    "adapter",
)


def validate_scouting_repository(
    path: Path = ARTIFACT_PATH,
) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if payload.get("repository_version") != REPOSITORY_VERSION:
        problems.append(f"repository_version must be {REPOSITORY_VERSION}")
    try:
        datetime.fromisoformat(str(payload.get("generated_at")).replace("Z", "+00:00"))
    except ValueError:
        problems.append("generated_at must be ISO-8601 parseable")

    source_policy = payload.get("source_policy") or {}
    for flag in (
        "dd_values_used",
        "dd_ranks_used",
        "external_rankings_used_for_report",
        "market_values_used_for_report",
        "feeds_live_rank",
        "feeds_live_value",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")
    if source_policy.get("llm_generated") is True:
        if source_policy.get("llm_generated_for_report_text_only") is not True:
            problems.append("source_policy.llm_generated_for_report_text_only must be true")
    elif source_policy.get("llm_generated") is not False:
        problems.append("source_policy.llm_generated must be true or false")

    validation = payload.get("validation") or {}
    if validation.get("ready_for_repository") is not True:
        problems.append("validation.ready_for_repository must be true")
    if validation.get("duplicate_identity_count") != 0:
        problems.append("validation.duplicate_identity_count must be zero")

    reports = payload.get("reports")
    if not isinstance(reports, list) or not reports:
        problems.append("reports must be a non-empty list")
    else:
        seen = set()
        for index, row in enumerate(reports, 1):
            key = (str(row.get("mlbam_id")), str(row.get("role")))
            if key in seen:
                problems.append(f"report {index} duplicate MLBAM+role identity")
            seen.add(key)
            for field in ("mlbam_id", "name", "role", "report", "published_report", "usage"):
                if row.get(field) in (None, "", []):
                    problems.append(f"report {index} missing {field}")
            source = row.get("published_report_source")
            if source not in {"deterministic", "llm"}:
                problems.append(f"report {index} invalid published_report_source")
            elif source == "llm":
                llm_report = row.get("report_llm")
                if (
                    not isinstance(llm_report, dict)
                    or llm_report.get("valid") is not True
                    or llm_report.get("hard_ok") is not True
                ):
                    problems.append(f"report {index} published as llm without valid report_llm")
                elif str(row.get("published_report") or "").strip() != str(
                    llm_report.get("text") or ""
                ).strip():
                    problems.append(f"report {index} llm published_report must match report_llm.text")
            if row.get("usage") != "scouting_repository_context_not_live_rank_or_value":
                problems.append(f"report {index} invalid usage")
            recent_signal = row.get("recent_signal")
            if recent_signal is not None:
                if not isinstance(recent_signal, dict):
                    problems.append(f"report {index} recent_signal must be an object")
                elif recent_signal.get("usage") != "recent_valucast_signal_context_not_live_rank_or_value":
                    problems.append(f"report {index} recent_signal invalid usage")
            card_data_status = row.get("card_data_status")
            if card_data_status is not None:
                if not isinstance(card_data_status, dict):
                    problems.append(f"report {index} card_data_status must be an object")
                elif card_data_status.get("status") not in {"ready", "watch"}:
                    problems.append(f"report {index} card_data_status invalid status")
            lowered = str(row.get("report") or "").lower()
            published_lowered = str(row.get("published_report") or "").lower()
            for phrase in PROHIBITED_REPORT_PHRASES:
                if phrase in lowered:
                    problems.append(f"report {index} contains prohibited phrase {phrase!r}")
                if phrase in published_lowered:
                    problems.append(f"report {index} published_report contains prohibited phrase {phrase!r}")
            for problem in handedness_problems(str(row.get("report") or ""), row):
                problems.append(f"report {index} handedness mismatch: {problem}")
            for problem in handedness_problems(str(row.get("published_report") or ""), row):
                problems.append(f"report {index} published_report handedness mismatch: {problem}")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    payload, problems = validate_scouting_repository(args.path)
    if problems:
        print(f"SCOUTING REPOSITORY VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    print(
        "scouting report repository: "
        f"reports={payload['validation'].get('report_count')} "
        f"ready={payload['validation'].get('ready_for_repository')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
