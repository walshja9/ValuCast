"""Phase A dev harness (shadow, dev cohorts only — NOT a registered look).

Program: pitcher-pass (owner-approved A+B, 2026-08-14). Evaluates
tie-killing architecture variants for the pitcher outcome layer on the
five seen development cohorts. Unlimited dev looks are allowed here; the
confirmatory claim comes only from the Phase C registration with the
pristine 2022 holdout. Nothing here touches served scoring.
"""
import json
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.model import (
    OUTCOME_MODEL_KIND,
    RIDGE_LAMBDA,
    _fit_neighbors,
    _fit_prediction_model,
    _fit_prior,
    _fit_ridge,
    _historical_rows,
    _neighbor_predict,
    _predict,
    _prior_predict,
)
from prospects.stage1_outcome_proof import _metric
from prospects.universal import INPUT_PATH, load_input_contract

DEV_MATURE_THROUGH = 2021


def _linear(model, features):
    """Raw ridge linear output — no [0,1] clamp."""
    standardized = [
        (v - c) / s for v, c, s in zip(features, model["means"], model["stds"])
    ]
    return model["weights"][0] + sum(
        w * v for w, v in zip(model["weights"][1:], standardized)
    )


def _sigmoid(x):
    import math
    return 1.0 / (1.0 + math.exp(-x))


def walk_forward_variants(role_rows):
    cohorts = sorted({row["cohort_year"] for row in role_rows})
    out = {k: [] for k in (
        "target", "served", "v1_unclamped_product", "v2_sigmoid_product",
        "v3_arrival_only", "neighbor", "prior",
    )}
    for test_year in cohorts[2:]:
        train = [r for r in role_rows if r["cohort_year"] < test_year]
        test = [r for r in role_rows if r["cohort_year"] == test_year]
        served = _fit_prediction_model(train, OUTCOME_MODEL_KIND["pitcher"], RIDGE_LAMBDA)
        arrival = _fit_ridge(
            [{**r, "target": 1.0 if r["target"] > 0 else 0.0} for r in train],
            RIDGE_LAMBDA,
        )
        conditional = _fit_ridge([r for r in train if r["target"] > 0], RIDGE_LAMBDA)
        canonical_train = [
            {**r, "features": r.get("baseline_features", r["features"])} for r in train
        ]
        neighbors = _fit_neighbors(canonical_train)
        prior = _fit_prior(train)
        if not served or not arrival or not conditional or not neighbors or not test:
            continue
        for r in test:
            f = r["features"]
            a_lin = _linear(arrival, f)
            c_clamped = _predict(conditional, f)
            out["target"].append(r["target"])
            out["served"].append(_predict(served["arrival_model"], f) * c_clamped)
            out["v1_unclamped_product"].append(a_lin * max(c_clamped, 1e-6))
            out["v2_sigmoid_product"].append(_sigmoid(4.0 * (a_lin - 0.5)) * c_clamped)
            out["v3_arrival_only"].append(a_lin)
            out["neighbor"].append(
                _neighbor_predict(neighbors, r.get("baseline_features", r["features"]))
            )
            out["prior"].append(_prior_predict(prior, r))
    return out


def report(out):
    targets = out["target"]
    n = len(targets)
    print(f"dev pitcher pooled n = {n}")
    print(f"{'variant':26s} {'spearman':>9s} {'kendall':>9s} {'auc':>9s} {'mae':>8s} {'maxtie':>7s}")
    for name in ("served", "v1_unclamped_product", "v2_sigmoid_product",
                 "v3_arrival_only", "neighbor", "prior"):
        preds = out[name]
        s = _metric("spearman_rho", preds, targets)
        k = _metric("kendall_tau_b", preds, targets)
        a = _metric("roc_auc", preds, targets)
        m = mean(abs(p - t) for p, t in zip(preds, targets))
        from collections import Counter
        maxtie = Counter(round(p, 10) for p in preds).most_common(1)[0][1]
        print(f"{name:26s} {s:9.4f} {k:9.4f} {a:9.4f} {m:8.4f} {maxtie:7d}")
    nb = out["neighbor"]
    for name in ("served", "v1_unclamped_product", "v2_sigmoid_product", "v3_arrival_only"):
        s = _metric("spearman_rho", out[name], targets) - _metric("spearman_rho", nb, targets)
        k = _metric("kendall_tau_b", out[name], targets) - _metric("kendall_tau_b", nb, targets)
        a = _metric("roc_auc", out[name], targets) - _metric("roc_auc", nb, targets)
        print(f"delta vs neighbors  {name:26s} spearman {s:+.4f}  kendall {k:+.4f}  auc {a:+.4f}")


def main():
    contract = load_input_contract(INPUT_PATH)
    rows = _historical_rows(contract["historical"]["rows"], "pitcher", DEV_MATURE_THROUGH)
    out = walk_forward_variants(rows)
    report(out)


if __name__ == "__main__":
    main()
