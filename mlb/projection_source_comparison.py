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
import subprocess
from datetime import datetime, timedelta, timezone
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
ACTUALS_SNAPSHOT_DIR = ROOT / "data" / "prediction_archive" / "valucast_actuals_snapshot"
HP_SNAPSHOT_DIR = ROOT / "data" / "prediction_archive" / "valucast_hp_snapshot"

ARTIFACT_NAME = "valucast_mlb_projection_source_comparison"
COMPARISON_VERSION = "0.1.0"
METRIC = "rate_stat_mae_ratio_vs_forward_actuals"

HITTER_RATE_KEYS = ("AVG", "OBP", "SLG", "OPS")
PITCHER_RATE_KEYS = ("ERA", "WHIP")  # the rate stats present across all three sources
HITTER_RATE_COMPONENT_KEYS = ("PA", "AB", "H", "1B", "2B", "3B", "HR", "BB", "HBP", "SF")
PITCHER_RATE_COMPONENT_KEYS = ("IP", "ER", "BB", "H_ALLOWED")
HITTER_COUNTING_KEYS = ("HR", "RBI", "R", "SB")
PITCHER_COUNTING_KEYS = ("ER", "BB", "H_ALLOWED", "K", "W", "SV", "HLD")
PITCHER_POOLS = {"pitcher", "starter", "reliever"}
COUNTING_WINDOW_START = "2026-06-18"
MLB_2026_REGULAR_SEASON_END = "2026-09-27"

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


def _counting_keys(role: str) -> tuple[str, ...]:
    return PITCHER_COUNTING_KEYS if role == "pitcher" else HITTER_COUNTING_KEYS


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


def _actual_rate_component_lines(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        mlbam_id = _mlbam_id(row)
        if not mlbam_id:
            continue
        role = _role(row)
        stats = row.get("stats") or {}
        keys = PITCHER_RATE_COMPONENT_KEYS if role == "pitcher" else HITTER_RATE_COMPONENT_KEYS
        components = {key: _finite(stats.get(key)) or 0.0 for key in keys}
        volume = components["IP" if role == "pitcher" else "PA"]
        existing = out.get(mlbam_id)
        if existing is None or volume > existing["volume"]:
            out[mlbam_id] = {"role": role, "components": components, "volume": volume}
    return out


def _actual_rate_deltas(as_of_rows: list[dict], current_rows: list[dict]) -> dict[str, dict]:
    starts = _actual_rate_component_lines(as_of_rows)
    ends = _actual_rate_component_lines(current_rows)
    out: dict[str, dict] = {}
    for mlbam_id, end in ends.items():
        start = starts.get(mlbam_id)
        if not start or start["role"] != end["role"]:
            continue
        components = {
            key: max(0.0, value - start["components"].get(key, 0.0))
            for key, value in end["components"].items()
        }
        role = end["role"]
        if role == "pitcher":
            volume = components["IP"]
            if volume <= 0:
                continue
            rates = {
                "ERA": round(9 * components["ER"] / volume, 4),
                "WHIP": round((components["BB"] + components["H_ALLOWED"]) / volume, 4),
            }
        else:
            ab = components["AB"]
            obp_denom = ab + components["BB"] + components["HBP"] + components["SF"]
            if ab <= 0 or obp_denom <= 0:
                continue
            total_bases = (
                components["1B"] + 2 * components["2B"]
                + 3 * components["3B"] + 4 * components["HR"]
            )
            avg = components["H"] / ab
            obp = (components["H"] + components["BB"] + components["HBP"]) / obp_denom
            slg = total_bases / ab
            rates = {
                "AVG": round(avg, 4), "OBP": round(obp, 4),
                "SLG": round(slg, 4), "OPS": round(obp + slg, 4),
            }
            volume = components["PA"]
        out[mlbam_id] = {"role": role, "rates": rates, "volume": round(volume, 3)}
    return out


# -------------------------------------------------------------- counting scores
def prorate_counting_projection(value: float, elapsed_days: int, remaining_days: int) -> float:
    """Prorate a rest-of-season counting projection into the elapsed test window."""
    if remaining_days <= 0:
        return round(float(value), 4)
    elapsed = min(max(elapsed_days, 0), remaining_days)
    return round(float(value) * elapsed / remaining_days, 4)


def _counting_lines(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        mlbam_id = _mlbam_id(row)
        if not mlbam_id:
            continue
        role = _role(row)
        stats = row.get("stats") or {}
        counts = {k: (_finite(stats.get(k)) or 0.0) for k in _counting_keys(role)}
        volume = _volume(stats, role)
        existing = out.get(mlbam_id)
        if existing is None or volume > existing["volume"]:
            out[mlbam_id] = {"role": role, "counts": counts, "volume": round(volume, 3)}
    return out


def _actual_counting_deltas(as_of_rows: list[dict], current_rows: list[dict]) -> dict[str, dict]:
    as_of = _counting_lines(as_of_rows)
    current = _counting_lines(current_rows)
    out: dict[str, dict] = {}
    for mlbam_id, end in current.items():
        start = as_of.get(mlbam_id)
        if not start:
            continue
        role = end["role"]
        keys = _counting_keys(role)
        counts = {
            key: round(max(0.0, end["counts"].get(key, 0.0) - start["counts"].get(key, 0.0)), 4)
            for key in keys
        }
        volume = round(max(0.0, end["volume"] - start["volume"]), 3)
        out[mlbam_id] = {"role": role, "counts": counts, "volume": volume}
    return out


def _counting_scoreable(
    valucast_hp: dict,
    steamer_ros: dict,
    actual_deltas: dict[str, dict],
) -> list[str]:
    out = []
    for mlbam_id, actual in actual_deltas.items():
        if mlbam_id not in valucast_hp or mlbam_id not in steamer_ros:
            continue
        role = actual["role"]
        min_volume = MIN_PITCHER_IP if role == "pitcher" else MIN_HITTER_PA
        if actual["volume"] >= min_volume:
            out.append(mlbam_id)
    return out


def _per_stat_counting_mae(
    source: dict,
    actual_deltas: dict,
    ids: list[str],
    elapsed_days: int,
    remaining_days: int,
) -> dict[str, float]:
    errs: dict[str, list[float]] = {}
    for mlbam_id in ids:
        proj = source.get(mlbam_id)
        actual = actual_deltas.get(mlbam_id)
        if not proj or not actual:
            continue
        for key, av in actual["counts"].items():
            pv = prorate_counting_projection(proj["counts"].get(key, 0.0), elapsed_days, remaining_days)
            errs.setdefault(key, []).append(abs(pv - av))
    return {stat: sum(v) / len(v) for stat, v in errs.items() if v}


def _score_counting_sources(
    valucast_hp: dict,
    steamer_ros: dict,
    actual_deltas: dict,
    ids: list[str],
    elapsed_days: int,
    remaining_days: int,
) -> dict:
    marcel_mae = _per_stat_counting_mae(valucast_hp, actual_deltas, ids, elapsed_days, remaining_days)
    steamer_mae = _per_stat_counting_mae(steamer_ros, actual_deltas, ids, elapsed_days, remaining_days)
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


def build_counting_stat_comparison(
    *,
    valucast_hp_rows: list[dict],
    steamer_ros_rows: list[dict],
    as_of_actual_rows: list[dict],
    current_actual_rows: list[dict],
    as_of: str,
    through: str,
    season_end: str = MLB_2026_REGULAR_SEASON_END,
    steamer_git_commit: str | None = None,
) -> dict:
    start = _parse_date(as_of)
    end = _parse_date(through)
    season_end_date = _parse_date(season_end)
    elapsed_days = (end - start).days if start and end else 0
    remaining_days = (season_end_date - start).days if start and season_end_date else 0
    actual_deltas = _actual_counting_deltas(as_of_actual_rows, current_actual_rows)
    valucast_hp = _counting_lines(valucast_hp_rows)
    steamer_ros = _counting_lines(steamer_ros_rows)
    ids = _counting_scoreable(valucast_hp, steamer_ros, actual_deltas)
    scores = _score_counting_sources(
        valucast_hp, steamer_ros, actual_deltas, ids, elapsed_days, remaining_days,
    ) if ids else {}
    return {
        "status": "scored" if ids else "insufficient_sample",
        "window": {
            "as_of": as_of,
            "through": through,
            "season_end": season_end,
            "elapsed_days": elapsed_days,
            "remaining_days_at_freeze": remaining_days,
            "proration_factor": round(elapsed_days / remaining_days, 4) if remaining_days > 0 else 1.0,
            "proration_method": (
                "calendar_days_elapsed_over_regular_season_days_remaining; "
                "projection rows are treated as rest-of-season counts"
            ),
        },
        "counting_keys": {
            "hitters": list(HITTER_COUNTING_KEYS),
            "pitchers": list(PITCHER_COUNTING_KEYS),
        },
        "scoreable_players": len(ids),
        "actual_counting_deltas": {mlbam_id: actual_deltas[mlbam_id] for mlbam_id in ids},
        "scores": scores,
        "steamer_ros_git_commit": steamer_git_commit,
    }


def load_steamer_ros_from_git(as_of: str, path: Path = STEAMER_ROS_PATH) -> tuple[list[dict], str]:
    rel = path.relative_to(ROOT).as_posix()
    start = _parse_date(as_of)
    before = (start + timedelta(days=1)).isoformat() if start else as_of
    sha = subprocess.run(
        ["git", "log", f"--before={before}", "-1", "--format=%H", "--", rel],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not sha:
        raise RuntimeError(f"no git commit found for {rel} before {before}")
    text = subprocess.run(
        ["git", "show", f"{sha}:{rel}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(text), sha


def build_counting_stat_comparison_from_paths(
    *,
    current_actuals_path: Path = ACTUALS_PATH,
    as_of: str = COUNTING_WINDOW_START,
    through: str,
    actuals_snapshot_dir: Path = ACTUALS_SNAPSHOT_DIR,
    hp_snapshot_dir: Path = HP_SNAPSHOT_DIR,
) -> dict:
    as_of_actuals_path = actuals_snapshot_dir / f"{as_of}.json"
    hp_snapshot_path = hp_snapshot_dir / f"{as_of}.json"
    missing = [
        str(path)
        for path in (as_of_actuals_path, hp_snapshot_path, current_actuals_path)
        if not path.exists()
    ]
    if missing:
        return {
            "status": "missing_inputs",
            "window": {"as_of": as_of, "through": through},
            "missing_inputs": missing,
        }
    steamer_rows, sha = load_steamer_ros_from_git(as_of)
    return build_counting_stat_comparison(
        valucast_hp_rows=_load(hp_snapshot_path) or [],
        steamer_ros_rows=steamer_rows,
        as_of_actual_rows=_load(as_of_actuals_path) or [],
        current_actual_rows=_load(current_actuals_path) or [],
        as_of=as_of,
        through=through,
        steamer_git_commit=sha,
    )


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
    rate_actuals_method: str = "unverified",
    live_layer: dict | None,
    shadow_layer: dict | None,
    generated_at: str,
    counting_stat_comparison: dict | None = None,
    now=None,
) -> dict:
    now_date = _parse_date(now) or _parse_date(generated_at) or datetime.now(timezone.utc).date()
    frozen_date = _parse_date((frozen or {}).get("date") or (frozen or {}).get("generated_at"))
    horizon_days = (now_date - frozen_date).days if frozen_date else None
    ids = _scoreable(frozen, actual_lines) if frozen else []
    scores = score_sources(frozen, actual_lines, ids) if frozen and ids else {}
    sample = len(ids)
    horizon_ok = horizon_days is not None and horizon_days >= MIN_HORIZON_DAYS

    def rate_gate(role_scores: dict, role_sample: int) -> dict:
        gate = decide_gate(
            metric=METRIC,
            model_score=role_scores.get("marcel_mean_ratio_vs_steamer"),
            baselines={"steamer_ros": 1.0},
            sample_size=role_sample if horizon_ok else 0,
            cv_method="post_freeze_component_deltas_vs_oldest_frozen_pure_projection",
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
        return gate

    ids_by_role = {
        "hitters": [mlbam_id for mlbam_id in ids if actual_lines[mlbam_id]["role"] == "hitter"],
        "pitchers": [mlbam_id for mlbam_id in ids if actual_lines[mlbam_id]["role"] == "pitcher"],
    }
    role_scores = {
        role: score_sources(frozen, actual_lines, role_ids) if frozen and role_ids else {}
        for role, role_ids in ids_by_role.items()
    }
    gate = rate_gate(scores, sample)
    role_gates = {
        role: rate_gate(role_scores[role], len(role_ids))
        for role, role_ids in ids_by_role.items()
    }
    method_ok = rate_actuals_method == "post_freeze_component_deltas"
    both_roles_active = all(role_gate["status"] == "active" for role_gate in role_gates.values())
    publication_clear = method_ok and gate["status"] == "active" and both_roles_active
    publication_veto = {
        "status": "clear" if publication_clear else "held",
        "affects_live_outputs": False,
        "reason": (
            "all rate gates active; any live-source change remains manual"
            if publication_clear
            else "rate actuals are not verified post-freeze component deltas"
            if not method_ok
            else "hitter and pitcher gates must both be active"
        ),
    }
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
            "rate_actuals_method": rate_actuals_method,
            "frozen_as_of": (frozen or {}).get("date"),
            "horizon_days": horizon_days,
            "min_horizon_days": MIN_HORIZON_DAYS,
            "horizon_sufficient": horizon_ok,
            "scoreable_players": sample,
            "scoreable_players_by_role": {
                role: len(role_ids) for role, role_ids in ids_by_role.items()
            },
            "min_sample": MIN_SAMPLE,
            "hitter_rate_keys": list(HITTER_RATE_KEYS),
            "pitcher_rate_keys": list(PITCHER_RATE_KEYS),
        },
        "caveats": [
            "Both sources are PURE projections frozen before the scored actuals (no leakage).",
            "Rate-stat and counting-stat comparisons are reported separately; the live-source "
            "gate still uses rate-stat MAE only.",
            "A 'win' (gate active) is necessary but NOT sufficient for a flip — review the "
            "what_would_change diff and flip manually via the env flag.",
        ],
        "scores": scores,
        "role_scores": role_scores,
        "role_gates": role_gates,
        "counting_stat_comparison": counting_stat_comparison or {"status": "not_requested"},
        "gate": gate,
        "publication_veto": publication_veto,
        "marcel_beats_steamer": publication_clear,
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
    actuals_snapshot_dir: Path = ACTUALS_SNAPSHOT_DIR,
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
    oldest_date = oldest.get("date")
    as_of_actuals_path = actuals_snapshot_dir / f"{oldest_date}.json" if oldest_date else None
    if as_of_actuals_path and as_of_actuals_path.exists():
        actual_lines = _actual_rate_deltas(_load(as_of_actuals_path) or [], actuals_rows)
        rate_actuals_method = "post_freeze_component_deltas"
    else:
        actual_lines = {}
        rate_actuals_method = "unavailable_missing_freeze_actuals_snapshot"

    comparison = build_comparison(
        frozen=oldest,
        actual_lines=actual_lines,
        rate_actuals_method=rate_actuals_method,
        live_layer=_load(live_layer_path),
        shadow_layer=_load(shadow_layer_path),
        generated_at=generated_at,
        counting_stat_comparison=build_counting_stat_comparison_from_paths(
            current_actuals_path=actuals_path,
            through=date_str,
        ),
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
    publication_veto = payload.get("publication_veto") or {}
    role_gates = payload.get("role_gates") or {}
    if publication_veto.get("status") == "clear" and not all(
        (role_gates.get(role) or {}).get("status") == "active"
        for role in ("hitters", "pitchers")
    ):
        problems.append("publication veto cleared without both role gates active")
    if publication_veto and publication_veto.get("affects_live_outputs") is not False:
        problems.append("publication veto must not affect live outputs")
    # A win cannot be claimed before enough forward horizon AND sample exist.
    if payload.get("marcel_beats_steamer") and gate.get("status") == "active":
        if basis.get("rate_actuals_method") != "post_freeze_component_deltas":
            problems.append("claimed a win without post-freeze component-delta actuals")
        if not basis.get("horizon_sufficient"):
            problems.append("claimed a win before the forward horizon is sufficient")
        if (basis.get("scoreable_players") or 0) < MIN_SAMPLE:
            problems.append("claimed a win below the minimum scoreable-player sample")
    return problems
