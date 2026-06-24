"""Ahead-of-the-Curve track record (earliness scorecard).

Turns the "ahead of consensus" claim into a MEASURED number: for every prospect
ValuCast flagged as an early call, did the public consensus later move TOWARD
ValuCast's higher rating? We mine the dated board archive -- the earliest date
each player cleared the divergence guard (consensus_then) vs the latest snapshot
(consensus_now) -- and aggregate a catch-up hit rate.

HONESTY GATE: the external boards refresh slowly (monthly-ish), so a credible
catch-up number needs weeks of horizon. `publishable` stays False until the
archive is deep enough; the UI shows an honest "tracking N calls since DATE"
state until then rather than a noisy near-zero rate. DISPLAY-ONLY: never feeds
score/rank/value.
"""
from __future__ import annotations

import glob
import json
import os
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.ahead_of_consensus import (  # noqa: E402
    ARCHIVE_DIR,
    _divergence_row,
    _is_guarded,
)

ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_ahead_of_consensus_scorecard.json"
ARTIFACT_NAME = "valucast_ahead_of_consensus_scorecard"
SIGNAL_VERSION = "0.1.0"

# Gate the public catch-up number until the record is credible. Boards move
# slowly, so a few days of history is pure noise.
MIN_PUBLISH_HORIZON_DAYS = 30
MIN_PUBLISH_RESOLVED = 25


def _guarded_rows(path: Path) -> dict[str, dict]:
    try:
        board = (json.loads(path.read_text(encoding="utf-8")) or {}).get("board") or []
    except (OSError, ValueError):
        return {}
    out: dict[str, dict] = {}
    for raw in board:
        if not isinstance(raw, dict):
            continue
        cand = _divergence_row(raw)
        if cand and _is_guarded(cand) and cand["identity_key"]:
            out[cand["identity_key"]] = cand
    return out


def _days_between(start: str, end: str) -> int:
    try:
        return max(0, (date.fromisoformat(end) - date.fromisoformat(start)).days)
    except ValueError:
        return 0


def build_scorecard(*, archive_dir: Path = ARCHIVE_DIR, generated_at: str | None = None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    files = sorted(glob.glob(str(archive_dir / "*.json")))
    today = generated_at[:10]

    # earliest guarded occurrence per identity (the provable "we called it" date)
    earliest: dict[str, dict] = {}
    for path in files:  # ascending -> first hit is earliest
        snap_date = os.path.basename(path)[:10]
        for key, row in _guarded_rows(Path(path)).items():
            if key not in earliest:
                earliest[key] = {"date": snap_date, "row": row}

    latest = _guarded_rows(Path(files[-1])) if files else {}
    latest_date = os.path.basename(files[-1])[:10] if files else today

    calls = []
    for key, first in earliest.items():
        now = latest.get(key)
        if not now:
            continue  # graduated / dropped off the guarded board -> not catch-up-resolvable
        catch_up = first["row"]["consensus_rank"] - now["consensus_rank"]  # + = field came toward us
        calls.append(
            {
                "identity_key": key,
                "name": now.get("name") or first["row"].get("name"),
                "ahead_since": first["date"],
                "days_tracked": _days_between(first["date"], latest_date),
                "consensus_then": first["row"]["consensus_rank"],
                "consensus_now": now["consensus_rank"],
                "valucast_then": first["row"]["valucast_rank"],
                "valucast_now": now["valucast_rank"],
                "consensus_catch_up": catch_up,
                "moved_toward_valucast": catch_up > 0,
            }
        )

    resolved = len(calls)
    moved = sum(1 for c in calls if c["moved_toward_valucast"])
    catch_ups = [c["consensus_catch_up"] for c in calls]
    first_call_date = min((e["date"] for e in earliest.values()), default=today)
    horizon_days = _days_between(first_call_date, latest_date)
    publishable = horizon_days >= MIN_PUBLISH_HORIZON_DAYS and resolved >= MIN_PUBLISH_RESOLVED

    calls.sort(key=lambda c: c["consensus_catch_up"], reverse=True)

    return {
        "artifact": ARTIFACT_NAME,
        "signal_version": SIGNAL_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "status": "candidate_ready" if files else "blocked",
        "source_policy": {
            "kind": "valucast_ahead_of_consensus_scorecard",
            "inputs": "valucast_prospect_rank_v1_dated_archive",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "gate": {
            "publishable": publishable,
            "min_publish_horizon_days": MIN_PUBLISH_HORIZON_DAYS,
            "min_publish_resolved": MIN_PUBLISH_RESOLVED,
            "reason": (
                "ready"
                if publishable
                else f"accruing: {horizon_days}d horizon / {resolved} resolved "
                f"(need {MIN_PUBLISH_HORIZON_DAYS}d and {MIN_PUBLISH_RESOLVED})"
            ),
        },
        "summary": {
            "ever_flagged": len(earliest),
            "resolved_count": resolved,
            "currently_active": len(latest),
            "moved_toward_count": moved,
            "catch_up_hit_rate": round(moved / resolved, 3) if resolved else None,
            "median_catch_up_spots": round(statistics.median(catch_ups), 1) if catch_ups else None,
            "mean_catch_up_spots": round(statistics.mean(catch_ups), 1) if catch_ups else None,
            "first_call_date": first_call_date,
            "horizon_days": horizon_days,
        },
        "calls": calls,
    }


def run_scorecard(*, archive_dir: Path = ARCHIVE_DIR, artifact_path: Path = ARTIFACT_PATH) -> dict:
    payload = build_scorecard(archive_dir=archive_dir)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "publishable": payload["gate"]["publishable"],
        "resolved": payload["summary"]["resolved_count"],
        "hit_rate": payload["summary"]["catch_up_hit_rate"],
        "horizon_days": payload["summary"]["horizon_days"],
    }


def main() -> int:
    r = run_scorecard()
    print(
        "ahead-of-consensus scorecard: "
        f"publishable={r['publishable']} resolved={r['resolved']} "
        f"hit_rate={r['hit_rate']} horizon={r['horizon_days']}d -> {r['artifact_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
