"""Front-office readiness report for ValuCast."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.buys_monitor import ARTIFACT_PATH as BUYS_MONITOR_PATH
from prospects.front_office_failures import ARTIFACT_PATH as FRONT_OFFICE_FAILURES_PATH
from prospects.outcome_backtest import ARTIFACT_PATH as OUTCOME_BACKTEST_PATH
from prospects.raw_data_independence import ARTIFACT_PATH as RAW_INDEPENDENCE_PATH
from quality.valucast_governor import ARTIFACT_PATH as QUALITY_GOVERNOR_PATH

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
MODEL_V07_PATH = ROOT / "data" / "models" / "valucast_prospect_model_v0_7.json"
MILB_STAT_FRESHNESS_PATH = (
    ROOT / "data" / "models" / "valucast_milb_stat_freshness_audit.json"
)
PIPELINE_OBSERVABILITY_PATH = (
    ROOT / "data" / "models" / "valucast_pipeline_observability.json"
)
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_front_office_report.json"

REPORT_VERSION = "0.1.0"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _grade_from_score(score: int) -> str:
    if score >= 97:
        return "A+"
    if score >= 93:
        return "A"
    if score >= 90:
        return "A-"
    if score >= 87:
        return "B+"
    if score >= 83:
        return "B"
    if score >= 80:
        return "B-"
    if score >= 75:
        return "C+"
    if score >= 70:
        return "C"
    return "Incomplete"


def _pillar(name: str, score: int, status: str, evidence: dict) -> dict:
    return {
        "name": name,
        "score": score,
        "grade": _grade_from_score(score),
        "status": status,
        "evidence": evidence,
    }


def _next_build_order(
    *,
    forward_progress: dict,
    v07_ready: bool,
    v07_bucket_ready: bool,
) -> list[str]:
    """Next steps derived from live report state, not a stale literal list.

    The forward-archive line reads the remaining observation span off
    front_office_failures; the v0.7 line reflects whether the challenger is
    already trained and bucket-comparable. The last two lines are evergreen
    operating commitments (keep uncertainty visible / stay public + fail-loud).
    """
    order: list[str] = []

    remaining_days = forward_progress.get("remaining_span_days")
    next_grade = forward_progress.get("next_target_grade")
    if isinstance(remaining_days, (int, float)) and remaining_days > 0:
        grade_clause = f" to reach {next_grade} forward support" if next_grade else ""
        order.append(
            f"Keep logging forward archives: ~{int(remaining_days)} more "
            f"observation day(s) needed{grade_clause}."
        )
    else:
        order.append(
            "Sustain the forward archive so the earned grade stays supported "
            "as new cohorts resolve."
        )

    if v07_ready and v07_bucket_ready:
        order.append(
            "Run the Prospect Model v0.7-vs-v0.6 bucket comparison and publish "
            "the by-bucket verdict."
        )
    else:
        order.append(
            "Train Prospect Model v0.7 as a scored challenger, then compare "
            "against v0.6 by bucket."
        )

    order.append(
        "Promote the ordinal bridge only after it beats the historical-neighbor "
        "baseline out of sample."
    )
    order.append(
        "Keep uncertainty-band explanations visible on every prospect detail surface."
    )
    order.append(
        "Keep the front-office report public and fail-loud when evidence regresses."
    )
    return order


def build_front_office_report(
    public_snapshot: dict,
    quality_governor: dict,
    outcome_backtest: dict,
    model_v07: dict,
    raw_independence: dict,
    buys_monitor: dict,
    front_office_failures: dict | None = None,
    milb_stat_freshness_audit: dict | None = None,
    pipeline_observability: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    generated = generated_at or public_snapshot.get("generated_at") or datetime.now(
        timezone.utc
    ).isoformat()
    snapshot_validation = public_snapshot.get("validation") or {}
    outcome_track = outcome_backtest.get("front_office_track") or {}
    v07_validation = model_v07.get("validation") or {}
    raw_validation = raw_independence.get("validation") or {}
    raw_evidence = raw_independence.get("independence") or {}
    raw_score = float(
        raw_evidence.get("direct_raw_ownership_score") or 0.0
    )
    buys_monitoring = buys_monitor.get("monitoring") or {}
    buys_validation = (buys_monitor.get("validation") or {})
    failure_summary = (front_office_failures or {}).get("summary") or {}
    blocking_findings = (front_office_failures or {}).get("blocking_findings") or []
    evidence_gates = (front_office_failures or {}).get("evidence_gates") or []
    forward_progress = (front_office_failures or {}).get(
        "forward_archive_progress"
    ) or {}
    failure_watchlist = {
        "status": (front_office_failures or {}).get("status", "unavailable"),
        "blocking_finding_count": failure_summary.get("blocking_finding_count", 0),
        "evidence_gate_count": failure_summary.get("evidence_gate_count", 0),
        "front_office_risk_count": failure_summary.get("front_office_risk_count", 0),
        "v0_7_disagreement_count": failure_summary.get("v0_7_disagreement_count", 0),
        "latest_rank_bucket_count": failure_summary.get("latest_rank_bucket_count"),
        "latest_buy_retention_rate": failure_summary.get("latest_buy_retention_rate"),
        "blocking_findings": blocking_findings[:5],
        "evidence_gates": evidence_gates[:5],
        "forward_archive_progress": forward_progress,
    }
    milb_freshness_metrics = (milb_stat_freshness_audit or {}).get("metrics") or {}
    milb_freshness_ready = (
        not milb_stat_freshness_audit
        or milb_stat_freshness_audit.get("status") == "candidate_ready"
    )
    pipeline_validation = (pipeline_observability or {}).get("validation") or {}
    pipeline_observability_ready = (
        not pipeline_observability
        or pipeline_validation.get("ready_for_daily_publication") is True
    )
    operations_watchlist = {
        "milb_stat_freshness": {
            "status": (milb_stat_freshness_audit or {}).get("status", "unavailable"),
            "top50_history_fallback_count": milb_freshness_metrics.get(
                "top50_history_fallback_count"
            ),
            "top50_stat_context_mismatch_count": milb_freshness_metrics.get(
                "top50_stat_context_mismatch_count"
            ),
            "top200_history_fallback_count": milb_freshness_metrics.get(
                "top200_history_fallback_count"
            ),
            "targeted_row_refresh_count": milb_freshness_metrics.get(
                "targeted_row_refresh_count"
            ),
            "blockers": (milb_stat_freshness_audit or {}).get("blockers") or [],
        },
        "pipeline_observability": {
            "status": (pipeline_observability or {}).get("status", "unavailable"),
            "expected_date": (pipeline_observability or {}).get("expected_date"),
            "ready_for_daily_publication": pipeline_validation.get(
                "ready_for_daily_publication"
            ),
            "date_mismatch_count": pipeline_validation.get("date_mismatch_count"),
            "missing_or_unreadable_count": pipeline_validation.get(
                "missing_or_unreadable_count"
            ),
            "targeted_row_refresh_count": pipeline_validation.get(
                "targeted_row_refresh_count"
            ),
        },
    }
    governor_ready = quality_governor.get("ready_for_public_snapshot") is True
    governor_checks = quality_governor.get("checks") or []
    governor_all_passed = bool(governor_checks) and all(
        check.get("status") == "passed" for check in governor_checks
    )
    public_ready = snapshot_validation.get("ready_for_live_consumers") is True
    surface_readiness = snapshot_validation.get("surface_readiness") or {}
    dynasty_ready = (
        bool(surface_readiness.get("dynasty"))
        if "dynasty" in surface_readiness
        else public_ready
    )
    prospects_ready = bool(surface_readiness.get("prospects"))
    prospect_board_caveat = (
        (snapshot_validation.get("surface_blockers") or {}).get("prospects") or []
    )
    if isinstance(prospect_board_caveat, list):
        prospect_board_caveat = "; ".join(
            str(item) for item in prospect_board_caveat if item
        ) or []
    row_count = (
        public_snapshot.get("row_count")
        or len(public_snapshot.get("players") or [])
        or len(public_snapshot.get("rows") or [])
        or None
    )
    duplicate_identity_count = snapshot_validation.get("duplicate_identity_count")
    product_a_plus_ready = (
        dynasty_ready
        and governor_ready
        and governor_all_passed
        and bool(row_count and row_count >= 3_000)
        and duplicate_identity_count == 0
    )
    pipeline_a_plus_ready = (
        snapshot_validation.get("same_day_freshness") is True
        and snapshot_validation.get("required_fields_complete") is True
        and duplicate_identity_count == 0
        and not snapshot_validation.get("blockers")
        and not snapshot_validation.get("buy_signal_blockers")
        and milb_freshness_ready
        and pipeline_observability_ready
    )

    canonical_contract_owned = raw_evidence.get("canonical_contract_owned") is True
    raw_ingestion_owned = raw_validation.get("raw_data_independence_complete") is True
    independence_score = (
        97
        if raw_ingestion_owned
        else 93
        if canonical_contract_owned and raw_validation.get("ready_for_current_publication")
        else 88
        if raw_validation.get("ready_for_current_publication")
        else 70
    )
    independence_status = (
        "raw_ingestion_owned"
        if raw_ingestion_owned
        else "canonical_contract_owned"
        if canonical_contract_owned
        else "boundary_hardened"
        if raw_validation.get("ready_for_current_publication")
        else "blocked"
    )
    bucket_cohort_ready = (
        (outcome_backtest.get("validation") or {}).get("bucket_cohort_evidence_ready")
        is True
    )
    v07_bucket_ready = v07_validation.get("bucket_comparison_ready") is True
    prospect_a_plus_ready = (
        outcome_backtest.get("status") == "evidence_ready"
        and v07_validation.get("ready_for_backtest") is True
        and bucket_cohort_ready
        and v07_bucket_ready
        and v07_validation.get("top200_factual_context_coverage") == 1.0
        and v07_validation.get("top200_availability_coverage") == 1.0
        and not v07_validation.get("blockers")
    )
    prospect_score = (
        97
        if prospect_a_plus_ready
        else 93
        if outcome_backtest.get("status") == "evidence_ready"
        and v07_validation.get("ready_for_backtest")
        and bucket_cohort_ready
        and v07_bucket_ready
        else 90
        if outcome_backtest.get("status") == "evidence_ready"
        and v07_validation.get("ready_for_backtest")
        else 78
    )

    pillars = [
        _pillar(
            "Product readiness",
            97
            if product_a_plus_ready
            else 95
            if dynasty_ready
            else 78,
            (
                "a_plus_public_ready"
                if product_a_plus_ready
                else "public_ready"
                if dynasty_ready
                else "needs_work"
            ),
            {
                "public_snapshot_ready": public_ready,
                "quality_governor_ready": governor_ready,
                "quality_governor_all_checks_passed": governor_all_passed,
                "row_count": row_count,
                "duplicate_identity_count": duplicate_identity_count,
                "surface_readiness": snapshot_validation.get("surface_readiness"),
                "dynasty_ready": dynasty_ready,
                "prospects_ready": prospects_ready,
                "prospect_board_caveat": prospect_board_caveat,
            },
        ),
        _pillar(
            "Data pipeline readiness",
            97
            if pipeline_a_plus_ready and raw_ingestion_owned
            else 92
            if snapshot_validation.get("same_day_freshness")
            else 72,
            (
                "a_plus_native_daily_pipeline"
                if pipeline_a_plus_ready and raw_ingestion_owned
                else "same_day_fresh"
                if snapshot_validation.get("same_day_freshness")
                else "stale"
            ),
            {
                "same_day_freshness": snapshot_validation.get("same_day_freshness"),
                "required_fields_complete": snapshot_validation.get(
                    "required_fields_complete"
                ),
                "duplicate_identity_count": duplicate_identity_count,
                "raw_data_independence_complete": raw_ingestion_owned,
                "buy_monitor_ready": buys_validation.get("ready_for_monitoring"),
                "milb_stat_freshness_ready": milb_freshness_ready,
                "pipeline_observability_ready": pipeline_observability_ready,
                "targeted_row_refresh_count": operations_watchlist[
                    "pipeline_observability"
                ].get("targeted_row_refresh_count"),
            },
        ),
        _pillar(
            "Independence",
            independence_score,
            independence_status,
            {
                "direct_raw_ownership_score": raw_score,
                "canonical_contract_owned": canonical_contract_owned,
                "raw_data_independence_complete": raw_validation.get(
                    "raw_data_independence_complete"
                ),
                "last_external_trust_boundary": raw_evidence.get(
                    "last_external_trust_boundary"
                ),
            },
        ),
        _pillar(
            "Prospect credibility",
            prospect_score,
            (
                "a_plus_bucket_evidence_ready"
                if prospect_score >= 97
                else "bucket_evidence_ready"
                if prospect_score >= 93
                else "historical_evidence_ready"
                if outcome_backtest.get("status") == "evidence_ready"
                else "needs_more_evidence"
            ),
            {
                "outcome_grade": outcome_track.get("grade"),
                "outcome_score": outcome_track.get("score"),
                "bucket_cohort_evidence_ready": bucket_cohort_ready,
                "v07_ready_for_backtest": v07_validation.get("ready_for_backtest"),
                "v07_bucket_comparison_ready": v07_bucket_ready,
                "v07_top200_factual_context_coverage": v07_validation.get(
                    "top200_factual_context_coverage"
                ),
                "v07_top200_availability_coverage": v07_validation.get(
                    "top200_availability_coverage"
                ),
            },
        ),
        _pillar(
            "MLB front-office track",
            int(outcome_track.get("score") or 0),
            "in_progress",
            {
                "current_grade": outcome_track.get("grade"),
                "target_grade": outcome_track.get("target_grade"),
                "uncapped_score": outcome_track.get("uncapped_score"),
                "score_cap": outcome_track.get("score_cap"),
                "cap_reasons": outcome_track.get("cap_reasons"),
                "forward_supported_grade": outcome_track.get(
                    "forward_supported_grade"
                ),
                "forward_next_target_grade": outcome_track.get(
                    "forward_next_target_grade"
                ),
                "forward_thresholds": outcome_track.get("forward_thresholds"),
                "evidence_gates": evidence_gates,
                "rank_comparisons_needed": forward_progress.get(
                    "remaining_rank_comparisons"
                ),
                "buy_comparisons_needed": forward_progress.get(
                    "remaining_buy_comparisons"
                ),
                "observation_days_needed": forward_progress.get(
                    "remaining_span_days"
                ),
                "limitations": outcome_track.get("interpretation"),
                "buys_monitor_status": buys_monitor.get("status"),
                "buy_comparison_count": buys_monitoring.get("buy_comparison_count"),
                "observation_span_days": buys_monitoring.get("observation_span_days"),
            },
        ),
    ]
    overall_score = round(sum(pillar["score"] for pillar in pillars) / len(pillars))
    next_build_order = _next_build_order(
        forward_progress=forward_progress,
        v07_ready=v07_validation.get("ready_for_backtest") is True,
        v07_bucket_ready=v07_bucket_ready,
    )
    return {
        "artifact": "valucast_front_office_report",
        "report_version": REPORT_VERSION,
        "generated_at": generated,
        "status": "front_office_track_active",
        "overall": {
            "score": overall_score,
            "grade": _grade_from_score(overall_score),
            "target": "A+ product/pipeline/independence/prospect credibility; MLB front-office track advances only when forward and ordinal evidence earn it.",
        },
        "source_policy": {
            "kind": "readiness_report",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "pillars": pillars,
        "failure_watchlist": failure_watchlist,
        "operations_watchlist": operations_watchlist,
        "next_build_order": next_build_order,
    }


def write_front_office_report(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_front_office_report(
    public_snapshot_path: Path = PUBLIC_SNAPSHOT_PATH,
    quality_governor_path: Path = QUALITY_GOVERNOR_PATH,
    outcome_backtest_path: Path = OUTCOME_BACKTEST_PATH,
    model_v07_path: Path = MODEL_V07_PATH,
    raw_independence_path: Path = RAW_INDEPENDENCE_PATH,
    buys_monitor_path: Path = BUYS_MONITOR_PATH,
    front_office_failures_path: Path = FRONT_OFFICE_FAILURES_PATH,
    milb_stat_freshness_path: Path = MILB_STAT_FRESHNESS_PATH,
    pipeline_observability_path: Path = PIPELINE_OBSERVABILITY_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    failures = (
        _load(front_office_failures_path)
        if front_office_failures_path.exists()
        else None
    )
    payload = build_front_office_report(
        _load(public_snapshot_path),
        _load(quality_governor_path),
        _load(outcome_backtest_path),
        _load(model_v07_path),
        _load(raw_independence_path),
        _load(buys_monitor_path),
        failures,
        _load(milb_stat_freshness_path)
        if milb_stat_freshness_path.exists()
        else None,
        _load(pipeline_observability_path)
        if pipeline_observability_path.exists()
        else None,
    )
    path = write_front_office_report(payload, artifact_path)
    return {
        "artifact_path": str(path),
        "grade": payload["overall"]["grade"],
        "score": payload["overall"]["score"],
        "status": payload["status"],
    }
