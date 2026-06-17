"""Validate the ValuCast shadow-model promotion report."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.gate import validate_gate  # noqa: E402
from prospects.shadow_promotion import (  # noqa: E402
    ARTIFACT_NAME,
    ARTIFACT_PATH,
    HARNESS_VERSION,
)


def validate_shadow_promotion(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if payload.get("harness_version") != HARNESS_VERSION:
        problems.append(f"harness_version must be {HARNESS_VERSION}")
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
        "feeds_card",
        "feeds_live_rank",
        "feeds_live_value",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")

    models = payload.get("models")
    if not isinstance(models, list) or not models:
        problems.append("models must be a non-empty list")
    else:
        for index, model in enumerate(models, 1):
            for field in ("key", "metric", "archive", "realized_outcome_kind", "gate"):
                if model.get(field) in (None, ""):
                    problems.append(f"model {index} missing {field}")
            gate = model.get("gate")
            if not validate_gate(gate):
                problems.append(f"model {index} ({model.get('key')}) has an invalid gate")
            # The harness's core guarantee: nothing reaches the card without an active gate.
            if model.get("feeds_card") is True and isinstance(gate, dict) and gate.get(
                "status"
            ) != "active":
                problems.append(
                    f"model {index} ({model.get('key')}) feeds the card without an active gate"
                )

    validation = payload.get("validation") or {}
    if validation.get("ready") is not True:
        problems.append(f"validation.ready must be true (blockers: {validation.get('blockers')})")

    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    payload, problems = validate_shadow_promotion(args.path)
    if problems:
        print(f"SHADOW PROMOTION VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    summary = payload["summary"]
    print(
        "shadow promotion: "
        f"models={summary.get('model_count')} "
        f"active={summary.get('active_count')} "
        f"insufficient_sample={summary.get('insufficient_sample_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
