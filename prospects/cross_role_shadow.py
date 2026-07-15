"""Observe-only cross-role validation for the ValuCast prospect board.

The shadow keeps retrospective concordance, change-detection power, current
board shape, and measured AAA evidence coverage separate. It never changes a
score, rank, or model flag.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_cross_role_shadow.json"
RANK_BACKTEST_PATH = ROOT / "data" / "models" / "valucast_rank_backtest.json"
POWER_PATH = ROOT / "data" / "models" / "rank_gate_power_check.json"
RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
AAA_PATH = ROOT / "data" / "models" / "valucast_aaa_statcast_features.json"

ABSOLUTE_CROSS_ROLE_FLOOR = 0.60
MIN_CROSS_ROLE_CHANGE_POWER = 0.70
MAX_TOP25_PITCHERS = 7
MAX_TOP50_PITCHER_RATE = 0.30
MIN_ELIGIBLE_TOP25_AAA_COVERAGE = 0.60
AAA_ELIGIBLE_LEVELS = frozenset({"AAA"})
AAA_METRICS = ("whiff_pct", "csw_pct", "chase_pct", "zone_pct", "gb_pct")
CHECK_NAMES = (
    "historical_absolute_concordance",
    "cross_role_change_power",
    "current_board_shape",
    "aaa_measured_coverage",
)


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _generated_at(value: str | None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _base_payload(generated_at: str) -> dict:
    return {
        "artifact": "valucast_prospect_cross_role_shadow",
        "schema_version": "1.1.0",
        "generated_at": generated_at,
        "source_policy": {
            "kind": "observe_only_orthogonal_validation",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "external_rankings_used_as_outcomes": False,
            "market_values_used": False,
        },
        "promotion": {
            "live_consumer": "blocked",
            "score_changes_authorized": False,
            "manual_board_adjustments_authorized": False,
            "failed_decay_flag_changed": False,
            "next_allowed_step": "continue_collection",
        },
        "limitations": [
            "Historical absolute concordance is retrospective and does not confirm a current scoring change.",
            "AAA Statcast is measured current evidence, not a historical outcome panel.",
            "Coverage and power must pass before a human review; review never authorizes live scoring.",
        ],
    }


def _blocked(generated_at: str, problems: list[str]) -> dict:
    payload = _base_payload(generated_at)
    payload.update(
        {
            "status": "blocked",
            "checks": {
                name: {"status": "blocked", "reason": "required_input_invalid"}
                for name in CHECK_NAMES
            },
            "consensus_sensitivity": [],
            "aaa_measured_evidence": {"covered_top25_pitchers": []},
            "validation": {"problems": problems},
        }
    )
    return payload


def _empirical_percentile(values: list[float], value: float) -> float | None:
    if not values:
        return None
    return round(100.0 * sum(item <= value for item in values) / len(values), 1)


def _has_measured_aaa(profile: object) -> bool:
    if not isinstance(profile, dict):
        return False
    overall = profile.get("overall") or {}
    return (
        _number(profile.get("n_pitches"))
        and profile["n_pitches"] > 0
        and all(_number(overall.get(metric)) for metric in AAA_METRICS)
        and bool(profile.get("pitch_types"))
    )


def build_cross_role_shadow(
    rank_backtest: dict,
    power_check: dict,
    rank_artifact: dict,
    aaa_artifact: dict,
    *,
    generated_at: str | None = None,
) -> dict:
    generated_at = _generated_at(generated_at)
    problems: list[str] = []

    c0 = (rank_backtest.get("variants") or {}).get("C0") or {}
    cross_value = (c0.get("weighted") or {}).get("c_cross_report_only")
    if not _number(cross_value):
        problems.append("rank_backtest.variants.C0.weighted.c_cross_report_only")
    folds = c0.get("folds")
    if not isinstance(folds, list) or not folds:
        problems.append("rank_backtest.variants.C0.folds")
    elif any(
        not isinstance(row, dict)
        or not isinstance(row.get("test_cohort"), int)
        or not _number(row.get("c_cross_report_only"))
        for row in folds
    ):
        problems.append("rank_backtest.variants.C0.folds.rows")

    effects = power_check.get("e2_cross_role")
    if not isinstance(effects, dict) or not effects:
        problems.append("power_check.e2_cross_role")
    elif not all(
        isinstance(row, dict) and _number(row.get("power")) for row in effects.values()
    ):
        problems.append("power_check.e2_cross_role.*.power")
    else:
        try:
            [float(effect) for effect in effects]
        except (TypeError, ValueError):
            problems.append("power_check.e2_cross_role.effect_keys")

    board = rank_artifact.get("board")
    if not isinstance(board, list) or not board:
        problems.append("rank_artifact.board")
    elif any(
        not isinstance(row, dict)
        or not isinstance(row.get("rank"), int)
        or row.get("role") not in {"hitter", "pitcher"}
        or not isinstance(row.get("mlbam_id"), int)
        for row in board
    ):
        problems.append("rank_artifact.board.rows")
    elif len({row["rank"] for row in board}) != len(board):
        problems.append("rank_artifact.board.duplicate_ranks")
    elif len({(row["mlbam_id"], row["role"]) for row in board}) != len(board):
        problems.append("rank_artifact.board.duplicate_identities")
    elif any(
        row["role"] == "pitcher"
        and (not isinstance(row.get("level"), str) or not row["level"].strip())
        for row in board
    ):
        problems.append("rank_artifact.board.pitcher_level")

    aaa_pitchers = aaa_artifact.get("pitchers")
    if not isinstance(aaa_pitchers, dict):
        problems.append("aaa_artifact.pitchers")

    if problems:
        return _blocked(generated_at, problems)

    ordered_board = sorted(board, key=lambda row: row["rank"])
    top25 = ordered_board[:25]
    top50 = ordered_board[:50]
    top25_pitchers = [row for row in top25 if row["role"] == "pitcher"]
    top50_pitchers = [row for row in top50 if row["role"] == "pitcher"]
    aaa_eligible_top25_pitchers = [
        row
        for row in top25_pitchers
        if str(row.get("level") or "").upper() in AAA_ELIGIBLE_LEVELS
    ]
    top50_rate = len(top50_pitchers) / len(top50) if top50 else 0.0

    fold_rows = [
        {
            "test_cohort": row.get("test_cohort"),
            "value": row.get("c_cross_report_only"),
        }
        for row in folds
    ]
    historical = {
        "status": "pass" if cross_value >= ABSOLUTE_CROSS_ROLE_FLOOR else "fail",
        "gate_name": "absolute_cross_role_adapter_floor",
        "metric": "c_cross_report_only",
        "value": round(float(cross_value), 6),
        "floor": ABSOLUTE_CROSS_ROLE_FLOOR,
        "fold_count": len(folds),
        "folds": fold_rows,
        "evidence_class": "retrospective_absolute_floor",
        "confirms_current_change": False,
    }

    tested_effects = [
        {"effect": float(effect), "power": round(float(row["power"]), 6)}
        for effect, row in sorted(effects.items(), key=lambda item: float(item[0]))
    ]
    max_power = max(row["power"] for row in tested_effects)
    power = {
        "status": "pass" if max_power >= MIN_CROSS_ROLE_CHANGE_POWER else "fail",
        "metric": "registered_cross_role_change_detection_power",
        "max_power": max_power,
        "floor": MIN_CROSS_ROLE_CHANGE_POWER,
        "tested_effects": tested_effects,
        "evidence_class": "prospective_change_gate",
    }

    shape = {
        "status": (
            "pass"
            if len(top25_pitchers) <= MAX_TOP25_PITCHERS
            and top50_rate <= MAX_TOP50_PITCHER_RATE
            else "fail"
        ),
        "top25_pitcher_count": len(top25_pitchers),
        "max_top25_pitchers": MAX_TOP25_PITCHERS,
        "top50_pitcher_count": len(top50_pitchers),
        "top50_pitcher_rate": round(top50_rate, 6),
        "max_top50_pitcher_rate": MAX_TOP50_PITCHER_RATE,
        "evidence_class": "current_publication_shape",
    }

    covered = [
        row
        for row in aaa_eligible_top25_pitchers
        if _has_measured_aaa(aaa_pitchers.get(str(row["mlbam_id"])))
    ]
    coverage_rate = (
        len(covered) / len(aaa_eligible_top25_pitchers)
        if aaa_eligible_top25_pitchers
        else 0.0
    )
    population_coverage_rate = (
        len(covered) / len(top25_pitchers) if top25_pitchers else 0.0
    )
    coverage = {
        "status": (
            "pass"
            if aaa_eligible_top25_pitchers
            and coverage_rate >= MIN_ELIGIBLE_TOP25_AAA_COVERAGE
            else "fail"
        ),
        "top25_pitcher_count": len(top25_pitchers),
        "eligible_top25_pitcher_count": len(aaa_eligible_top25_pitchers),
        "covered_top25_pitcher_count": len(covered),
        "coverage_rate": round(coverage_rate, 6),
        "top25_population_coverage_rate": round(population_coverage_rate, 6),
        "floor": MIN_ELIGIBLE_TOP25_AAA_COVERAGE,
        "evidence_class": "current_measured_aaa_pitch_data_among_eligible",
        "confirms_cross_role_calibration": False,
    }

    metric_distributions = {
        metric: [
            float((profile.get("overall") or {})[metric])
            for profile in aaa_pitchers.values()
            if isinstance(profile, dict)
            and _number((profile.get("overall") or {}).get(metric))
        ]
        for metric in AAA_METRICS
    }
    covered_rows = []
    for row in covered:
        profile = aaa_pitchers[str(row["mlbam_id"])]
        overall = profile.get("overall") or {}
        covered_rows.append(
            {
                "rank": row["rank"],
                "mlbam_id": row["mlbam_id"],
                "name": row.get("name"),
                "n_pitches": profile.get("n_pitches"),
                "overall": {
                    metric: {
                        "value": overall.get(metric),
                        "aaa_empirical_percentile": (
                            _empirical_percentile(
                                metric_distributions[metric], float(overall[metric])
                            )
                            if _number(overall.get(metric))
                            else None
                        ),
                    }
                    for metric in AAA_METRICS
                },
                "pitch_types": profile.get("pitch_types") or {},
            }
        )

    sensitivity = []
    for minimum_sources in range(1, 6):
        eligible = []
        for row in top25:
            source_ranks = (row.get("context_only") or {}).get("source_ranks") or {}
            numeric = [value for value in source_ranks.values() if _number(value)]
            if len(numeric) >= minimum_sources:
                eligible.append((row, numeric))
        pitcher_rows = [item for item in eligible if item[0]["role"] == "pitcher"]
        sensitivity.append(
            {
                "minimum_sources": minimum_sources,
                "eligible_top25_count": len(eligible),
                "pitcher_count": len(pitcher_rows),
                "pitcher_source_rank_median": (
                    round(median(median(values) for _, values in pitcher_rows), 1)
                    if pitcher_rows
                    else None
                ),
            }
        )

    checks = {
        "historical_absolute_concordance": historical,
        "cross_role_change_power": power,
        "current_board_shape": shape,
        "aaa_measured_coverage": coverage,
    }
    review_ready = all(check["status"] == "pass" for check in checks.values())
    payload = _base_payload(generated_at)
    payload.update(
        {
            "status": "review_ready" if review_ready else "collecting",
            "source_dates": {
                "rank_artifact_generated_at": rank_artifact.get("generated_at"),
                "aaa_artifact_generated_at": aaa_artifact.get("generated_at"),
            },
            "checks": checks,
            "consensus_sensitivity": sensitivity,
            "aaa_measured_evidence": {
                "aaa_pitcher_population": len(aaa_pitchers),
                "covered_top25_pitchers": covered_rows,
            },
            "validation": {"problems": []},
        }
    )
    payload["promotion"]["next_allowed_step"] = (
        "human_methodology_review" if review_ready else "continue_collection"
    )
    return payload


def validate_cross_role_shadow(payload: dict) -> list[str]:
    problems: list[str] = []
    if payload.get("artifact") != "valucast_prospect_cross_role_shadow":
        problems.append("artifact must be valucast_prospect_cross_role_shadow")
    if payload.get("status") not in {"blocked", "collecting", "review_ready"}:
        problems.append("status must be blocked, collecting, or review_ready")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    checks = payload.get("checks") or {}
    for name in CHECK_NAMES:
        if (checks.get(name) or {}).get("status") not in {"blocked", "pass", "fail"}:
            problems.append(f"checks.{name}.status is invalid")
    promotion = payload.get("promotion") or {}
    for flag in (
        "score_changes_authorized",
        "manual_board_adjustments_authorized",
        "failed_decay_flag_changed",
    ):
        if promotion.get(flag) is not False:
            problems.append(f"promotion.{flag} must be false")
    if promotion.get("live_consumer") != "blocked":
        problems.append("promotion.live_consumer must be blocked")
    source_policy = payload.get("source_policy") or {}
    for flag in (
        "feeds_model_score",
        "feeds_public_rank",
        "feeds_buy_score",
        "external_rankings_used_as_outcomes",
        "market_values_used",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")
    validation = payload.get("validation") or {}
    if not isinstance(validation.get("problems"), list):
        problems.append("validation.problems must be a list")
    return problems


def run_cross_role_shadow(
    *,
    rank_backtest_path: Path = RANK_BACKTEST_PATH,
    power_path: Path = POWER_PATH,
    rank_path: Path = RANK_PATH,
    aaa_path: Path = AAA_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    generated_at: str | None = None,
) -> dict:
    inputs = []
    read_problems = []
    for name, path in (
        ("rank_backtest", rank_backtest_path),
        ("power_check", power_path),
        ("rank_artifact", rank_path),
        ("aaa_artifact", aaa_path),
    ):
        try:
            inputs.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            read_problems.append(f"{name}: {exc}")
            inputs.append({})
    payload = (
        _blocked(_generated_at(generated_at), read_problems)
        if read_problems
        else build_cross_role_shadow(*inputs, generated_at=generated_at)
    )
    validation_problems = validate_cross_role_shadow(payload)
    if validation_problems:
        raise ValueError("; ".join(validation_problems))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "status": payload["status"],
        "failed_checks": [
            name
            for name, check in payload["checks"].items()
            if check["status"] == "fail"
        ],
    }
