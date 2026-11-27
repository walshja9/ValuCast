"""Rolling-origin pitcher backtest. Scores skill cats vs persistence. Reuses
scorecard metrics. Eval population gated on role-specific IP floor. The v1 bar is
beat-persistence on SKILL cats; W/SV/QS/HLD are reported as context, not the bar."""
from __future__ import annotations

from projections.constants import (
    MIN_SP_IP_EVAL, MIN_RP_IP_EVAL, PITCHER_HEADLINE_SKILL, PITCHER_HEADLINE_CONTEXT,
)
from projections.data.pitching_historical import load_pitching_season
from projections.backtest.scorecard import correlation, mae, normalized_ratio, rmse
from projections.models.marcel_pitcher import build_pitcher_projections
from projections.models.pitcher_params import PitcherMarcelParams
from projections.models.pitcher_role import role_share

HEADLINE = PITCHER_HEADLINE_SKILL + PITCHER_HEADLINE_CONTEXT


def _derive(row: dict) -> dict:
    ip = float(row.get("IP", 0))
    out = dict(row)
    out["ERA"] = 9 * float(row.get("ER", 0)) / ip if ip > 0 else 0.0
    out["WHIP"] = (float(row.get("BB", 0)) + float(row.get("H_ALLOWED", 0))) / ip if ip > 0 else 0.0
    out["K_9"] = 9 * float(row.get("K", 0)) / ip if ip > 0 else 0.0
    out["BB_9"] = 9 * float(row.get("BB", 0)) / ip if ip > 0 else 0.0
    return out


def _qualified(row: dict) -> bool:
    ip = float(row.get("IP", 0))
    floor = MIN_SP_IP_EVAL if role_share(row) >= 0.5 else MIN_RP_IP_EVAL
    return ip >= floor


def backtest_pitching_season(target_season, data_dir, params: PitcherMarcelParams) -> dict:
    actual = {r["mlbam_id"]: _derive(r) for r in load_pitching_season(target_season, data_dir)}
    try:
        prev = {r["mlbam_id"]: _derive(r) for r in load_pitching_season(target_season - 1, data_dir)}
    except FileNotFoundError:
        prev = {}
    marcel = {r["metadata"]["mlbam_id"]: r["stats"]
              for r in build_pitcher_projections(target_season, data_dir, params)}

    eval_ids = [pid for pid, a in actual.items()
                if _qualified(a) and pid in marcel and pid in prev]

    per_stat = {}
    for stat in HEADLINE:
        if not eval_ids:
            per_stat[stat] = {}
            continue
        act = [actual[pid].get(stat, 0.0) for pid in eval_ids]
        mar = [marcel[pid].get(stat, 0.0) for pid in eval_ids]
        per = [prev[pid].get(stat, 0.0) for pid in eval_ids]
        m_mae, p_mae = mae(mar, act), mae(per, act)
        per_stat[stat] = {
            "marcel_mae": m_mae, "persistence_mae": p_mae,
            "marcel_rmse": rmse(mar, act), "persistence_rmse": rmse(per, act),
            "mae_ratio": normalized_ratio(m_mae, p_mae),
            "marcel_corr": correlation(mar, act), "persistence_corr": correlation(per, act),
            "is_skill": stat in PITCHER_HEADLINE_SKILL,
        }
    return {"target_season": target_season, "eval_n": len(eval_ids), "per_stat": per_stat}


def rolling_origin_pitching(target_seasons, data_dir, params) -> dict:
    seasons = [backtest_pitching_season(t, data_dir, params) for t in target_seasons]
    ratios, cw, ct = [], 0, 0
    for s in seasons:
        for stat, m in s["per_stat"].items():
            if not m or not m["is_skill"]:   # bar measured on SKILL cats only
                continue
            ratios.append(m["mae_ratio"]); ct += 1
            if m["marcel_corr"] > m["persistence_corr"]:
                cw += 1
    mr = sum(ratios) / len(ratios) if ratios else float("inf")
    return {"seasons": seasons, "mean_skill_mae_ratio": mr,
            "skill_corr_win_rate": cw / ct if ct else 0.0,
            "beats_persistence": mr < 1.0 and (cw / ct if ct else 0) > 0.5}
