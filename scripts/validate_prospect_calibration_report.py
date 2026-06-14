"""Validate the ValuCast Prospect Rank v1 calibration-report artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REPORT_PATH = ROOT / "data" / "models" / "valucast_prospect_calibration_report.json"


def validate_report(path: Path = REPORT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems = []
    if payload.get("artifact") != "valucast_prospect_calibration_report":
        problems.append("artifact must be valucast_prospect_calibration_report")
    if not payload.get("report_version"):
        problems.append("report_version is required")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    if payload.get("status") not in {"review_ready", "needs_review"}:
        problems.append("status must be review_ready or needs_review")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        problems.append("metrics must be an object")
    else:
        bands = metrics.get("bands")
        if not isinstance(bands, dict) or "50" not in bands:
            problems.append("metrics.bands.50 is required")
        if "tuning_flag_count" not in metrics:
            problems.append("metrics.tuning_flag_count is required")
    source_policy = payload.get("source_policy")
    if not isinstance(source_policy, dict):
        problems.append("source_policy must be an object")
    elif source_policy.get("feeds_model_score") is not False:
        problems.append("source_policy.feeds_model_score must be false")
    watchlists = payload.get("watchlists")
    if not isinstance(watchlists, dict):
        problems.append("watchlists must be an object")
    elif "top50_dd_context_disagreements" not in watchlists:
        problems.append("watchlists.top50_dd_context_disagreements is required")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    payload, problems = validate_report(args.path)
    if problems:
        print(f"PROSPECT CALIBRATION REPORT VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    metrics = payload.get("metrics") or {}
    print(
        "prospect calibration report: "
        f"status={payload.get('status')} "
        f"rows={metrics.get('row_count')} "
        f"flags={metrics.get('tuning_flag_count')} "
        f"availability_top50={metrics.get('availability_watchlist_count_top50')} "
        f"context_disagreements_top50={metrics.get('context_disagreement_count_top50')}"
    )
    for flag in payload.get("tuning_flags") or []:
        print(f"  flag: {flag.get('id')} {flag.get('message')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
