"""Pooled-multi-level vs single-level prospect backtest (non-circular, outcome-gated).

Tests the live-change hypothesis: does scoring a prospect's POOLED multi-level cohort
line predict realized MLB outcomes better than the single highest-level slice the model
serves today? Same trained models per fold; only the TEST-TIME feature vector differs
(pooled candidate vs single-level baseline), both scored against the realized _raw_target
labels (the non-circular target). Runs on the MULTI-LEVEL discriminating subset so the
63% single-level rows (where pooled == single) don't dilute the signal; aggregate sample
across folds clears MIN_GATE_SAMPLE. Reuses the committed dynasty_backtest folding/gate.

Requires the by-level backfill: scripts/build_historical_by_level_lines.py.
OBSERVE-ONLY: prints a verdict, writes nothing live.
"""
from __future__ import annotations

import json
from pathlib import Path

from prospects.dynasty import coherent_distribution
from prospects.gate import decide_gate
from prospects.dynasty_backtest import (
    MIN_GATE_IMPROVEMENT_PCT,
    MIN_GATE_SAMPLE,
    OUTCOME_COMPLETE_THROUGH,
    OUTCOME_HORIZON_YEARS,
    PROBABILITY_TARGETS,
    _actual_distribution,
    _horizon_seasons,
    _score_fold,
    _temporal_stability_guard,
    _weighted_fold_metric,
)
from prospects.universal import (
    INPUT_PATH,
    _base_historical_rows,
    _canonical_feature_vector,
    _feature_vector,
    _num,
    _selected_prediction,
    load_input_contract,
    train_target,
)

ROOT = Path(__file__).resolve().parents[1]
BACKFILL = ROOT / "data" / "prospects" / "raw" / "historical_by_level_lines.json"

HIT_RATE = ("iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip")
HIT_COUNT = ("home_runs", "stolen_bases", "walks", "hits", "strikeouts", "at_bats",
             "doubles", "triples", "runs", "rbi", "sac_flies")
PIT_RATE = ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")
PIT_COUNT = ("strikeouts", "walks", "earned_runs", "hits", "home_runs", "batters_faced",
             "games_played", "games_started", "wins", "losses", "runs")


def _pool_record(original: dict, level_lines: list[dict], role: str) -> dict | None:
    """Mirror the live _pool_current_records: PA/IP-weighted rate means + summed counts,
    tagged at the original (highest-level) record's level/age/draft metadata."""
    wkey = "plate_appearances" if role == "hitter" else "innings_pitched"
    rates = HIT_RATE if role == "hitter" else PIT_RATE
    counts = HIT_COUNT if role == "hitter" else PIT_COUNT
    weights = [_num(ll.get(wkey)) or 0.0 for ll in level_lines]
    total_w = sum(weights)
    if total_w <= 0:
        return None
    pooled = dict(original)
    for key in rates:
        pooled[key] = round(
            sum((_num(ll.get(key)) or 0.0) * w for ll, w in zip(level_lines, weights)) / total_w, 4
        )
    for key in counts:
        pooled[key] = sum(_num(ll.get(key)) or 0.0 for ll in level_lines)
    pooled[wkey] = total_w
    return pooled


def _pooled_features(contract: dict) -> dict:
    """key (mlbam_id, cohort_year, role) -> (pooled_full_features, pooled_canonical) for
    MULTI-LEVEL players where pooling yields a valid feature vector that DIFFERS from single."""
    by_key = {}
    for row in json.loads(BACKFILL.read_text(encoding="utf-8"))["rows"]:
        if row["n_levels"] >= 2:
            by_key[(int(row["mlbam_id"]), int(row["cohort_year"]), row["role"])] = row["level_lines"]
    out = {}
    for record in contract["historical"]["rows"]:
        role = record.get("role")
        key = (int(record.get("mlbam_id") or -1), int(record.get("cohort_year") or -1), role)
        lines = by_key.get(key)
        if not lines:
            continue
        pooled = _pool_record(record, lines, role)
        if pooled is None:
            continue
        full = _feature_vector(pooled, role)
        canon = _canonical_feature_vector(pooled, role)
        single = _feature_vector(record, role)
        if full is None or canon is None or single is None or full == single:
            continue
        out[(key[0], key[1])] = (full, canon)
    return out


def _predict(features, baseline_features, level, age, models) -> dict:
    probs = {}
    for target in PROBABILITY_TARGETS:
        prediction, _ = _selected_prediction(
            models[target], {"level": level, "age": age}, features, baseline_features
        )
        probs[target] = prediction
    return coherent_distribution(probs["established_probability"], probs["star_probability"])


def _role(contract: dict, horizon: dict, role: str, pooled_feats: dict, now: str) -> dict:
    historical = contract["historical"]["rows"]
    base = _base_historical_rows(
        historical, role, mature_through=OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS
    )
    folds = []
    for test_year in sorted({r["cohort_year"] for r in base}):
        train_through = test_year - OUTCOME_HORIZON_YEARS
        training_rows = [r for r in historical if int(r.get("cohort_year") or 9999) <= train_through]
        test = [
            (r, pooled_feats[(r["mlbam_id"], r["cohort_year"])])
            for r in base
            if r["cohort_year"] == test_year and (r["mlbam_id"], r["cohort_year"]) in pooled_feats
        ]
        if not training_rows or not test:
            continue
        models = {t: train_target(role, t, training_rows, horizon, now=now) for t in PROBABILITY_TARGETS}
        candidate = [_predict(pf[0], pf[1], r["level"], r["age"], models) for r, pf in test]
        baseline = [_predict(r["features"], r["baseline_features"], r["level"], r["age"], models) for r, _ in test]
        actual = [_actual_distribution(r, role, horizon) for r, _ in test]
        fold = _score_fold(candidate, baseline, actual)
        fold["test_cohort"] = test_year
        fold["train_rows"] = len(training_rows)
        fold["sources"] = {t: models[t].get("prediction_source") or "level_age_prior" for t in PROBABILITY_TARGETS}
        folds.append(fold)

    sample = sum(f["sample_size"] for f in folds)
    cand_brier = _weighted_fold_metric(folds, "candidate_multiclass_brier")
    base_brier = _weighted_fold_metric(folds, "baseline_multiclass_brier")
    cand_rank = _weighted_fold_metric(folds, "candidate_rank_concordance")
    base_rank = _weighted_fold_metric(folds, "baseline_rank_concordance")
    gate = decide_gate(
        metric="pooled_vs_single_multiclass_brier",
        model_score=cand_brier,
        baselines={"single_level_line": base_brier},
        sample_size=sample,
        cv_method="nested_fixed_horizon_cohort_walk_forward",
        validated_through=str(OUTCOME_COMPLETE_THROUGH),
        min_sample=MIN_GATE_SAMPLE,
        min_improvement_pct=MIN_GATE_IMPROVEMENT_PCT,
        lower_is_better=True,
        now=now,
    )
    stability = _temporal_stability_guard(folds)
    return {
        "role": role, "sample": sample, "fold_count": len(folds),
        "candidate_brier": cand_brier, "baseline_brier": base_brier,
        "candidate_rank": cand_rank, "baseline_rank": base_rank,
        "gate_status": gate["status"], "improvement_pct": gate.get("improvement_pct"),
        "stability": stability["status"], "folds": folds,
    }


def main() -> None:
    contract = load_input_contract(INPUT_PATH)
    now = contract.get("generated_at") or "2026-06-28T00:00:00+00:00"
    horizon = _horizon_seasons(contract)
    pooled_feats = _pooled_features(contract)
    print(f"multi-level discriminating players with valid pooled features: {len(pooled_feats)}\n")
    for role in ("hitter", "pitcher"):
        res = _role(contract, horizon, role, pooled_feats, now)
        print(f"=== {role.upper()} ===  sample={res['sample']} folds={res['fold_count']}")
        print(f"  pooled  Brier {res['candidate_brier']:.5f} | single Brier {res['baseline_brier']:.5f} "
              f"| improvement {res['improvement_pct']}%")
        print(f"  pooled  rank  {res['candidate_rank']:.4f} | single rank  {res['baseline_rank']:.4f}")
        print(f"  GATE: {res['gate_status']}  |  temporal-stability: {res['stability']}")
        for f in res["folds"]:
            cb, bb = f["candidate_multiclass_brier"], f["baseline_multiclass_brier"]
            tag = "pooled<single" if cb is not None and bb is not None and cb < bb else "no-improve"
            print(f"    {f['test_cohort']}: n={f['sample_size']:3d} train={f['train_rows']:4d} "
                  f"pooled {cb:.5f} vs single {bb:.5f}  [{tag}]  src={f['sources']}")
        print()


if __name__ == "__main__":
    main()
