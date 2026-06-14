"""Validate the ValuCast prospect coverage-audit artifact shape."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AUDIT_PATH = ROOT / "data" / "models" / "valucast_prospect_coverage_audit.json"


def validate_audit(path: Path = AUDIT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems = []
    if payload.get("artifact") != "valucast_prospect_coverage_audit":
        problems.append("artifact must be valucast_prospect_coverage_audit")
    if not payload.get("audit_version"):
        problems.append("audit_version is required")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    if payload.get("status") not in {"blocked", "candidate_ready"}:
        problems.append("status must be blocked or candidate_ready")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        problems.append("metrics must be an object")
    elif "elite_factual_raw_fallback_top_200_count" not in metrics:
        problems.append("metrics.elite_factual_raw_fallback_top_200_count is required")
    if not isinstance(payload.get("source_policy"), dict):
        problems.append("source_policy must be an object")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=AUDIT_PATH)
    args = parser.parse_args()

    payload, problems = validate_audit(args.path)
    if problems:
        print(f"PROSPECT COVERAGE AUDIT VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    metrics = payload.get("metrics") or {}
    print(
        "prospect coverage audit: "
        f"status={payload.get('status')} "
        f"rows={metrics.get('row_count')} "
        f"raw_fallback_top200={metrics.get('raw_fallback_top_200_count')} "
        "elite_factual_raw_fallback_top200="
        f"{metrics.get('elite_factual_raw_fallback_top_200_count')}"
    )
    for blocker in payload.get("blockers") or []:
        print(f"  blocker: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
