from __future__ import annotations

from typing import Iterable

from .models import PlayerProjection, PlayerPool

_SUFFIXES = ("_P", "_H")


def strip_suffix(player_id: str) -> str:
    """Remove a trailing two-way dedupe suffix (_P / _H) added by ProjectionStore."""
    for suffix in _SUFFIXES:
        if player_id.endswith(suffix):
            return player_id[: -len(suffix)]
    return player_id


def _base(player: PlayerProjection) -> str:
    return player.metadata.get("base_id") or strip_suffix(player.id)


def _meets_threshold(
    player: PlayerProjection,
    hitter_pa: float,
    sp_ip: float,
    rp_ip: float,
) -> bool:
    if player.pool is PlayerPool.HITTER:
        volume = player.stats.get("PA", 0.0) or player.stats.get("AB", 0.0)
        return volume >= hitter_pa
    if player.pool is PlayerPool.STARTER:
        return player.stats.get("IP", 0.0) >= sp_ip
    if player.pool is PlayerPool.RELIEVER:
        return player.stats.get("IP", 0.0) >= rp_ip
    if player.pool is PlayerPool.PITCHER:
        # ambiguous generic pitcher (none in current data): use the lower bar
        return player.stats.get("IP", 0.0) >= rp_ip
    return True


def filter_by_playing_time(
    players: Iterable[PlayerProjection],
    *,
    hitter_pa: float,
    sp_ip: float,
    rp_ip: float,
    always_keep: Iterable[str] = frozenset(),
) -> list[PlayerProjection]:
    """Keep players clearing their pool's PA/IP bar, plus any in always_keep.

    The always_keep bypass joins two-way siblings on their shared base_id, so
    passing any identifier of a two-way player (display id, suffixed id, or
    base_id) retains both the hitter and pitcher rows.
    """
    players = list(players)
    keep_ids = set(always_keep)
    keep_bases = {strip_suffix(k) for k in keep_ids}

    # Pass 1: any explicitly kept id contributes its base to the keep set.
    for player in players:
        if player.id in keep_ids:
            keep_bases.add(_base(player))

    # Pass 2: retain by threshold, exact id, or shared base.
    return [
        player
        for player in players
        if _meets_threshold(player, hitter_pa, sp_ip, rp_ip)
        or player.id in keep_ids
        or _base(player) in keep_bases
    ]
