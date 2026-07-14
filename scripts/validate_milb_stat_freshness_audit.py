"""Validate the ValuCast MiLB stat freshness audit artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AUDIT_PATH = ROOT / "data" / "models" / "valucast_milb_stat_freshness_audit.json"


def validate_milb_stat_freshness_audit(
    path: Path = AUDIT_PATH,
) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != "valucast_milb_stat_freshness_audit":
        problems.append("artifact must be valucast_milb_stat_freshness_audit")
    if not payload.get("audit_version"):
        problems.append("audit_version is required")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    if payload.get("status") not in {"blocked", "candidate_ready"}:
        problems.append("status must be blocked or candidate_ready")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        problems.append("metrics must be an object")
    else:
        for field in (
            "current_row_count",
            "current_season_row_count",
            "latest_milb_history_row_count",
            "targeted_row_refresh_count",
            "current_row_stale_fetch_count",
            "top50_history_fallback_count",
            "top50_stat_context_mismatch_count",
            "top200_history_fallback_count",
        ):
            if not isinstance(metrics.get(field), int):
                problems.append(f"metrics.{field} must be an integer")
        fallback_count = metrics.get("top50_history_fallback_count")
        if payload.get("status") == "blocked" and isinstance(fallback_count, int) and fallback_count > 0:
            problems.append(
                "status=blocked feed is serving "
                f"{fallback_count} top50_history_fallback rows; blocked feeds must not "
                "serve fallback history"
            )
    if not isinstance(payload.get("criteria"), dict):
        problems.append("criteria must be an object")
    if not isinstance(payload.get("blockers"), list):
        problems.append("blockers must be a list")
    if not isinstance(payload.get("samples"), dict):
        problems.append("samples must be an object")
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
    parser.add_argument("--path", type=Path, default=AUDIT_PATH)
    args = parser.parse_args()

    payload, problems = validate_milb_stat_freshness_audit(args.path)
    if problems:
        print(f"MILB STAT FRESHNESS AUDIT VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    metrics = payload.get("metrics") or {}
    print(
        "milb stat freshness audit: "
        f"status={payload.get('status')} "
        f"rows={metrics.get('current_row_count')} "
        f"top50_history={metrics.get('top50_history_fallback_count')} "
        f"top200_history={metrics.get('top200_history_fallback_count')} "
        f"targeted_refreshes={metrics.get('targeted_row_refresh_count')}"
    )
    for blocker in payload.get("blockers") or []:
        print(f"  blocker: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
