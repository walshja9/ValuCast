"""Orchestrator: fetch ROS projections + actuals, combine, write output."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone

from .fangraphs import fetch_all, save_raw
from .blend import blend_projections
from .mlb_actuals import build_actuals, regular_season_games_final
from .combine import attach_actuals, combine_outlook
from . import season as season_config
from .season import context_season

_BASE = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_OUTPUT = os.path.join(_BASE, "data", "projections", "current.json")
DEFAULT_ROS_OUTPUT = os.path.join(_BASE, "data", "projections", "ros.json")
DEFAULT_ACTUALS_OUTPUT = os.path.join(_BASE, "data", "actuals", "current.json")
DEFAULT_METADATA = os.path.join(_BASE, "data", "projections", "metadata.json")
DEFAULT_RAW_DIR = os.path.join(_BASE, "data", "projections", "raw")


def _write_json(data, path: str) -> str:
    """Write exact JSON bytes via .tmp + os.replace and return their SHA-256."""
    payload_bytes = json.dumps(data, indent=2).encode("utf-8")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(payload_bytes)
    os.replace(tmp_path, path)
    return hashlib.sha256(payload_bytes).hexdigest()


def refresh(
    output_path: str = DEFAULT_OUTPUT,
    ros_output_path: str = DEFAULT_ROS_OUTPUT,
    actuals_output_path: str = DEFAULT_ACTUALS_OUTPUT,
    metadata_path: str = DEFAULT_METADATA,
    raw_dir: str = DEFAULT_RAW_DIR,
    delay: float = 1.0,
    season: int | None = None,
) -> list[dict]:
    as_of = date.today().isoformat()
    season = season or int(os.environ.get("VALUCAST_ACTUALS_SEASON") or context_season())

    # Step 1: Fetch and blend ROS projections
    print("Fetching ROS projections from FanGraphs...")
    preseason = season_config.is_preseason()
    raw = fetch_all(delay=delay, system="steamer") if preseason else fetch_all(delay=delay)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    for key, players in raw.items():
        print(f"  {key}: {len(players)} players")
    if all(not players for players in raw.values()) and regular_season_games_final(
        (date.fromisoformat(as_of) - timedelta(days=7)).isoformat(), as_of
    ) == 0:
        try:
            with open(metadata_path, encoding="utf-8") as f:
                prior_metadata = json.load(f)
        except FileNotFoundError as exc:
            if preseason:
                raise RuntimeError("Cannot verify prior ROS target_season") from exc
            prior_metadata = {}
        except (OSError, ValueError) as exc:
            if preseason:
                raise RuntimeError("Cannot verify prior ROS target_season") from exc
            raise RuntimeError("Cannot read prior ROS provenance metadata") from exc
        if preseason:
            if (not isinstance(prior_metadata, dict)
                    or prior_metadata.get("target_season") != season_config.TARGET_SEASON):
                raise RuntimeError("Prior ROS target_season must match TARGET_SEASON")
        if not isinstance(prior_metadata, dict):
            raise RuntimeError("Prior ROS metadata must be an object")
        # Legacy build dates do not establish the retained source's vintage.
        ros_provenance = prior_metadata.get("ros_provenance", {})
        if not isinstance(ros_provenance, dict):
            raise RuntimeError("Prior ROS provenance must be an object")
        if (ros_provenance.get("target_season") is not None
                and ros_provenance["target_season"] != season_config.TARGET_SEASON):
            raise RuntimeError("Prior ROS provenance target_season must match TARGET_SEASON")
        try:
            with open(ros_output_path, "rb") as f:
                ros_bytes = f.read()
            ros_players = json.loads(ros_bytes.decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Cannot read prior ROS projections from {ros_output_path}") from exc
        if not isinstance(ros_players, list) or not ros_players:
            raise RuntimeError("Prior ROS projections must be a non-empty list")
        # Legacy provenance without a digest remains unqualified; never backfill a binding.
        ros_input_sha256 = hashlib.sha256(ros_bytes).hexdigest()
        if ("ros_sha256" in ros_provenance
                and ros_provenance["ros_sha256"] != ros_input_sha256):
            raise RuntimeError("Prior ROS provenance SHA-256 does not match retained ROS bytes")
        ros_status = "retained"
        print("::warning::FanGraphs feed is empty with no regular-season games in the last 7 days; "
              "prior ros.json is retained.")
    else:
        save_raw(raw, raw_dir)

        print("Blending ROS projections...")
        ros_players = blend_projections(raw)
        print(f"  {len(ros_players)} ROS players")
        ros_status = "fetched"
        ros_provenance = {
            "source": "fangraphs_steamer_full_season" if preseason else "fangraphs_steamer_ros",
            "target_season": season_config.TARGET_SEASON,
            "projection_phase": "preseason_full_season" if preseason else "in_season_outlook",
            "source_retrieved_at": retrieved_at,
            "source_observed_at": None,
            "source_published_at": None,
        }

    # Step 2: Fetch actuals from MLB Stats API
    print(f"Fetching {season} actuals from MLB Stats API...")
    actual_players = build_actuals(season=season, as_of=as_of)
    actual_hitters = sum(1 for p in actual_players if p["pool"] == "hitter")
    actual_pitchers = len(actual_players) - actual_hitters
    print(f"  {actual_hitters} hitters, {actual_pitchers} pitchers")
    actuals_sha256 = _write_json(actual_players, actuals_output_path)

    # Step 3: Combine into season outlook
    print("Combining actuals + ROS into season outlook...")
    outlook = attach_actuals(ros_players, actual_players) if preseason else combine_outlook(ros_players, actual_players)
    ros_count_h = sum(1 for p in ros_players if p["pool"] == "hitter")
    ros_count_p = len(ros_players) - ros_count_h
    no_ros = sum(1 for p in outlook if not p.get("metadata", {}).get("has_ros", True))
    print(f"  {len(outlook)} outlook players ({no_ros} without ROS)")

    # Step 4: Publish projections after the build succeeds, then their metadata.
    if ros_status == "fetched":
        ros_input_sha256 = _write_json(ros_players, ros_output_path)
        ros_provenance["ros_sha256"] = ros_input_sha256
    current_sha256 = _write_json(outlook, output_path)
    print(f"Written to {output_path}")

    metadata = {
        "as_of": as_of,
        "season": season,
        "target_season": season_config.TARGET_SEASON,
        "projection_phase": "preseason_full_season" if preseason else "in_season_outlook",
        "actuals_source": "mlb_stats_api",
        "ros_source": "fangraphs_steamer_full_season" if preseason else "fangraphs_steamer_ros",
        "ros_status": ros_status,
        "ros_provenance": ros_provenance,
        "payload_provenance": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "current_sha256": current_sha256,
            "input_sha256": {"ros": ros_input_sha256, "actuals": actuals_sha256},
        },
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
