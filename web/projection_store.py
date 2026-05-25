from __future__ import annotations

import json
from pathlib import Path

from league_values.models import PlayerPool, PlayerProjection


class ProjectionStore:
    """Loads and caches player projections from a JSON file."""

    def __init__(self, path: str | Path) -> None:
        self._players: list[PlayerProjection] = []
        self._by_id: dict[str, PlayerProjection] = {}
        self._load(Path(path))

    def _load(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        seen_ids: set[str] = set()

        for entry in raw:
            meta = dict(entry.get("metadata", {}))
            meta["team"] = entry.get("team", "")

            stats = dict(entry.get("stats", {}))
            stats["TB"] = (
                stats.get("1B", 0) + 2 * stats.get("2B", 0)
                + 3 * stats.get("3B", 0) + 4 * stats.get("HR", 0)
            )
            stats["NSB"] = stats.get("SB", 0) - stats.get("CS", 0)

            entry_copy = dict(entry)
            entry_copy["metadata"] = meta
            entry_copy["stats"] = stats

            # Deduplicate IDs for two-way players (e.g. Ohtani as hitter + pitcher).
            # Suffix pitcher entry so engine can value each against the correct pool.
            player_id = str(entry_copy.get("id", ""))
            if player_id in seen_ids:
                pool = entry_copy.get("pool", "")
                suffix = "_P" if pool in ("starter", "reliever", "pitcher") else "_H"
                entry_copy["id"] = player_id + suffix
                meta["base_id"] = player_id
            seen_ids.add(player_id)

            player = PlayerProjection.from_dict(entry_copy)
            self._players.append(player)
            self._by_id[player.id] = player

    def get_all(self) -> list[PlayerProjection]:
        return list(self._players)

    def get_by_id(self, player_id: str) -> PlayerProjection | None:
        return self._by_id.get(player_id)

    def filter(
        self,
        pool: str | None = None,
        position: str | None = None,
        search: str | None = None,
    ) -> list[PlayerProjection]:
        results = self._players
        if pool:
            pool_enum = PlayerPool(pool)
            if pool_enum is PlayerPool.PITCHER:
                results = [
                    p for p in results
                    if p.pool in (PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER)
                ]
            else:
                results = [p for p in results if p.pool == pool_enum]
        if position:
            results = [p for p in results if position in p.positions]
        if search:
            query = search.lower()
            results = [p for p in results if query in p.name.lower()]
        return results

    @property
    def player_count(self) -> int:
        return len(self._players)
