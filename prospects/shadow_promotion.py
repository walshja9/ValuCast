"""ValuCast shadow-model promotion harness (the accountability harness).

Observe-only / shadow models (peak projection v2, playing-time role tracker v2, the
prospect dynasty layer) archive a dated forecast every build, but nothing decides when
one has earned its way onto the card. Without that, "observe-only" silently becomes
"write-only forever."

This harness reads each shadow's prediction archive, measures how much *graded* evidence
has accrued, and emits an honest per-model promotion gate (via prospects.gate.decide_gate)
— `insufficient_sample` until the evidence calendar is met. It is deliberately honest
about what it cannot yet do: a model is promoted by EVIDENCE, not by date, and realized
outcomes for most shadows accrue over weeks (same-season playing time) to years (dynasty
horizon). Realized-accuracy scorers plug in at `_realized` per model as that outcome
becomes available; until then the gate stays `insufficient_sample` and says why.

The one protective check it CAN run today: a shadow that already feeds the card while its
gate is not `active` is flagged as a blocker — promotion without evidence is the exact
failure mode this harness exists to prevent.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from prospects.gate import decide_gate, validate_gate

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_BASE = ROOT / "data" / "prediction_archive"
MODELS_DIR = ROOT / "data" / "models"
ARTIFACT_NAME = "valucast_prospect_shadow_promotion"
ARTIFACT_PATH = MODELS_DIR / f"{ARTIFACT_NAME}.json"
SELF_ARCHIVE_DIR = ARCHIVE_BASE / ARTIFACT_NAME
HARNESS_VERSION = "0.1.0"
MIN_IMPROVEMENT_PCT = 2.0

# realized-outcome availability:
#   same_season_actuals -> gradeable within the season once a forecast has aged
#   multi_year_horizon  -> realized peak/dynasty outcome only after the horizon closes
SHADOW_MODELS = [
    {
        "key": "playing_time_role_v2",
        "archive": "valucast_playing_time_role_tracker",
        "metric": "role_volume_realized_concordance",
        "realized": "same_season_actuals",
        "min_sample": 50,
        "min_span_days": 30,
        "lower_is_better": False,
        "card_flag_path": "v2.feeds_card",
        "promotion_target": "playing_time_role_tracker.role_v2 -> card",
    },
    {
        "key": "peak_projection_v2",
        "archive": "valucast_prospect_peak_projection_v1",
        "metric": "peak_role_outcome_brier",
        "realized": "multi_year_horizon",
        "min_sample": 250,
        "min_span_days": 0,
        "lower_is_better": True,
        "card_flag_path": "v2.feeds_card",
        "promotion_target": "peak_projection.peak_v2 -> card",
    },
    {
        "key": "prospect_dynasty_layer",
        "archive": "valucast_prospect_dynasty_layer",
        "metric": "bust_role_star_brier",
        "realized": "multi_year_horizon",
        "min_sample": 250,
        "min_span_days": 0,
        "lower_is_better": True,
        "card_flag_path": None,
        "promotion_target": "prospect dynasty_signal -> live consumer",
    },
]


def _archive_dates(name: str, archive_base: Path) -> list[str]:
    directory = archive_base / name
    if not directory.exists():
        return []
    dates = []
    for path in directory.glob("*.json"):
        try:
            date.fromisoformat(path.stem)
        except ValueError:
            continue
        dates.append(path.stem)
    return sorted(dates)


def _span_days(dates: list[str]) -> int:
    if len(dates) < 2:
        return 0
    return (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days


def _realized(spec: dict, dates: list[str], span: int) -> tuple[int, str]:
    """Realized-outcome sample available to grade TODAY, and an honest status string.

    Returns 0 until a real realized-accuracy scorer is wired for this model AND the
    evidence has accrued — grading 2-5 days of archives against incomplete outcomes
    would be grading noise. This is the seam where per-model scorers attach."""
    realized = spec["realized"]
    if realized == "multi_year_horizon":
        return 0, "realized peak/dynasty outcome accrues over the dynasty horizon; not yet available"
    if realized == "same_season_actuals":
        if span < spec["min_span_days"]:
            return 0, f"forecast not yet aged for a same-season realized check ({span}d/{spec['min_span_days']}d)"
        return 0, "evidence window met; realized-accuracy scorer pending (roster status + actuals)"
    return 0, "no realized-outcome source registered"


def _dig(obj, dotted_path: str):
    cur = obj
    for part in dotted_path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _live_card_flag(spec: dict, models_dir: Path):
    path = spec.get("card_flag_path")
    if not path:
        return None
    artifact = models_dir / f"{spec['archive']}.json"
    if not artifact.exists():
        return None
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt live artifact must not crash the harness
        return None
    return _dig(payload, path)


def _model_report(
    spec: dict, *, archive_base: Path, models_dir: Path, now: str
) -> tuple[dict, list[str]]:
    dates = _archive_dates(spec["archive"], archive_base)
    span = _span_days(dates)
    realized_sample, realized_status = _realized(spec, dates, span)
    gate = decide_gate(
        metric=spec["metric"],
        model_score=None,
        baselines={"prior_or_v1_baseline": None},
        sample_size=realized_sample,
        cv_method="forward_archive_vs_realized_outcome",
        validated_through=(dates[-1] if dates else None),
        min_sample=spec["min_sample"],
        min_improvement_pct=MIN_IMPROVEMENT_PCT,
        lower_is_better=spec["lower_is_better"],
        now=now,
    )
    card_flag = _live_card_flag(spec, models_dir)
    blockers: list[str] = []
    if not validate_gate(gate):
        blockers.append(f"{spec['key']} produced an invalid gate")
    if card_flag is True and gate["status"] != "active":
        blockers.append(
            f"{spec['key']} feeds the card but its promotion gate is {gate['status']}, not active"
        )
    report = {
        "key": spec["key"],
        "metric": spec["metric"],
        "archive": spec["archive"],
        "realized_outcome_kind": spec["realized"],
        "observation_count": len(dates),
        "observed_first": dates[0] if dates else None,
        "observed_last": dates[-1] if dates else None,
        "span_days": span,
        "realized_sample": realized_sample,
        "realized_status": realized_status,
        "feeds_card": card_flag,
        "gate": gate,
        "gradeable_when": {
            "min_sample": spec["min_sample"],
            "min_span_days": spec["min_span_days"],
            "span_met": span >= spec["min_span_days"],
            "sample_met": realized_sample >= spec["min_sample"],
        },
        "promotion_target": spec["promotion_target"],
    }
    return report, blockers


def build_shadow_promotion(
    *,
    archive_base: Path = ARCHIVE_BASE,
    models_dir: Path = MODELS_DIR,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    models: list[dict] = []
    blockers: list[str] = []
    for spec in SHADOW_MODELS:
        report, model_blockers = _model_report(
            spec, archive_base=archive_base, models_dir=models_dir, now=generated_at
        )
        models.append(report)
        blockers.extend(model_blockers)
    statuses = [model["gate"]["status"] for model in models]
    return {
        "artifact": ARTIFACT_NAME,
        "harness_version": HARNESS_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "purpose": (
            "Grade shadow models against realized outcomes and gate card promotion by "
            "evidence, not by date."
        ),
        "source_policy": {
            "dd_values_used": False,
            "dd_ranks_used": False,
            "public_rankings_used": False,
            "market_values_used": False,
            "feeds_card": False,
            "feeds_live_rank": False,
            "feeds_live_value": False,
        },
        "models": models,
        "summary": {
            "model_count": len(models),
            "active_count": statuses.count("active"),
            "fallback_count": statuses.count("fallback"),
            "failed_count": statuses.count("failed"),
            "insufficient_sample_count": statuses.count("insufficient_sample"),
        },
        "validation": {
            "ready": not blockers,
            "blockers": blockers,
        },
    }


def archive_shadow_promotion(
    payload: dict, date_str: str, archive_dir: Path = SELF_ARCHIVE_DIR
) -> tuple[Path, bool]:
    """Persist the day's promotion report so each model's path from insufficient_sample
    to active is auditable over time. Content-deduped + atomic, mirroring archive_rank."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "harness_version": payload["harness_version"],
        "generated_at": payload["generated_at"],
        "models": payload["models"],
        "summary": payload["summary"],
        "validation": payload["validation"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run_shadow_promotion(
    *,
    archive_base: Path = ARCHIVE_BASE,
    models_dir: Path = MODELS_DIR,
    artifact_path: Path = ARTIFACT_PATH,
    self_archive_dir: Path = SELF_ARCHIVE_DIR,
) -> dict:
    payload = build_shadow_promotion(archive_base=archive_base, models_dir=models_dir)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    date_str = str(payload["generated_at"])[:10]
    archive_path, archive_changed = archive_shadow_promotion(
        payload, date_str, archive_dir=self_archive_dir
    )
    return {
        "artifact_path": str(artifact_path),
        "ready": payload["validation"]["ready"],
        "model_count": payload["summary"]["model_count"],
        "active_count": payload["summary"]["active_count"],
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
    }


if __name__ == "__main__":
    result = run_shadow_promotion()
    print(
        "shadow promotion: "
        f"models={result['model_count']} active={result['active_count']} ready={result['ready']}"
    )
