"""Public ValuCast dynasty snapshot row models.

These rows intentionally mirror the read surface used by the current dynasty
templates while avoiding DD ownership language in the snapshot contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field


_INTERNAL_SOURCES = frozenset({"milb_perf", "milb_breakout", "cfr_raw"})


def _clean_float(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _format_status(raw) -> str | None:
    if not raw:
        return None
    return str(raw).replace("_", " ").title()


@dataclass(frozen=True)
class PublicSnapshotRow:
    id: str
    name: str
    player_type: str
    positions: tuple[str, ...]
    team: str
    age: int | None
    rank: int
    value: float
    value_scale: str
    value_source: str
    confidence: str | dict | None
    updated_at: str
    mlbam_id: str | None
    role: str | None = None
    status: str | None = None
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
    prospect_rank: int | None = None
    level: str | None = None
    eta: int | None = None
    source_ranks: dict | None = None
    source_divergence: float | None = None
    breakout_label: str | None = None
    breakout_rank_change: int | None = None
    value_history: tuple = ()
    stat_line: dict | None = None
    mlb_stat_line: dict | None = None
    stat_line_translated: dict | None = None
    dynasty_signal: dict | None = None
    drivers: tuple[str, ...] = ()
    context: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @property
    def dynasty_rank(self) -> int:
        return self.rank

    @property
    def dynasty_value(self) -> float:
        return self.value

    @property
    def is_prospect(self) -> bool:
        return self.player_type == "prospect"

    @property
    def public_source_ranks(self) -> dict:
        return {
            source: rank
            for source, rank in (self.source_ranks or {}).items()
            if source not in _INTERNAL_SOURCES and isinstance(rank, (int, float))
        }

    @property
    def public_source_consensus(self) -> int | None:
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

    @property
    def prospect_components(self) -> dict:
        for raw in (
            self.metadata.get("components") if isinstance(self.metadata, dict) else None,
            self.context.get("components") if isinstance(self.context, dict) else None,
        ):
            if isinstance(raw, dict) and raw:
                return raw
        return {}

    @property
    def availability_context(self) -> dict:
        raw = self.prospect_components.get("availability")
        return raw if isinstance(raw, dict) else {}

    @property
    def availability_adjusted(self) -> bool:
        discount = _clean_float(self.prospect_components.get("availability_risk_discount"))
        return self.prospect_components.get("availability_adjusted") is True or (discount or 0.0) > 0

    @property
    def availability_risk_discount(self) -> float | None:
        return _clean_float(self.prospect_components.get("availability_risk_discount"))

    @property
    def availability_status_label(self) -> str | None:
        return _format_status(self.availability_context.get("status"))

    @property
    def availability_sample_label(self) -> str | None:
        sample = _clean_float(self.availability_context.get("sample"))
        unit = self.availability_context.get("sample_unit")
        if sample is None or not unit:
            return None
        if sample.is_integer():
            sample_text = str(int(sample))
        else:
            sample_text = f"{sample:.1f}"
        return f"{sample_text} {unit}"

    @property
    def availability_note(self) -> str | None:
        note = self.availability_context.get("note")
        return str(note) if note else None

    @property
    def bucket_calibration_context(self) -> dict:
        raw = self.prospect_components.get("bucket_calibration")
        return raw if isinstance(raw, dict) else {}

    @property
    def bucket_calibration_adjusted(self) -> bool:
        return bool(self.bucket_calibration_context)

    @property
    def bucket_calibration_label(self) -> str | None:
        context = self.bucket_calibration_context
        if not context:
            return None
        bucket = str(context.get("bucket") or "").replace("_", " ").title()
        adjustment = _clean_float(context.get("adjustment"))
        if adjustment is None:
            return bucket or "Bucket Calibration"
        return f"{bucket} ({adjustment:+.1f})"

    @staticmethod
    def _coerce_int(raw):
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_value_history(raw) -> tuple:
        out = []
        for item in raw or ():
            try:
                date, value = item[0], float(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if isinstance(date, str) and date:
                out.append((date, value))
        return tuple(out)

    @staticmethod
    def _coerce_dict(raw):
        return raw if isinstance(raw, dict) and raw else None

    @staticmethod
    def _coerce_confidence(raw):
        if isinstance(raw, dict):
            return raw or None
        if isinstance(raw, str) and raw:
            return {"level": raw}
        return None

    @staticmethod
    def _normalize_positions(raw) -> tuple[str, ...]:
        positions = []
        for position in raw or []:
            if position in (None, "", "N/A"):
                continue
            text = str(position)
            if text not in positions:
                positions.append(text)
        return tuple(positions) if positions else ("DH",)

    @classmethod
    def from_snapshot(cls, record: dict) -> "PublicSnapshotRow":
        context = record.get("context") if isinstance(record.get("context"), dict) else {}
        return cls(
            id=record["id"],
            name=record["name"],
            player_type=record["player_type"],
            positions=cls._normalize_positions(record.get("positions")),
            team=record.get("team") or record.get("mlb_team") or "",
            age=cls._coerce_int(record.get("age")),
            rank=int(record["rank"]),
            value=float(record["value"]),
            value_scale=record["value_scale"],
            value_source=record["value_source"],
            confidence=cls._coerce_confidence(record.get("confidence")),
            updated_at=record["updated_at"],
            mlbam_id=str(record["mlbam_id"]) if record.get("mlbam_id") not in (None, "") else None,
            role=record.get("role"),
            status=record.get("status"),
            tier=record.get("tier"),
            value_type=record.get("value_type"),
            market_value=record.get("market_value"),
            trend_delta=record.get("trend_delta"),
            trend_direction=record.get("trend_direction"),
            proj_pa=record.get("proj_pa"),
            proj_ip=record.get("proj_ip"),
            is_rp_only=record.get("is_rp_only"),
            dna=record.get("dna"),
            z_scores=cls._coerce_dict(record.get("z_scores")),
            prospect_rank=cls._coerce_int(record.get("prospect_rank")),
            level=record.get("level"),
            eta=cls._coerce_int(record.get("eta")),
            source_ranks=cls._coerce_dict(context.get("source_ranks")),
            source_divergence=record.get("source_divergence"),
            breakout_label=record.get("breakout_label") or context.get("breakout_label"),
            breakout_rank_change=cls._coerce_int(
                record.get("breakout_rank_change")
                if record.get("breakout_rank_change") is not None
                else context.get("breakout_rank_change")
            ),
            value_history=cls._coerce_value_history(context.get("value_history")),
            stat_line=cls._coerce_dict(record.get("stat_line")),
            mlb_stat_line=cls._coerce_dict(record.get("mlb_stat_line")),
            stat_line_translated=cls._coerce_dict(record.get("stat_line_translated")),
            dynasty_signal=cls._coerce_dict(record.get("dynasty_signal")),
            drivers=tuple(str(item) for item in record.get("drivers") or ()),
            context=context,
            metadata=record,
        )
