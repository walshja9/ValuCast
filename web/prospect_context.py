"""Display helpers for ValuCast prospect model context."""
from __future__ import annotations

from typing import Any


_SKILL_LABELS = {
    ("hitter", "impact"): "Impact bat",
    ("hitter", "balanced"): "Balanced bat",
    ("hitter", "low_impact"): "Low impact",
    ("hitter", "thin"): "Thin sample",
    ("hitter", "limited"): "Limited sample",
    ("hitter", "mixed"): "Mixed bat",
    ("pitcher", "starter_volume"): "Starter volume",
    ("pitcher", "bat_missing"): "Bat-missing arm",
    ("pitcher", "thin"): "Thin sample",
    ("pitcher", "limited"): "Limited sample",
    ("pitcher", "mixed"): "Mixed arm",
}

_SKILL_KIND = {
    "impact": "positive",
    "starter_volume": "positive",
    "bat_missing": "positive",
    "balanced": "neutral",
    "mixed": "neutral",
    "low_impact": "caution",
    "thin": "caution",
    "limited": "caution",
}


def _clean_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def _format_sample(context: dict) -> str | None:
    sample = _clean_float(context.get("sample"))
    unit = context.get("sample_unit")
    if sample is None or not unit:
        return None
    sample_text = str(int(sample)) if sample.is_integer() else f"{sample:.1f}"
    return f"{sample_text} {unit}"


def _format_rate(value: Any, digits: int = 3) -> str | None:
    numeric = _clean_float(value)
    if numeric is None:
        return None
    return f"{numeric:.{digits}f}"


def _format_pct(value: Any) -> str | None:
    numeric = _clean_float(value)
    if numeric is None:
        return None
    return f"{numeric:.1f}%"


def _format_num(value: Any, digits: int = 1) -> str | None:
    numeric = _clean_float(value)
    if numeric is None:
        return None
    return f"{numeric:.{digits}f}"


def skill_band_label(context: dict | None) -> str | None:
    if not isinstance(context, dict):
        return None
    role = str(context.get("role") or "").lower()
    band = str(context.get("skill_band") or "").lower()
    return _SKILL_LABELS.get((role, band)) or band.replace("_", " ").title() or None


def skill_band_kind(context: dict | None) -> str:
    if not isinstance(context, dict):
        return "neutral"
    band = str(context.get("skill_band") or "").lower()
    return _SKILL_KIND.get(band, "neutral")


def stat_items(context: dict | None) -> tuple[dict[str, str], ...]:
    if not isinstance(context, dict):
        return ()
    role = str(context.get("role") or "").lower()
    items: list[dict[str, str]] = []
    sample = _format_sample(context)
    if sample:
        items.append({"label": "Sample", "value": sample})
    if role == "pitcher":
        for label, key, formatter in (
            ("K-BB%", "k_bb_pct", _format_pct),
            ("K/9", "k_per_9", lambda value: _format_num(value, 1)),
            ("BB/9", "bb_per_9", lambda value: _format_num(value, 1)),
        ):
            value = formatter(context.get(key))
            if value:
                items.append({"label": label, "value": value})
    else:
        for label, key, formatter in (
            ("OPS", "ops", _format_rate),
            ("ISO", "iso", _format_rate),
            ("BB-K", "bb_minus_k_pct", _format_pct),
        ):
            value = formatter(context.get(key))
            if value:
                items.append({"label": label, "value": value})
    return tuple(items)


def context_note(context: dict | None) -> str | None:
    if not isinstance(context, dict):
        return None
    label = skill_band_label(context)
    sample = _format_sample(context)
    if not label and not sample:
        return None
    if label and sample:
        return f"{label} from the current {sample} factual sample."
    if label:
        return f"{label} from the current factual sample."
    return f"Current factual sample: {sample}."


def why_rank_chips(components: dict | None, role: str | None = None) -> tuple[dict[str, str], ...]:
    if not isinstance(components, dict):
        return ()
    chips: list[dict[str, str]] = []
    context = components.get("factual_current_context")
    label = skill_band_label(context if isinstance(context, dict) else None)
    if label:
        chips.append(
            {
                "label": label,
                "kind": skill_band_kind(context),
                "title": context_note(context) or "Current factual sample context.",
            }
        )
    availability = components.get("availability")
    availability = availability if isinstance(availability, dict) else {}
    discount = _clean_float(components.get("availability_risk_discount")) or _clean_float(
        availability.get("risk_discount")
    ) or 0.0
    if components.get("availability_adjusted") is True or discount > 0:
        chips.append(
            {
                "label": "Sample adjusted",
                "kind": "caution",
                "title": "Availability or sample risk is priced into the score.",
            }
        )
    bucket = components.get("bucket_calibration")
    if isinstance(bucket, dict) and bucket:
        chips.append(
            {
                "label": "Bucket calibrated",
                "kind": "neutral",
                "title": str(bucket.get("reason") or "Bucket-level calibration rule applied."),
            }
        )
    return tuple(chips[:3])


def uncertainty_driver_items(context: dict | None) -> tuple[dict[str, str], ...]:
    if not isinstance(context, dict):
        return ()
    drivers = context.get("drivers")
    if not isinstance(drivers, dict):
        return ()
    items: list[dict[str, str]] = []
    for label, key in (
        ("Source", "score_source"),
        ("Confidence", "confidence"),
        ("Sample Reliability", "sample_reliability"),
        ("Skill Band", "skill_band"),
        ("Risk Discount", "availability_risk_discount"),
    ):
        value = drivers.get(key)
        if value in (None, ""):
            continue
        if key == "sample_reliability":
            numeric = _clean_float(value)
            value = f"{numeric:.1f}" if numeric is not None else str(value)
        elif key == "availability_risk_discount":
            numeric = _clean_float(value)
            value = f"{numeric * 100:.1f}%" if numeric is not None else str(value)
        else:
            value = str(value).replace("_", " ").title()
        items.append({"label": label, "value": str(value)})
    return tuple(items)


def uncertainty_note(context: dict | None) -> str | None:
    if not isinstance(context, dict):
        return None
    band = str(context.get("band") or "").replace("_", " ").lower()
    width = _clean_float(context.get("width"))
    if width is None:
        lower = _clean_float(context.get("lower"))
        upper = _clean_float(context.get("upper"))
        if lower is not None and upper is not None:
            width = abs(upper - lower) / 2.0
    if not band or width is None:
        return None
    return (
        f"This is a {band} uncertainty band of plus/minus "
        f"{width:.1f} points around the current ValuCast score. It shows "
        "confidence and doesn't move the rank or value."
    )
