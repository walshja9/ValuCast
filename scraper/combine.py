"""Combine YTD actuals with ROS projections into season outlook."""
from __future__ import annotations


HITTER_COUNTING = ("PA", "AB", "H", "HR", "R", "RBI", "SB", "CS", "BB", "SO",
                   "HBP", "SF", "1B", "2B", "3B", "G")
PITCHER_COUNTING = ("IP", "ER", "BB", "H_ALLOWED", "K", "W", "L", "SV", "HLD",
                    "GS", "G", "QS")


def _pool_family(pool: str) -> str:
    """Map pool string to 'hitter' or 'pitcher'."""
    if pool == "hitter":
        return "hitter"
    return "pitcher"


def _safe(stats: dict, key: str) -> float:
    return float(stats.get(key, 0) or 0)


def _combine_hitter(ros: dict, actual: dict) -> dict:
    """Combine a hitter's actuals + ROS into season outlook."""
    combined_stats = {}
    for stat in HITTER_COUNTING:
        combined_stats[stat] = _safe(actual["stats"], stat) + _safe(ros["stats"], stat)

    combined_stats["TB"] = (combined_stats["1B"] + 2 * combined_stats["2B"]
                            + 3 * combined_stats["3B"] + 4 * combined_stats["HR"])
    combined_stats["NSB"] = combined_stats["SB"] - combined_stats["CS"]

    ab = combined_stats["AB"]
    h = combined_stats["H"]
    bb = combined_stats["BB"]
    hbp = combined_stats["HBP"]
    sf = combined_stats["SF"]
    tb = combined_stats["TB"]
    pa_denom = ab + bb + hbp + sf

    combined_stats["AVG"] = round(h / ab, 3) if ab > 0 else 0.0
    obp_num = h + bb + hbp
    combined_stats["OBP"] = round(obp_num / pa_denom, 3) if pa_denom > 0 else 0.0
    combined_stats["SLG"] = round(tb / ab, 3) if ab > 0 else 0.0
    combined_stats["OPS"] = round(combined_stats["OBP"] + combined_stats["SLG"], 3)

    meta = dict(ros.get("metadata", {}))
    meta["base_id"] = f"mlbam_{meta.get('mlbam_id', '')}"
    meta["has_ros"] = True
    meta["stats_actual"] = actual["stats"]
    meta["stats_ros"] = ros["stats"]

    return {
        "id": ros["id"],
        "name": ros["name"],
        "pool": ros["pool"],
        "positions": ros.get("positions", []),
        "team": ros.get("team", ""),
        "stats": {k: round(v, 4) if isinstance(v, float) else int(v)
                  for k, v in combined_stats.items()},
        "metadata": meta,
        "sources": list(ros.get("sources", [])),
    }


def _combine_pitcher(ros: dict, actual: dict) -> dict:
    """Combine a pitcher's actuals + ROS into season outlook."""
    combined_stats = {}
    for stat in PITCHER_COUNTING:
        combined_stats[stat] = _safe(actual["stats"], stat) + _safe(ros["stats"], stat)

    combined_stats["SV_HLD"] = combined_stats["SV"] + combined_stats["HLD"]

    ip = combined_stats["IP"]
    er = combined_stats["ER"]
    bb = combined_stats["BB"]
    h_allowed = combined_stats["H_ALLOWED"]
    k = combined_stats["K"]

    combined_stats["ERA"] = round(9 * er / ip, 2) if ip > 0 else 0.0
    combined_stats["WHIP"] = round((bb + h_allowed) / ip, 2) if ip > 0 else 0.0
    combined_stats["K_BB"] = round(k / bb, 2) if bb > 0 else 0.0
    combined_stats["K_9"] = round(9 * k / ip, 2) if ip > 0 else 0.0
    combined_stats["BB_9"] = round(9 * bb / ip, 2) if ip > 0 else 0.0

    meta = dict(ros.get("metadata", {}))
    meta["base_id"] = f"mlbam_{meta.get('mlbam_id', '')}"
    meta["has_ros"] = True
    meta["stats_actual"] = actual["stats"]
    meta["stats_ros"] = ros["stats"]

    return {
        "id": ros["id"],
        "name": ros["name"],
        "pool": ros["pool"],
        "positions": ros.get("positions", []),
        "team": ros.get("team", ""),
        "stats": {k_: round(v, 4) if isinstance(v, float) else int(v)
                  for k_, v in combined_stats.items()},
        "metadata": meta,
        "sources": list(ros.get("sources", [])),
    }


def combine_outlook(ros_players: list[dict], actual_players: list[dict]) -> list[dict]:
    """Join actuals to ROS projections and produce season outlook.

    Join key: (mlbam_id, pool_family). Matched records combine stats.
    ROS-only records pass through. Actuals-only records included with has_ros=False.
    """
    actuals_by_key: dict[tuple[str, str], dict] = {}
    for p in actual_players:
        mlbam_id = p.get("metadata", {}).get("mlbam_id", "")
        if mlbam_id:
            key = (mlbam_id, _pool_family(p["pool"]))
            actuals_by_key[key] = p

    matched_actual_keys: set[tuple[str, str]] = set()
    outlook: list[dict] = []

    for ros in ros_players:
        mlbam_id = ros.get("metadata", {}).get("mlbam_id", "")
        if not mlbam_id:
            meta = dict(ros.get("metadata", {}))
            meta["has_ros"] = True
            ros_copy = dict(ros)
            ros_copy["metadata"] = meta
            outlook.append(ros_copy)
            continue

        key = (mlbam_id, _pool_family(ros["pool"]))
        actual = actuals_by_key.get(key)

        if actual:
            matched_actual_keys.add(key)
            if _pool_family(ros["pool"]) == "hitter":
                outlook.append(_combine_hitter(ros, actual))
            else:
                outlook.append(_combine_pitcher(ros, actual))
        else:
            meta = dict(ros.get("metadata", {}))
            meta["base_id"] = f"mlbam_{mlbam_id}"
            meta["has_ros"] = True
            ros_copy = dict(ros)
            ros_copy["metadata"] = meta
            outlook.append(ros_copy)

    for key, actual in actuals_by_key.items():
        if key not in matched_actual_keys:
            meta = dict(actual.get("metadata", {}))
            meta["has_ros"] = False
            actual_copy = dict(actual)
            actual_copy["metadata"] = meta
            outlook.append(actual_copy)

    return outlook
