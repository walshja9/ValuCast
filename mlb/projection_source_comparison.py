"""Advisory MLB projection-source comparison: ValuCast Marcel/H+P vs Steamer/ROS.

Daily-freezes both PURE projection sources (no actual leakage) so they can later be
scored against actuals that accrue FORWARD of the freeze. The comparison is ADVISORY
ONLY — it never flips the live dynasty source. The live source flip is a separate,
manual, default-off env switch (`VALUCAST_MLB_LIVE_PROJECTION_SOURCE`) consulted by
scripts/build_mlb_dynasty_layer.py.

Fairness: both sides are frozen pure projections; the comparison reads the OLDEST freeze
so its projection genuinely predates the scored actuals (mirrors the role_v2 forward
scorer). The gate cannot claim a win before enough forward horizon + sample exist.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.gate import decide_gate, validate_gate

ROOT = Path(__file__).resolve().parents[1]
MARCEL_PATH = ROOT / "projections" / "runs" / "valucast_hp_2026_v2" / "projections.json"
STEAMER_ROS_PATH = ROOT / "data" / "projections" / "ros.json"
ACTUALS_PATH = ROOT / "data" / "actuals" / "current.json"
LIVE_LAYER_PATH = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
SHADOW_LAYER_PATH = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer_marcel_shadow.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_mlb_projection_source_comparison.json"
FREEZE_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_mlb_projection_source_freeze"
COMPARISON_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_mlb_projection_source_comparison"

ARTIFACT_NAME = "valucast_mlb_projection_source_comparison"
COMPARISON_VERSION = "0.1.0"
METRIC = "rate_stat_mae_ratio_vs_forward_actuals"

HITTER_RATE_KEYS = ("AVG", "OBP", "SLG", "OPS")
PITCHER_RATE_KEYS = ("ERA", "WHIP")  # the rate stats present across all three sources
PITCHER_POOLS = {"pitcher", "starter", "reliever"}

MIN_HITTER_PA = 50.0       # forward actual volume needed for a hitter to be scoreable
MIN_PITCHER_IP = 20.0      # forward actual volume needed for a pitcher to be scoreable
MIN_SAMPLE = 50            # min scoreable players before the gate may claim a result
MIN_HORIZON_DAYS = 30      # the frozen projection must predate the actuals by this much
MIN_IMPROVEMENT_PCT = 2.0  # Marcel must beat Steamer by this margin to "win"
WHAT_WOULD_CHANGE_TOP_N = 25


# --------------------------------------------------------------------------- helpers
def _role(row: dict) -> str:
    return "pitcher" if str(row.get("pool") or "").lower() in PITCHER_POOLS else "hitter"


def _mlbam_id(row: dict) -> str | None:
    value = (row.get("metadata") or {}).get("mlbam_id", row.get("mlbam_id"))
    return None if value in (None, "") else str(value)


def _finite(value) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric and numeric not in (float("inf"), float("-inf")) else None


def _rate_keys(role: str) -> tuple[str, ...]:
    return PITCHER_RATE_KEYS if role == "pitcher" else HITTER_RATE_KEYS


def _volume(stats: dict, role: str) -> float:
    key = "IP" if role == "pitcher" else "PA"
    return _finite(stats.get(key)) or 0.0


def _rate_lines(rows: list[dict]) -> dict[str, dict]:
    """{mlbam_id: {role, rates:{key:val}, volume}} for one source, largest-volume wins on dup."""
    out: dict[str, dict] = {}
    for row in rows:
        mlbam_id = _mlbam_id(row)
        if not mlbam_id:
            continue
        role = _role(row)
        stats = row.get("stats") or {}
        rates = {k: v for k in _rate_keys(role) if (v := _finite(stats.get(k))) is not None}
        if not rates:
            continue
        volume = _volume(stats, role)
        existing = out.get(mlbam_id)
        if existing is None or volume > existing["volume"]:
            out[mlbam_id] = {"role": role, "rates": rates, "volume": round(volume, 3)}
    return out


def _coverage(lines: dict[str, dict]) -> dict:
    hitters = sum(1 for v in lines.values() if v["role"] == "hitter")
    return {"player_count": len(lines), "hitter_count": hitters, "pitcher_count": len(lines) - hitters}


def _date_part(value) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _parse_date(value):
    iso = _date_part(value)
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        return None


# --------------------------------------------------------------------------- freeze
def build_freeze(marcel_rows: list[dict], steamer_rows: list[dict], generated_at: str) -> dict:
    marcel = _rate_lines(marcel_rows)
    steamer = _rate_lines(steamer_rows)
    return {
        "date": _date_part(generated_at),
        "generated_at": generated_at,
        "comparison_version": COMPARISON_VERSION,
        "sources": {
            "valucast_hp": {
                "source": "projections/runs/valucast_hp_2026_v2/projections.json",
                "kind": "valucast_hp_projection_run",
                "coverage": _coverage(marcel),
                "rate_lines": marcel,
            },
            "steamer_ros": {
                "source": "data/projections/ros.json",
                "kind": "steamer_rest_of_season",
                "coverage": _coverage(steamer),
                "rate_lines": steamer,
            },
        },
    }


def archive_freeze(payload: dict, date_str: str, archive_dir: Path = FREEZE_ARCHIVE_DIR) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def load_oldest_freeze(archive_dir: Path = FREEZE_ARCHIVE_DIR) -> dict | None:
    if not archive_dir.exists():
        return None
    files = sorted(p for p in archive_dir.glob("*.json"))
    if not files:
        return None
    return json.loads(files[0].read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- scoring
def _scoreable(frozen: dict, actual_lines: dict[str, dict]) -> list[str]:
    """Players present in BOTH frozen sources AND actuals with enough forward volume."""
    marcel = frozen["sources"]["valucast_hp"]["rate_lines"]
    steamer = frozen["sources"]["steamer_ros"]["rate_lines"]
    out = []
    for mlbam_id, actual in actual_lines.items():
        if mlbam_id not in marcel or mlbam_id not in steamer:
            continue
        role = actual["role"]
        min_volume = MIN_PITCHER_IP if role == "pitcher" else MIN_HITTER_PA
        if actual["volume"] >= min_volume:
            out.append(mlbam_id)
    return out


def _per_stat_mae(frozen_source: dict, actual_lines: dict, ids: list[str]) -> dict[str, float]:
    """{stat: mean |projected - actual|} over scoreable players that carry the stat both sides."""
    errs: dict[str, list[float]] = {}
    for mlbam_id in ids:
        proj = frozen_source.get(mlbam_id)
        actual = actual_lines.get(mlbam_id)
        if not proj or not actual:
            continue
        for key, pv in proj["rates"].items():
            av = actual["rates"].get(key)
            if av is not None:
                errs.setdefault(key, []).append(abs(pv - av))
    return {stat: sum(v) / len(v) for stat, v in errs.items() if v}


def score_sources(frozen: dict, actual_lines: dict, ids: list[str]) -> dict:
    """Per-stat Marcel/Steamer MAE + a scale-robust mean per-stat ratio (Marcel/Steamer)."""
    marcel_mae = _per_stat_mae(frozen["sources"]["valucast_hp"]["rate_lines"], actual_lines, ids)
    steamer_mae = _per_stat_mae(frozen["sources"]["steamer_ros"]["rate_lines"], actual_lines, ids)
    ratios = {
        stat: marcel_mae[stat] / steamer_mae[stat]
        for stat in marcel_mae
        if stat in steamer_mae and steamer_mae[stat] > 0
    }
    mean_ratio = round(sum(ratios.values()) / len(ratios), 4) if ratios else None
    return {
        "marcel_mae": {k: round(v, 5) for k, v in marcel_mae.items()},
        "steamer_mae": {k: round(v, 5) for k, v in steamer_mae.items()},
        "per_stat_ratio": {k: round(v, 4) for k, v in ratios.items()},
        "marcel_mean_ratio_vs_steamer": mean_ratio,
    }


def _actual_lines(actuals_rows: list[dict]) -> dict[str, dict]:
    return _rate_lines(actuals_rows)


# ----------------------------------------------------------------- what-would-change
def _layer_rows(layer: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in (layer or {}).get("players") or []:
        mlbam_id = _mlbam_id(row)
        role = row.get("role") or _role(row)
        if mlbam_id:
            out[f"{mlbam_id}_{role}"] = row
    return out


def build_what_would_change(live_layer: dict | None, shadow_layer: dict | None, top_n: int = WHAT_WOULD_CHANGE_TOP_N) -> list[dict]:
    """Top players by |live value - Marcel-shadow value| — what a manual flip would move."""
    live = _layer_rows(live_layer)
    shadow = _layer_rows(shadow_layer)
    changes = []
    for key in set(live) | set(shadow):
        lv = _finite((live.get(key) or {}).get("value"))
        sv = _finite((shadow.get(key) or {}).get("value"))
        ref = live.get(key) or shadow.get(key) or {}
        changes.append({
            "mlbam_id": _mlbam_id(ref),
            "name": ref.get("name"),
            "role": ref.get("role") or _role(ref),
            "live_value": lv,
            "marcel_value": sv,
            "value_delta": round((sv or 0.0) - (lv or 0.0), 2),
            "only_in": None if (lv is not None and sv is not None) else ("live" if lv is not None else "shadow"),
        })
    changes.sort(key=lambda c: abs(c["value_delta"]), reverse=True)
    return changes[:top_n]


# --------------------------------------------------------------------------- assemble
def build_comparison(
    *,
    frozen: dict | None,
    actual_lines: dict,
    live_layer: dict | None,
    shadow_layer: dict | None,
    generated_at: str,
    now=None,
) -> dict:
    now_date = _parse_date(now) or _parse_date(generated_at) or datetime.now(timezone.utc).date()
    frozen_date = _parse_date((frozen or {}).get("date") or (frozen or {}).get("generated_at"))
    horizon_days = (now_date - frozen_date).days if frozen_date else None
    ids = _scoreable(frozen, actual_lines) if frozen else []
    scores = score_sources(frozen, actual_lines, ids) if frozen and ids else {}
    sample = len(ids)
    model_score = scores.get("marcel_mean_ratio_vs_steamer")

    horizon_ok = horizon_days is not None and horizon_days >= MIN_HORIZON_DAYS
    # decide_gate owns sample/improvement logic; gate the horizon by withholding the sample
    # until the frozen projection genuinely predates the actuals (honest reason set after).
    gate = decide_gate(
        metric=METRIC,
        model_score=model_score,
        baselines={"steamer_ros": 1.0},
        sample_size=sample if horizon_ok else 0,
        cv_method="forward_actuals_vs_oldest_frozen_pure_projection",
        validated_through=_date_part(generated_at),
        min_sample=MIN_SAMPLE,
        min_improvement_pct=MIN_IMPROVEMENT_PCT,
        lower_is_better=True,
        now=_date_part(generated_at) if horizon_ok else None,
    )
    if not horizon_ok:
        gate["reason"] = (
            f"forward horizon {horizon_days}d < required {MIN_HORIZON_DAYS}d"
            if horizon_days is not None
            else "no frozen projection snapshot yet"
        )

    marcel_wins = gate["status"] == "active"
    return {
        "artifact": ARTIFACT_NAME,
        "status": "shadow_only",  # repo-wide provenance label; this layer never feeds live
        "comparison_version": COMPARISON_VERSION,
        "generated_at": generated_at,
        "advisory_only": True,
        "live_source_flip": {
            "automatic": False,
            "manual_env_flag": "VALUCAST_MLB_LIVE_PROJECTION_SOURCE",
            "default": "current",
            "note": "Flipping the live dynasty source to Marcel is manual and default-off; "
                    "this comparison is advisory evidence only and never flips it.",
        },
        "comparison_basis": {
            "metric": METRIC,
            "frozen_as_of": (frozen or {}).get("date"),
            "horizon_days": horizon_days,
            "min_horizon_days": MIN_HORIZON_DAYS,
            "horizon_sufficient": horizon_ok,
            "scoreable_players": sample,
            "min_sample": MIN_SAMPLE,
            "hitter_rate_keys": list(HITTER_RATE_KEYS),
            "pitcher_rate_keys": list(PITCHER_RATE_KEYS),
        },
        "caveats": [
            "Both sources are PURE projections frozen before the scored actuals (no leakage).",
            "Rate-stat MAE only; counting/volume accuracy is out of scope.",
            "A 'win' (gate active) is necessary but NOT sufficient for a flip — review the "
            "what_would_change diff and flip manually via the env flag.",
        ],
        "scores": scores,
        "gate": gate,
        "marcel_beats_steamer": marcel_wins,
        "what_would_change": build_what_would_change(live_layer, shadow_layer),
    }


def archive_comparison(payload: dict, date_str: str, archive_dir: Path = COMPARISON_ARCHIVE_DIR) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {k: v for k, v in payload.items() if k != "what_would_change"}
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def run_projection_source_comparison(
    *,
    marcel_path: Path = MARCEL_PATH,
    steamer_ros_path: Path = STEAMER_ROS_PATH,
    actuals_path: Path = ACTUALS_PATH,
    live_layer_path: Path = LIVE_LAYER_PATH,
    shadow_layer_path: Path = SHADOW_LAYER_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    freeze_archive_dir: Path = FREEZE_ARCHIVE_DIR,
    comparison_archive_dir: Path = COMPARISON_ARCHIVE_DIR,
    generated_at: str | None = None,
    now=None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    date_str = _date_part(generated_at)
    marcel_rows = _load(marcel_path) or []
    steamer_rows = _load(steamer_ros_path) or []
    actuals_rows = _load(actuals_path) or []

    # Freeze today's pure projections, then score the OLDEST freeze against current actuals.
    freeze = build_freeze(marcel_rows, steamer_rows, generated_at)
    archive_freeze(freeze, date_str, freeze_archive_dir)
    oldest = load_oldest_freeze(freeze_archive_dir) or freeze

    comparison = build_comparison(
        frozen=oldest,
        actual_lines=_actual_lines(actuals_rows),
        live_layer=_load(live_layer_path),
        shadow_layer=_load(shadow_layer_path),
        generated_at=generated_at,
        now=now,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(comparison, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    archive_comparison(comparison, date_str, comparison_archive_dir)
    return comparison


def validate_comparison(payload: dict) -> list[str]:
    problems: list[str] = []
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append("artifact name mismatch")
    if payload.get("advisory_only") is not True:
        problems.append("advisory_only must be True")
    if (payload.get("live_source_flip") or {}).get("automatic") is not False:
        problems.append("live_source_flip.automatic must be False (no auto-flip)")
    gate = payload.get("gate")
    if not validate_gate(gate):
        problems.append("gate is not a valid gate object")
        return problems
    basis = payload.get("comparison_basis") or {}
    # A win cannot be claimed before enough forward horizon AND sample exist.
    if payload.get("marcel_beats_steamer") and gate.get("status") == "active":
        if not basis.get("horizon_sufficient"):
            problems.append("claimed a win before the forward horizon is sufficient")
        if (basis.get("scoreable_players") or 0) < MIN_SAMPLE:
            problems.append("claimed a win below the minimum scoreable-player sample")
    return problems
