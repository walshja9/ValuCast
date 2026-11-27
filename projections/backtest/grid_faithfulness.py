"""Faithfulness of our grid xBA/xSLG vs Savant's stored values: correlation (gate)
plus calibration (slope/intercept/bias) — corr alone can't catch an affine bias."""
from __future__ import annotations

from collections.abc import Sequence
from statistics import mean, pstdev

MIN_AB = 200            # qualified-population AB floor
MIN_TRACKED_BIP = 50    # qualified-population batted-ball floor
MIN_QUALIFIED_PAIRS = 100  # below this, joins likely failed -> fail loud, not a fake SHORTFALL


def correlation(xs: Sequence[float], ys: Sequence[float]) -> float:
    sx, sy = pstdev(xs), pstdev(ys)
    if sx == 0 or sy == 0:
        return 0.0
    mx, my = mean(xs), mean(ys)
    return mean((a - mx) * (b - my) for a, b in zip(xs, ys)) / (sx * sy)


def calibration(ours: Sequence[float], savant: Sequence[float]) -> dict:
    """Regress ours on savant -> slope/intercept; plus mean signed error + MAE.
    Clean calibration ~ slope 1, intercept 0, bias 0."""
    n = len(ours)
    ms, mo = mean(savant), mean(ours)
    var_s = sum((s - ms) ** 2 for s in savant)
    slope = sum((s - ms) * (o - mo) for s, o in zip(savant, ours)) / var_s if var_s else 0.0
    intercept = mo - slope * ms
    signed = [o - s for o, s in zip(ours, savant)]
    return {
        "slope": slope, "intercept": intercept,
        "mean_signed_error": sum(signed) / n if n else 0.0,
        "mae": sum(abs(x) for x in signed) / n if n else 0.0,
        "n": n,
    }


def qualified(ab: int, tracked_bip: int) -> bool:
    return ab >= MIN_AB and tracked_bip >= MIN_TRACKED_BIP


def faithfulness_report(paired: list[dict]) -> dict:
    """paired: [{our_xba, our_xslg, savant_xba, savant_xslg}] for the QUALIFIED pop.
    Returns corr (gate) + calibration for xBA and xSLG.
    Fails loud below MIN_QUALIFIED_PAIRS: a join failure that pairs ~0 rows must NOT
    silently emit a fake SHORTFALL."""
    if len(paired) < MIN_QUALIFIED_PAIRS:
        raise ValueError(
            f"insufficient qualified pairs: {len(paired)} < {MIN_QUALIFIED_PAIRS} "
            "(likely a join/data failure, not a real faithfulness shortfall)."
        )
    out = {"n": len(paired)}
    for stat in ("xba", "xslg"):
        ours = [p[f"our_{stat}"] for p in paired]
        sav = [p[f"savant_{stat}"] for p in paired]
        corr = correlation(ours, sav)
        out[stat] = {"corr": corr, "passes_gate": corr >= 0.95, **calibration(ours, sav)}
    return out
