"""Validate the ValuCast MLB projection scorecard artifact."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCORECARD_PATH = ROOT / "data" / "validation" / "methodology_scorecard.json"
EXTERNAL_COMPARISON_TOKENS = (
    "steamer",
    "zips",
    "atc",
    "the bat",
    "batx",
    "public rank",
    "market value",
)


def _is_numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_generated_at(payload: dict, problems: list[str]) -> None:
    value = payload.get("generated_at")
    if value is None:
        problems.append("generated_at is required")
        return
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        problems.append("generated_at must be ISO-8601 parseable")


def _validate_projection_block(
    payload: dict,
    name: str,
    expected_baseline: str,
    problems: list[str],
) -> None:
    block = payload.get(name)
    if not isinstance(block, dict):
        problems.append(f"{name} must be a dict")
        return

    baseline = block.get("baseline")
    if baseline != expected_baseline:
        problems.append(
            f"{name}.baseline must be {expected_baseline!r}, got {baseline!r}"
        )
    if not _is_numeric(block.get("aggregate_mae_ratio")):
        problems.append(f"{name}.aggregate_mae_ratio must be numeric")
    sample_size = block.get("sample_size")
    if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size <= 0:
        problems.append(f"{name}.sample_size must be a positive integer")
    if not _is_numeric(block.get("correlation_win_rate")):
        problems.append(f"{name}.correlation_win_rate must be numeric")
    per_stat = block.get("per_stat_mae_ratio")
    if not isinstance(per_stat, dict) or not per_stat:
        problems.append(f"{name}.per_stat_mae_ratio must be a non-empty dict")


def _walk_external_claims(
    value: object,
    problems: list[str],
    path: str = "$",
    in_not_shipped: bool = False,
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            _walk_external_claims(
                child,
                problems,
                child_path,
                in_not_shipped or key == "not_shipped",
            )
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            _walk_external_claims(
                child,
                problems,
                f"{path}[{index}]",
                in_not_shipped,
            )
        return

    if not isinstance(value, str) or in_not_shipped:
        return

    lowered = value.lower()
    for token in EXTERNAL_COMPARISON_TOKENS:
        if token in lowered:
            problems.append(
                f"{path} must not contain external comparison token {token!r}"
            )
            return


def validate_projection_scorecard(
    path: Path = SCORECARD_PATH,
) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    if not isinstance(payload, dict):
        return None, ["scorecard payload must be a JSON object"]

    problems: list[str] = []
    _validate_generated_at(payload, problems)
    if not str(payload.get("version") or "").strip():
        problems.append("version is required")
    _validate_projection_block(payload, "hitting", "classic Marcel", problems)
    _validate_projection_block(payload, "pitching", "persistence", problems)
    if not isinstance(payload.get("not_shipped"), list):
        problems.append("not_shipped must be a list")
    _walk_external_claims(payload, problems)
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=SCORECARD_PATH)
    args = parser.parse_args()

    payload, problems = validate_projection_scorecard(args.path)
    if problems:
        print(f"PROJECTION SCORECARD VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    hitting = payload.get("hitting") or {}
    pitching = payload.get("pitching") or {}
    print(
        "projection scorecard: "
        f"version={payload.get('version')} "
        f"hitting={hitting.get('aggregate_mae_ratio')} "
        f"pitching={pitching.get('aggregate_mae_ratio')} "
        f"generated_at={payload.get('generated_at')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
