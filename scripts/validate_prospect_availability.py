"""Validate the ValuCast prospect availability artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_availability.json"


def validate_prospect_availability(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems = []
    if payload.get("artifact") != "valucast_prospect_availability":
        problems.append("artifact must be valucast_prospect_availability")
    if not payload.get("artifact_version"):
        problems.append("artifact_version is required")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")

    source_policy = payload.get("source_policy")
    if not isinstance(source_policy, dict):
        problems.append("source_policy must be an object")
    else:
        for flag in (
            "dd_values_used",
            "dd_ranks_used",
            "external_rankings_used",
            "market_values_used",
        ):
            if source_policy.get(flag) is not False:
                problems.append(f"source_policy.{flag} must be false")

    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        problems.append("profiles must be a non-empty list")
        return payload, problems

    identities = []
    risk_count = 0
    max_discount = payload.get("max_risk_discount", 0.12)
    for index, row in enumerate(profiles):
        if not isinstance(row, dict):
            problems.append(f"profiles[{index}] must be an object")
            continue
        if row.get("mlbam_id") in (None, ""):
            problems.append(f"profiles[{index}].mlbam_id is required")
        if row.get("role") not in {"hitter", "pitcher"}:
            problems.append(f"profiles[{index}].role must be hitter or pitcher")
        if row.get("present") is not True:
            problems.append(f"profiles[{index}].present must be true")
        if row.get("risk_basis") in (None, ""):
            problems.append(f"profiles[{index}].risk_basis is required")
        discount = row.get("risk_discount")
        if not isinstance(discount, (int, float)) or isinstance(discount, bool):
            problems.append(f"profiles[{index}].risk_discount must be numeric")
        elif discount < 0 or discount > max_discount:
            problems.append(f"profiles[{index}].risk_discount is out of bounds")
        elif discount > 0:
            risk_count += 1
        identities.append((str(row.get("mlbam_id")), row.get("role")))

    if len(identities) != len(set(identities)):
        problems.append("duplicate MLBAM+role identities")
    if payload.get("profile_count") != len(profiles):
        problems.append("profile_count does not match profiles")
    if payload.get("risk_profile_count") != risk_count:
        problems.append("risk_profile_count does not match profiles")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        problems.append("summary must be an object")
    elif summary.get("risk_profile_count") != risk_count:
        problems.append("summary.risk_profile_count does not match profiles")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()

    payload, problems = validate_prospect_availability(args.path)
    if problems:
        print(f"PROSPECT AVAILABILITY VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    print(
        "prospect availability: "
        f"profiles={payload.get('profile_count')} "
        f"risk={payload.get('risk_profile_count')} "
        f"version={payload.get('artifact_version')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
