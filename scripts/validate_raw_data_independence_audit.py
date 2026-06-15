"""Validate the ValuCast raw-data independence audit."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AUDIT_PATH = ROOT / "data" / "models" / "valucast_raw_data_independence_audit.json"


def validate_raw_data_independence(path: Path = AUDIT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != "valucast_raw_data_independence_audit":
        problems.append("artifact must be valucast_raw_data_independence_audit")
    if payload.get("status") not in {"boundary_hardened", "blocked"}:
        problems.append("status must be boundary_hardened or blocked")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    source_policy = payload.get("source_policy") or {}
    for flag in (
        "feeds_model_score",
        "feeds_public_rank",
        "dd_values_used",
        "dd_ranks_used",
        "external_rankings_used",
        "market_values_used",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")
    independence = payload.get("independence") or {}
    if independence.get("contract_factual_only") is not True:
        problems.append("independence.contract_factual_only must be true")
    if independence.get("prohibited_flags_clean") is not True:
        problems.append("independence.prohibited_flags_clean must be true")
    if not isinstance(independence.get("last_external_trust_boundary"), dict):
        problems.append("last_external_trust_boundary must be documented")
    validation = payload.get("validation") or {}
    if validation.get("raw_data_independence_complete") is not False:
        problems.append("raw_data_independence_complete must be false until direct ingestion exists")
    if not isinstance(validation.get("blockers"), list):
        problems.append("validation.blockers must be a list")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=AUDIT_PATH)
    args = parser.parse_args()

    payload, problems = validate_raw_data_independence(args.path)
    if problems:
        print(f"RAW DATA INDEPENDENCE VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    independence = payload.get("independence") or {}
    print(
        "raw data independence: "
        f"status={payload.get('status')} "
        f"direct_raw_ownership_score={independence.get('direct_raw_ownership_score')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
