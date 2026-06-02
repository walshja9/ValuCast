"""Rolling-origin backtest: project season T from data < T, score vs actuals
on the qualified eval population. Compares Marcel against a persistence
baseline (T-1 = T)."""
from __future__ import annotations

from pathlib import Path

from projections.constants import HEADLINE_STATS, MIN_EVAL_PA
from projections.data.historical import load_season
from projections.export.marcel_run import build_marcel_projections
from projections.backtest.scorecard import correlation, mae, normalized_ratio, rmse
from projections.models.marcel_params import MarcelParams


def _rates(row: dict) -> dict:
    pa = float(row.get("PA", 0))
    ab = float(row.get("AB", 0))
    h = float(row.get("H", 0))
    bb, hbp, sf = (float(row.get(k, 0)) for k in ("BB", "HBP", "SF"))
    tb = (float(row.get("1B", 0)) + 2 * float(row.get("2B", 0))
          + 3 * float(row.get("3B", 0)) + 4 * float(row.get("HR", 0)))
    denom = ab + bb + hbp + sf
    avg = h / ab if ab > 0 else 0.0
    obp = (h + bb + hbp) / denom if denom > 0 else 0.0
    slg = tb / ab if ab > 0 else 0.0
    return {**row, "AVG": avg, "OBP": obp, "SLG": slg, "OPS": obp + slg}


def backtest_season(
    target_season: int,
    data_dir: Path,
    params: MarcelParams,
    identities: dict[str, dict],
) -> dict:
    actual_rows = {r["mlbam_id"]: _rates(r) for r in load_season(target_season, data_dir)}
    try:
        prev_rows = {r["mlbam_id"]: _rates(r)
                     for r in load_season(target_season - 1, data_dir)}
    except FileNotFoundError:
        prev_rows = {}

    marcel = {r["metadata"]["mlbam_id"]: r["stats"]
              for r in build_marcel_projections(target_season, data_dir, params, identities)}

    # Eval population: qualified actual PA AND projectable AND has persistence baseline.
    eval_ids = [
        pid for pid, a in actual_rows.items()
        if a.get("PA", 0) >= MIN_EVAL_PA and pid in marcel and pid in prev_rows
    ]

    per_stat: dict[str, dict] = {}
    for stat in HEADLINE_STATS:
        if not eval_ids:
            per_stat[stat] = {}
            continue
        act = [actual_rows[pid][stat] for pid in eval_ids]
        mar = [marcel[pid].get(stat, 0.0) for pid in eval_ids]
        per = [prev_rows[pid].get(stat, 0.0) for pid in eval_ids]
        m_mae, p_mae = mae(mar, act), mae(per, act)
        per_stat[stat] = {
            "marcel_mae": m_mae,
            "persistence_mae": p_mae,
            "marcel_rmse": rmse(mar, act),
            "persistence_rmse": rmse(per, act),
            "mae_ratio": normalized_ratio(m_mae, p_mae),
            "marcel_corr": correlation(mar, act),
            "persistence_corr": correlation(per, act),
        }
    return {"target_season": target_season, "eval_n": len(eval_ids), "per_stat": per_stat}


def rolling_origin(
    target_seasons: list[int],
    data_dir: Path,
    params: MarcelParams,
    identities: dict[str, dict],
) -> dict:
    """Run backtest_season across many targets; aggregate the pass-bar verdict."""
    seasons = [backtest_season(t, data_dir, params, identities) for t in target_seasons]
    ratios, corr_wins, corr_total = [], 0, 0
    for s in seasons:
        for stat, m in s["per_stat"].items():
            if not m:
                continue
            ratios.append(m["mae_ratio"])
            corr_total += 1
            if m["marcel_corr"] > m["persistence_corr"]:
                corr_wins += 1
    mean_ratio = sum(ratios) / len(ratios) if ratios else float("inf")
    return {
        "seasons": seasons,
        "mean_mae_ratio": mean_ratio,
        "corr_win_rate": corr_wins / corr_total if corr_total else 0.0,
        "beats_persistence": mean_ratio < 1.0 and (corr_wins / corr_total if corr_total else 0) > 0.5,
    }


def vs_classic(
    candidate_seasons: list[dict],
    classic_seasons: list[dict],
    epsilon: float = 0.0,
) -> dict:
    """Compare a candidate config's per-season scorecards against classic Marcel's
    (both from rolling_origin over the SAME target seasons). Beating classic is the
    Rung 2 bar; persistence is only a sanity floor."""
    ratios: list[float] = []
    corr_wins = corr_total = 0
    for cs, ks in zip(candidate_seasons, classic_seasons):
        for stat, cm in cs["per_stat"].items():
            km = ks["per_stat"].get(stat)
            if not cm or not km or km["marcel_mae"] == 0:
                continue
            ratios.append(cm["marcel_mae"] / km["marcel_mae"])
            corr_total += 1
            if cm["marcel_corr"] > km["marcel_corr"]:
                corr_wins += 1
    mean_ratio = sum(ratios) / len(ratios) if ratios else float("inf")
    cwr = corr_wins / corr_total if corr_total else 0.0
    return {
        "mean_ratio_vs_classic": mean_ratio,
        "corr_win_rate": cwr,
        "beats_classic": mean_ratio < 1.0 - epsilon and cwr > 0.5,
    }
