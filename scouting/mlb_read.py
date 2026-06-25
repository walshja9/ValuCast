"""Deterministic MLB scouting reads from offline projection + Statcast inputs."""
from __future__ import annotations

RATE_STATS = {"AVG", "OBP", "SLG", "OPS", "ISO"}


def stat_line_stats(stat_line: dict | None) -> dict:
    """Return the projection stats dict from an MLB snapshot stat_line."""
    if not isinstance(stat_line, dict):
        return {}
    stats = stat_line.get("stats")
    if isinstance(stats, dict):
        return {
            str(key).upper(): value
            for key, value in stats.items()
            if value is not None
        }
    return {
        str(key).upper(): value
        for key, value in stat_line.items()
        if isinstance(value, (int, float))
    }


def _number(stats: dict, key: str) -> float | None:
    value = stats.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _format_stat(key: str, value: float) -> str:
    if key in RATE_STATS:
        text = f"{value:.3f}"
        return text.replace("0.", ".", 1) if text.startswith("0.") else text
    if key == "ERA":
        return f"{value:.2f}"
    if key == "WHIP":
        return f"{value:.2f}"
    if key in {"IP", "K", "HR", "SB", "R", "RBI", "W", "QS", "SV", "HLD", "PA"}:
        return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
    return f"{value:g}"


def _ordinal(value: int | float) -> str:
    number = int(value)
    suffix = (
        "th"
        if 10 <= number % 100 <= 20
        else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    )
    return f"{number}{suffix}"


def _flatten_metrics(statcast_groups: list[dict] | tuple[dict, ...] | None) -> list[dict]:
    metrics = []
    for group in statcast_groups or ():
        if not isinstance(group, dict):
            continue
        group_label = str(group.get("label") or "").strip()
        for metric in group.get("metrics") or ():
            if not isinstance(metric, dict):
                continue
            pct = metric.get("pct")
            if not isinstance(pct, (int, float)):
                continue
            item = {
                "group": group_label,
                "label": str(metric.get("label") or "").strip(),
                "pct": int(pct),
                "raw": metric.get("raw"),
                "display": metric.get("display"),
            }
            if item["label"]:
                metrics.append(item)
    return metrics


def _metric_phrase(metric: dict) -> str:
    phrase = f"{metric['label']} at the {_ordinal(metric['pct'])} percentile"
    display = str(metric.get("display") or "").strip()
    if display:
        phrase = f"{phrase} ({display})"
    return phrase


def _statcast_sentence(statcast_groups) -> str | None:
    metrics = _flatten_metrics(statcast_groups)
    if not metrics:
        return None
    strongest = max(metrics, key=lambda item: item["pct"])
    weakest = min(metrics, key=lambda item: item["pct"])
    if strongest is weakest:
        return f"The Statcast card leads with {_metric_phrase(strongest)}."
    return (
        f"The Statcast card leads with {_metric_phrase(strongest)}, "
        f"while {_metric_phrase(weakest)} is the main weakness."
    )


def _hitter_shape(stats: dict) -> str:
    parts = []
    hr = _number(stats, "HR")
    sb = _number(stats, "SB")
    obp = _number(stats, "OBP")
    if hr is not None and hr >= 25:
        parts.append("power")
    if sb is not None and sb >= 15:
        parts.append("speed")
    if obp is not None and obp >= 0.350:
        parts.append("OBP")
    return "/".join(parts) if parts else "batting-line"


def _hitter_projection_sentence(stats: dict) -> str:
    pieces = []
    for key in ("AVG", "OBP", "OPS", "HR", "SB", "RBI", "R"):
        value = _number(stats, key)
        if value is not None:
            pieces.append(f"{_format_stat(key, value)} {key}")
    pa = _number(stats, "PA")
    suffix = f" over {_format_stat('PA', pa)} PA" if pa is not None else ""
    if not pieces:
        return "The projection line is present, but it does not expose readable hitter stats."
    return f"The projection line is a {_hitter_shape(stats)} shape: {', '.join(pieces[:5])}{suffix}."


def _pitcher_projection_sentence(stats: dict) -> str:
    pieces = []
    for key in ("ERA", "WHIP", "K", "W", "QS", "SV"):
        value = _number(stats, key)
        if value is not None:
            pieces.append(f"{_format_stat(key, value)} {key}")
    ip = _number(stats, "IP")
    suffix = f" over {_format_stat('IP', ip)} IP" if ip is not None else ""
    if not pieces:
        return "The projection line is present, but it does not expose readable pitcher stats."
    return f"The projection line is a run-prevention/volume shape: {', '.join(pieces[:5])}{suffix}."


def build_mlb_scouting_read(
    row,
    statcast_groups: list[dict] | tuple[dict, ...] | None,
    stat_line_stats: dict | None,
) -> str:
    """Build a short MLB read from offline Statcast groups and projection stats."""
    stats = stat_line_stats or {}
    role = str(getattr(row, "role", "") or "").lower()
    projection = (
        _pitcher_projection_sentence(stats)
        if role == "pitcher"
        else _hitter_projection_sentence(stats)
    )
    statcast = _statcast_sentence(statcast_groups)
    if statcast:
        return f"{statcast} {projection}"
    return f"With no current percentile card, the read stays on the projected stat shape. {projection}"
