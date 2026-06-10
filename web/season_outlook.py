"""Join a dynasty feed row to its season-outlook projection.

The DD feed carries no mlbam_id today, so the only available join key is the
player name — which collides (192 duplicated names in the projection set,
e.g. Will Smith the catcher vs Will Smith the reliever). A naive first-match
join shows the wrong player's stats. This module resolves the join safely:

  1. If the feed row has an mlbam_id, join by mlbam_id (the real key).
  2. Otherwise join by normalized name + pool/position compatibility.
     - exactly one compatible projection -> use it
     - multiple compatible projections sharing a base_id -> two-way player,
       merge their stat lines
     - multiple with differing base_id -> genuinely different people, return
       None (a missing outlook beats a wrong one)
"""
from __future__ import annotations

from typing import Iterable

from league_values.models import PlayerPool, PlayerProjection
from .dynasty_models import DynastyRankingRow

_PITCHER_POSITIONS = {"SP", "RP", "P"}
_PITCHER_POOLS = {PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER}

Outlook = tuple[dict | None, dict | None, dict | None]


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


def _row_sides(positions: Iterable[str]) -> tuple[bool, bool]:
    """(pitcher_side, hitter_side) for a feed row's positions.

    Any non-pitcher position (incl. UT/DH) counts as a hitter side.
    """
    pos = set(positions or ())
    return bool(pos & _PITCHER_POSITIONS), bool(pos - _PITCHER_POSITIONS)


def _is_pitcher(proj: PlayerProjection) -> bool:
    return proj.pool in _PITCHER_POOLS


def _base(proj: PlayerProjection) -> str:
    return proj.metadata.get("base_id") or proj.id


def _outlook(proj: PlayerProjection) -> Outlook:
    return (
        proj.stats,
        proj.metadata.get("stats_actual"),
        proj.metadata.get("stats_ros"),
    )


def _merge(dicts: Iterable[dict | None]) -> dict | None:
    """Union of stat dicts; first writer wins on key collisions."""
    merged: dict = {}
    for d in dicts:
        if d:
            for key, value in d.items():
                merged.setdefault(key, value)
    return merged or None


def _merged_outlook(projs: list[PlayerProjection]) -> Outlook:
    # Hitters first so shared counting stats (e.g. G) resolve to the hitter side.
    ordered = sorted(projs, key=_is_pitcher)
    return (
        _merge(p.stats for p in ordered),
        _merge(p.metadata.get("stats_actual") for p in ordered),
        _merge(p.metadata.get("stats_ros") for p in ordered),
    )


def find_outlook_projections(
    dd_row: DynastyRankingRow,
    projections: Iterable[PlayerProjection],
) -> list[PlayerProjection]:
    """The projection row(s) safely matching a feed row; [] when none/ambiguous.

    Multiple rows means a two-way player (shared base_id). Callers needing
    identity (mlbam_id / fangraphs_id) read it from any returned row.
    """
    projections = list(projections)

    # 1. mlbam_id is the real key (feed has none today; future-proofing).
    feed_mlbam = dd_row.mlbam_id
    if feed_mlbam:
        for proj in projections:
            if str(proj.metadata.get("mlbam_id") or "") == str(feed_mlbam):
                return [proj]

    # 2. Name + pool/position compatibility.
    name = _normalize_name(dd_row.name)
    pitcher_side, hitter_side = _row_sides(dd_row.positions)

    compatible = []
    for proj in projections:
        if _normalize_name(proj.name) != name:
            continue
        if (_is_pitcher(proj) and pitcher_side) or (not _is_pitcher(proj) and hitter_side):
            compatible.append(proj)

    if len(compatible) <= 1:
        return compatible

    # Multiple compatible: same person (shared base_id) -> two-way; else ambiguous.
    if len({_base(p) for p in compatible}) == 1:
        return compatible
    return []


def find_season_outlook(
    dd_row: DynastyRankingRow,
    projections: Iterable[PlayerProjection],
) -> Outlook | None:
    """Return (stats, stats_actual, stats_ros) for the matching projection, or None."""
    matches = find_outlook_projections(dd_row, projections)
    if not matches:
        return None
    if len(matches) == 1:
        return _outlook(matches[0])
    return _merged_outlook(matches)
