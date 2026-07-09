#!/usr/bin/env python3
"""Validate the ValuCast MLB active-roster status contract."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_mlb_roster_status.json"


def validate_mlb_roster_status(path: Path = ARTIFACT_PATH) -> list[str]:
    problems = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"{path} unreadable: {exc}"]

    if payload.get("artifact") != "valucast_mlb_roster_status":
        problems.append("artifact must be valucast_mlb_roster_status")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")

    source_policy = payload.get("source_policy") or {}
    if source_policy.get("kind") != "official_mlb_active_roster_status":
        problems.append("source_policy.kind must be official_mlb_active_roster_status")
    for key in (
        "name_matching_used",
        "dd_values_used",
        "dd_ranks_used",
        "external_rankings_used",
        "market_values_used",
        "public_prospect_ranks_used",
    ):
        if source_policy.get(key) is not False:
            problems.append(f"source_policy.{key} must be false")
    if source_policy.get("official_mlb_rosters_used") is not True:
        problems.append("source_policy.official_mlb_rosters_used must be true")

    validation = payload.get("validation") or {}
    if validation.get("ready_for_public_snapshot") is not True:
        problems.append("validation.ready_for_public_snapshot must be true")
    if validation.get("duplicate_identity_count", 0) != 0:
        problems.append("duplicate_identity_count must be zero")
    active_count = validation.get("active_roster_profile_count", 0)
    if active_count <= 0:
        problems.append("active_roster_profile_count must be positive")
    elif active_count < 300:
        problems.append(
            f"active roster has {active_count} profiles (< 300) -- degraded fetch"
        )

    seen = set()
    for idx, row in enumerate(payload.get("profiles") or []):
        mlbam_id = row.get("mlbam_id")
        if mlbam_id in (None, ""):
            problems.append(f"profiles[{idx}].mlbam_id is required")
            continue
        if str(mlbam_id) in seen:
            problems.append(f"duplicate profile for MLBAM {mlbam_id}")
        seen.add(str(mlbam_id))
        if row.get("active_mlb_roster") is not True:
            problems.append(f"profiles[{idx}].active_mlb_roster must be true")
        if not row.get("team_id"):
            problems.append(f"profiles[{idx}].team_id is required")
        if not row.get("status_code"):
            problems.append(f"profiles[{idx}].status_code is required")

    return problems


def main() -> int:
    problems = validate_mlb_roster_status()
    if problems:
        print("MLB ROSTER STATUS VALIDATION FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    validation = payload.get("validation") or {}
    print(
        "MLB roster status contract valid: "
        f"active_profiles={validation.get('active_roster_profile_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
