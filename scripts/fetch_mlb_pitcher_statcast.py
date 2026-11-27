#!/usr/bin/env python3
"""Fetch immutable compact MLB pitcher Statcast research artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from projections.data.pitching_statcast import (  # noqa: E402
    REGULAR_SEASON_BOUNDS,
    acquire_season,
)


def _season(value: str) -> int:
    if len(value) != 4 or not value.isdigit():
        raise argparse.ArgumentTypeError("season must be YYYY")
    season = int(value)
    if season not in REGULAR_SEASON_BOUNDS:
        raise argparse.ArgumentTypeError(
            f"season must be {min(REGULAR_SEASON_BOUNDS)}.."
            f"{max(REGULAR_SEASON_BOUNDS)}"
        )
    return season


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=_season)
    parser.add_argument("--start-season", type=_season)
    parser.add_argument("--end-season", type=_season)
    args = parser.parse_args(argv)

    single = args.season is not None
    ranged = args.start_season is not None or args.end_season is not None
    if single == ranged:
        parser.error(
            "choose exactly one mode: --season YYYY or "
            "--start-season YYYY --end-season YYYY"
        )
    if ranged and (args.start_season is None or args.end_season is None):
        parser.error("range mode requires both --start-season and --end-season")
    if ranged and args.start_season > args.end_season:
        parser.error("start season must not exceed end season")

    args.seasons = (
        [args.season]
        if single
        else list(range(args.start_season, args.end_season + 1))
    )
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    data_dir = ROOT / "projections" / "data"
    cache_root = data_dir / "pitching_statcast_cache"
    output_dir = data_dir / "pitching_statcast"
    for season in args.seasons:
        entry = acquire_season(
            season,
            data_dir=data_dir,
            cache_root=cache_root,
            output_dir=output_dir,
        )
        print(
            f"{season}: {entry['qualified_feature_row_count']} qualified rows, "
            f"sha256={entry['canonical_sha256']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
