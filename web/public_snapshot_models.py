"""Public ValuCast dynasty snapshot row models.

These rows intentionally mirror the read surface used by the current dynasty
templates while avoiding DD ownership language in the snapshot contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .prospect_context import (
    context_note,
    skill_band_label,
    stat_items,
    uncertainty_driver_items,
    uncertainty_note,
    why_rank_chips,
)


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


def _format_sample(sample: float | None, unit: str | None) -> str | None:
    if sample is None or not unit:
        return None
    if sample.is_integer():
        sample_text = str(int(sample))
    else:
        sample_text = f"{sample:.1f}"
    return f"{sample_text} {unit}"


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
    peak_projection: dict | None = None
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
        return _format_sample(sample, unit)

    @property
    def stat_line_sample_label(self) -> str | None:
        sample = _clean_float(self.context.get("stat_line_sample"))
        unit = self.context.get("stat_line_sample_unit")
        return _format_sample(sample, unit)

    @property
    def stat_line_level_label(self) -> str | None:
        level = self.context.get("stat_line_level") or self.level
        return str(level) if level else None

    @staticmethod
    def _is_mlb_level(level: str | None) -> bool:
        return str(level or "").strip().upper() == "MLB"

    @property
    def _current_season_stat_line_level_label(self) -> str | None:
        if self.context.get("stat_line_source_kind") != "current_season":
            return None
        if not self.stat_line_sample_label:
            return None
        level = self.context.get("stat_line_level")
        return str(level) if level else None

    @property
    def has_graduated(self) -> bool:
        context = self.graduation_context
        return context.get("graduated") is True or context.get("status") == "graduated"

    @property
    def card_level_label(self) -> str | None:
        feed_level = str(self.level) if self.level else None
        current_level = self._current_season_stat_line_level_label
        if not self.is_prospect:
            return feed_level
        if self.has_graduated:
            return "MLB"
        if self._is_mlb_level(current_level) or self._is_mlb_level(feed_level):
            return "MLB"
        return current_level or feed_level

    @property
    def current_level_sample_label(self) -> str | None:
        sample = self.stat_line_sample_label
        if not sample:
            return None
        level = self.stat_line_level_label
        return f"{level} sample: {sample}" if level else f"Current sample: {sample}"

    @property
    def current_level_sample_badge(self) -> str | None:
        sample = self.stat_line_sample_label
        if not sample:
            return None
        level = self.stat_line_level_label
        return f"{level} {sample}" if level else sample

    @property
    def _season_total_sample_parts(self) -> tuple[float | None, str | None, str | None, str | None]:
        translated = self.stat_line_translated or {}
        sample = _clean_float(translated.get("sample"))
        unit = translated.get("sample_unit")
        if sample is None:
            sample = _clean_float(self.availability_context.get("sample"))
        if not unit:
            unit = self.availability_context.get("sample_unit")
        season = translated.get("season") or self.context.get("stat_line_sample_season")
        levels = translated.get("level_label")
        if not levels and isinstance(translated.get("levels"), list):
            levels = "+".join(str(level) for level in translated["levels"] if level)
        return sample, unit, str(season) if season else None, str(levels) if levels else None

    @property
    def has_split_level_sample(self) -> bool:
        total, unit, _season, levels = self._season_total_sample_parts
        current = _clean_float(self.context.get("stat_line_sample"))
        current_unit = self.context.get("stat_line_sample_unit")
        if total is None or current is None or not unit or unit != current_unit:
            return False
        threshold = 1.0 if str(unit).upper() == "PA" else 0.5
        return total > current + threshold and bool(levels)

    @property
    def season_total_sample_label(self) -> str | None:
        if not self.has_split_level_sample:
            return None
        sample, unit, season, levels = self._season_total_sample_parts
        sample_label = _format_sample(sample, unit)
        if not sample_label:
            return None
        label = f"{season or 'Season'} total: {sample_label}"
        if levels:
            label = f"{label} across {levels}"
        return label

    @property
    def season_total_sample_badge(self) -> str | None:
        if not self.has_split_level_sample:
            return None
        sample, unit, season, _levels = self._season_total_sample_parts
        sample_label = _format_sample(sample, unit)
        if not sample_label:
            return None
        return f"{season or 'Season'} total {sample_label}"

    @property
    def sample_context_label(self) -> str | None:
        labels = [
            self.current_level_sample_label,
            self.season_total_sample_label,
        ]
        labels = [label for label in labels if label]
        return " | ".join(labels) if labels else None

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
        return why_rank_chips(self.prospect_components, self.role)

    @property
    def peak_projection_context(self) -> dict:
        raw = self.peak_projection
        return raw if isinstance(raw, dict) else {}

    @property
    def has_peak_projection(self) -> bool:
        return bool(self.peak_projection_context)

    @property
    def peak_projection_summary(self) -> str | None:
        summary = self.peak_projection_context.get("summary")
        if not summary:
            return None
        text = str(summary)
        for marker in (
            "; this is a role and skill-shape projection, not a full stat forecast.",
            " This is a role and skill-shape projection, not a full stat forecast.",
        ):
            text = text.replace(marker, ".")
        return text.replace("Peak read:", "Projection:")

    @property
    def peak_card_v2_context(self) -> dict:
        raw = self.peak_projection_context.get("card_v2")
        return raw if isinstance(raw, dict) else {}

    @property
    def peak_projection_card_copy(self) -> str | None:
        text = self.peak_card_v2_context.get("card_copy")
        return str(text) if text else self.peak_projection_summary

    @property
    def peak_projection_note(self) -> str:
        return "Projected peak role and shape — context only, it doesn't change the current rank or value."

    @property
    def peak_score_label(self) -> str | None:
        value = _clean_float(self.peak_projection_context.get("peak_score"))
        return f"{value:.1f}" if value is not None else None

    @property
    def peak_role_label(self) -> str | None:
        role = self.peak_projection_context.get("peak_role")
        return _format_status(role)

    @property
    def peak_floor_label(self) -> str | None:
        floor = self.peak_projection_context.get("floor_band")
        return _format_status(floor)

    @property
    def peak_risk_label(self) -> str | None:
        risk = self.peak_projection_context.get("risk_band")
        return _format_status(risk)

    @property
    def peak_confidence_label(self) -> str | None:
        confidence = self.peak_projection_context.get("confidence")
        return _format_status(confidence)

    @property
    def peak_eta_label(self) -> str | None:
        eta = self.peak_projection_context.get("eta_window")
        if eta in (None, ""):
            return None
        return str(eta).replace("_", " ").title()

    @property
    def peak_delta_label(self) -> str | None:
        value = _clean_float(self.peak_card_v2_context.get("score_delta"))
        if value is None:
            return None
        sign = "+" if value > 0 else ""
        return f"{sign}{value:.1f}"

    @property
    def peak_trajectory_label(self) -> str | None:
        trajectory = self.peak_card_v2_context.get("trajectory")
        if not trajectory:
            return None
        labels = {
            "more_peak_than_current_value": "More peak than current value",
            "current_value_ahead_of_peak_read": "Current value ahead of peak read",
            "current_and_peak_aligned": "Current and peak aligned",
        }
        return labels.get(str(trajectory), str(trajectory).replace("_", " ").title())

    @property
    def peak_role_probability_items(self) -> tuple[dict[str, str], ...]:
        raw = self.peak_card_v2_context.get("role_probabilities")
        if not isinstance(raw, dict):
            return ()
        labels = {
            "regular_or_better": "Regular+",
            "bench_or_platoon": "Bench/platoon",
            "depth_or_reserve": "Depth/reserve",
            "starter_or_better": "Starter+",
            "multi_inning_or_setup": "Multi-inning/setup",
            "relief_or_depth": "Relief/depth",
        }
        items = []
        for key, label in labels.items():
            value = _clean_float(raw.get(key))
            if value is None:
                continue
            pct = max(0, min(100, round(value * 100)))
            items.append(
                {
                    "key": key,
                    "label": label,
                    "pct": pct,
                    "value": f"{pct}%",
                }
            )
        return tuple(items)

    @property
    def peak_shape_items(self) -> tuple[dict[str, str | int], ...]:
        items = []
        for raw in self.peak_projection_context.get("shape") or ():
            if not isinstance(raw, dict):
                continue
            grade = self._coerce_int(raw.get("grade"))
            label = raw.get("label")
            if grade is None or not label:
                continue
            items.append(
                {
                    "label": str(label),
                    "grade": grade,
                    "metrics": str(raw.get("source") or ""),
                }
            )
        return tuple(items)

    @property
    def graduation_context(self) -> dict:
        raw = self.context.get("graduation_context")
        return raw if isinstance(raw, dict) else {}

    @property
    def graduation_context_label(self) -> str | None:
        context = self.graduation_context
        if not context:
            return None
        if context.get("status") == "near_graduation":
            unit = context.get("unit") or ""
            current = _clean_float(context.get("current"))
            limit = _clean_float(context.get("limit"))
            if current is not None and limit is not None:
                return f"Near grad {current:.1f}/{limit:.0f} {unit}".strip()
            return "Near graduation"
        if context.get("status") == "graduated":
            return "Graduated"
        return str(context.get("label") or "").strip() or None

    @property
    def graduation_context_note(self) -> str | None:
        context = self.graduation_context
        if not context:
            return None
        unit = context.get("unit") or "rookie-limit units"
        current = _clean_float(context.get("current"))
        limit = _clean_float(context.get("limit"))
        remaining = _clean_float(context.get("remaining"))
        if current is None or limit is None:
            return None
        if context.get("graduated") is True:
            return (
                f"MLB service is at {current:.1f}/{limit:.0f} {unit}; this player "
                "has crossed the rookie-limit line and should move to the MLB surface."
            )
        if remaining is not None:
            return (
                f"MLB service is at {current:.1f}/{limit:.0f} {unit}, about "
                f"{remaining:.1f} {unit} from prospect graduation."
            )
        return f"MLB service is at {current:.1f}/{limit:.0f} {unit}."

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
            peak_projection=cls._coerce_dict(record.get("peak_projection")),
            dynasty_signal=cls._coerce_dict(record.get("dynasty_signal")),
            drivers=tuple(str(item) for item in record.get("drivers") or ()),
            context=context,
            metadata=record,
        )
