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
        "llm_generated",
        "feeds_live_rank",
        "feeds_live_value",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")

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
        for index, row in enumerate(reports[:300], 1):
            key = (str(row.get("mlbam_id")), str(row.get("role")))
            if key in seen:
                problems.append(f"report {index} duplicate MLBAM+role identity")
            seen.add(key)
            for field in ("mlbam_id", "name", "role", "report", "usage"):
                if row.get(field) in (None, "", []):
                    problems.append(f"report {index} missing {field}")
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
            for phrase in PROHIBITED_REPORT_PHRASES:
                if phrase in lowered:
                    problems.append(f"report {index} contains prohibited phrase {phrase!r}")
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
