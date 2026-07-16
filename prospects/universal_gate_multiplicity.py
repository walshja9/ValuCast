"""Multiplicity correction for the 24 universal target gates (audit repair R3).

The universal prospect model runs 24 out-of-sample promotion gates (11 hitter +
13 pitcher targets), each a walk-forward comparison of the ridge model against
the best factual baseline. Only the rank backtest applies a Bonferroni
correction; these 24 gates are reported uncorrected, so the family-wise false
positive rate is understated.

This artifact adds REPORTING-ONLY multiplicity fields per gate:
- a paired case (player) bootstrap two-sided CI on the gate's OOS improvement
  percentage (against the same baseline the served gate selected). Each player
  appears once in the walk-forward, so this is an ordinary nonparametric case
  bootstrap (no within-player correlation to preserve),
- a descriptive z-score from that bootstrap (NOT the significance criterion), and
- nominal (percentile-CI-excludes-0) and Bonferroni-corrected significance flags
  at family-wise alpha 0.05 over the 24 gates.

It also carries each gate's served status and improvement_pct VERBATIM so a
reader can confirm the correction changed no active/fallback decision. Nothing
here feeds a score, rank, value, or gate decision. No consensus/third-party
ranks are read or stored.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import norm

from prospects.model import _walk_forward
from prospects.universal import (
    INPUT_PATH,
    MODEL_VERSION,
    RIDGE_LAMBDA,
    TARGET_SPECS,
    _horizon_clipped_seasons,
    _target_rows,
    load_input_contract,
    train_target,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_universal_gate_multiplicity.json"
SCHEMA_VERSION = "1.0.0"
BOOTSTRAP_SEED = 28016  # documented, reporting-only
N_BOOTSTRAPS = 10_000
FAMILY_ALPHA = 0.05
# Metric direction: brier (probability) and mae (conditional) are both
# lower-is-better, so improvement% = (baseline - model) / |baseline| * 100.
_BASELINE_PREDICTION_KEY = {
    "level_age_prior": "prior_predictions",
    "historical_neighbors_25": "neighbor_predictions",
    "canonical_historical_neighbors_25": "canonical_neighbor_predictions",
}


def _generated_at(value: str | None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _paired_errors(
    validation: dict, baseline_name: str, kind: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-item metric contributions for model and the chosen baseline.

    Mirrors universal._validation_score exactly: probability targets score on
    per-item Brier (squared error), conditional targets on absolute error (MAE).
    Using the wrong power would flip the sign of the delta versus the served
    gate. Returns (model_error, baseline_error, player_ids).
    """
    targets = np.array(validation["targets"], dtype=float)
    power = 2.0 if kind == "probability" else 1.0

    def contribution(predictions_key: str) -> np.ndarray:
        residual = np.array(validation[predictions_key], dtype=float) - targets
        return np.abs(residual) ** power

    model = contribution("model_predictions")
    baseline = contribution(_BASELINE_PREDICTION_KEY[baseline_name])
    cluster_ids = np.empty(len(targets), dtype=np.int64)
    offset = 0
    for fold in validation["folds"]:
        for local, mlbam_id in enumerate(fold["test_ids"]):
            cluster_ids[offset + local] = int(mlbam_id)
        offset += len(fold["test_ids"])
    return model, baseline, cluster_ids


def _ci_excludes_zero(low, high) -> bool:
    """A two-sided percentile interval is significant iff it does not straddle 0."""
    return low is not None and high is not None and (low > 0.0 or high < 0.0)


def _delta_pct(model: np.ndarray, baseline: np.ndarray) -> float:
    baseline_mean = float(baseline.mean())
    if baseline_mean == 0:
        return 0.0
    return (baseline_mean - float(model.mean())) / abs(baseline_mean) * 100.0


def _bootstrap(model: np.ndarray, baseline: np.ndarray, cluster_ids: np.ndarray) -> dict:
    point = _delta_pct(model, baseline)
    unique, inverse = np.unique(cluster_ids, return_inverse=True)
    members = [np.flatnonzero(inverse == index) for index in range(len(unique))]
    count = len(unique)
    if count < 2:
        return {"point": point, "draws": np.array([point])}
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = np.empty(N_BOOTSTRAPS)
    for draw in range(N_BOOTSTRAPS):
        picks = rng.integers(0, count, count)
        index = np.concatenate([members[pick] for pick in picks])
        draws[draw] = _delta_pct(model[index], baseline[index])
    return {"point": point, "draws": draws}


def build_gate_multiplicity(
    gate_records: list[dict],
    *,
    input_sha256: str,
    model_version: str = MODEL_VERSION,
    generated_at: str | None = None,
) -> dict:
    family_size = len(gate_records)
    corrected_alpha = FAMILY_ALPHA / family_size if family_size else FAMILY_ALPHA
    corrected_z = float(norm.ppf(1.0 - corrected_alpha / 2.0)) if family_size else None
    # Significance is read off the percentile bootstrap CIs, not a symmetric Wald
    # z: the bootstrap deltas are skewed, so |point/SE| >= 1.96 can disagree with a
    # percentile CI that excludes 0 (pitcher representative_ip is exactly that
    # case). Nominal uses the two-sided 95% percentile CI; Bonferroni uses the
    # per-gate two-sided alpha 0.05/family_size, so each tail is alpha/(2*family).
    nominal_tail = 100.0 * FAMILY_ALPHA / 2.0
    bonferroni_tail = 100.0 * corrected_alpha / 2.0
    gates = []
    for record in gate_records:
        draws = record["draws"]
        point = float(record["point"])
        if len(draws) > 1:
            ci_low = round(float(np.percentile(draws, nominal_tail)), 4)
            ci_high = round(float(np.percentile(draws, 100.0 - nominal_tail)), 4)
            bonf_low = round(float(np.percentile(draws, bonferroni_tail)), 4)
            bonf_high = round(float(np.percentile(draws, 100.0 - bonferroni_tail)), 4)
            standard_error = float(np.std(draws, ddof=1))
            z_score = point / standard_error if standard_error > 0 else None
        else:
            ci_low = ci_high = None
            bonf_low = bonf_high = None
            standard_error = None
            z_score = None
        # Significance is the REPORTED (rounded) percentile CI excluding 0, so the
        # flag always agrees with the published interval a reader sees -- sub-1e-4
        # bootstrap noise never manufactures significance. The stricter (wider)
        # Bonferroni interval excluding 0 implies the nominal one does too, so a
        # Bonferroni survivor is always nominally significant.
        nominal_significant = _ci_excludes_zero(ci_low, ci_high)
        bonferroni_significant = _ci_excludes_zero(bonf_low, bonf_high)
        gates.append(
            {
                "role": record["role"],
                "target": record["target"],
                "metric": record["metric"],
                "baseline": record["baseline"],
                "sample_size": record["sample_size"],
                # served decision, carried verbatim (proves no decision change)
                "served_gate_status": record["served_gate_status"],
                "served_improvement_pct": record["served_improvement_pct"],
                # reporting-only multiplicity statistics
                "improvement_pct_point": round(point, 4),
                # nominal two-sided 95% percentile CI (drives nominal_significant)
                "ci_low": ci_low,
                "ci_high": ci_high,
                # Bonferroni per-gate percentile CI (drives bonferroni_significant)
                "bonferroni_ci_low": bonf_low,
                "bonferroni_ci_high": bonf_high,
                # descriptive only -- NOT the significance criterion (skewed draws)
                "bootstrap_z_descriptive": None if z_score is None else round(z_score, 4),
                "standard_error": (
                    None if standard_error is None else round(standard_error, 6)
                ),
                "nominal_significant": bool(nominal_significant),
                "bonferroni_significant": bool(bonferroni_significant),
            }
        )
    survivors = sum(1 for gate in gates if gate["bonferroni_significant"])
    nominal = sum(1 for gate in gates if gate["nominal_significant"])
    active = sum(1 for gate in gates if gate["served_gate_status"] == "active")
    return {
        "artifact": "valucast_universal_gate_multiplicity",
        "schema_version": SCHEMA_VERSION,
        "status": "research_only",
        "generated_at": _generated_at(generated_at),
        "universal_model_version": model_version,
        "input": {
            "path": "data/prospects/prospect_model_inputs.json",
            "sha256": input_sha256,
        },
        "family": {
            "family_size": family_size,
            "family_wise_alpha": FAMILY_ALPHA,
            "bonferroni_alpha_per_gate": corrected_alpha,
            "bonferroni_two_sided_z": None if corrected_z is None else round(corrected_z, 6),
            "nominal_two_sided_z": round(float(norm.ppf(1.0 - FAMILY_ALPHA / 2.0)), 6),
            "served_active_gates": active,
            "nominal_significant_gates": nominal,
            "bonferroni_significant_gates": survivors,
            "note": (
                "The 24 universal target gates were reported without a "
                "multiplicity correction. Under a Bonferroni family-wise alpha of "
                "0.05, only the gates flagged bonferroni_significant clear the "
                "corrected evidence bar. These flags are REPORTING ONLY: served "
                "active/fallback gate decisions are unchanged (see "
                "served_gate_status)."
            ),
        },
        "procedure": {
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_draws": N_BOOTSTRAPS,
            "resample_unit": "player_mlbam_id",
            "resample_note": (
                "each player appears once in the walk-forward, so this is an "
                "ordinary nonparametric case (player) bootstrap"
            ),
            "nominal_ci": "two_sided_percentile_95",
            "bonferroni_ci": (
                "two_sided_percentile at per-gate alpha family_wise_alpha/"
                "family_size"
            ),
            "significance_criterion": "percentile_ci_excludes_zero",
            "bootstrap_z_descriptive_note": (
                "point / bootstrap_standard_error, reported for context only; the "
                "skewed bootstrap makes the symmetric Wald z disagree with the "
                "percentile CI, so it is NOT the significance criterion"
            ),
            "metric_direction": "lower_is_better",
            "consensus_or_third_party_ranks_used": False,
            "feeds_gate_decision": False,
        },
        "gates": gates,
        "validation": {"problems": []},
    }


def validate_gate_multiplicity(payload: dict) -> list[str]:
    problems: list[str] = []
    if payload.get("artifact") != "valucast_universal_gate_multiplicity":
        problems.append("artifact must be valucast_universal_gate_multiplicity")
    if payload.get("status") != "research_only":
        problems.append("status must be research_only")
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is invalid")
    input_sha = (payload.get("input") or {}).get("sha256")
    if not isinstance(input_sha, str) or len(input_sha) != 64:
        problems.append("input.sha256 must be a 64-character digest")
    procedure = payload.get("procedure") or {}
    if procedure.get("feeds_gate_decision") is not False:
        problems.append("procedure.feeds_gate_decision must be false")
    if procedure.get("consensus_or_third_party_ranks_used") is not False:
        problems.append("procedure must not read consensus/third-party ranks")
    family = payload.get("family") or {}
    gates = payload.get("gates")
    if not isinstance(gates, list) or not gates:
        problems.append("gates must be a non-empty list")
        gates = []
    if family.get("family_size") != len(gates):
        problems.append("family_size does not match the gate count")
    if family.get("family_wise_alpha") != FAMILY_ALPHA:
        problems.append("family_wise_alpha is invalid")
    expected_alpha = FAMILY_ALPHA / len(gates) if gates else None
    if gates and not math.isclose(
        family.get("bonferroni_alpha_per_gate", -1), expected_alpha, rel_tol=1e-9
    ):
        problems.append("bonferroni_alpha_per_gate is not family_wise_alpha/family_size")
    active = 0
    nominal = 0
    survivors = 0
    seen = set()
    for index, gate in enumerate(gates):
        identity = (gate.get("role"), gate.get("target"))
        if identity in seen:
            problems.append(f"gates[{index}] duplicates a target")
        seen.add(identity)
        if gate.get("served_gate_status") not in {
            "active",
            "fallback",
            "failed",
            "insufficient_sample",
        }:
            problems.append(f"gates[{index}].served_gate_status is invalid")
        if gate.get("served_gate_status") == "active":
            active += 1
        if gate.get("nominal_significant"):
            nominal += 1
        if gate.get("bonferroni_significant"):
            survivors += 1
        # Significance is the percentile CI excluding 0 (FIX 2), so each flag must
        # agree with its own interval -- no stray Wald-derived flag can survive.
        if _ci_excludes_zero(gate.get("ci_low"), gate.get("ci_high")) != bool(
            gate.get("nominal_significant")
        ):
            problems.append(f"gates[{index}] nominal_significant disagrees with its CI")
        if _ci_excludes_zero(
            gate.get("bonferroni_ci_low"), gate.get("bonferroni_ci_high")
        ) != bool(gate.get("bonferroni_significant")):
            problems.append(
                f"gates[{index}] bonferroni_significant disagrees with its CI"
            )
        # A Bonferroni survivor must also be nominally significant (stricter bar).
        if gate.get("bonferroni_significant") and not gate.get("nominal_significant"):
            problems.append(f"gates[{index}] bonferroni-significant but not nominal")
    if family.get("served_active_gates") != active:
        problems.append("family.served_active_gates does not match gates")
    if family.get("nominal_significant_gates") != nominal:
        problems.append("family.nominal_significant_gates does not match gates")
    if family.get("bonferroni_significant_gates") != survivors:
        problems.append("family.bonferroni_significant_gates does not match gates")
    return problems


def _gate_records(contract: dict, now: str | None) -> list[dict]:
    rows = contract["historical"]["rows"]
    # Serving path clips outcome seasons to the fixed training horizon before
    # training the target gates (build_shadow_model); we MUST do the same or the
    # reconstructed gate leaks future outcomes and diverges from the served gate.
    seasons = _horizon_clipped_seasons(rows, contract["historical_mlb_seasons"])
    records = []
    for role in ("hitter", "pitcher"):
        for target_name in TARGET_SPECS[role]:
            # Authoritative served gate (identical serving code path + clip).
            trained = train_target(role, target_name, rows, seasons, now=now)
            gate = trained["gate"]
            baseline_name = gate["baseline"]
            kind = TARGET_SPECS[role][target_name]["kind"]
            # Reconstruct per-item OOF against the gate-selected baseline. When a
            # gate has no baseline (insufficient sample / failed), there is no
            # delta to bootstrap; carry the served status with null statistics.
            record = {
                "role": role,
                "target": target_name,
                "metric": gate["metric"],
                "baseline": baseline_name,
                "sample_size": gate["sample_size"],
                "served_gate_status": gate["status"],
                "served_improvement_pct": gate["improvement_pct"],
                "point": 0.0,
                "draws": np.array([0.0]),
            }
            if baseline_name in _BASELINE_PREDICTION_KEY:
                target_rows = _target_rows(rows, seasons, role, target_name)
                validation = _walk_forward(target_rows, ridge_lambda=RIDGE_LAMBDA)
                if validation["targets"]:
                    model, baseline, clusters = _paired_errors(
                        validation, baseline_name, kind
                    )
                    boot = _bootstrap(model, baseline, clusters)
                    record["point"] = boot["point"]
                    record["draws"] = boot["draws"]
            records.append(record)
    return records


def run_gate_multiplicity(
    *,
    input_path: Path = INPUT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    now: str | None = None,
) -> dict:
    input_bytes = input_path.read_bytes()
    contract = load_input_contract(input_path)
    records = _gate_records(contract, now)
    payload = build_gate_multiplicity(
        records, input_sha256=hashlib.sha256(input_bytes).hexdigest(), generated_at=now
    )
    problems = validate_gate_multiplicity(payload)
    if problems:
        raise ValueError("; ".join(problems))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "family_size": payload["family"]["family_size"],
        "served_active_gates": payload["family"]["served_active_gates"],
        "bonferroni_significant_gates": payload["family"]["bonferroni_significant_gates"],
    }
