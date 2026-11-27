"""Validate the ValuCast prospect-card data audit artifact."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.card_data_audit import ARTIFACT_NAME, ARTIFACT_PATH, AUDIT_VERSION  # noqa: E402


def validate_prospect_card_data_audit(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]
    problems: list[str] = []
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if payload.get("audit_version") != AUDIT_VERSION:
        problems.append(f"audit_version must be {AUDIT_VERSION}")
    try:
        datetime.fromisoformat(str(payload.get("generated_at")).replace("Z", "+00:00"))
    except ValueError:
        problems.append("generated_at must be ISO-8601 parseable")
    if payload.get("status") not in {"blocked", "candidate_ready"}:
        problems.append("status must be blocked or candidate_ready")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        problems.append("metrics must be an object")
    else:
        for field in (
            "prospect_count",
            "top50_count",
            "top200_count",
            "top50_watch_count",
            "top200_watch_count",
            "duplicate_identity_count",
            "missing_identity_count",
            "missing_stat_line_count",
            "active_mlb_level_count",
        ):
            if not isinstance(metrics.get(field), int):
                problems.append(f"metrics.{field} must be an integer")
    validation = payload.get("validation")
    if not isinstance(validation, dict):
        problems.append("validation must be an object")
    elif not isinstance(validation.get("ready_for_cards"), bool):
        problems.append("validation.ready_for_cards must be boolean")
    if not isinstance(payload.get("cards"), list):
        problems.append("cards must be a list")
    else:
        seen = set()
        for index, row in enumerate(payload["cards"][:250], 1):
            if not isinstance(row, dict):
                problems.append(f"card {index} must be an object")
                continue
            if row.get("identity_key"):
                if row["identity_key"] in seen:
                    problems.append(f"card {index} duplicate identity_key")
                seen.add(row["identity_key"])
            if row.get("status") not in {"ready", "watch"}:
                problems.append(f"card {index} status must be ready or watch")
            if not isinstance(row.get("problems"), list):
                problems.append(f"card {index} problems must be a list")
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
    payload, problems = validate_prospect_card_data_audit(args.path)
    if problems:
        print(f"PROSPECT CARD DATA AUDIT VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    print(
        "prospect card data audit: "
        f"status={payload.get('status')} "
        f"top200={payload.get('metrics', {}).get('top200_count')} "
        f"watch={payload.get('metrics', {}).get('top200_watch_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
