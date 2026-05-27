"""Orchestrator: fetch ROS projections + actuals, combine, write output."""
from __future__ import annotations

import json
import os
from datetime import date

from .fangraphs import fetch_all, save_raw
from .blend import blend_projections
from .mlb_actuals import build_actuals
from .combine import combine_outlook

_BASE = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_OUTPUT = os.path.join(_BASE, "data", "projections", "current.json")
DEFAULT_ROS_OUTPUT = os.path.join(_BASE, "data", "projections", "ros.json")
DEFAULT_ACTUALS_OUTPUT = os.path.join(_BASE, "data", "actuals", "current.json")
DEFAULT_METADATA = os.path.join(_BASE, "data", "projections", "metadata.json")
DEFAULT_RAW_DIR = os.path.join(_BASE, "data", "projections", "raw")


def _write_json(data, path: str) -> None:
    """Write JSON via .tmp + os.replace for safer publish."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def refresh(
    output_path: str = DEFAULT_OUTPUT,
    ros_output_path: str = DEFAULT_ROS_OUTPUT,
    actuals_output_path: str = DEFAULT_ACTUALS_OUTPUT,
    metadata_path: str = DEFAULT_METADATA,
    raw_dir: str = DEFAULT_RAW_DIR,
    delay: float = 1.0,
    season: int = 2026,
) -> list[dict]:
    as_of = date.today().isoformat()

    # Step 1: Fetch and blend ROS projections
    print("Fetching ROS projections from FanGraphs...")
    raw = fetch_all(delay=delay)
    for key, players in raw.items():
        print(f"  {key}: {len(players)} players")
    save_raw(raw, raw_dir)

    print("Blending ROS projections...")
    ros_players = blend_projections(raw)
    print(f"  {len(ros_players)} ROS players")
    _write_json(ros_players, ros_output_path)

    # Step 2: Fetch actuals from MLB Stats API
    print("Fetching 2026 actuals from MLB Stats API...")
    actual_players = build_actuals(season=season, as_of=as_of)
    actual_hitters = sum(1 for p in actual_players if p["pool"] == "hitter")
    actual_pitchers = len(actual_players) - actual_hitters
    print(f"  {actual_hitters} hitters, {actual_pitchers} pitchers")
    _write_json(actual_players, actuals_output_path)

    # Step 3: Combine into season outlook
    print("Combining actuals + ROS into season outlook...")
    outlook = combine_outlook(ros_players, actual_players)
    ros_count_h = sum(1 for p in ros_players if p["pool"] == "hitter")
    ros_count_p = len(ros_players) - ros_count_h
    no_ros = sum(1 for p in outlook if not p.get("metadata", {}).get("has_ros", True))
    print(f"  {len(outlook)} outlook players ({no_ros} without ROS)")

    # Step 4: Staged publish — current.json first (load-bearing), metadata second
    _write_json(outlook, output_path)
    print(f"Written to {output_path}")

    metadata = {
        "as_of": as_of,
        "actuals_source": "mlb_stats_api",
        "ros_source": "fangraphs_steamer_ros",
        "actuals_hitters": actual_hitters,
        "actuals_pitchers": actual_pitchers,
        "ros_hitters": ros_count_h,
        "ros_pitchers": ros_count_p,
        "outlook_players": len(outlook),
        "players_without_ros": no_ros,
    }
    _write_json(metadata, metadata_path)
    print(f"Metadata written to {metadata_path}")

    return outlook


if __name__ == "__main__":
    refresh()
