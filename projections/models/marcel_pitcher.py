"""Role-routed Marcel pitcher projector: per-BF skill rates with a leakage-safe
SP/RP role-shift, separate SP/RP usage, blended by SP-probability, reconstructed
into engine pitching categories (primary-pool export)."""
from __future__ import annotations

from collections.abc import Sequence

from projections.constants import PITCHER_SKILL_RATES
from projections.models.pitcher_params import PitcherMarcelParams
from projections.models.pitcher_role import historical_role_mix, project_p_sp, is_mixed


def compute_pitcher_league_rates(
    prior_snapshots: Sequence[Sequence[dict]],
    weights: Sequence[float],
    bf_floor: float,
) -> dict[str, float]:
    """Weighted per-BF league rates (leakage-safe; pre-target snapshots only)."""
    totals = {c: 0.0 for c in PITCHER_SKILL_RATES}
    bf_total = 0.0
    for snap, w in zip(prior_snapshots, weights):
        for row in snap:
            if float(row.get("BF", 0)) < bf_floor:
                continue
            bf_total += w * float(row.get("BF", 0))
            for c in PITCHER_SKILL_RATES:
                totals[c] += w * float(row.get(c, 0))
    if bf_total <= 0:
        return {c: 0.0 for c in PITCHER_SKILL_RATES}
    return {c: totals[c] / bf_total for c in PITCHER_SKILL_RATES}


def compute_role_factors(
    prior_snapshots: Sequence[Sequence[dict]],
    bf_floor: float,
) -> dict[str, float]:
    """f[c] = league RP-context per-BF rate / SP-context per-BF rate (leakage-safe).
    Split each pitcher-season by role_share>=0.5. f>1 means relievers post more of
    that component per BF (e.g. K); f<1 for ER/H. A zero on EITHER side neutralizes
    to 1.0 so f^(negative exponent) can't blow up."""
    sp_tot = {c: 0.0 for c in PITCHER_SKILL_RATES}; sp_bf = 0.0
    rp_tot = {c: 0.0 for c in PITCHER_SKILL_RATES}; rp_bf = 0.0
    for snap in prior_snapshots:
        for row in snap:
            bf = float(row.get("BF", 0))
            if bf < bf_floor:
                continue
            g = float(row.get("G", 0)); gs = float(row.get("GS", 0))
            is_sp = (gs / g) >= 0.5 if g > 0 else False
            if is_sp:
                sp_bf += bf
                for c in PITCHER_SKILL_RATES:
                    sp_tot[c] += float(row.get(c, 0))
            else:
                rp_bf += bf
                for c in PITCHER_SKILL_RATES:
                    rp_tot[c] += float(row.get(c, 0))
    f = {}
    for c in PITCHER_SKILL_RATES:
        sp_rate = sp_tot[c] / sp_bf if sp_bf > 0 else 0.0
        rp_rate = rp_tot[c] / rp_bf if rp_bf > 0 else 0.0
        f[c] = (rp_rate / sp_rate) if (sp_rate > 0 and rp_rate > 0) else 1.0
    return f


def project_pitcher_rates(
    prior_seasons: Sequence[dict | None],
    league_rates: dict[str, float],
    role_factors: dict[str, float],
    h_sp: float,
    p_sp: float,
    params: PitcherMarcelParams,
) -> dict[str, float]:
    """Per-BF skill rates: weighted + regressed (Marcel), then role-shifted by
    f[c]^(h_sp - p_sp). Age is neutral in v1 (no curve)."""
    # Offset-aligned: prior_seasons[i] may be None (missed year). zip with the full
    # season_weights pins each PRESENT season to its true offset weight — do NOT
    # compress (a pitcher who missed T-1 but pitched T-2 keeps the T-2 weight).
    pairs = [(s, w) for s, w in zip(prior_seasons, params.season_weights) if s is not None]
    weighted_bf = sum(w * float(s.get("BF", 0)) for s, w in pairs)
    out: dict[str, float] = {}
    for c in PITCHER_SKILL_RATES:
        wtot = sum(w * float(s.get(c, 0)) for s, w in pairs)
        regressed = (wtot + params.n_reg * league_rates.get(c, 0.0)) / (weighted_bf + params.n_reg)
        shift = role_factors.get(c, 1.0) ** (h_sp - p_sp)
        out[c] = max(0.0, regressed * shift)
    return out


def _wmean(prior_seasons, weights, fn):
    pairs = [(fn(s), w) for s, w in zip(prior_seasons, weights) if s is not None]
    wsum = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / wsum if wsum > 0 else 0.0


def project_sp_usage(prior_seasons: Sequence[dict], weights: Sequence[float]) -> dict[str, float]:
    """Starter volume/role: GS, BF (=GS*BF/start), IP (=GS*IP/start), QS (=GS*QS/GS)."""
    gs = _wmean(prior_seasons, weights, lambda s: float(s.get("GS", 0)))
    bf_per_start = _wmean(prior_seasons, weights,
                          lambda s: float(s["BF"]) / s["GS"] if s.get("GS") else 0.0)
    ip_per_start = _wmean(prior_seasons, weights,
                          lambda s: float(s["IP"]) / s["GS"] if s.get("GS") else 0.0)
    qs_per_start = _wmean(prior_seasons, weights,
                          lambda s: float(s.get("QS", 0)) / s["GS"] if s.get("GS") else 0.0)
    return {"GS": gs, "BF": gs * bf_per_start, "IP": gs * ip_per_start, "QS": gs * qs_per_start}


def project_rp_usage(prior_seasons: Sequence[dict], weights: Sequence[float]) -> dict[str, float]:
    """Reliever volume/role: G, BF (=G*BF/app), IP (=G*IP/app), SV/HLD (=G*rate)."""
    g = _wmean(prior_seasons, weights, lambda s: float(s.get("G", 0)))
    bf_per_app = _wmean(prior_seasons, weights,
                        lambda s: float(s["BF"]) / s["G"] if s.get("G") else 0.0)
    ip_per_app = _wmean(prior_seasons, weights,
                        lambda s: float(s["IP"]) / s["G"] if s.get("G") else 0.0)
    sv_per_app = _wmean(prior_seasons, weights,
                        lambda s: float(s.get("SV", 0)) / s["G"] if s.get("G") else 0.0)
    hld_per_app = _wmean(prior_seasons, weights,
                         lambda s: float(s.get("HLD", 0)) / s["G"] if s.get("G") else 0.0)
    return {"G": g, "BF": g * bf_per_app, "IP": g * ip_per_app,
            "SV": g * sv_per_app, "HLD": g * hld_per_app}


def _reconstruct(rates: dict[str, float], usage: dict[str, float]) -> dict[str, float]:
    """Counts from per-BF rates * projected BF + the usage volume/role stats."""
    bf = usage["BF"]
    out = {c: max(0.0, rates.get(c, 0.0) * bf) for c in PITCHER_SKILL_RATES}
    out["BF"] = bf
    out["IP"] = usage["IP"]
    out["GS"] = usage.get("GS", 0.0)
    out["G"] = usage.get("G", 0.0)
    out["SV"] = usage.get("SV", 0.0)
    out["HLD"] = usage.get("HLD", 0.0)
    out["QS"] = usage.get("QS", 0.0)
    return out


def project_pitcher(
    prior_seasons: Sequence[dict | None],
    league_rates: dict[str, float],
    role_factors: dict[str, float],
    params: PitcherMarcelParams,
) -> dict:
    """Project one pitcher: SP-line and RP-line, blend by p_sp, reconstruct cats,
    primary-pool export row. prior_seasons offset-aligned (newest-first, None gaps)."""
    weights = params.season_weights[: len(prior_seasons)]
    p_sp = project_p_sp(prior_seasons, weights)
    h_sp = historical_role_mix(prior_seasons)
    first = next((s for s in prior_seasons if s is not None), {})  # T-1 may be None
    mlbam_id = first.get("mlbam_id", "")

    sp_rates = project_pitcher_rates(prior_seasons, league_rates, role_factors, h_sp, 1.0, params)
    rp_rates = project_pitcher_rates(prior_seasons, league_rates, role_factors, h_sp, 0.0, params)
    sp_line = _reconstruct(sp_rates, project_sp_usage(prior_seasons, weights))
    rp_line = _reconstruct(rp_rates, project_rp_usage(prior_seasons, weights))

    # Blend the COUNTS by p_sp; derive ratios from blended counts.
    keys = set(sp_line) | set(rp_line)
    blended = {k: p_sp * sp_line.get(k, 0.0) + (1 - p_sp) * rp_line.get(k, 0.0) for k in keys}
    # W is team-context; project crudely from prior W per IP, scaled to blended IP.
    w_per_ip = _wmean(prior_seasons, weights,
                      lambda s: float(s.get("W", 0)) / s["IP"] if s.get("IP") else 0.0)
    blended["W"] = max(0.0, w_per_ip * blended["IP"])
    blended["SV_HLD"] = blended.get("SV", 0.0) + blended.get("HLD", 0.0)

    ip = blended["IP"]
    blended["ERA"] = round(9 * blended["ER"] / ip, 3) if ip > 0 else 0.0
    blended["WHIP"] = round((blended["BB"] + blended["H_ALLOWED"]) / ip, 3) if ip > 0 else 0.0
    blended["K_9"] = round(9 * blended["K"] / ip, 3) if ip > 0 else 0.0
    blended["BB_9"] = round(9 * blended["BB"] / ip, 3) if ip > 0 else 0.0
    blended["K_BB"] = round(blended["K"] / blended["BB"], 3) if blended["BB"] > 0 else 0.0

    return {
        "id": f"mlbam_{mlbam_id}_P",
        "pool": "starter" if p_sp >= 0.5 else "reliever",   # primary-pool approximation
        "stats": {k: round(v, 4) for k, v in blended.items()},
        "metadata": {"mlbam_id": mlbam_id, "base_id": f"mlbam_{mlbam_id}",
                     "source": "valucast_pitching", "p_sp": round(p_sp, 4),
                     "mixed_role": is_mixed(p_sp)},
    }


def build_pitcher_projections(
    target_season: int,
    data_dir,
    params: PitcherMarcelParams,
) -> list[dict]:
    """Project all pitchers with >=1 prior season (data < target). League rates use
    the 3 weight-years; role factors use the wide pre-target window. Offset-aligned."""
    from projections.data.pitching_historical import (
        available_pitching_seasons, load_pitching_season,
    )
    prior_years = [target_season - 1, target_season - 2, target_season - 3]
    snaps = []
    for yr in prior_years:
        try:
            snaps.append(load_pitching_season(yr, data_dir))
        except FileNotFoundError:
            snaps.append([])

    BF_FLOOR = 100  # league-rate/role-factor sample floor (per-BF stability)
    weights = params.season_weights[: len(snaps)]
    league = compute_pitcher_league_rates(snaps, weights=weights, bf_floor=BF_FLOOR)
    wide = [load_pitching_season(s, data_dir)
            for s in available_pitching_seasons(data_dir) if s < target_season]
    role_factors = compute_role_factors(wide, bf_floor=BF_FLOOR)

    index_maps = [{r["mlbam_id"]: r for r in snap} for snap in snaps]
    all_ids = {pid for m in index_maps for pid in m}

    rows = []
    for mlbam_id in all_ids:
        # Offset-aligned: index 0 = T-1, 1 = T-2, 2 = T-3; None = missed year. Same
        # no-compress rule as hitting — do NOT promote a T-2 season to the T-1 weight.
        prior_seasons = [m.get(mlbam_id) for m in index_maps]
        if all(s is None for s in prior_seasons):
            continue
        proj = project_pitcher(prior_seasons, league, role_factors, params)
        proj["name"] = mlbam_id  # identity-name wiring is a follow-up; id-keyed for now
        if proj["metadata"]["mixed_role"]:
            proj["positions"] = ["SP", "RP"]   # mixed arm: eligible both ways
        else:
            proj["positions"] = ["SP"] if proj["pool"] == "starter" else ["RP"]
        proj["metadata"]["as_of_season"] = target_season
        proj["metadata"]["model"] = "valucast_pitching_marcel"
        rows.append(proj)
    return rows
