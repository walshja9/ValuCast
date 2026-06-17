"""Validate the ValuCast playing-time and role tracker."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlb.playing_time_role import ARTIFACT_NAME, ARTIFACT_PATH, TRACKER_VERSION  # noqa: E402


def validate_playing_time_role_tracker(
    path: Path = ARTIFACT_PATH,
) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if payload.get("tracker_version") != TRACKER_VERSION:
        problems.append(f"tracker_version must be {TRACKER_VERSION}")
    try:
        datetime.fromisoformat(str(payload.get("generated_at")).replace("Z", "+00:00"))
    except ValueError:
        problems.append("generated_at must be ISO-8601 parseable")

    source_policy = payload.get("source_policy") or {}
    for flag in (
        "dd_values_used",
        "dd_ranks_used",
        "public_rankings_used",
        "market_values_used",
        "name_based_joins_used",
        "feeds_live_rank",
        "feeds_live_value",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")

    validation = payload.get("validation") or {}
    if validation.get("ready_for_role_context") is not True:
        problems.append("validation.ready_for_role_context must be true")
    if validation.get("duplicate_identity_count") != 0:
        problems.append("validation.duplicate_identity_count must be zero")

    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        problems.append("profiles must be a non-empty list")
    else:
        seen = set()
        for index, row in enumerate(profiles[:200], 1):
            mlbam_id = row.get("mlbam_id")
            key = row.get("identity_key") or f"{mlbam_id}_{row.get('pool')}"
            if not mlbam_id:
                problems.append(f"profile {index} missing mlbam_id")
            if key in seen:
                problems.append(f"profile {index} duplicate identity")
            seen.add(key)
            for field in (
                "name",
                "projected_role",
                "projected_volume",
                "projected_volume_unit",
                "usage",
            ):
                if row.get(field) in (None, "", []):
                    problems.append(f"profile {index} missing {field}")
            if row.get("usage") != "role_context_not_live_rank_or_value":
                problems.append(f"profile {index} invalid usage")
            role_v2 = row.get("role_v2")
            if not isinstance(role_v2, dict):
                problems.append(f"profile {index} missing role_v2")
            else:
                if role_v2.get("feeds_card") is True:
                    problems.append(f"profile {index} role_v2 must not feed the card")
                if not isinstance(role_v2.get("role_probabilities"), dict) or not role_v2.get(
                    "role_probabilities"
                ):
                    problems.append(f"profile {index} role_v2 missing role_probabilities")
                if not isinstance(role_v2.get("volume_forecast"), dict):
                    problems.append(f"profile {index} role_v2 missing volume_forecast")

    v2_summary = payload.get("v2")
    if not isinstance(v2_summary, dict):
        problems.append("v2 summary must be an object")
    else:
        for flag in ("feeds_card", "feeds_live_rank", "feeds_live_value"):
            if v2_summary.get(flag) is not False:
                problems.append(f"v2.{flag} must be false")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    payload, problems = validate_playing_time_role_tracker(args.path)
    if problems:
        print(f"PLAYING-TIME ROLE TRACKER VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    print(
        "playing-time role tracker: "
        f"profiles={payload['validation'].get('profile_count')} "
        f"ready={payload['validation'].get('ready_for_role_context')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
