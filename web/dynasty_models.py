"""Data models for DD Dynasty mode — separate from engine ValuationResult."""
from __future__ import annotations

from dataclasses import dataclass, field


# DD-internal model signals — not independent public boards, so they are
# excluded from the public-consensus surfaces.
_INTERNAL_SOURCES = frozenset({"milb_perf", "milb_breakout"})


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
    tier: str | int | None = None
    value_type: str | None = None
    market_value: float | None = None
    trend_delta: float | None = None
    trend_direction: str | None = None
    proj_pa: float | None = None
    proj_ip: float | None = None
    is_rp_only: bool | None = None
    dna: str | None = None
    z_scores: dict | None = None
    confidence: dict | None = None
    # MLB-specific (populated by join to season outlook)
    mlb_stats: dict | None = None
    mlb_stats_actual: dict | None = None
    mlb_stats_ros: dict | None = None
    # Prospect-specific (from feed)
    prospect_rank: int | None = None
    level: str | None = None
    eta: int | None = None
    source_ranks: dict | None = None
    source_divergence: float | None = None
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

    @property
    def public_source_ranks(self) -> dict:
        """Public prospect-board ranks, excluding DD's proprietary performance signal."""
        return {
            source: rank
            for source, rank in (self.source_ranks or {}).items()
            if source not in _INTERNAL_SOURCES and isinstance(rank, (int, float))
        }

    @property
    def public_source_consensus(self) -> int | None:
        """Rounded median public-board rank for a compact consensus comparison."""
        ranks = sorted(self.public_source_ranks.values())
        if not ranks:
            return None
        midpoint = len(ranks) // 2
        if len(ranks) % 2:
            return round(ranks[midpoint])
        return round((ranks[midpoint - 1] + ranks[midpoint]) / 2)

    @property
    def milb_performance_rank(self) -> int | float | None:
        return (self.source_ranks or {}).get("milb_perf")

    @classmethod
    def _normalize_positions(cls, positions: list) -> tuple:
        """Clean up noisy position data from feed."""
        cleaned = []
        has_sp = "SP" in positions
        has_rp = "RP" in positions
        for pos in positions:
            if pos == "P" and (has_sp or has_rp):
                continue  # drop redundant P
            if pos == "N/A" or pos is None:
                continue  # drop N/A
            if pos in ("RF", "LF", "CF") and "OF" in positions:
                continue  # drop specific OF when generic OF exists
            if pos not in cleaned:
                cleaned.append(pos)
        return tuple(cleaned) if cleaned else ("DH",)

    @classmethod
    def from_feed(cls, record: dict) -> DynastyRankingRow:
        """Create from a DD feed record."""
        positions = cls._normalize_positions(record.get("positions") or [])
        raw_team = record.get("mlb_team", "")
        team = cls.TEAM_CODE_MAP.get(raw_team, raw_team)
        return cls(
            id=record["id"],
            name=record["name"],
            player_type=record["player_type"],
            positions=positions,
            team=team,
            age=record.get("age"),
            dynasty_rank=record["dynasty_rank"],
            dynasty_value=record["dynasty_value"],
            status=record.get("status"),
            mlbam_id=record.get("mlbam_id"),
            tier=record.get("tier"),
            value_type=record.get("value_type"),
            market_value=record.get("market_value"),
            trend_delta=record.get("trend_delta"),
            trend_direction=record.get("trend_direction"),
            proj_pa=record.get("proj_pa"),
            proj_ip=record.get("proj_ip"),
            is_rp_only=record.get("is_rp_only"),
            dna=record.get("dna"),
            z_scores=record.get("z_scores"),
            confidence=record.get("confidence"),
            prospect_rank=record.get("prospect_rank"),
            level=record.get("level"),
            eta=record.get("eta"),
            source_ranks=record.get("source_ranks"),
            source_divergence=record.get("source_divergence"),
            breakout_label=record.get("breakout_label"),
            breakout_rank_change=record.get("breakout_rank_change"),
            stat_line=record.get("stat_line"),
            metadata=record,
        )
