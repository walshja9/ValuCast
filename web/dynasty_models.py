"""Data models for DD Dynasty mode — separate from engine ValuationResult."""
from __future__ import annotations

from dataclasses import dataclass, field

from prospects.availability import eta_window as prospect_eta_window
from prospects.availability import eta_window_label

from .prospect_context import (
    context_note,
    skill_band_label,
    stat_items,
    uncertainty_driver_items,
    uncertainty_note,
    why_rank_chips,
)


# DD-internal model signals — not independent public boards, so they are
# excluded from the public-consensus surfaces. cfr is also excluded: it is a deep
# stat-formula list (scale ~1-5700) that poisons a median against top-N boards.
_INTERNAL_SOURCES = frozenset({"milb_perf", "milb_breakout", "cfr", "cfr_raw"})
# Only count ranks inside the top-prospect ceiling (600, ~PL+/HKB depth) so
# deep-list ranks (sts/fg run thousands deep) can't poison the median consensus.
_CONSENSUS_RANK_CAP = 600


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
    stat_line: dict | None = None
    # v1.1 feed fields (all optional — 1.0 feeds simply lack them)
    value_history: tuple = ()              # ((date, value), ...) chronological
    mlb_stat_line: dict | None = None      # call-ups: current-season MLB line
    stat_line_translated: dict | None = None  # MLB-equivalent peripherals
    combined_season_stat_line: dict | None = None  # display-only all-level 2026 line
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
            if source not in _INTERNAL_SOURCES
            and isinstance(rank, (int, float))
            and rank <= _CONSENSUS_RANK_CAP
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

    @property
    def eta_display(self) -> str | None:
        if self.eta is not None:
            return str(self.eta)
        return eta_window_label(
            self.metadata.get("eta_window")
            or prospect_eta_window({"eta": self.eta, "level": self.level})
        )

    @property
    def prospect_components(self) -> dict:
        if not isinstance(self.metadata, dict):
            return {}
        raw = self.metadata.get("components")
        if isinstance(raw, dict) and raw:
            return raw
        context = self.metadata.get("context")
        if isinstance(context, dict) and isinstance(context.get("components"), dict):
            return context["components"]
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
        if context.get("label"):
            return str(context["label"])
        bucket = str(context.get("bucket") or "").replace("_", " ").title()
        if "Lower Minors" in bucket:
            return "Lower-minors context"
        return bucket or "Model context"

    @property
    def factual_current_context(self) -> dict:
        raw = self.prospect_components.get("factual_current_context")
        return raw if isinstance(raw, dict) else {}

    @property
    def factual_skill_label(self) -> str | None:
        return skill_band_label(self.factual_current_context)

    @property
    def factual_context_note(self) -> str | None:
        return context_note(self.factual_current_context)

    @property
    def factual_context_stat_items(self) -> tuple[dict[str, str], ...]:
        return stat_items(self.factual_current_context)

    @property
    def uncertainty_context(self) -> dict:
        raw = self.prospect_components.get("uncertainty")
        return raw if isinstance(raw, dict) else {}

    @property
    def uncertainty_label(self) -> str | None:
        context = self.uncertainty_context
        band = str(context.get("band") or "").replace("_", " ").title()
        lower = _clean_float(context.get("lower"))
        upper = _clean_float(context.get("upper"))
        if lower is None or upper is None:
            return band or None
        return f"{band or 'Model'} band: {lower:.1f}-{upper:.1f}"

    @property
    def uncertainty_driver_items(self) -> tuple[dict[str, str], ...]:
        return uncertainty_driver_items(self.uncertainty_context)

    @property
    def uncertainty_note(self) -> str | None:
        return uncertainty_note(self.uncertainty_context)

    @property
    def why_rank_chips(self) -> tuple[dict[str, str], ...]:
        return why_rank_chips(self.prospect_components, self.metadata.get("role"))

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

    @staticmethod
    def _coerce_value_history(raw) -> tuple:
        """((date, value), ...) — drop malformed pairs, never reject the row."""
        out = []
        for item in raw or ():
            try:
                d, v = item[0], float(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if isinstance(d, str) and d:
                out.append((d, v))
        return tuple(out)

    @staticmethod
    def _coerce_int(raw):
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_dict(raw):
        return raw if isinstance(raw, dict) and raw else None

