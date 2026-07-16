"""Level-translation challenger — EXPLORATORY dry-run (research-only, look NOT spent).

Dry-runs the fitted level-translation challenger and the pitcher strike% lever
(prospects/level_translation_challenger.py; all flags OFF by default) against
the incumbent, on BOTH registered gate axes, using the SAME fold structure and
the SAME bootstrap machinery as the registered harnesses:

  AXIS A — dynasty multiclass-Brier improvement % PER ROLE, over the identical
    nested fixed-horizon cohort walk-forward folds that
    prospects/dynasty_backtest.py uses (test cohorts 2018/2019/2021,
    train_through = test - 4), with the identical paired player-cluster
    bootstrap resampling (dynasty_backtest._delta_pct + the
    _cluster_bootstrap_delta_ci loop), reported with the one-sided 98.33%
    normal-approx lower bound the rank-gate machinery uses (Z_ONE_SIDED).

  AXIS B — within-role tier-concordance delta (delta_c) over the SAME folds via
    prospects.rank_backtest._fold_board_scores + paired_bootstrap_lower_bound
    (the registered 98.33% LB procedure), pitcher and hitter reported
    SEPARATELY. QUARANTINE: only within-role fields ever land in this artifact
    (no c_all / c_cross / any hitter-vs-pitcher comparison).

This is EXPLORATORY only:
  * EXPLORATORY seed 31017 — never the registered 28013, never the spent
    exploratory 28017, never the test seed 29001, and never the PROPOSED (not
    yet run) registered seed 31013.
  * Output labeled research_only / exploratory_replay / gate_look_spent: false,
    written OUTSIDE data/models/ (data/validation/level_translation_dryrun.json).

Fold hygiene: the translation table is refit INSIDE every fold from that fold's
training window only (train_through = test_year - 4); per-fold table
fingerprints are recorded and asserted pairwise distinct. Test-cohort players
cannot appear in the anchor set: the deduped row selection keeps each player's
EARLIEST cohort, so a player whose row lands in the test cohort has no row at or
below train_through by construction.

Strike% counts (pitches/strikes) live on the RAW dataset rows
(data/prospects/raw/valucast_universal_prospect_dataset.json) but are excluded
by the contract's _HISTORICAL_FIELDS whitelist, so this script joins them into
the in-memory contract copy only. Nothing on disk changes; the served path
never sees them.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from prospects import level_translation_challenger as ltc  # noqa: E402
from prospects.dynasty_backtest import (  # noqa: E402
    OUTCOME_COMPLETE_THROUGH,
    OUTCOME_HORIZON_YEARS,
    PROBABILITY_TARGETS,
    _actual_distribution,
    _delta_pct,
    _horizon_seasons,
    _multiclass_brier,
    _predicted_distribution,
)
from prospects.model import (  # noqa: E402
    _impact_references,
    score_current as model_score_current,
    train_impact_role,
    train_role,
)
from prospects.rank_backtest import (  # noqa: E402
    BOOTSTRAP_SEED as REGISTERED_SEED,
    N_BOOTSTRAPS,
    Z_ONE_SIDED,
    _eligible_fold_rows,
    _fold_board_scores,
    _fold_contract,
    _fold_metrics,
    _fold_now,
    _model_flags,
    paired_bootstrap_lower_bound,
)
from prospects.universal import (  # noqa: E402
    INPUT_PATH,
    _base_historical_rows,
    load_input_contract,
    train_target,
)

ROOT = Path(__file__).resolve().parents[1]
RAW_DATASET_PATH = ROOT / "data" / "prospects" / "raw" / "valucast_universal_prospect_dataset.json"
OUTPUT_PATH = ROOT / "data" / "validation" / "level_translation_dryrun.json"

# EXPLORATORY seed for this wave. Guarded below against every burned seed and
# against the proposed-but-never-run registered seed 31013.
EXPLORATORY_SEED = 31017
FORBIDDEN_SEEDS = {28013, 28017, 29001, 31013}

INCUMBENT_SPEC: dict = {}
ABLATION_SPECS = {
    "fitted_translation_only": {
        "model_flags": {"LEVEL_TRANSLATION_FITTED_ENABLED": True},
        "needs_table": True,
    },
    "strike_pct_only": {
        "model_flags": {"PITCHER_STRIKE_PCT_ENABLED": True},
        "needs_table": False,
    },
    "both": {
        "model_flags": {
            "LEVEL_TRANSLATION_FITTED_ENABLED": True,
            "PITCHER_STRIKE_PCT_ENABLED": True,
        },
        "needs_table": True,
    },
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


def _augment_contract_with_counts(contract: dict) -> tuple[dict, dict]:
    """In-memory join of raw pitch/strike counts onto historical pitcher rows.

    Keyed (mlbam_id, cohort_year, level) — verified unique in the raw dataset.
    Returns (augmented contract copy, join diagnostics). Disk untouched."""
    raw = json.loads(RAW_DATASET_PATH.read_text(encoding="utf-8"))
    counts = {}
    for row in raw.get("rows", []):
        if row.get("role") != "pitcher" or row.get("pitches") is None:
            continue
        key = (row.get("mlbam_id"), row.get("cohort_year"), str(row.get("level")))
        counts[key] = (row.get("pitches"), row.get("strikes"))
    joined = 0
    pitcher_rows = 0
    new_rows = []
    for row in contract["historical"]["rows"]:
        if row.get("role") != "pitcher":
            new_rows.append(row)
            continue
        pitcher_rows += 1
        key = (row.get("mlbam_id"), row.get("cohort_year"), str(row.get("level")))
        found = counts.get(key)
        if found is None:
            new_rows.append(row)
            continue
        joined += 1
        new_rows.append({**row, "pitches": found[0], "strikes": found[1]})
    augmented = {
        **contract,
        "historical": {**contract["historical"], "rows": new_rows},
    }
    return augmented, {"pitcher_rows": pitcher_rows, "joined": joined}


def _paired_cluster_delta_pct(
    cand_err: np.ndarray, base_err: np.ndarray, cluster_ids: np.ndarray
) -> dict:
    """Per-role Brier delta%: point + bootstrap evidence at the exploratory seed.

    The resampling loop is dynasty_backtest._cluster_bootstrap_delta_ci's,
    verbatim (paired player-cluster case bootstrap on _delta_pct), extended with
    the one-sided 98.33% normal-approx lower bound (Z_ONE_SIDED) the rank-gate
    machinery reports. No new evaluation protocol — same resamples, same delta."""
    point = _delta_pct(cand_err, base_err, lower_is_better=True)
    unique, inverse = np.unique(cluster_ids, return_inverse=True)
    members = [np.flatnonzero(inverse == index) for index in range(len(unique))]
    cluster_count = len(unique)
    rng = np.random.default_rng(EXPLORATORY_SEED)
    deltas = np.empty(N_BOOTSTRAPS)
    for draw in range(N_BOOTSTRAPS):
        picks = rng.integers(0, cluster_count, cluster_count)
        index = np.concatenate([members[pick] for pick in picks])
        deltas[draw] = _delta_pct(cand_err[index], base_err[index], lower_is_better=True)
    sd = float(np.std(deltas, ddof=1))
    low, high = np.percentile(deltas, [2.5, 97.5])
    return {
        "point": round(point, 4),
        "ci_low_95": round(float(low), 4),
        "ci_high_95": round(float(high), 4),
        "lower_bound_9833": round(point - Z_ONE_SIDED * sd, 4),
        "bootstrap_sd": round(sd, 4),
        "n_bootstraps": N_BOOTSTRAPS,
        "seed": EXPLORATORY_SEED,
        "cluster_count": cluster_count,
    }


def _within_role_metrics(scores: dict, tiers: dict) -> dict:
    """QUARANTINE projection over _fold_metrics: within-role fields ONLY.

    _fold_metrics also emits c_all / c_cross_report_only — cross-role accuracy
    readouts that must never land in this research artifact."""
    metrics = _fold_metrics(scores, tiers)
    return {
        k: metrics[k]
        for k in ("c_pitcher", "pitcher_sample", "c_hitter", "hitter_sample")
    }


def _brier_axis_variant(
    contract: dict,
    fold_years: list[int],
    horizon_seasons: dict,
    tables: dict,
    spec: dict | None,
) -> dict:
    """Per-fold dynasty candidate distributions for one variant.

    Mirrors dynasty_backtest._role_backtest's fold loop exactly (same test-row
    selection, same trainers, same distributions), with the variant's flags and
    per-fold translation table active around BOTH training and scoring."""
    flags = (spec or {}).get("model_flags")
    needs_table = bool((spec or {}).get("needs_table"))
    historical = contract["historical"]["rows"]
    out: dict = {"hitter": [], "pitcher": []}
    for test_year in fold_years:
        table = tables[test_year] if needs_table else None
        train_through = test_year - OUTCOME_HORIZON_YEARS
        training_rows = [
            row
            for row in historical
            if int(row.get("cohort_year") or 9999) <= train_through
        ]
        now = _fold_now(test_year)
        with _model_flags(flags), ltc.active_translation(table):
            for role in ("hitter", "pitcher"):
                role_rows = _base_historical_rows(
                    historical,
                    role,
                    mature_through=OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS,
                )
                test_rows = [
                    row for row in role_rows if row["cohort_year"] == test_year
                ]
                if not training_rows or not test_rows:
                    continue
                models = {
                    target: train_target(
                        role, target, training_rows, horizon_seasons, now=now
                    )
                    for target in PROBABILITY_TARGETS
                }
                candidate = [
                    _predicted_distribution(row, models, "selected")
                    for row in test_rows
                ]
                actual = [
                    _actual_distribution(row, role, horizon_seasons)
                    for row in test_rows
                ]
                out[role].append(
                    {
                        "test_cohort": test_year,
                        "mlbam_ids": [row["mlbam_id"] for row in test_rows],
                        "candidate": candidate,
                        "actual": actual,
                    }
                )
    return out


def _brier_axis_evidence(incumbent: dict, variant: dict) -> dict:
    """Within-role Brier improvement % (variant vs incumbent) + per-fold detail."""
    evidence = {}
    for role in ("hitter", "pitcher"):
        base_err, cand_err, clusters = [], [], []
        per_fold = []
        for base_fold, cand_fold in zip(incumbent[role], variant[role]):
            if base_fold["mlbam_ids"] != cand_fold["mlbam_ids"]:
                raise RuntimeError(
                    f"{role} fold {base_fold['test_cohort']}: identity sets differ"
                )
            actual = base_fold["actual"]
            fold_base = [
                sum((b[k] - a[k]) ** 2 for k in a)
                for b, a in zip(base_fold["candidate"], actual)
            ]
            fold_cand = [
                sum((c[k] - a[k]) ** 2 for k in a)
                for c, a in zip(cand_fold["candidate"], actual)
            ]
            base_err.extend(fold_base)
            cand_err.extend(fold_cand)
            clusters.extend(base_fold["mlbam_ids"])
            base_brier = _multiclass_brier(base_fold["candidate"], actual)
            cand_brier = _multiclass_brier(cand_fold["candidate"], actual)
            per_fold.append(
                {
                    "test_cohort": base_fold["test_cohort"],
                    "n": len(actual),
                    "incumbent_brier": round(base_brier, 6),
                    "challenger_brier": round(cand_brier, 6),
                    "improvement_pct": round(
                        (base_brier - cand_brier) / base_brier * 100.0, 4
                    )
                    if base_brier
                    else None,
                }
            )
        evidence[role] = {
            "pooled": _paired_cluster_delta_pct(
                np.array(cand_err), np.array(base_err), np.array(clusters)
            ),
            "per_fold": per_fold,
        }
    return evidence


def _strike_hitter_freeze(contract: dict, fold_years: list[int]) -> dict:
    """Model-level invariant for the strike% lever: ZERO hitter scores move.

    Mirrors run_e1_exploratory_replay._model_level_hitter_freeze. Only asserted
    for strike_pct_only — the translation lever legitimately moves hitters."""
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
    cand = score(ABLATION_SPECS["strike_pct_only"]["model_flags"])
    counts = {"hitter": {"changed": 0, "total": 0}, "pitcher": {"changed": 0, "total": 0}}
    for key, base_val in base.items():
        role = key[1]
        counts[role]["total"] += 1
        if cand.get(key) != base_val:
            counts[role]["changed"] += 1
    assert counts["hitter"]["changed"] == 0, (
        f"MODEL-LEVEL LEAK: {counts['hitter']['changed']} hitter model scores "
        "moved; the strike% lever must be pitcher-only"
    )
    assert counts["pitcher"]["changed"] > 0, "strike% lever changed no pitcher scores"
    return {"fold": test_year, **counts}


def _round_evidence(evidence: dict) -> dict:
    return {
        k: (round(v, 6) if isinstance(v, float) else v) for k, v in evidence.items()
    }


def run(contract: dict) -> dict:
    if EXPLORATORY_SEED in FORBIDDEN_SEEDS or EXPLORATORY_SEED == REGISTERED_SEED:
        raise RuntimeError(
            "exploratory seed collides with a burned/registered/proposed seed; "
            "refusing to run"
        )
    contract, join_diag = _augment_contract_with_counts(contract)
    fold_years = _fold_years(contract)

    # Fold-fitted translation tables (fold hygiene: training window only).
    tables = {
        year: ltc.fit_translation_table(
            contract["historical"]["rows"],
            contract["historical_mlb_seasons"],
            year - OUTCOME_HORIZON_YEARS,
        )
        for year in fold_years
    }
    fingerprints = {year: tables[year]["fingerprint"] for year in fold_years}
    if len(set(fingerprints.values())) != len(fingerprints):
        raise RuntimeError(
            f"fold translation tables are not distinct: {fingerprints}"
        )

    strike_freeze = _strike_hitter_freeze(contract, fold_years)

    # ---- AXIS A: dynasty Brier per role ---------------------------------------
    horizon_seasons = _horizon_seasons(contract)  # flags off; feature-independent
    incumbent_brier = _brier_axis_variant(
        contract, fold_years, horizon_seasons, tables, None
    )
    brier_axis = {}
    for label, spec in ABLATION_SPECS.items():
        variant = _brier_axis_variant(
            contract, fold_years, horizon_seasons, tables, spec
        )
        brier_axis[label] = _brier_axis_evidence(incumbent_brier, variant)

    # ---- AXIS B: board within-role delta_c -------------------------------------
    base_by_year: dict[int, dict] = {}
    incumbent_fold_metrics = []
    for test_year in fold_years:
        base_data, _diag = _fold_board_scores(contract, test_year, None)
        base_by_year[test_year] = base_data
        incumbent_fold_metrics.append(
            {
                "test_cohort": test_year,
                **_within_role_metrics(base_data["scores"], base_data["tiers"]),
            }
        )
    delta_c_axis = {}
    for label, spec in ABLATION_SPECS.items():
        fold_pairs = []
        per_fold = []
        for test_year in fold_years:
            table = tables[test_year] if spec["needs_table"] else None
            with ltc.active_translation(table):
                cand_data, _ = _fold_board_scores(
                    contract, test_year, {"model_flags": spec["model_flags"]}
                )
            base_data = base_by_year[test_year]
            if set(base_data["scores"]) != set(cand_data["scores"]):
                raise RuntimeError(
                    f"{label} fold {test_year}: identity sets differ"
                )
            shared = sorted(set(base_data["scores"]) & set(cand_data["scores"]))
            fold_pairs.append(
                {
                    "baseline": base_data["scores"],
                    "candidate": cand_data["scores"],
                    "tiers": {k: base_data["tiers"][k] for k in shared},
                }
            )
            base_m = _within_role_metrics(base_data["scores"], base_data["tiers"])
            cand_m = _within_role_metrics(cand_data["scores"], cand_data["tiers"])
            per_fold.append(
                {
                    "test_cohort": test_year,
                    "delta_c_pitcher": round(
                        cand_m["c_pitcher"] - base_m["c_pitcher"], 6
                    ),
                    "delta_c_hitter": round(cand_m["c_hitter"] - base_m["c_hitter"], 6),
                    "pitcher_sample": base_m["pitcher_sample"],
                    "hitter_sample": base_m["hitter_sample"],
                }
            )
        delta_c_axis[label] = {
            "pitcher": _round_evidence(
                paired_bootstrap_lower_bound(
                    fold_pairs, "pitcher", n_bootstraps=N_BOOTSTRAPS, seed=EXPLORATORY_SEED
                )
            ),
            "hitter": _round_evidence(
                paired_bootstrap_lower_bound(
                    fold_pairs, "hitter", n_bootstraps=N_BOOTSTRAPS, seed=EXPLORATORY_SEED
                )
            ),
            "per_fold": per_fold,
        }

    return {
        "status": "research_only",
        "kind": "exploratory_replay",
        "gate_look_spent": False,
        "note": (
            "EXPLORATORY dry-run of the fitted level-translation challenger + "
            "pitcher strike% lever. NOT the registered look: exploratory seed "
            "31017; the proposed registered seed 31013 has never been executed. "
            "The orchestrator decides whether to spend the one registered look "
            "based on these numbers. Within-role metrics only."
        ),
        "exploratory_seed": EXPLORATORY_SEED,
        "registered_seed_avoided": REGISTERED_SEED,
        "n_bootstraps": N_BOOTSTRAPS,
        "bootstrap_lower_bound_z": Z_ONE_SIDED,
        "fold_years": fold_years,
        "strike_count_join": join_diag,
        "translation_table_fingerprints": fingerprints,
        "translation_table_anchor_counts": {
            year: {
                role: {
                    stat: tables[year]["roles"][role][stat]["anchor_count"]
                    for stat in tables[year]["roles"][role]
                }
                for role in tables[year]["roles"]
            }
            for year in fold_years
        },
        "strike_pct_hitter_freeze": strike_freeze,
        "dynasty_brier_improvement_pct": brier_axis,
        "board_delta_c": delta_c_axis,
        "incumbent_board_per_fold": incumbent_fold_metrics,
    }


def main() -> dict:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    payload = run(load_input_contract(INPUT_PATH))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(OUTPUT_PATH)
    summary = {
        "output_path": str(OUTPUT_PATH),
        "gate_look_spent": payload["gate_look_spent"],
        "exploratory_seed": payload["exploratory_seed"],
        "dynasty_brier_improvement_pct": {
            label: {
                role: evidence[role]["pooled"]
                for role in ("hitter", "pitcher")
            }
            for label, evidence in payload["dynasty_brier_improvement_pct"].items()
        },
        "board_delta_c": {
            label: {
                role: {
                    k: evidence[role][k]
                    for k in ("point", "lower_bound")
                }
                for role in ("hitter", "pitcher")
            }
            for label, evidence in payload["board_delta_c"].items()
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == "__main__":
    main()
