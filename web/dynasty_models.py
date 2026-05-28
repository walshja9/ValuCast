"""Data models for DD Dynasty mode — separate from engine ValuationResult."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DynastyRankingRow:
    """A single player row in DD Dynasty rankings. Not an engine result."""
    id: str
    name: str
    player_type: str
    positions: tuple[str, ...]
    team: str
    age: int | None
    dynasty_rank: int
    dynasty_value: float
    status: str | None
    mlbam_id: str | None
    # MLB-specific (populated by join to season outlook)
    mlb_stats: dict | None = None
    mlb_stats_actual: dict | None = None
    mlb_stats_ros: dict | None = None
    # Prospect-specific (from feed)
    prospect_rank: int | None = None
    level: str | None = None
    eta: int | None = None
    source_ranks: dict | None = None
    breakout_label: str | None = None
    breakout_rank_change: int | None = None
    stat_line: dict | None = None
    # Raw metadata passthrough
    metadata: dict = field(default_factory=dict)

    TEAM_CODE_MAP = {
        "KCR": "KC", "SDP": "SD", "SFG": "SF", "TBR": "TB", "WSN": "WSH",
    }

    @property
    def is_prospect(self) -> bool:
        return self.player_type == "prospect"

    @classmethod
    def from_feed(cls, record: dict) -> DynastyRankingRow:
        """Create from a DD feed record."""
        positions = record.get("positions") or []
        raw_team = record.get("mlb_team", "")
        team = cls.TEAM_CODE_MAP.get(raw_team, raw_team)
        return cls(
            id=record["id"],
            name=record["name"],
            player_type=record["player_type"],
            positions=tuple(positions),
            team=team,
            age=record.get("age"),
            dynasty_rank=record["dynasty_rank"],
            dynasty_value=record["dynasty_value"],
            status=record.get("status"),
            mlbam_id=record.get("mlbam_id"),
            prospect_rank=record.get("prospect_rank"),
            level=record.get("level"),
            eta=record.get("eta"),
            source_ranks=record.get("source_ranks"),
            breakout_label=record.get("breakout_label"),
            breakout_rank_change=record.get("breakout_rank_change"),
            stat_line=record.get("stat_line"),
            metadata=record,
        )
