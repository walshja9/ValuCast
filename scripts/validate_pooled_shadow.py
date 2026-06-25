"""Validate the ValuCast pooled-line prospect shadow artifact."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.pooled_shadow import ARTIFACT_NAME, ARTIFACT_PATH, SHADOW_VERSION  # noqa: E402
from prospects.model import POOLED_SHADOW_USAGE  # noqa: E402

EXPECTED_FALSE_SOURCE_FLAGS = (
    "feeds_model_score",
    "feeds_public_rank",
    "feeds_buy_score",
    "feeds_live_valucast_rank",
    "feeds_live_dd_value",
    "dd_values_used",
    "external_rankings_used",
    "market_values_used",
)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_pooled_shadow(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]
    problems: list[str] = []
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if payload.get("shadow_version") != SHADOW_VERSION:
        problems.append(f"shadow_version must be {SHADOW_VERSION}")
    try:
        datetime.fromisoformat(str(payload.get("generated_at")).replace("Z", "+00:00"))
    except ValueError:
        problems.append("generated_at must be ISO-8601 parseable")
    if payload.get("status") not in {"blocked", "candidate_ready"}:
        problems.append("status must be blocked or candidate_ready")

    source_policy = payload.get("source_policy")
    if not isinstance(source_policy, dict):
        problems.append("source_policy must be an object")
    else:
        if source_policy.get("kind") != "valucast_pooled_line_shadow":
            problems.append("source_policy.kind must be valucast_pooled_line_shadow")
        for key in EXPECTED_FALSE_SOURCE_FLAGS:
            if source_policy.get(key) is not False:
                problems.append(f"source_policy.{key} must be false")
        for key, value in source_policy.items():
            if key in EXPECTED_FALSE_SOURCE_FLAGS:
                continue
            if key.startswith("feeds_") or key.endswith("_used"):
                if value is not False:
                    problems.append(f"source_policy.{key} must be false")

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        problems.append("summary must be an object")
    else:
        for field in (
            "scored_count",
            "shadowed_count",
            "multi_level_count",
            "nontrivial_delta_count",
        ):
            if not isinstance(summary.get(field), int) or isinstance(
                summary.get(field), bool
            ):
                problems.append(f"summary.{field} must be an integer")
        for field in ("median_abs_delta", "p90_abs_delta"):
            if not _is_number(summary.get(field)):
                problems.append(f"summary.{field} must be numeric")
        if not isinstance(summary.get("largest_movers"), list):
            problems.append("summary.largest_movers must be a list")

    validation = payload.get("validation")
    if not isinstance(validation, dict):
        problems.append("validation must be an object")
    else:
        if not isinstance(validation.get("ready"), bool):
            problems.append("validation.ready must be boolean")
        if not isinstance(validation.get("blockers"), list):
            problems.append("validation.blockers must be a list")

    shadows = payload.get("shadows")
    if not isinstance(shadows, list):
        problems.append("shadows must be a list")
    else:
        for index, row in enumerate(shadows, 1):
            if not isinstance(row, dict):
                problems.append(f"shadow {index} must be an object")
                continue
            if row.get("usage") != POOLED_SHADOW_USAGE:
                problems.append(f"shadow {index} invalid usage")
            n_levels = row.get("n_levels")
            if not isinstance(n_levels, int) or isinstance(n_levels, bool):
                problems.append(f"shadow {index} n_levels must be an integer")
                continue
            if n_levels >= 2:
                served_sample = row.get("served_sample")
                pooled_sample = row.get("pooled_sample")
                if not _is_number(served_sample) or not _is_number(pooled_sample):
                    problems.append(
                        f"shadow {index} served_sample and pooled_sample must be numeric"
                    )
                elif pooled_sample < served_sample:
                    problems.append(
                        f"shadow {index} pooled_sample must be >= served_sample"
                    )
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    payload, problems = validate_pooled_shadow(args.path)
    if problems:
        print(f"POOLED SHADOW VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    summary = payload.get("summary", {})
    print(
        "pooled shadow: "
        f"status={payload.get('status')} "
        f"scored={summary.get('scored_count')} "
        f"shadowed={summary.get('shadowed_count')} "
        f"multi_level={summary.get('multi_level_count')} "
        f"nontrivial_delta={summary.get('nontrivial_delta_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
