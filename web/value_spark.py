"""Server-rendered sparkline geometry for dynasty value history.

Pure function: feed pairs in, SVG polyline geometry out. Rendering lives in
partials/_value_spark.html — no JS, so it works inside htmx-swapped card
partials and in non-JS contexts.
"""
from __future__ import annotations

W, H, PAD = 280, 56, 4


def build_spark(value_history, width: int = W, height: int = H):
    """value_history: ((date, value), ...) chronological. None when < 2 pts."""
    pts = [(d, float(v)) for d, v in (value_history or ()) if d]
    if len(pts) < 2:
        return None
    values = [v for _, v in pts]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = (width - 2 * PAD) / (len(pts) - 1)
    coords = [
        (round(PAD + i * step, 1),
         round(height - PAD - ((v - lo) / span) * (height - 2 * PAD), 1))
        for i, (_, v) in enumerate(pts)
    ]
    delta = round(values[-1] - values[0], 1)
    return {
        "points": " ".join(f"{x},{y}" for x, y in coords),
        "last_x": coords[-1][0], "last_y": coords[-1][1],
        "width": width, "height": height,
        "first_date": pts[0][0], "last_date": pts[-1][0],
        "min": round(lo, 1), "max": round(hi, 1),
        "delta": delta,
        "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
    }
