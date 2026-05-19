"""Blend Steamer and ZiPS projections into a single player set."""
from __future__ import annotations


HITTER_COUNTING = ("PA", "AB", "H", "HR", "R", "RBI", "SB", "SO", "BB",
                    "1B", "2B", "3B", "HBP", "SF", "SH", "GDP", "CS", "IBB", "G")
PITCHER_COUNTING = ("IP", "SO", "W", "L", "GS", "G", "SV", "HLD", "ER", "H",
                     "BB", "QS", "HR", "R", "TBF", "IBB", "HBP", "BS")

HITTER_RATE = ("AVG", "OBP", "SLG", "OPS")
PITCHER_RATE = ("ERA", "WHIP")


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _avg(a: float, b: float) -> float:
    return (a + b) / 2


def _weighted_avg(val_a: float, vol_a: float, val_b: float, vol_b: float) -> float:
    total_vol = vol_a + vol_b
    if total_vol == 0:
        return 0.0
    return (val_a * vol_a + val_b * vol_b) / total_vol


def blend_hitters(steamer: list[dict], zips: list[dict]) -> list[dict]:
    steamer_by_id = {str(p.get("playerids", "")): p for p in steamer if p.get("playerids")}
    zips_by_id = {str(p.get("playerids", "")): p for p in zips if p.get("playerids")}
    all_ids = set(steamer_by_id) | set(zips_by_id)
    result = []
    for pid in all_ids:
        s = steamer_by_id.get(pid)
        z = zips_by_id.get(pid)
        if s and z:
            result.append(_blend_hitter(s, z, pid))
        elif s:
            result.append(_single_hitter(s, pid, "steamer"))
        else:
            result.append(_single_hitter(z, pid, "zips"))
    return result


def _blend_hitter(s: dict, z: dict, pid: str) -> dict:
    stats = {}
    for stat in HITTER_COUNTING:
        stats[stat] = _avg(_safe_float(s.get(stat)), _safe_float(z.get(stat)))
    s_pa = _safe_float(s.get("PA", 0))
    z_pa = _safe_float(z.get("PA", 0))
    for stat in HITTER_RATE:
        stats[stat] = _weighted_avg(_safe_float(s.get(stat)), s_pa, _safe_float(z.get(stat)), z_pa)
    ab = stats.get("AB", 0)
    if ab > 0:
        stats["AVG"] = stats.get("H", 0) / ab
    return {
        "id": pid, "name": s.get("PlayerName", ""), "pool": "hitter",
        "positions": [], "team": s.get("Team", ""),
        "stats": {k: round(v, 3) if isinstance(v, float) else v for k, v in stats.items()},
        "metadata": {"fangraphs_id": pid, "mlbam_id": str(s.get("xMLBAMID", "") or s.get("MLBAMID", ""))},
        "sources": ["steamer", "zips"],
    }


def _single_hitter(p: dict, pid: str, source: str) -> dict:
    stats = {}
    for stat in HITTER_COUNTING:
        stats[stat] = _safe_float(p.get(stat))
    for stat in HITTER_RATE:
        stats[stat] = _safe_float(p.get(stat))
    return {
        "id": pid, "name": p.get("PlayerName", ""), "pool": "hitter",
        "positions": [], "team": p.get("Team", ""),
        "stats": {k: round(v, 3) if isinstance(v, float) else v for k, v in stats.items()},
        "metadata": {"fangraphs_id": pid, "mlbam_id": str(p.get("xMLBAMID", "") or p.get("MLBAMID", ""))},
        "sources": [source],
    }


def _detect_pitcher_pool(stats: dict) -> str:
    gs = _safe_float(stats.get("GS", 0))
    sv = _safe_float(stats.get("SV", 0))
    hld = _safe_float(stats.get("HLD", 0))
    if gs > 0:
        return "starter"
    if sv > 0 or hld > 0:
        return "reliever"
    return "starter"


def _detect_pitcher_positions(stats: dict) -> list[str]:
    gs = _safe_float(stats.get("GS", 0))
    sv = _safe_float(stats.get("SV", 0))
    hld = _safe_float(stats.get("HLD", 0))
    positions = []
    if gs > 0:
        positions.append("SP")
    if sv > 0 or hld > 0:
        positions.append("RP")
    if not positions:
        positions.append("SP")
    return positions


def _finalize_pitcher_stats(stats: dict) -> dict:
    """Rename SO→K and add derived stats."""
    if "SO" in stats:
        stats["K"] = stats.pop("SO")
    stats["SV_HLD"] = _safe_float(stats.get("SV", 0)) + _safe_float(stats.get("HLD", 0))
    bb = _safe_float(stats.get("BB", 0))
    k = _safe_float(stats.get("K", 0))
    stats["K_BB"] = round(k / bb, 2) if bb > 0 else 0.0
    return stats


def blend_pitchers(steamer: list[dict], zips: list[dict]) -> list[dict]:
    steamer_by_id = {str(p.get("playerids", "")): p for p in steamer if p.get("playerids")}
    zips_by_id = {str(p.get("playerids", "")): p for p in zips if p.get("playerids")}
    all_ids = set(steamer_by_id) | set(zips_by_id)
    result = []
    for pid in all_ids:
        s = steamer_by_id.get(pid)
        z = zips_by_id.get(pid)
        if s and z:
            result.append(_blend_pitcher(s, z, pid))
        elif s:
            result.append(_single_pitcher(s, pid, "steamer"))
        else:
            result.append(_single_pitcher(z, pid, "zips"))
    return result


def _blend_pitcher(s: dict, z: dict, pid: str) -> dict:
    stats = {}
    for stat in PITCHER_COUNTING:
        stats[stat] = _avg(_safe_float(s.get(stat)), _safe_float(z.get(stat)))
    s_ip = _safe_float(s.get("IP", 0))
    z_ip = _safe_float(z.get("IP", 0))
    for stat in PITCHER_RATE:
        stats[stat] = _weighted_avg(_safe_float(s.get(stat)), s_ip, _safe_float(z.get(stat)), z_ip)
    stats = _finalize_pitcher_stats(stats)
    pool = _detect_pitcher_pool(stats)
    positions = _detect_pitcher_positions(stats)
    return {
        "id": pid, "name": s.get("PlayerName", ""), "pool": pool,
        "positions": positions, "team": s.get("Team", ""),
        "stats": {k: round(v, 3) if isinstance(v, float) else v for k, v in stats.items()},
        "metadata": {"fangraphs_id": pid, "mlbam_id": str(s.get("xMLBAMID", "") or s.get("MLBAMID", ""))},
        "sources": ["steamer", "zips"],
    }


def _single_pitcher(p: dict, pid: str, source: str) -> dict:
    stats = {}
    for stat in PITCHER_COUNTING:
        stats[stat] = _safe_float(p.get(stat))
    for stat in PITCHER_RATE:
        stats[stat] = _safe_float(p.get(stat))
    stats = _finalize_pitcher_stats(stats)
    pool = _detect_pitcher_pool(stats)
    positions = _detect_pitcher_positions(stats)
    return {
        "id": pid, "name": p.get("PlayerName", ""), "pool": pool,
        "positions": positions, "team": p.get("Team", ""),
        "stats": {k: round(v, 3) if isinstance(v, float) else v for k, v in stats.items()},
        "metadata": {"fangraphs_id": pid, "mlbam_id": str(p.get("xMLBAMID", "") or p.get("MLBAMID", ""))},
        "sources": [source],
    }


def blend_projections(raw: dict[str, list[dict]]) -> list[dict]:
    hitters = blend_hitters(raw.get("steamer_hitters", []), raw.get("zips_hitters", []))
    pitchers = blend_pitchers(raw.get("steamer_pitchers", []), raw.get("zips_pitchers", []))
    return hitters + pitchers
