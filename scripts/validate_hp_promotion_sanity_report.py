"""Validate the ValuCast H+P promotion sanity report."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from projections.promotion_sanity import ARTIFACT_NAME, ARTIFACT_PATH, REPORT_VERSION  # noqa: E402


def _valid_generated_at(value: object) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return True


def validate_hp_promotion_sanity_report(
    path: Path = ARTIFACT_PATH,
) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if payload.get("report_version") != REPORT_VERSION:
        problems.append(f"report_version must be {REPORT_VERSION}")
    if not _valid_generated_at(payload.get("generated_at")):
        problems.append("generated_at must be ISO-8601 parseable")

    run = payload.get("run") or {}
    if run.get("source_name") != "valucast":
        problems.append("run.source_name must be valucast")
    if int(run.get("hitter_count") or 0) <= 0:
        problems.append("run.hitter_count must be positive")
    if int(run.get("pitcher_count") or 0) <= 0:
        problems.append("run.pitcher_count must be positive")

    promotion = payload.get("promotion") or {}
    if promotion.get("ready_for_default_promotion") is not False:
        problems.append("promotion.ready_for_default_promotion must be false")
    if promotion.get("human_approval_required_for_default") is not True:
        problems.append("promotion.human_approval_required_for_default must be true")
    if promotion.get("default_source") != "steamer":
        problems.append("promotion.default_source must remain steamer")

    source_policy = payload.get("source_policy") or {}
    for flag in (
        "dd_values_used",
        "dd_ranks_used",
        "public_rankings_used",
        "market_values_used",
        "external_projection_stats_copied",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")

    gates = payload.get("gates")
    if not isinstance(gates, list) or not gates:
        problems.append("gates must be a non-empty list")
    elif any(gate.get("passed") is not True for gate in gates):
        problems.append("all gates must pass before publishing this report")

    validation = payload.get("validation") or {}
    if validation.get("ready_for_opt_in_source") is not True:
        problems.append("validation.ready_for_opt_in_source must be true")
    if validation.get("ready_for_default_promotion") is not False:
        problems.append("validation.ready_for_default_promotion must be false")
    if validation.get("duplicate_identity_count") != 0:
        problems.append("validation.duplicate_identity_count must be zero")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    payload, problems = validate_hp_promotion_sanity_report(args.path)
    if problems:
        print(f"H+P PROMOTION SANITY VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    print(
        "H+P promotion sanity report: "
        f"run={payload['run'].get('run_id')} "
        f"opt_in_ready={payload['validation'].get('ready_for_opt_in_source')} "
        f"default_ready={payload['validation'].get('ready_for_default_promotion')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
