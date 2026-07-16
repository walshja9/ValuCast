"""E1 pitcher challenger — EXPLORATORY replay (research-only, gate look NOT spent).

Dry-runs the E1 challenger (prospects/pitcher_challenger.py, both model_flags OFF
by default) against the incumbent over the committed historical cohort folds, using
the SAME within-role tier-concordance C statistic and the SAME production board
pipeline as the registered Rank-gate v1 harness (prospects/rank_backtest.py). This
is EXPLORATORY only:

  * EXPLORATORY seed 28017 (NEVER the registered 28013).
  * The E1 model_flags variant (NEVER the registered C1 pedigree lever).
  * Output is labeled research_only / exploratory_replay / gate_look_spent: false,
    written OUTSIDE data/models/ (data/validation/e1_exploratory_replay.json).

The orchestrator decides whether to spend the ONE registered look (seed 28013,
delta_c_pitcher point >= +0.005 AND 98.33% bootstrap lower bound > 0) based on this
report. This script must NEVER reproduce that registered configuration.

Reads only; the served model and its gate are untouched. Reported numbers:
delta_c_pitcher (point + per-fold + exploratory paired-bootstrap CI), the AA and
age<=20 pitcher slice deltas, and the hitter-side delta (asserted ~0 — the
challenger must not touch hitters).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from prospects.dynasty_backtest import OUTCOME_COMPLETE_THROUGH, OUTCOME_HORIZON_YEARS
from prospects.model import (
    _impact_references,
    score_current as model_score_current,
    train_impact_role,
    train_role,
)
from prospects.rank_backtest import (
    BOOTSTRAP_SEED as REGISTERED_SEED,
    N_BOOTSTRAPS,
    Z_ONE_SIDED,
    _eligible_fold_rows,
    _fold_board_scores,
    _fold_contract,
    _fold_metrics,
    _fold_now,
    _model_flags,
    _tier_concordance_fast,
    paired_bootstrap_lower_bound,
)
from prospects.universal import load_input_contract, INPUT_PATH

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "validation" / "e1_exploratory_replay.json"

# EXPLORATORY seed. Guarded below so this can never silently become the registered
# 28013 look. Documented, deterministic.
EXPLORATORY_SEED = 28017

# The E1 challenger variant: both dark levers flipped ON around training+scoring
# via the incumbent's own _model_flags mechanism. C0 = incumbent (empty spec).
INCUMBENT_SPEC: dict = {}
E1_SPEC = {
    "model_flags": {
        "PITCHER_OUTCOME_ROLE_SPLIT_ENABLED": True,
        "PITCHER_PER_GROUP_SHRINK_ENABLED": True,
    }
}


def _fold_years(contract: dict) -> list[int]:
    cohorts = sorted(
        {int(row.get("cohort_year") or 0) for row in contract["historical"]["rows"]}
    )
    return [
        year
        for year in cohorts
        if year <= OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS
        and year - OUTCOME_HORIZON_YEARS >= min(cohorts)
    ]


def _pitcher_slice_keys(contract: dict, test_year: int) -> dict[str, set]:
    """Slice membership (AA pitchers, age<=20 pitchers) for one fold's pseudo-universe."""
    aa, young = set(), set()
    for key, row in _eligible_fold_rows(contract, test_year).items():
        if key[1] != "pitcher":
            continue
        if str(row.get("level") or "").upper() == "AA":
            aa.add(key)
        try:
            age = float(row.get("age")) if row.get("age") is not None else 99.0
        except (TypeError, ValueError):
            age = 99.0
        if age <= 20:
            young.add(key)
    return {"aa_pitcher": aa, "age_le_20_pitcher": young}


def _slice_delta(fold_pairs: list[dict], slice_keys_per_fold: list[set]) -> dict:
    """Weighted point delta_c on a within-role slice, plus per-fold detail.

    Restricts each fold to the slice keys (already all pitchers), then measures the
    incumbent vs challenger tier-concordance delta with the fast estimator, weighted
    by slice sample. No bootstrap here (slices are small; the CI is the headline
    pitcher metric). Report-only.
    """
    per_fold = []
    deltas, weights = [], []
    for fold, keys in zip(fold_pairs, slice_keys_per_fold):
        sel = sorted(k for k in fold["baseline"] if k in keys)
        if len(sel) < 2:
            per_fold.append({"n": len(sel), "delta_c": None})
            continue
        base = np.array([fold["baseline"][k] for k in sel], dtype=float)
        cand = np.array([fold["candidate"][k] for k in sel], dtype=float)
        tiers = np.array([fold["tiers"][k] for k in sel], dtype=float)
        base_c = _tier_concordance_fast(base, tiers)
        cand_c = _tier_concordance_fast(cand, tiers)
        if base_c is None or cand_c is None:
            per_fold.append({"n": len(sel), "delta_c": None})
            continue
        per_fold.append(
            {
                "n": len(sel),
                "c_incumbent": round(base_c, 6),
                "c_challenger": round(cand_c, 6),
                "delta_c": round(cand_c - base_c, 6),
            }
        )
        deltas.append(cand_c - base_c)
        weights.append(len(sel))
    point = float(np.average(deltas, weights=weights)) if deltas else None
    return {
        "point_delta_c": round(point, 6) if point is not None else None,
        "pooled_n": int(sum(weights)),
        "per_fold": per_fold,
    }


def _model_level_hitter_freeze(contract: dict, fold_years: list[int]) -> dict:
    """The REAL hitter invariant: at the model-score level (before the board's
    cross-role pooled normalization), the challenger changes ZERO hitter scores.

    Re-runs the production trainers+scorer for one fold with the E1 flags off then
    on, and counts how many hitter vs pitcher (outcome, impact) score pairs move.
    Hitters must be exactly 0 (flags are pitcher-only); pitchers must be > 0 (the
    lever is actually doing something). Report-only sanity, not the gate.
    """
    test_year = fold_years[0]
    now = _fold_now(test_year)
    train_through = test_year - OUTCOME_HORIZON_YEARS
    training_rows = [
        row
        for row in contract["historical"]["rows"]
        if int(row.get("cohort_year") or 9999) <= train_through
    ]
    fold_rows = _eligible_fold_rows(contract, test_year)
    fold_contract = _fold_contract(contract, fold_rows, test_year)
    seasons = contract["historical_mlb_seasons"]
    references = _impact_references(seasons)

    def score(flags: dict | None) -> dict:
        with _model_flags(flags):
            role_models = {
                role: train_role(role, training_rows, now=now)
                for role in ("hitter", "pitcher")
            }
            impact_models = {
                role: train_impact_role(role, training_rows, seasons, references, now=now)
                for role in ("hitter", "pitcher")
            }
            return {
                (row["mlbam_id"], row["role"]): (
                    row["expected_outcome_score"],
                    row["expected_category_impact_score"],
                )
                for row in model_score_current(fold_contract, role_models, impact_models)
            }

    base = score(None)
    cand = score(E1_SPEC["model_flags"])
    counts = {"hitter": {"changed": 0, "total": 0}, "pitcher": {"changed": 0, "total": 0}}
    for key, base_val in base.items():
        role = key[1]
        counts[role]["total"] += 1
        if cand.get(key) != base_val:
            counts[role]["changed"] += 1
    assert counts["hitter"]["changed"] == 0, (
        f"MODEL-LEVEL LEAK: {counts['hitter']['changed']} hitter model scores "
        "moved; the challenger must be pitcher-only"
    )
    assert counts["pitcher"]["changed"] > 0, "challenger changed no pitcher scores"
    return {"fold": test_year, **counts}


# Single-lever ablations (research-only): which lever carries the pooled delta,
# and is either fold-robust on its own? Same exploratory seed; never 28013.
ABLATION_SPECS = {
    "role_split_only": {"model_flags": {"PITCHER_OUTCOME_ROLE_SPLIT_ENABLED": True}},
    "per_group_shrink_only": {"model_flags": {"PITCHER_PER_GROUP_SHRINK_ENABLED": True}},
}


def _within_role_pitcher_metrics(scores: dict, tiers: dict) -> dict:
    """QUARANTINE projection over _fold_metrics: pitcher-only fields.

    _fold_metrics also emits c_hitter / c_all / c_cross_report_only -- a
    hitter-vs-pitcher accuracy readout that must never land in this research
    artifact (one-look quarantine), so only the within-role pitcher fields
    survive into the payload.
    """
    metrics = _fold_metrics(scores, tiers)
    return {k: metrics[k] for k in ("c_pitcher", "pitcher_sample")}


def _ablation_evidence(
    contract: dict, fold_years: list[int], base_by_year: dict
) -> dict:
    out: dict = {}
    for label, spec in ABLATION_SPECS.items():
        pairs: list[dict] = []
        per_fold: list[dict] = []
        for test_year in fold_years:
            base_data = base_by_year[test_year]
            cand_data, _ = _fold_board_scores(contract, test_year, spec)
            if set(base_data["scores"]) != set(cand_data["scores"]):
                raise RuntimeError(
                    f"ablation {label} fold {test_year}: identity sets differ"
                )
            shared = sorted(set(base_data["scores"]) & set(cand_data["scores"]))
            pairs.append(
                {
                    "baseline": base_data["scores"],
                    "candidate": cand_data["scores"],
                    "tiers": {k: base_data["tiers"][k] for k in shared},
                }
            )
            base_m = _within_role_pitcher_metrics(base_data["scores"], base_data["tiers"])
            cand_m = _within_role_pitcher_metrics(cand_data["scores"], cand_data["tiers"])
            per_fold.append(
                {
                    "test_cohort": test_year,
                    "delta_c_pitcher": round(cand_m["c_pitcher"] - base_m["c_pitcher"], 6),
                }
            )
        evidence = paired_bootstrap_lower_bound(
            pairs, "pitcher", n_bootstraps=N_BOOTSTRAPS, seed=EXPLORATORY_SEED
        )
        out[label] = {
            "model_flags": spec["model_flags"],
            "evidence": {
                k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in evidence.items()
            },
            "per_fold_delta_c_pitcher": per_fold,
        }
    return out


def run(contract: dict) -> dict:
    if EXPLORATORY_SEED == REGISTERED_SEED:
        raise RuntimeError(
            "exploratory seed collides with the REGISTERED gate seed; refusing to run"
        )
    fold_years = _fold_years(contract)
    model_level_hitter_freeze = _model_level_hitter_freeze(contract, fold_years)

    fold_pairs: list[dict] = []
    slice_keys_per_fold: list[dict[str, set]] = []
    per_fold_metrics = {"incumbent": [], "challenger": []}
    diagnostics = []
    base_by_year: dict = {}

    for test_year in fold_years:
        base_data, base_diag = _fold_board_scores(contract, test_year, INCUMBENT_SPEC or None)
        base_by_year[test_year] = base_data
        cand_data, _ = _fold_board_scores(contract, test_year, E1_SPEC)

        # Registered invariant (mirrors rank_backtest): both variants must score the
        # exact same identity set, or the paired comparison is incoherent.
        if set(base_data["scores"]) != set(cand_data["scores"]):
            raise RuntimeError(
                f"fold {test_year}: incumbent/challenger identity sets differ"
            )
        shared = sorted(set(base_data["scores"]) & set(cand_data["scores"]))
        fold_pairs.append(
            {
                "baseline": base_data["scores"],
                "candidate": cand_data["scores"],
                "tiers": {k: base_data["tiers"][k] for k in shared},
            }
        )
        slice_keys_per_fold.append(_pitcher_slice_keys(contract, test_year))
        per_fold_metrics["incumbent"].append(
            {
                "test_cohort": test_year,
                **_within_role_pitcher_metrics(base_data["scores"], base_data["tiers"]),
            }
        )
        per_fold_metrics["challenger"].append(
            {
                "test_cohort": test_year,
                **_within_role_pitcher_metrics(cand_data["scores"], cand_data["tiers"]),
            }
        )
        diagnostics.append(base_diag)

    # Headline: paired case-bootstrap on delta_c_pitcher at the EXPLORATORY seed.
    pitcher_evidence = paired_bootstrap_lower_bound(
        fold_pairs, "pitcher", n_bootstraps=N_BOOTSTRAPS, seed=EXPLORATORY_SEED
    )
    # Hitter non-regression. The challenger flags are pitcher-only, so the hitter
    # MODEL output is byte-identical (verified separately at the model level). But
    # the board's cross-role pooled-quantile normalization (rank_v1
    # _apply_role_quantile_model_score_normalization) remaps every role's
    # percentile onto the POOLED value distribution, so shifting pitcher raw scores
    # ripples a tiny amount into hitter BOARD scores. That ripple is a downstream
    # normalization artifact, not the challenger touching hitters, so the board
    # tolerance is a small epsilon rather than exact zero. |delta_c_hitter| far
    # above this would signal a real leak.
    hitter_evidence = paired_bootstrap_lower_bound(
        fold_pairs, "hitter", n_bootstraps=N_BOOTSTRAPS, seed=EXPLORATORY_SEED
    )
    hitter_point = hitter_evidence.get("point")
    hitter_board_epsilon = 5e-3
    assert hitter_point is not None and abs(hitter_point) < hitter_board_epsilon, (
        f"hitter board delta_c={hitter_point!r} exceeds pooled-normalization "
        f"ripple tolerance {hitter_board_epsilon}; possible cross-role leak"
    )

    # Slice deltas (report-only, no bootstrap).
    aa_delta = _slice_delta(
        fold_pairs, [sk["aa_pitcher"] for sk in slice_keys_per_fold]
    )
    young_delta = _slice_delta(
        fold_pairs, [sk["age_le_20_pitcher"] for sk in slice_keys_per_fold]
    )

    def _round_evidence(ev: dict) -> dict:
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in ev.items()}

    return {
        "status": "research_only",
        "kind": "exploratory_replay",
        "gate_look_spent": False,
        "note": (
            "EXPLORATORY dry-run of the E1 pitcher challenger. NOT the registered "
            "look: exploratory seed 28017, E1 model_flags variant, never seed 28013 "
            "on the C1 pedigree lever. The orchestrator decides whether to spend the "
            "one registered look based on these numbers."
        ),
        "exploratory_seed": EXPLORATORY_SEED,
        "registered_seed_avoided": REGISTERED_SEED,
        "n_bootstraps": N_BOOTSTRAPS,
        "bootstrap_lower_bound_z": Z_ONE_SIDED,
        "challenger_flags": E1_SPEC["model_flags"],
        "fold_years": fold_years,
        "delta_c_pitcher": _round_evidence(pitcher_evidence),
        "hitter_non_regression": {
            "delta_c_hitter_board_point": round(hitter_point, 12),
            "board_tolerance": hitter_board_epsilon,
            "board_note": (
                "nonzero is the rank_v1 cross-role pooled-quantile normalization "
                "ripple, not the challenger touching hitters"
            ),
            "model_level_freeze": model_level_hitter_freeze,
        },
        "slices": {"aa_pitcher": aa_delta, "age_le_20_pitcher": young_delta},
        "ablations": _ablation_evidence(contract, fold_years, base_by_year),
        "per_fold_metrics": {
            axis: [
                {k: (round(v, 6) if isinstance(v, float) else v) for k, v in fold.items()}
                for fold in folds
            ]
            for axis, folds in per_fold_metrics.items()
        },
        "fold_diagnostics": diagnostics,
    }


def main() -> dict:
    payload = run(load_input_contract(INPUT_PATH))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(OUTPUT_PATH)
    summary = {
        "output_path": str(OUTPUT_PATH),
        "gate_look_spent": payload["gate_look_spent"],
        "exploratory_seed": payload["exploratory_seed"],
        "delta_c_pitcher_point": payload["delta_c_pitcher"]["point"],
        "delta_c_pitcher_lower_bound": payload["delta_c_pitcher"]["lower_bound"],
        "hitter_delta_c_board": payload["hitter_non_regression"][
            "delta_c_hitter_board_point"
        ],
        "hitter_model_scores_changed": payload["hitter_non_regression"][
            "model_level_freeze"
        ]["hitter"]["changed"],
        "aa_pitcher_delta_c": payload["slices"]["aa_pitcher"]["point_delta_c"],
        "age_le_20_pitcher_delta_c": payload["slices"]["age_le_20_pitcher"]["point_delta_c"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == "__main__":
    main()
