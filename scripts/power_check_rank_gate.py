"""Power check for the Rank-gate v1 registration thresholds (Sol design #5).

Before freezing the pre-registered acceptance criteria (delta-C >= +0.005 with
a one-sided 98.33% bootstrap lower bound above zero, three folds, one look),
this simulation asks: could a GENUINELY GOOD lever even pass that bar? If a
true effect of plausible size fails most of the time, the gate is not strict,
it is an unpassable veto -- and the honest move is registering a threshold the
evidence could actually clear.

Anchored to the frozen historical fold structure registered in Plan 028 and
data/prospects/prospect_model_inputs.json (the former DD adapter artifact is
retired and is not a runtime dependency):
- real fold sizes and per-fold candidate concordances,
- real bust/role/star tier mixes per fold (ties are dropped by the metric, so
  the ~80% bust share collapses the effective sample),
- levers simulated as ORACLE-OPTIMAL (effect applied in the exactly right
  direction), so reported power is an UPPER bound on real-lever power.

Run once, commit the output with the registration. Seed 28013 (registered).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import norm  # scipy is available transitively; fall back below if not

ROOT = Path(__file__).resolve().parents[1]

# Real per-fold structure: (test_cohort, {tier: count}, candidate concordance).
FOLDS = {
    "hitter": [
        (2018, {"bust": 282, "role": 59, "star": 4}, 0.796306),
        (2019, {"bust": 305, "role": 44, "star": 11}, 0.730732),
        (2021, {"bust": 310, "role": 64, "star": 12}, 0.808877),
    ],
    "pitcher": [
        (2018, {"bust": 285, "role": 55, "star": 12}, 0.450922),
        (2019, {"bust": 343, "role": 57, "star": 10}, 0.484980),
        (2021, {"bust": 309, "role": 49, "star": 7}, 0.469247),
    ],
}
TIER_VALUE = {"bust": 0.0, "role": 0.5, "star": 1.0}

SEED = 28013
N_SIMS = 400
N_BOOT = 2000
Z_ONE_SIDED = norm.ppf(1 - 0.05 / 3)  # Bonferroni 98.33% one-sided, per Sol
POINT_THRESHOLD = 0.005


def _phi(x):
    return norm.cdf(x)


def calibrate_signal(counts: dict, target_c: float) -> float:
    """Solve for signal strength a in pred = a*outcome + N(0,1) such that the
    closed-form aggregate concordance over this tier mix equals target_c."""
    tiers = [(TIER_VALUE[t], n) for t, n in counts.items() if n > 0]
    pairs = []
    for i, (v1, n1) in enumerate(tiers):
        for v2, n2 in tiers[i + 1:]:
            lo, hi = min(v1, v2), max(v1, v2)
            pairs.append((hi - lo, n1 * n2))
    total = sum(w for _, w in pairs)

    def agg_c(a):
        return sum(w * _phi(a * gap / np.sqrt(2)) for gap, w in pairs) / total

    lo_a, hi_a = -8.0, 8.0
    for _ in range(80):
        mid = (lo_a + hi_a) / 2
        if agg_c(mid) < target_c:
            lo_a = mid
        else:
            hi_a = mid
    return (lo_a + hi_a) / 2


def concordance_rows(preds: np.ndarray, outcomes: np.ndarray) -> np.ndarray:
    """Tie-dropping pairwise concordance per row. preds/outcomes: (B, n).
    Predictions are continuous (no pred ties). Vectorized via sorted cumsums."""
    order = np.argsort(preds, axis=1)
    osorted = np.take_along_axis(outcomes, order, axis=1)
    conc = np.zeros(preds.shape[0])
    disc = np.zeros(preds.shape[0])
    values = (0.0, 0.5, 1.0)
    ind = {v: (osorted == v).astype(np.float64) for v in values}
    cum = {v: np.cumsum(ind[v], axis=1) - ind[v] for v in values}  # strictly-before counts
    # ascending pred order: higher tier after lower tier = concordant
    conc += np.sum(ind[0.5] * cum[0.0] + ind[1.0] * (cum[0.0] + cum[0.5]), axis=1)
    disc += np.sum(ind[0.0] * (cum[0.5] + cum[1.0]) + ind[0.5] * cum[1.0], axis=1)
    return conc / np.maximum(conc + disc, 1.0)


def weighted_fold_metric(pred_rows, out_rows, fold_slices, fold_weights):
    """Per-fold concordance then sample-weighted mean (mirrors the harness)."""
    per_fold = []
    for sl in fold_slices:
        per_fold.append(concordance_rows(pred_rows[:, sl], out_rows[:, sl]))
    per_fold = np.stack(per_fold, axis=1)  # (B, n_folds)
    w = np.asarray(fold_weights, dtype=np.float64)
    return per_fold @ (w / w.sum())


def build_population(role: str, rng):
    """One simulated dataset for a role: outcomes fixed by real tier counts,
    preds = a_fold * outcome + N(0,1), a_fold calibrated to the real fold C."""
    outcomes, preds, slices, weights = [], [], [], []
    start = 0
    for _, counts, fold_c in FOLDS[role]:
        o = np.concatenate([
            np.full(n, TIER_VALUE[t]) for t, n in counts.items()
        ])
        a = calibrate_signal(counts, fold_c)
        p = a * o + rng.standard_normal(o.shape[0])
        outcomes.append(o)
        preds.append(p)
        n = o.shape[0]
        slices.append(slice(start, start + n))
        weights.append(n)
        start += n
    return np.concatenate(preds), np.concatenate(outcomes), slices, weights


def bootstrap_lower_bound(pred0, pred1, outcomes, slices, weights, rng):
    """Paired, fold-stratified bootstrap of delta-C; normal-approx one-sided
    lower bound at the Bonferroni level. Returns (point_delta, lower_bound)."""
    n = outcomes.shape[0]
    idx = np.empty((N_BOOT, n), dtype=np.int64)
    for sl in slices:
        lo, hi = sl.start, sl.stop
        idx[:, lo:hi] = rng.integers(lo, hi, size=(N_BOOT, hi - lo))
    o_b = outcomes[idx]
    d_b = (
        weighted_fold_metric(pred1[idx], o_b, slices, weights)
        - weighted_fold_metric(pred0[idx], o_b, slices, weights)
    )
    point = float(
        weighted_fold_metric(pred1[None, :], outcomes[None, :], slices, weights)[0]
        - weighted_fold_metric(pred0[None, :], outcomes[None, :], slices, weights)[0]
    )
    return point, point - Z_ONE_SIDED * float(d_b.std(ddof=1))


def calibrate_lever_within(role, target_delta, subset_share, rng):
    """Find lambda so the conditional oracle lever (pred += lam*outcome on a
    random subset) produces population delta-C = target_delta. Calibrated on a
    20x-replicated population to kill noise."""
    reps = 20
    p0_list, o_list, s_list, w_list = [], [], [], []
    for _ in range(reps):
        p0, o, sl, w = build_population(role, rng)
        p0_list.append(p0)
        o_list.append(o)
    p0 = np.concatenate(p0_list)
    o = np.concatenate(o_list)
    # single pooled slice is fine for calibration (population-level delta)
    slices = [slice(0, o.shape[0])]
    weights = [o.shape[0]]
    mask = rng.random(o.shape[0]) < subset_share

    def delta(lam):
        p1 = p0 + lam * o * mask
        return float(
            weighted_fold_metric(p1[None, :], o[None, :], slices, weights)[0]
            - weighted_fold_metric(p0[None, :], o[None, :], slices, weights)[0]
        )

    lo_l, hi_l = 0.0, 6.0
    for _ in range(40):
        mid = (lo_l + hi_l) / 2
        if delta(mid) < target_delta:
            lo_l = mid
        else:
            hi_l = mid
    return (lo_l + hi_l) / 2


def experiment_within_pitcher(target_deltas, subset_share=0.25):
    """C1 shape: conditional within-pitcher improvement (oracle direction)."""
    rng = np.random.default_rng(SEED)
    results = {}
    for target in target_deltas:
        lam = calibrate_lever_within("pitcher", target, subset_share, rng)
        passes, points, bounds = 0, [], []
        for _ in range(N_SIMS):
            p0, o, slices, weights = build_population("pitcher", rng)
            mask = rng.random(o.shape[0]) < subset_share
            p1 = p0 + lam * o * mask
            point, lower = bootstrap_lower_bound(p0, p1, o, slices, weights, rng)
            ok = (point >= POINT_THRESHOLD) and (lower > 0)
            passes += int(ok)
            points.append(point)
            bounds.append(lower)
        results[target] = {
            "power": passes / N_SIMS,
            "median_point": float(np.median(points)),
            "median_lower_bound": float(np.median(bounds)),
            "lambda": lam,
        }
    return results


def experiment_cross_role(target_deltas):
    """C2/C3 shape: uniform pitcher down-shift against an injected lean.

    Baseline injects a pitcher score bias (the lean); the lever removes it
    exactly (k = bias, the best case). Bias per target is calibrated so the
    full correction yields population delta-C_cross = target."""
    rng = np.random.default_rng(SEED + 1)

    def build_pooled(bias, rng_local):
        preds, outs, roles_arr, slices, weights = [], [], [], [], []
        start = 0
        for fold_i in range(3):
            fold_p, fold_o, fold_r = [], [], []
            for role in ("hitter", "pitcher"):
                _, counts, fold_c = FOLDS[role][fold_i]
                o = np.concatenate([np.full(n, TIER_VALUE[t]) for t, n in counts.items()])
                a = calibrate_signal(counts, fold_c)
                p = a * o + rng_local.standard_normal(o.shape[0])
                if role == "pitcher":
                    p = p + bias
                fold_p.append(p)
                fold_o.append(o)
                fold_r.append(np.full(o.shape[0], 1.0 if role == "pitcher" else 0.0))
            fp, fo, fr = map(np.concatenate, (fold_p, fold_o, fold_r))
            preds.append(fp)
            outs.append(fo)
            roles_arr.append(fr)
            n = fo.shape[0]
            slices.append(slice(start, start + n))
            weights.append(n)
            start += n
        return (
            np.concatenate(preds),
            np.concatenate(outs),
            np.concatenate(roles_arr),
            slices,
            weights,
        )

    def cross_concordance(pred_rows, out_rows, role_rows, fold_slices, fold_weights):
        """Concordance restricted to cross-role, tier-differing pairs:
        C_cross = conc_all - conc_within, computed by inclusion-exclusion on
        pair counts. Implemented directly: score pairs via the same sorted-cum
        trick but only counting hitter-vs-pitcher pairs."""
        per_fold = []
        for sl in fold_slices:
            p = pred_rows[:, sl]
            o = out_rows[:, sl]
            r = role_rows[:, sl]
            order = np.argsort(p, axis=1)
            os_ = np.take_along_axis(o, order, axis=1)
            rs_ = np.take_along_axis(r, order, axis=1)
            conc = np.zeros(p.shape[0])
            disc = np.zeros(p.shape[0])
            values = (0.0, 0.5, 1.0)
            for other_role in (0.0, 1.0):
                # counts of earlier elements of the OTHER role per tier
                ind_other = {
                    v: ((os_ == v) & (rs_ == other_role)).astype(np.float64)
                    for v in values
                }
                cum_other = {
                    v: np.cumsum(ind_other[v], axis=1) - ind_other[v] for v in values
                }
                this = 1.0 - other_role
                ind_this = {
                    v: ((os_ == v) & (rs_ == this)).astype(np.float64) for v in values
                }
                conc += np.sum(
                    ind_this[0.5] * cum_other[0.0]
                    + ind_this[1.0] * (cum_other[0.0] + cum_other[0.5]),
                    axis=1,
                )
                disc += np.sum(
                    ind_this[0.0] * (cum_other[0.5] + cum_other[1.0])
                    + ind_this[0.5] * cum_other[1.0],
                    axis=1,
                )
            per_fold.append(conc / np.maximum(conc + disc, 1.0))
        per_fold = np.stack(per_fold, axis=1)
        w = np.asarray(fold_weights, dtype=np.float64)
        return per_fold @ (w / w.sum())

    def population_delta(bias, rng_local, reps=12):
        deltas = []
        for _ in range(reps):
            p0, o, r, slices, weights = build_pooled(bias, rng_local)
            p1 = p0 - bias * r  # perfect correction
            d = cross_concordance(p1[None], o[None], r[None], slices, weights)[0] - \
                cross_concordance(p0[None], o[None], r[None], slices, weights)[0]
            deltas.append(float(d))
        return float(np.mean(deltas))

    results = {}
    for target in target_deltas:
        # calibrate bias so full correction produces the target delta
        lo_b, hi_b = 0.0, 3.0
        for _ in range(24):
            mid = (lo_b + hi_b) / 2
            if population_delta(mid, np.random.default_rng(SEED + 7)) < target:
                lo_b = mid
            else:
                hi_b = mid
        bias = (lo_b + hi_b) / 2
        passes, points, bounds = 0, [], []
        for _ in range(N_SIMS):
            p0, o, r, slices, weights = build_pooled(bias, rng)
            p1 = p0 - bias * r
            n = o.shape[0]
            idx = np.empty((N_BOOT, n), dtype=np.int64)
            for sl in slices:
                lo_i, hi_i = sl.start, sl.stop
                idx[:, lo_i:hi_i] = rng.integers(lo_i, hi_i, size=(N_BOOT, hi_i - lo_i))
            d_b = cross_concordance(p1[idx], o[idx], r[idx], slices, weights) - \
                cross_concordance(p0[idx], o[idx], r[idx], slices, weights)
            point = float(
                cross_concordance(p1[None], o[None], r[None], slices, weights)[0]
                - cross_concordance(p0[None], o[None], r[None], slices, weights)[0]
            )
            lower = point - Z_ONE_SIDED * float(d_b.std(ddof=1))
            ok = (point >= POINT_THRESHOLD) and (lower > 0)
            passes += int(ok)
            points.append(point)
            bounds.append(lower)
        results[target] = {
            "power": passes / N_SIMS,
            "median_point": float(np.median(points)),
            "median_lower_bound": float(np.median(bounds)),
            "bias": bias,
        }
    return results


def main() -> int:
    targets = (0.005, 0.010, 0.020, 0.030)
    print(f"seed={SEED} sims={N_SIMS} bootstraps={N_BOOT} z={Z_ONE_SIDED:.4f}")
    print("point threshold =", POINT_THRESHOLD, "(pass = point >= threshold AND lower bound > 0)")
    print()
    print("E1 -- C1 shape: conditional within-pitcher oracle lever (25% subset)")
    e1 = experiment_within_pitcher(targets)
    for t, r in e1.items():
        print(
            f"  true dC={t:.3f}: power={r['power']:.2f} "
            f"median point={r['median_point']:+.4f} "
            f"median LB={r['median_lower_bound']:+.4f}"
        )
    print()
    print("E2 -- C2/C3 shape: uniform pitcher down-shift, perfect correction")
    e2 = experiment_cross_role(targets)
    for t, r in e2.items():
        print(
            f"  true dC_cross={t:.3f}: power={r['power']:.2f} "
            f"median point={r['median_point']:+.4f} "
            f"median LB={r['median_lower_bound']:+.4f} (bias={r['bias']:.3f})"
        )
    out = {"seed": SEED, "n_sims": N_SIMS, "n_boot": N_BOOT,
           "z": float(Z_ONE_SIDED), "point_threshold": POINT_THRESHOLD,
           "e1_within_pitcher": {str(k): v for k, v in e1.items()},
           "e2_cross_role": {str(k): v for k, v in e2.items()}}
    out_path = ROOT / "data" / "models" / "rank_gate_power_check.json"
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nwritten: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
