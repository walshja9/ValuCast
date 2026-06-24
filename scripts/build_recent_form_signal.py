"""Build the display-only recent-form momentum signal.

Joins ValuCast-owned MiLB season-to-date stats against the trailing-window
(byDateRange) stats and emits per-prospect momentum (Heating Up / Cooling Off /
Steady). This is DISPLAY/CONTEXT-ONLY: source_policy.feeds_*=False and the
module is never imported by the score path (prospects/raw_input_builder.py).
Closing the recency gap a season-aggregate model is blind to -- a hot week is
otherwise diluted into the whole-season line.

Fail-soft: if the trailing-window file is missing (e.g. a local build before the
workflow's recent-stats refresh ran), emit an empty-but-valid artifact so the
freshness validator still passes and the board simply shows no momentum.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.recent_form import compute_momentum  # noqa: E402

SEASON_PATH = ROOT / "data" / "prospects" / "raw" / "milb_season_stats.json"
RECENT_PATH = ROOT / "data" / "prospects" / "raw" / "milb_recent_stats.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_recent_form_signal.json"

ARTIFACT_NAME = "valucast_recent_form_signal"
SIGNAL_VERSION = "0.1.0"

# Rate fields surfaced on the card for the trailing window (display only).
_HITTER_DISPLAY = ("plate_appearances", "ops", "iso", "k_pct", "bb_pct")
_PITCHER_DISPLAY = ("innings_pitched", "k_bb_pct", "k_per_9", "bb_per_9", "era")


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- fail-soft, missing/corrupt -> empty
        return {}


def _identity_key(mlbam_id, role: str) -> str | None:
    if mlbam_id in (None, "", 0) or role not in {"hitter", "pitcher"}:
        return None
    return f"{mlbam_id}_{role}"


def _index(payload: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for group in ("hitters", "pitchers"):
        for row in payload.get(group) or []:
            key = _identity_key(row.get("mlbam_id"), row.get("role"))
            if key:
                out[key] = row
    return out


def _display_line(row: dict, role: str) -> dict:
    fields = _PITCHER_DISPLAY if role == "pitcher" else _HITTER_DISPLAY
    return {field: row.get(field) for field in fields}


def build_recent_form_signal(
    *,
    season_path: Path = SEASON_PATH,
    recent_path: Path = RECENT_PATH,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    season = _load(season_path)
    recent = _load(recent_path)
    season_by_key = _index(season)
    recent_by_key = _index(recent)

    by_identity: dict[str, dict] = {}
    for key, recent_row in recent_by_key.items():
        season_row = season_by_key.get(key)
        if not season_row:
            continue
        role = recent_row.get("role")
        result = compute_momentum(season_row, recent_row, role)
        if result.get("momentum_label") is None:
            continue  # below min-sample guard or no comparable stats
        sample = (
            recent_row.get("innings_pitched")
            if role == "pitcher"
            else recent_row.get("plate_appearances")
        )
        by_identity[key] = {
            "mlbam_id": str(recent_row.get("mlbam_id")),
            "role": role,
            "name": recent_row.get("name"),
            "team": recent_row.get("team"),
            "level": recent_row.get("level"),
            "momentum_score": result["momentum_score"],
            "momentum_label": result["momentum_label"],
            "window_days": recent.get("window_days"),
            "recent_sample": sample,
            "recent_line": _display_line(recent_row, role),
            "season_line": _display_line(season_row, role),
            "usage": "recent_form_context_not_live_rank_or_value",
        }

    ranked = sorted(
        by_identity.values(),
        key=lambda row: row["momentum_score"],
        reverse=True,
    )
    heating = [row for row in ranked if row["momentum_label"] == "Heating Up"][:25]
    cooling = [
        row for row in reversed(ranked) if row["momentum_label"] == "Cooling Off"
    ][:25]

    blockers: list[str] = []
    if not recent_by_key:
        blockers.append("No trailing-window MiLB stats are available yet.")
    if not by_identity:
        blockers.append("No prospect cleared the recent-form sample guard.")

    return {
        "artifact": ARTIFACT_NAME,
        "signal_version": SIGNAL_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "status": "blocked" if blockers else "candidate_ready",
        "source_policy": {
            "kind": "valucast_recent_form_signal",
            "inputs": "valucast_owned_milb_season_and_trailing_window_stats",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "input_artifacts": {
            "season_fetched_date": season.get("fetched_date"),
            "recent_window_days": recent.get("window_days"),
            "recent_start_date": recent.get("start_date"),
            "recent_end_date": recent.get("end_date"),
        },
        "summary": {
            "evaluated_count": len(by_identity),
            "heating_up_count": sum(
                1 for row in by_identity.values() if row["momentum_label"] == "Heating Up"
            ),
            "cooling_off_count": sum(
                1 for row in by_identity.values() if row["momentum_label"] == "Cooling Off"
            ),
            "window_days": recent.get("window_days"),
        },
        "validation": {
            "ready_for_recent_form": not blockers,
            "blockers": blockers,
        },
        "by_identity": by_identity,
        "heating_up": heating,
        "cooling_off": cooling,
    }


def run_recent_form_signal(
    *,
    season_path: Path = SEASON_PATH,
    recent_path: Path = RECENT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_recent_form_signal(season_path=season_path, recent_path=recent_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "status": payload["status"],
        "evaluated_count": payload["summary"]["evaluated_count"],
        "heating_up_count": payload["summary"]["heating_up_count"],
        "cooling_off_count": payload["summary"]["cooling_off_count"],
    }


def main() -> int:
    result = run_recent_form_signal()
    print(
        "recent form signal: "
        f"status={result['status']} "
        f"evaluated={result['evaluated_count']} "
        f"heating={result['heating_up_count']} "
        f"cooling={result['cooling_off_count']} "
        f"-> {result['artifact_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
