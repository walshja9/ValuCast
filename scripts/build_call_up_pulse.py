"""Same-day call-up pulse.

The daily board (valucast_prospect_rank_v1) excludes active-MLB-roster ids at
build time, so any board prospect who now appears on a FRESH active roster was
called up AFTER the morning build -- an intraday call-up the board hasn't caught
yet. We surface that as a display-only "Called up" badge; an afternoon workflow
refreshes the roster + this pulse so the highest-visibility prospect event shows
same-day instead of waiting for tomorrow's build.

DISPLAY-ONLY: official MLB rosters in, never feeds score/rank/value/buy.
Fail-soft: missing board or roster -> empty-but-valid artifact.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlb.roster_status import active_roster_lookup  # noqa: E402

BOARD_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
ROSTER_PATH = ROOT / "data" / "models" / "valucast_mlb_roster_status.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_call_up_pulse.json"

ARTIFACT_NAME = "valucast_call_up_pulse"
SIGNAL_VERSION = "0.1.0"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- fail-soft
        return {}


def _identity_key(mlbam_id, role: str) -> str | None:
    if mlbam_id in (None, "", 0) or role not in {"hitter", "pitcher"}:
        return None
    return f"{mlbam_id}_{role}"


def build_call_up_pulse(
    *,
    board_path: Path = BOARD_PATH,
    roster_path: Path = ROSTER_PATH,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    board = (_load(board_path).get("board") or [])
    active = active_roster_lookup(_load(roster_path))

    by_identity: dict[str, dict] = {}
    for row in board:
        mlbam = row.get("mlbam_id")
        role = row.get("role")
        key = _identity_key(mlbam, role)
        if not key:
            continue
        profile = active.get(str(mlbam))
        if not profile:
            continue  # still a prospect -> no call-up
        by_identity[key] = {
            "mlbam_id": str(mlbam),
            "role": role,
            "name": row.get("name"),
            "prospect_rank": row.get("rank"),
            "mlb_team": profile.get("team_abbreviation") or profile.get("team_name"),
            "position": profile.get("position"),
            "status": profile.get("status_description"),
            "usage": "call_up_pulse_context_not_live_rank_or_value",
        }

    call_ups = sorted(
        by_identity.values(),
        key=lambda r: (r.get("prospect_rank") is None, r.get("prospect_rank") or 0),
    )
    blockers: list[str] = []
    if not board:
        blockers.append("No prospect board rows are available.")
    if not active:
        blockers.append("No active MLB roster profiles are available.")

    return {
        "artifact": ARTIFACT_NAME,
        "signal_version": SIGNAL_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "status": "blocked" if blockers else "candidate_ready",
        "source_policy": {
            "kind": "valucast_call_up_pulse",
            "inputs": "valucast_prospect_board_intersect_official_mlb_active_roster",
            "official_mlb_rosters_used": True,
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "input_artifacts": {
            "board_generated_at": _load(board_path).get("generated_at"),
            "roster_generated_at": _load(roster_path).get("generated_at"),
        },
        "summary": {"call_up_count": len(call_ups)},
        "validation": {
            "ready_for_call_up_pulse": not blockers,
            "blockers": blockers,
        },
        "call_ups": call_ups,
        "by_identity": by_identity,
    }


def run_call_up_pulse(
    *,
    board_path: Path = BOARD_PATH,
    roster_path: Path = ROSTER_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_call_up_pulse(board_path=board_path, roster_path=roster_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "status": payload["status"],
        "call_up_count": payload["summary"]["call_up_count"],
    }


def main() -> int:
    result = run_call_up_pulse()
    print(
        "call-up pulse: "
        f"status={result['status']} call_ups={result['call_up_count']} "
        f"-> {result['artifact_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
