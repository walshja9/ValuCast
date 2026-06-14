#!/usr/bin/env python3
"""Validate the ValuCast MLB availability contract."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_mlb_availability.json"


def validate_mlb_availability(path: Path = ARTIFACT_PATH) -> list[str]:
    problems = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"{path} unreadable: {exc}"]

    if payload.get("artifact") != "valucast_mlb_availability":
        problems.append("artifact must be valucast_mlb_availability")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")

    source_policy = payload.get("source_policy") or {}
    if source_policy.get("kind") != "official_mlb_transaction_availability":
        problems.append("source_policy.kind must be official_mlb_transaction_availability")
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
    if source_policy.get("official_mlb_transactions_used") is not True:
        problems.append("source_policy.official_mlb_transactions_used must be true")

    validation = payload.get("validation") or {}
    if validation.get("ready_for_mlb_dynasty_layer") is not True:
        problems.append("validation.ready_for_mlb_dynasty_layer must be true")
    if validation.get("duplicate_identity_count", 0) != 0:
        problems.append("duplicate_identity_count must be zero")
    if validation.get("transaction_count", 0) <= 0:
        problems.append("transaction_count must be positive")

    seen = set()
    for idx, row in enumerate(payload.get("profiles") or []):
        mlbam_id = row.get("mlbam_id")
        if mlbam_id in (None, ""):
            problems.append(f"profiles[{idx}].mlbam_id is required")
            continue
        if str(mlbam_id) in seen:
            problems.append(f"duplicate profile for MLBAM {mlbam_id}")
        seen.add(str(mlbam_id))
        if row.get("status") not in {"injured", "rehab", "available"}:
            problems.append(f"profiles[{idx}].status is invalid")
        if row.get("active_injury_risk") != (row.get("status") in {"injured", "rehab"}):
            problems.append(f"profiles[{idx}].active_injury_risk disagrees with status")
        if not row.get("effective_date"):
            problems.append(f"profiles[{idx}].effective_date is required")
        if not row.get("description"):
            problems.append(f"profiles[{idx}].description is required")

    return problems


def main() -> int:
    problems = validate_mlb_availability()
    if problems:
        print("MLB AVAILABILITY VALIDATION FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    validation = payload.get("validation") or {}
    print(
        "MLB availability contract valid: "
        f"profiles={validation.get('profile_count', 0)} "
        f"risk_profiles={validation.get('risk_profile_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
