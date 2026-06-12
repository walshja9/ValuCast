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

from collections import defaultdict
from typing import Iterable

from league_values.models import PlayerPool, PlayerProjection
from .dynasty_models import DynastyRankingRow

_PITCHER_POSITIONS = {"SP", "RP", "P"}
_PITCHER_POOLS = {PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER}

Outlook = tuple[dict | None, dict | None, dict | None]
SplitStats = dict[str, dict | None]
SplitOutlook = tuple[SplitStats, SplitStats, SplitStats]


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


def _split_dicts(projs: Iterable[PlayerProjection], getter) -> SplitStats:
    hitting = _merge(getter(p) for p in projs if not _is_pitcher(p))
    pitching = _merge(getter(p) for p in projs if _is_pitcher(p))
    return {"hitting": hitting, "pitching": pitching}


def split_outlook(projs: Iterable[PlayerProjection]) -> SplitOutlook:
    """Hitting/pitching views of outlook, actuals, and ROS for matched rows."""
    rows = list(projs)
    return (
        _split_dicts(rows, lambda p: p.stats),
        _split_dicts(rows, lambda p: p.metadata.get("stats_actual")),
        _split_dicts(rows, lambda p: p.metadata.get("stats_ros")),
    )


class OutlookMatchIndex:
    """Reusable safe matcher for a static projection collection."""

    def __init__(self, projections: Iterable[PlayerProjection]) -> None:
        self.projections = list(projections)
        self._by_mlbam: dict[str, list[PlayerProjection]] = defaultdict(list)
        self._by_name: dict[str, list[PlayerProjection]] = defaultdict(list)
        for proj in self.projections:
            mlbam = str(proj.metadata.get("mlbam_id") or "").strip()
            if mlbam:
                self._by_mlbam[mlbam].append(proj)
            self._by_name[_normalize_name(proj.name)].append(proj)

    def find(self, dd_row: DynastyRankingRow) -> list[PlayerProjection]:
        feed_mlbam = str(dd_row.mlbam_id or "").strip()
        if feed_mlbam:
            matches = self._by_mlbam.get(feed_mlbam, [])
            if matches:
                return list(matches)

        pitcher_side, hitter_side = _row_sides(dd_row.positions)
        compatible = [
            proj for proj in self._by_name.get(_normalize_name(dd_row.name), [])
            if (_is_pitcher(proj) and pitcher_side)
            or (not _is_pitcher(proj) and hitter_side)
        ]
        if len(compatible) <= 1:
            return compatible
        if len({_base(p) for p in compatible}) == 1:
            return compatible
        return []


def build_outlook_match_index(
    projections: Iterable[PlayerProjection],
) -> OutlookMatchIndex:
    """Build the safe name+team/pool guarded matcher once for batch joins."""
    return OutlookMatchIndex(projections)


def find_outlook_projections(
    dd_row: DynastyRankingRow,
    projections: Iterable[PlayerProjection] | OutlookMatchIndex,
) -> list[PlayerProjection]:
    """The projection row(s) safely matching a feed row; [] when none/ambiguous.

    Multiple rows means a two-way player (shared base_id). Callers needing
    identity (mlbam_id / fangraphs_id) read it from any returned row.
    """
    index = (
        projections
        if isinstance(projections, OutlookMatchIndex)
        else build_outlook_match_index(projections)
    )
    return index.find(dd_row)


def find_season_outlook(
    dd_row: DynastyRankingRow,
    projections: Iterable[PlayerProjection] | OutlookMatchIndex,
) -> Outlook | None:
    """Return (stats, stats_actual, stats_ros) for the matching projection, or None."""
    matches = find_outlook_projections(dd_row, projections)
    if not matches:
        return None
    if len(matches) == 1:
        return _outlook(matches[0])
    return _merged_outlook(matches)


def find_season_outlook_split(
    dd_row: DynastyRankingRow,
    projections: Iterable[PlayerProjection] | OutlookMatchIndex,
) -> SplitOutlook | None:
    """Return split hitting/pitching outlook views for a safely matched row."""
    matches = find_outlook_projections(dd_row, projections)
    return split_outlook(matches) if matches else None
