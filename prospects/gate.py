"""Honest promotion gates for ValuCast prospect-model artifacts."""
from __future__ import annotations

GATE_STATUSES = ("active", "fallback", "failed", "insufficient_sample")
_GATE_KEYS = (
    "status",
    "reason",
    "metric",
    "baseline",
    "model_score",
    "baseline_score",
    "improvement_pct",
    "sample_size",
    "cv_method",
    "validated_through",
    "activated_at",
)


def _round(value, digits: int = 6):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(value, digits)
    return value


def pick_baseline(baselines: dict, lower_is_better: bool = True):
    items = [(name, score) for name, score in baselines.items() if score is not None]
    if not items:
        return None, None
    chooser = min if lower_is_better else max
    return chooser(items, key=lambda item: item[1])


def decide_gate(
    *,
    metric,
    model_score,
    baselines,
    sample_size,
    cv_method,
    validated_through,
    min_sample,
    min_improvement_pct: float = 0.0,
    lower_is_better: bool = True,
    now=None,
) -> dict:
    base_name, base_score = pick_baseline(baselines, lower_is_better)
    gate = {
        "status": None,
        "reason": "",
        "metric": metric,
        "baseline": base_name,
        "model_score": _round(model_score),
        "baseline_score": _round(base_score),
        "improvement_pct": None,
        "sample_size": sample_size,
        "cv_method": cv_method,
        "validated_through": validated_through,
        "activated_at": None,
    }
    if sample_size is None or sample_size < min_sample:
        gate["status"] = "insufficient_sample"
        gate["reason"] = f"sample_size {sample_size} < min_sample {min_sample}"
        return gate
    if model_score is None or base_score is None:
        gate["status"] = "failed"
        gate["reason"] = "model or baseline score unavailable"
        return gate
    if base_score == 0:
        improvement = 0.0
    elif lower_is_better:
        improvement = (base_score - model_score) / abs(base_score) * 100.0
    else:
        improvement = (model_score - base_score) / abs(base_score) * 100.0
    gate["improvement_pct"] = _round(improvement, 4)
    if improvement >= min_improvement_pct:
        gate["status"] = "active"
        gate["reason"] = f"beats {base_name} by {improvement:.2f}% OOS ({metric})"
        gate["activated_at"] = now
    else:
        gate["status"] = "fallback"
        gate["reason"] = (
            f"does not beat {base_name}: {improvement:.2f}% "
            f"< required {min_improvement_pct}%"
        )
    return gate


def validate_gate(gate) -> bool:
    return (
        isinstance(gate, dict)
        and set(gate) == set(_GATE_KEYS)
        and gate.get("status") in GATE_STATUSES
    )

