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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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

RAW = json.load(open(Path(__file__).resolve().parents[1] / "data/prospects/raw/valucast_universal_prospect_dataset.json"))
BY_KEY = {
    (int(r["mlbam_id"]), int(r["cohort_year"])): r
    for r in RAW["rows"]
    if r.get("role") == "pitcher" and r.get("mlbam_id")
}


def load_rows(with_strike=True):
    contract = load_input_contract(INPUT_PATH)
    rows = _historical_rows(contract["historical"]["rows"], "pitcher", 2021)
    if not with_strike:
        return rows
    out = []
    for r in rows:
        rec = BY_KEY.get((r["mlbam_id"], r["cohort_year"]))
        extra = strike_pct_extra(rec) if rec else [0.0, 0.0]
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


def run():
    rows = load_rows(with_strike=True)
    cohorts = sorted({r["cohort_year"] for r in rows})
    out = {k: [] for k in ("target", "hurdle", "neighbor", "stack_ridge",
                           "stack_logit", "band_blend")}
    for test_year in cohorts[2:]:
        train = [r for r in rows if r["cohort_year"] < test_year]
        test = [r for r in rows if r["cohort_year"] == test_year]
        tr_can = np.array([r.get("baseline_features", r["features"]) for r in train], float)
        te_can = np.array([r.get("baseline_features", r["features"]) for r in test], float)
        tr_y = np.array([r["target"] for r in train], float)
        te_y = [r["target"] for r in test]

        outer = _fit_prediction_model(train, "hurdle_ridge", RIDGE_LAMBDA)
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
    blend50 = [0.5 * h + 0.5 * n for h, n in zip(out["hurdle"], out["neighbor"])]
    for name, preds in (
        ("hurdle(+strike%)", out["hurdle"]),
        ("50/50 blend (ref)", blend50),
        ("stack_ridge", out["stack_ridge"]),
        ("stack_contrib", out["stack_logit"]),
        ("band_blend", out["band_blend"]),
    ):
        s = _metric("spearman_rho", preds, t) - ns
        k = _metric("kendall_tau_b", preds, t) - nk
        a = _metric("roc_auc", preds, t) - na
        print(f"{name:20s} d-sp {s:+.4f}  d-kt {k:+.4f}  d-auc {a:+.4f}")


if __name__ == "__main__":
    run()
