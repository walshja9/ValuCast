"""Dev: fold-safe learned stacking + per-band blends (shadow, dev cohorts).

Program: docs/program-2026-08-14-pitcher-pass.md. Dev-only, no claims.
Fold hygiene: for TRAINING rows the stacker's inputs are inner-walk-forward
hurdle predictions (trained only on earlier train cohorts) and
leave-one-out 25-NN predictions; test rows use the outer-fold models.
"""
import json
import sys
from pathlib import Path
from statistics import mean

import numpy as np
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prospects.level_translation_challenger import strike_pct_extra
from prospects.model import (
    NEIGHBOR_K,
    RIDGE_LAMBDA,
    _fit_prediction_model,
    _fit_ridge,
    _historical_rows,
    _predict,
)
from prospects.stage1_outcome_proof import _metric
from prospects.universal import INPUT_PATH, load_input_contract

RAW = json.loads(
    (ROOT / "data/prospects/raw/valucast_universal_prospect_dataset.json").read_text(
        encoding="utf-8"
    )
)
RAW_PITCHERS = [
    row for row in RAW["rows"]
    if row.get("role") == "pitcher" and row.get("mlbam_id")
]


def _strike_key(row):
    return int(row["mlbam_id"]), int(row["cohort_year"]), row["level"]


BY_KEY = {_strike_key(row): row for row in RAW_PITCHERS}
if len(BY_KEY) != len(RAW_PITCHERS):
    raise ValueError("duplicate raw strike row for mlbam_id/cohort_year/level")


def strike_coverage():
    rows = [
        row for row in RAW_PITCHERS
        if 2014 <= int(row["cohort_year"]) <= 2022
    ]
    by_cohort = {}
    for row in rows:
        year = int(row["cohort_year"])
        known, total = by_cohort.get(year, (0, 0))
        by_cohort[year] = (known + int(strike_pct_extra(row)[1] == 1.0), total + 1)
    incomplete = {year: counts for year, counts in by_cohort.items() if counts[0] != counts[1]}
    if incomplete:
        raise ValueError(f"incomplete raw strike coverage: {incomplete}")
    return sum(known for known, _ in by_cohort.values()), len(rows), by_cohort


def load_rows(with_strike=True):
    contract = load_input_contract(INPUT_PATH)
    rows = _historical_rows(contract["historical"]["rows"], "pitcher", 2021)
    if not with_strike:
        return rows
    out = []
    for r in rows:
        rec = BY_KEY.get(_strike_key(r))
        if rec is None:
            raise ValueError(f"missing raw strike row for {_strike_key(r)}")
        extra = strike_pct_extra(rec)
        if extra[1] != 1.0:
            raise ValueError(f"invalid raw strike row for {_strike_key(r)}")
        out.append({**r, "features": r["features"] + list(extra)})
    return out


def knn_means(train_feats, train_targets, query_feats, exclude_self=False, k=NEIGHBOR_K):
    """Vectorized 25-NN mean target, matching _fit_neighbors/_neighbor_predict
    (z-scored L2 on canonical features, mean of k nearest)."""
    mu = train_feats.mean(axis=0)
    sd = train_feats.std(axis=0)
    sd[sd == 0] = 1.0
    tz = (train_feats - mu) / sd
    qz = (query_feats - mu) / sd
    d2 = ((qz[:, None, :] - tz[None, :, :]) ** 2).sum(axis=2)
    if exclude_self:
        np.fill_diagonal(d2, np.inf)
    idx = np.argsort(d2, axis=1, kind="stable")[:, :k]
    return train_targets[idx].mean(axis=1)


def hurdle_predict(model, feats):
    return np.array([
        _predict(model["arrival_model"], f) * _predict(model["conditional_model"], f)
        for f in feats
    ])


def metric_deltas(preds, targets, neighbors):
    return tuple(
        _metric(metric, preds, targets) - _metric(metric, neighbors, targets)
        for metric in ("spearman_rho", "kendall_tau_b", "roc_auc")
    )


def print_deltas(name, preds, targets, neighbors):
    spearman, kendall, auc = metric_deltas(preds, targets, neighbors)
    print(f"{name:24s} d-sp {spearman:+.4f}  d-kt {kendall:+.4f}  d-auc {auc:+.4f}")


def run():
    known, total, coverage_by_cohort = strike_coverage()
    cohort_text = " ".join(
        f"{year}={counts[0]}/{counts[1]}"
        for year, counts in sorted(coverage_by_cohort.items())
    )
    print(f"strike coverage: total {known}/{total}; 2022 {coverage_by_cohort[2022][0]}/{coverage_by_cohort[2022][1]}")
    print(f"strike coverage by cohort: {cohort_text}")

    rows = load_rows(with_strike=True)
    cohorts = sorted({r["cohort_year"] for r in rows})
    out = {k: [] for k in ("target", "base_hurdle", "hurdle", "neighbor",
                           "stack_ridge", "stack_logit", "band_blend")}
    for test_year in cohorts[2:]:
        train = [r for r in rows if r["cohort_year"] < test_year]
        test = [r for r in rows if r["cohort_year"] == test_year]
        tr_can = np.array([r.get("baseline_features", r["features"]) for r in train], float)
        te_can = np.array([r.get("baseline_features", r["features"]) for r in test], float)
        tr_y = np.array([r["target"] for r in train], float)
        te_y = [r["target"] for r in test]

        outer = _fit_prediction_model(train, "hurdle_ridge", RIDGE_LAMBDA)
        base_train = [{**r, "features": r["features"][:-2]} for r in train]
        base_outer = _fit_prediction_model(base_train, "hurdle_ridge", RIDGE_LAMBDA)
        if not outer or not base_outer:
            raise ValueError(f"could not fit outer models for cohort {test_year}")
        te_base = hurdle_predict(base_outer, [r["features"][:-2] for r in test])
        te_h = hurdle_predict(outer, [r["features"] for r in test])
        te_n = knn_means(tr_can, tr_y, te_can)

        # Inner-OOF stacker training rows: hurdle trained on earlier train
        # cohorts only; neighbors leave-one-out over full train.
        loo_n = knn_means(tr_can, tr_y, tr_can, exclude_self=True)
        inner_h, inner_n, inner_y = [], [], []
        train_cohorts = sorted({r["cohort_year"] for r in train})
        for inner_year in train_cohorts[2:]:
            inner_train = [r for r in train if r["cohort_year"] < inner_year]
            inner_test_ix = [i for i, r in enumerate(train) if r["cohort_year"] == inner_year]
            im = _fit_prediction_model(inner_train, "hurdle_ridge", RIDGE_LAMBDA)
            if not im:
                continue
            ih = hurdle_predict(im, [train[i]["features"] for i in inner_test_ix])
            inner_h.extend(ih)
            inner_n.extend(loo_n[inner_test_ix])
            inner_y.extend(tr_y[inner_test_ix])
        inner_h, inner_n, inner_y = map(np.array, (inner_h, inner_n, inner_y))

        fallback = [0.5 * h + 0.5 * n for h, n in zip(te_h, te_n)]

        def apply_stack(model, transform):
            if model is None:
                return list(fallback)
            return [
                model["weights"][0] + sum(
                    w * ((v - c) / s)
                    for w, v, c, s in zip(
                        model["weights"][1:], transform(h, n), model["means"], model["stds"]
                    )
                )
                for h, n in zip(te_h, te_n)
            ]

        triple = lambda h, n: [h, n, h * n]
        # Stacker 1: ridge on (h, n, h*n)
        srows = [{"features": triple(h, n), "target": y}
                 for h, n, y in zip(inner_h, inner_n, inner_y)]
        stack_r = apply_stack(_fit_ridge(srows, 1.0) if srows else None, triple)
        # Stacker 2: contributor-target ridge (ordering by P(contributor))
        crows = [{"features": triple(h, n), "target": 1.0 if y > 0 else 0.0}
                 for h, n, y in zip(inner_h, inner_n, inner_y)]
        stack_c = apply_stack(_fit_ridge(crows, 1.0) if crows else None, triple)
        # Per-band blend: alpha per hurdle-zero vs nonzero band, tuned on inner
        if len(inner_y):
            best = {}
            for zero_band in (True, False):
                mask = (inner_h == 0.0) if zero_band else (inner_h > 0.0)
                grid = {}
                for alpha in np.arange(0.0, 1.01, 0.1):
                    blend = alpha * inner_h[mask] + (1 - alpha) * inner_n[mask]
                    grid[round(alpha, 1)] = _metric(
                        "spearman_rho", list(blend), list(inner_y[mask])
                    ) or 0.0
                best[zero_band] = max(grid, key=grid.get)
            band = [
                (best[True] * h + (1 - best[True]) * n) if h == 0.0
                else (best[False] * h + (1 - best[False]) * n)
                for h, n in zip(te_h, te_n)
            ]
        else:
            band = list(fallback)

        out["target"].extend(te_y)
        out["base_hurdle"].extend(te_base)
        out["hurdle"].extend(te_h)
        out["neighbor"].extend(te_n)
        out["stack_ridge"].extend(stack_r)
        out["stack_logit"].extend(stack_c)
        out["band_blend"].extend(band)

    t = out["target"]
    nb = out["neighbor"]
    ns = _metric("spearman_rho", nb, t)
    nk = _metric("kendall_tau_b", nb, t)
    na = _metric("roc_auc", nb, t)
    print(f"pooled n={len(t)}  neighbors: sp {ns:.4f} kt {nk:.4f} auc {na:.4f}")
    mae = lambda preds: mean(abs(p - target) for p, target in zip(preds, t))
    base_blend50 = [
        0.5 * h + 0.5 * n for h, n in zip(out["base_hurdle"], out["neighbor"])
    ]
    print(
        f"MAE: base hurdle {mae(out['base_hurdle']):.6f} -> "
        f"strike hurdle {mae(out['hurdle']):.6f}"
    )
    print(f"MAE: base 50/50 {mae(base_blend50):.6f} vs neighbors {mae(nb):.6f}")

    for alpha in (0.3, 0.5, 0.7):
        blend = [
            alpha * h + (1.0 - alpha) * n
            for h, n in zip(out["base_hurdle"], out["neighbor"])
        ]
        print_deltas(f"base score alpha={alpha:.1f}", blend, t, nb)

    base_ranks = ((rankdata(out["base_hurdle"], method="average") - 1) / (len(t) - 1)).tolist()
    neighbor_ranks = ((rankdata(nb, method="average") - 1) / (len(t) - 1)).tolist()
    for alpha in (0.3, 0.5, 0.7):
        blend = [
            alpha * h + (1.0 - alpha) * n
            for h, n in zip(base_ranks, neighbor_ranks)
        ]
        print_deltas(f"base rank alpha={alpha:.1f}", blend, t, nb)

    distinct_hurdle = sorted(set(out["base_hurdle"]))
    min_gap = min(
        right - left for left, right in zip(distinct_hurdle, distinct_hurdle[1:])
    )
    epsilon_scale = 0.5 * min_gap
    epsilon = [
        h + epsilon_scale * n for h, n in zip(out["base_hurdle"], neighbor_ranks)
    ]
    print_deltas("epsilon tie-break", epsilon, t, nb)

    blend50 = [0.5 * h + 0.5 * n for h, n in zip(out["hurdle"], out["neighbor"])]
    for name, preds in (
        ("hurdle(+strike%)", out["hurdle"]),
        ("50/50 +strike", blend50),
        ("stack_ridge", out["stack_ridge"]),
        ("stack_contrib", out["stack_logit"]),
        ("band_blend", out["band_blend"]),
    ):
        print_deltas(name, preds, t, nb)


if __name__ == "__main__":
    run()
