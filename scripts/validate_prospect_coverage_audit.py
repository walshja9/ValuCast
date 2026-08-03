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
    investment_context = payload.get("investment_context")
    if not isinstance(investment_context, dict):
        problems.append("investment_context must be an object")
    else:
        if investment_context.get("status") not in {"complete", "incomplete"}:
            problems.append("investment_context.status must be complete or incomplete")
        bands = investment_context.get("bands")
        if not isinstance(bands, dict):
            problems.append("investment_context.bands must be an object")
        else:
            for band in ("top_25", "top_50", "top_100", "top_200"):
                if not isinstance(bands.get(band), dict):
                    problems.append(f"investment_context.bands.{band} must be an object")
        if not isinstance(investment_context.get("direct_score_sensitivity"), dict):
            problems.append("investment_context.direct_score_sensitivity must be an object")
        queue = investment_context.get("missing_evidence_queue")
        if not isinstance(queue, list):
            problems.append("investment_context.missing_evidence_queue must be a list")
        elif any(row.get("changes_ranks_or_values") is not False for row in queue):
            problems.append(
                "investment_context.missing_evidence_queue must be non-serving"
            )
        verified_evidence = investment_context.get("verified_evidence")
        if not isinstance(verified_evidence, dict):
            problems.append("investment_context.verified_evidence must be an object")
        else:
            if verified_evidence.get("feeds_rank_score") is not True:
                problems.append(
                    "investment_context.verified_evidence.feeds_rank_score must be true"
                )
            if verified_evidence.get("feeds_v06_model") is not False:
                problems.append(
                    "investment_context.verified_evidence.feeds_v06_model must be false"
                )
            if verified_evidence.get("feeds_universal_model") is not False:
                problems.append(
                    "investment_context.verified_evidence.feeds_universal_model must be false"
                )
            if verified_evidence.get("changes_ranks_or_values") is not True:
                problems.append(
                    "investment_context.verified_evidence.changes_ranks_or_values must be true"
                )
            if not isinstance(verified_evidence.get("bands"), dict):
                problems.append(
                    "investment_context.verified_evidence.bands must be an object"
                )
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
    top_50_hitters = (
        ((payload.get("investment_context") or {}).get("bands") or {})
        .get("top_50", {})
        .get("hitter", {})
    )
    verified_top_50_hitters = (
        (
            (
                (payload.get("investment_context") or {}).get("verified_evidence")
                or {}
            ).get("bands")
            or {}
        )
        .get("top_50", {})
        .get("hitter", {})
    )
    print(
        "prospect coverage audit: "
        f"status={payload.get('status')} "
        f"rows={metrics.get('row_count')} "
        f"raw_fallback_top200={metrics.get('raw_fallback_top_200_count')} "
        "elite_factual_raw_fallback_top200="
        f"{metrics.get('elite_factual_raw_fallback_top_200_count')} "
        "investment_top50_hitters_missing="
        f"{top_50_hitters.get('missing')} "
        "investment_top50_hitters_coverage="
        f"{top_50_hitters.get('coverage_rate')} "
        "verified_investment_top50_hitters_coverage="
        f"{verified_top_50_hitters.get('coverage_rate')}"
    )
    for blocker in payload.get("blockers") or []:
        print(f"  blocker: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
