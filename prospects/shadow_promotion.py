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
ACTUALS_PATH = ROOT / "data" / "actuals" / "current.json"
ARTIFACT_NAME = "valucast_prospect_shadow_promotion"
ARTIFACT_PATH = MODELS_DIR / f"{ARTIFACT_NAME}.json"
SELF_ARCHIVE_DIR = ARCHIVE_BASE / ARTIFACT_NAME
HARNESS_VERSION = "0.1.0"
MIN_IMPROVEMENT_PCT = 2.0
# ponytail: fixed 2026 regular-season bounds for pro-rating a full-season forecast to
# the realized-to-date window. Bump per season; a stale window only mis-scales an
# interim same-season proxy, never the live card.
SEASON_START = date(2026, 3, 26)
SEASON_END = date(2026, 9, 28)

# realized-outcome availability:
#   same_season_actuals -> gradeable within the season once a forecast has aged
#   multi_year_horizon  -> realized peak/dynasty outcome only after the horizon closes
SHADOW_MODELS = [
    {
        "key": "playing_time_role_v2",
        "archive": "valucast_playing_time_role_tracker",
        "metric": "volume_forecast_mae_vs_realized",
        "realized": "same_season_actuals",
        "min_sample": 50,
        "min_span_days": 30,
        "lower_is_better": True,
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


def _season_fraction(as_of: date) -> float:
    total = (SEASON_END - SEASON_START).days
    elapsed = (as_of - SEASON_START).days
    return max(0.05, min(1.0, elapsed / total)) if total > 0 else 1.0


def _load_actuals(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - corrupt actuals must not crash the harness
        return {}
    out: dict[str, dict] = {}
    for row in rows if isinstance(rows, list) else []:
        meta = row.get("metadata") or {}
        mlbam_id = meta.get("mlbam_id") or row.get("mlbam_id")
        if mlbam_id in (None, ""):
            continue
        stats = row.get("stats") or {}
        out[str(mlbam_id)] = {"PA": stats.get("PA"), "IP": stats.get("IP"), "as_of": meta.get("as_of")}
    return out


def _score_role_v2(
    spec: dict, archive_base: Path, actuals_path: Path, today: date
) -> tuple[int, str, float | None, dict]:
    """Grade the OLDEST archived role-v2 volume forecast against realized PA/IP.

    Metric = mean absolute error of the volume forecast PRO-RATED to the realized window
    (forecast * season_fraction vs actual-to-date) — pro-rating down is stable, where
    annualizing actuals up amplifies small mid-season samples by 1/fraction. v2's
    injury/reliability-shaved point is scored against v1's raw projection as the baseline.
    Honest interim same-season proxy: the full season is not yet realized."""
    none_base = {"v1_volume_point": None}
    dates = _archive_dates(spec["archive"], archive_base)
    if not dates:
        return 0, "no role-tracker archive yet", None, none_base
    earliest = dates[0]
    horizon = (today - date.fromisoformat(earliest)).days
    if horizon < spec["min_span_days"]:
        return 0, f"earliest forecast {horizon}d old (<{spec['min_span_days']}d to grade)", None, none_base
    try:
        forecast = json.loads(
            (archive_base / spec["archive"] / f"{earliest}.json").read_text(encoding="utf-8")
        )
    except Exception:  # noqa: BLE001
        return 0, "earliest role archive unreadable", None, none_base
    actuals = _load_actuals(actuals_path)
    if not actuals:
        return 0, "no realized actuals available", None, none_base
    as_of_str = next((a["as_of"] for a in actuals.values() if a.get("as_of")), None)
    try:
        as_of = date.fromisoformat(as_of_str) if as_of_str else today
    except ValueError:
        as_of = today
    frac = _season_fraction(as_of)
    v1_err: list[float] = []
    v2_err: list[float] = []
    for profile in forecast.get("profiles") or []:
        realized = actuals.get(str(profile.get("mlbam_id")))
        if not realized:
            continue
        unit = profile.get("projected_volume_unit")
        actual = realized.get("PA") if unit == "PA" else realized.get("IP")
        v1_point = profile.get("projected_volume")
        v2_point = ((profile.get("role_v2") or {}).get("volume_forecast") or {}).get("point")
        if actual is None or v1_point in (None, 0) or v2_point is None:
            continue
        v1_err.append(abs(float(actual) - v1_point * frac))
        v2_err.append(abs(float(actual) - v2_point * frac))
    sample = len(v2_err)
    if sample == 0:
        return 0, f"no forecast rows from {earliest} matched realized actuals", None, none_base
    v2_mae = round(sum(v2_err) / sample, 2)
    v1_mae = round(sum(v1_err) / sample, 2)
    status = (
        f"graded {sample} forecasts from {earliest} vs actuals "
        f"(pro-rated to season fraction {frac:.2f}); interim same-season proxy"
    )
    return sample, status, v2_mae, {"v1_volume_point": v1_mae}


def _realized(
    spec: dict, *, archive_base: Path, actuals_path: Path, today: date
) -> tuple[int, str, float | None, dict]:
    """Realized-outcome sample + honest status + (model_score, baselines) to grade TODAY.

    Scorers attach per realized-outcome kind. Multi-year-horizon shadows stay
    insufficient_sample until the dynasty horizon closes (years); grading a few days of
    archives against incomplete outcomes would be grading noise."""
    realized = spec["realized"]
    if realized == "same_season_actuals":
        return _score_role_v2(spec, archive_base, actuals_path, today)
    if realized == "multi_year_horizon":
        return (
            0,
            "realized peak/dynasty outcome accrues over the dynasty horizon; not yet available",
            None,
            {"prior": None},
        )
    return 0, "no realized-outcome source registered", None, {"prior": None}


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
    spec: dict, *, archive_base: Path, models_dir: Path, actuals_path: Path, today: date, now: str
) -> tuple[dict, list[str]]:
    dates = _archive_dates(spec["archive"], archive_base)
    span = _span_days(dates)
    horizon = (today - date.fromisoformat(dates[0])).days if dates else 0
    realized_sample, realized_status, model_score, baselines = _realized(
        spec, archive_base=archive_base, actuals_path=actuals_path, today=today
    )
    gate = decide_gate(
        metric=spec["metric"],
        model_score=model_score,
        baselines=baselines,
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
        "forecast_horizon_days": horizon,
        "realized_sample": realized_sample,
        "realized_status": realized_status,
        "feeds_card": card_flag,
        "gate": gate,
        "gradeable_when": {
            "min_sample": spec["min_sample"],
            "min_span_days": spec["min_span_days"],
            "horizon_met": horizon >= spec["min_span_days"],
            "sample_met": realized_sample >= spec["min_sample"],
        },
        "promotion_target": spec["promotion_target"],
    }
    return report, blockers


def build_shadow_promotion(
    *,
    archive_base: Path = ARCHIVE_BASE,
    models_dir: Path = MODELS_DIR,
    actuals_path: Path = ACTUALS_PATH,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    today = date.fromisoformat(str(generated_at)[:10])
    models: list[dict] = []
    blockers: list[str] = []
    for spec in SHADOW_MODELS:
        report, model_blockers = _model_report(
            spec,
            archive_base=archive_base,
            models_dir=models_dir,
            actuals_path=actuals_path,
            today=today,
            now=generated_at,
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
    actuals_path: Path = ACTUALS_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    self_archive_dir: Path = SELF_ARCHIVE_DIR,
) -> dict:
    payload = build_shadow_promotion(
        archive_base=archive_base, models_dir=models_dir, actuals_path=actuals_path
    )
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
