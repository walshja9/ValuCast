"""Load and validate the DD dynasty feed for the web app."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .dynasty_models import DynastyRankingRow

logger = logging.getLogger(__name__)

REQUIRED_RECORD_FIELDS = ("id", "player_type", "name", "dynasty_rank", "dynasty_value")


class DDFeedStore:
    """Loads and serves the DD dynasty rankings feed."""

    def __init__(self, path: str | Path) -> None:
        self._rows: list[DynastyRankingRow] = []
        self._by_id: dict[str, DynastyRankingRow] = {}
        self._is_available: bool = False
        self._generated_at: str | None = None
        self._load(Path(path))

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning("DD dynasty feed not found at %s", path)
            return

        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load DD feed: %s", e)
            return

        if raw.get("schema_version") != "1.0":
            logger.warning("DD feed schema_version is %s, expected 1.0", raw.get("schema_version"))
            return

        players = raw.get("players")
        if not players:
            logger.warning("DD feed has no players")
            return

        ids = [p.get("id") for p in players if p.get("id")]
        if len(ids) != len(set(ids)):
            logger.warning("DD feed contains duplicate IDs")
            return

        valid_rows = []
        skipped = 0
        for record in players:
            if not self._is_valid_record(record):
                skipped += 1
                continue
            try:
                row = DynastyRankingRow.from_feed(record)
                valid_rows.append(row)
            except Exception:
                skipped += 1

        total = len(players)
        if total > 0 and skipped / total > 0.50:
            logger.warning("DD feed has %.1f%% invalid records (%d/%d), rejecting",
                          skipped / total * 100, skipped, total)
            return

        if skipped > 0:
            logger.warning("DD feed: skipped %d invalid records", skipped)

        valid_rows.sort(key=lambda r: r.dynasty_rank)

        self._rows = valid_rows
        self._by_id = {r.id: r for r in valid_rows}
        self._generated_at = raw.get("generated_at")
        self._is_available = True

    @staticmethod
    def _is_valid_record(record: dict) -> bool:
        for fld in REQUIRED_RECORD_FIELDS:
            if fld not in record or record[fld] is None:
                return False
        if not isinstance(record.get("dynasty_value"), (int, float)):
            return False
        if not isinstance(record.get("dynasty_rank"), int):
            return False
        return True

    @property
    def is_available(self) -> bool:
        return self._is_available

    @property
    def generated_at(self) -> str | None:
        return self._generated_at

    def get_all(self) -> list[DynastyRankingRow]:
        return list(self._rows)

    def get_by_id(self, row_id: str) -> DynastyRankingRow | None:
        return self._by_id.get(row_id)

    def filter(
        self,
        player_type: str | None = None,
        position: str | None = None,
        search: str | None = None,
        pool: str | None = None,
    ) -> list[DynastyRankingRow]:
        results = self._rows
        if player_type:
            results = [r for r in results if r.player_type == player_type]
        if pool:
            if pool == "prospect":
                results = [r for r in results if r.is_prospect]
            elif pool == "mlb":
                results = [r for r in results if not r.is_prospect]
            elif pool == "hitter":
                results = [r for r in results
                           if any(p not in ("SP", "RP", "P") for p in r.positions)]
            elif pool == "pitcher":
                results = [r for r in results
                           if any(p in ("SP", "RP", "P") for p in r.positions)]
        if position:
            results = [r for r in results if position in r.positions]
        if search:
            query = search.lower()
            results = [r for r in results if query in r.name.lower()]
        return results
