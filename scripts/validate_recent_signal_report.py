"""Validate the ValuCast recent prospect signal report."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.recent_signal import ARTIFACT_NAME, ARTIFACT_PATH, SIGNAL_VERSION  # noqa: E402


def validate_recent_signal_report(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]
    problems: list[str] = []
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if payload.get("signal_version") != SIGNAL_VERSION:
        problems.append(f"signal_version must be {SIGNAL_VERSION}")
    try:
        datetime.fromisoformat(str(payload.get("generated_at")).replace("Z", "+00:00"))
    except ValueError:
        problems.append("generated_at must be ISO-8601 parseable")
    if payload.get("status") not in {"blocked", "candidate_ready"}:
        problems.append("status must be blocked or candidate_ready")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        problems.append("summary must be an object")
    else:
        for field in ("signal_count", "top_mover_count", "archive_day_span"):
            if not isinstance(summary.get(field), int):
                problems.append(f"summary.{field} must be an integer")
    validation = payload.get("validation")
    if not isinstance(validation, dict):
        problems.append("validation must be an object")
    elif not isinstance(validation.get("ready_for_recent_signal"), bool):
        problems.append("validation.ready_for_recent_signal must be boolean")
    signals = payload.get("signals")
    if not isinstance(signals, list):
        problems.append("signals must be a list")
    else:
        seen = set()
        for index, row in enumerate(signals[:300], 1):
            if not isinstance(row, dict):
                problems.append(f"signal {index} must be an object")
                continue
            for field in ("identity_key", "mlbam_id", "role", "name", "prospect_rank", "movement_label", "usage"):
                if row.get(field) in (None, "", []):
                    problems.append(f"signal {index} missing {field}")
            if row.get("identity_key") in seen:
                problems.append(f"signal {index} duplicate identity_key")
            seen.add(row.get("identity_key"))
            if row.get("usage") != "recent_valucast_signal_context_not_live_rank_or_value":
                problems.append(f"signal {index} invalid usage")
    source_policy = payload.get("source_policy") or {}
    for flag in (
        "feeds_model_score",
        "feeds_public_rank",
        "feeds_buy_score",
        "dd_values_used",
        "dd_ranks_used",
        "external_rankings_used",
        "market_values_used",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    payload, problems = validate_recent_signal_report(args.path)
    if problems:
        print(f"RECENT SIGNAL REPORT VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    print(
        "recent signal report: "
        f"status={payload.get('status')} "
        f"signals={payload.get('summary', {}).get('signal_count')} "
        f"archive_days={payload.get('summary', {}).get('archive_day_span')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
