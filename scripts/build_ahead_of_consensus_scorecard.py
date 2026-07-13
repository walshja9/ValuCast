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
# 0.2.1 = the 2026-07-12 compliance fix (headline pinned to the registered
# matured cohort). Scoring rules are otherwise the frozen 2026-07-02 set.
SIGNAL_VERSION = "0.2.1"

# Gate the public catch-up number until the record is credible. Boards move
# slowly, so a few days of history is pure noise.
MIN_PUBLISH_HORIZON_DAYS = 30
MIN_PUBLISH_RESOLVED = 25

# --- v2 (0.2.0, frozen 2026-07-02, pre-registered before the publish gate) ---
# Noise floor: a move only counts as toward/away when it clears BOTH board jitter
# (spots) and a fraction of the call's own initial gap. Empirically the raw >0
# metric showed ZERO edge vs matched controls (29.8% vs 29.2%) while the floored
# metric showed 1.44x -- the floor is what separates signal from jitter.
NOISE_FLOOR_SPOTS = 10
NOISE_FLOOR_GAP_FRAC = 0.15
# Maturity: a call must live through at least one deep-board refresh cycle before
# it belongs in the headline cohort.
MATURITY_DAYS = 14
# Matched controls: same snapshot, same role, never-flagged players with a
# computable consensus inside this band of the call's consensus rank.
CONTROL_BAND = (0.80, 1.25)
CONTROLS_PER_CALL = 5
# Pre-registered aspirational targets (display-only accountability; the model
# NEVER optimizes toward this scorecard -- it stays blind to consensus).
TARGET_DECIDED_RATE = 0.50
TARGET_CONTROL_LIFT = 1.5


def _all_divergence_rows(path: Path) -> dict[str, dict] | None:
    """Every board row with a computable consensus, flagged guarded or not.
    Non-guarded rows are needed twice: to attribute WHY a call's divergence
    closed (field caught up vs we backed off) and as the matched-control pool.
    Returns None (not {}) for an UNREADABLE file so callers can drop the date
    instead of treating it as an empty board."""
    try:
        board = (json.loads(path.read_text(encoding="utf-8")) or {}).get("board") or []
    except (OSError, ValueError):
        return None
    out: dict[str, dict] = {}
    for raw in board:
        if not isinstance(raw, dict):
            continue
        cand = _divergence_row(raw)
        if cand and cand["identity_key"]:
            cand["guarded"] = _is_guarded(cand)
            out[cand["identity_key"]] = cand
    return out


def _classify_move(catch_up: int, initial_gap: int) -> str:
    floor = max(NOISE_FLOOR_SPOTS, NOISE_FLOOR_GAP_FRAC * initial_gap)
    if catch_up >= floor:
        return "toward"
    if catch_up <= -floor:
        return "away"
    return "flat"


def _bucket_rates(calls: list[dict]) -> dict | None:
    if not calls:
        return None
    toward = sum(1 for c in calls if c["bucket"] == "toward")
    away = sum(1 for c in calls if c["bucket"] == "away")
    catch_ups = [c["consensus_catch_up"] for c in calls]
    return {
        "n": len(calls),
        "toward": toward,
        "away": away,
        "flat": len(calls) - toward - away,
        "toward_rate": round(toward / len(calls), 3),
        "mean_catch_up_spots": round(statistics.mean(catch_ups), 1),
        "median_catch_up_spots": round(statistics.median(catch_ups), 1),
    }


def _exit_context(root: Path) -> tuple[set[str], set[str]]:
    """(active roster mlbam ids, service-graduated mlbam ids) -- fail-soft."""
    active: set[str] = set()
    graduated: set[str] = set()
    try:
        roster = json.loads((root / "data" / "models" / "valucast_mlb_roster_status.json").read_text(encoding="utf-8"))
        active = {
            str(p.get("mlbam_id"))
            for p in roster.get("profiles") or []
            if p.get("active_mlb_roster") is True
        }
    except (OSError, ValueError):
        pass
    try:
        inputs = json.loads((root / "data" / "prospects" / "prospect_model_inputs.json").read_text(encoding="utf-8"))
        graduated = {
            str(r.get("mlbam_id"))
            for r in inputs.get("mlb_service") or []
            if r.get("graduated") is True
        }
    except (OSError, ValueError):
        pass
    return active, graduated


def _days_between(start: str, end: str) -> int:
    try:
        return max(0, (date.fromisoformat(end) - date.fromisoformat(start)).days)
    except ValueError:
        return 0


def build_scorecard(*, archive_dir: Path = ARCHIVE_DIR, generated_at: str | None = None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    files = sorted(glob.glob(str(archive_dir / "*.json")))
    today = generated_at[:10]
    root = Path(__file__).resolve().parents[1]

    snaps: dict[str, dict[str, dict]] = {}
    for path in files:
        rows = _all_divergence_rows(Path(path))
        if rows is None:
            # Unreadable file: skip the DATE entirely (matching the sibling
            # _ahead_streak_dates), or one corrupt snapshot resets every
            # ledger streak and desyncs the ledger from the receipts card.
            continue
        snaps[os.path.basename(path)[:10]] = rows
    dates = sorted(snaps)
    latest_date = dates[-1] if dates else today
    latest = snaps.get(latest_date, {})

    # earliest guarded occurrence per identity (the provable "we called it" date)
    earliest: dict[str, dict] = {}
    for snap_date in dates:
        for key, row in snaps[snap_date].items():
            if row["guarded"] and key not in earliest:
                # A call may only OPEN while the player is in the minors. Archived
                # rows carry the active_mlb_roster stamp from 7/4 on (rookie-rule
                # retention keeps call-ups ranked, and boards delisting them
                # inflates the consensus median into a fake "gap"). Pre-stamp
                # history is untouched, and only ENROLLMENT checks this -- a call
                # opened in the minors survives its player's later debut.
                if row.get("in_mlb"):
                    continue
                earliest[key] = {"date": snap_date, "row": row}

    # Continuous-streak anchor (DISPLAY-ONLY; scoring stays pinned to the
    # earliest guarded date above): the unbroken run of guarded snapshots
    # ending at the latest archive date. A ledger row that says "since 6/13
    # · 19d" for a call that lapsed below the guard and re-qualified 6/30 is
    # falsifiable from our own archive -- the row must show the streak (7/2).
    streak_start: dict[str, str] = {}
    for snap_date in dates:
        rows = snaps[snap_date]
        for key, row in rows.items():
            if row["guarded"]:
                streak_start.setdefault(key, snap_date)
        for key in list(streak_start):
            current = rows.get(key)
            if current is None or not current["guarded"]:
                streak_start.pop(key)

    active_ids, graduated_ids = _exit_context(root)
    ever_flagged_keys = set(earliest)

    # --- exit-accounted funnel: every flagged call ends in exactly one bucket ---
    calls: list[dict] = []
    funnel = {
        "open_toward": 0, "open_away": 0, "open_flat": 0,
        "closed_caught_up": 0, "retired_we_backed_off": 0,
        "resolved_called_up_or_graduated": 0, "left_universe": 0,
    }
    for key, first in earliest.items():
        f = first["row"]
        initial_gap = f["divergence"]
        now = latest.get(key)
        entry = {
            "identity_key": key,
            "name": (now or f).get("name") or f.get("name"),
            "ahead_since": first["date"],
            "days_tracked": _days_between(first["date"], latest_date),
            "streak_since": streak_start.get(key),
            "streak_days": (
                _days_between(streak_start[key], latest_date)
                if key in streak_start else None
            ),
            "consensus_then": f["consensus_rank"],
            "valucast_then": f["valucast_rank"],
            "initial_gap": initial_gap,
            # DISPLAY-ONLY: current active-roster status, for the "in the
            # majors" provenance chip (7/3: the rookie-retention board change
            # entered 8 already-debuted players into tracking — disclosed,
            # never silent). Feeds no status/funnel/rate math.
            "in_mlb": str(f.get("mlbam_id") or key.split("_")[0]) in active_ids,
        }
        if now is None:
            mlbam = f.get("mlbam_id") or key.split("_")[0]
            status = (
                "resolved_called_up_or_graduated"
                if str(mlbam) in graduated_ids or str(mlbam) in active_ids
                else "left_universe"
            )
            entry.update({"status": status, "consensus_now": None,
                          "valucast_now": None, "consensus_catch_up": None,
                          "bucket": None})
            funnel[status] += 1
            calls.append(entry)
            continue
        catch_up = (
            f["consensus_rank"] - now["consensus_rank"]
            if now.get("consensus_rank") is not None
            else None
        )
        entry.update({
            "consensus_now": now.get("consensus_rank"),
            "valucast_now": now.get("valucast_rank"),
            "consensus_catch_up": catch_up,
        })
        if now["guarded"]:
            bucket = _classify_move(catch_up, initial_gap) if catch_up is not None else "flat"
            entry.update({"status": "open_" + bucket, "bucket": bucket})
            funnel["open_" + bucket] += 1
        else:
            # Divergence closed while still on the board: attribute the close.
            field_came = max(0, catch_up or 0)
            vc_backed = max(0, (now.get("valucast_rank") or 0) - (f.get("valucast_rank") or 0))
            if catch_up is None and vc_backed <= 0:
                # Board coverage vanished (consensus uncomputable) and our own
                # rank never dropped: NEITHER side's retreat is measurable, so
                # exit-account it. Labeling it "we backed off" would render a
                # row whose own numbers contradict its chip (7/2 audit).
                entry.update({"status": "left_universe", "bucket": None})
                funnel["left_universe"] += 1
            elif field_came > vc_backed:
                entry.update({"status": "closed_caught_up", "bucket": "toward"})
                funnel["closed_caught_up"] += 1
            else:
                # ties count against us -- conservative by construction
                entry.update({"status": "retired_we_backed_off", "bucket": None})
                funnel["retired_we_backed_off"] += 1
        calls.append(entry)

    open_calls = [c for c in calls if str(c.get("status", "")).startswith("open_")]
    matured_calls = [c for c in open_calls if c["days_tracked"] >= MATURITY_DAYS]

    # --- matched controls: same day, same role, never flagged, similar consensus ---
    control_entries: list[dict] = []
    used_controls: set[str] = set()
    for c in open_calls:
        day = snaps.get(c["ahead_since"]) or {}
        first_row = earliest[c["identity_key"]]["row"]
        lo = c["consensus_then"] * CONTROL_BAND[0]
        hi = c["consensus_then"] * CONTROL_BAND[1]
        pool = [
            r for k, r in day.items()
            if k not in ever_flagged_keys and k not in used_controls
            and r.get("role") == first_row.get("role")
            and r.get("consensus_rank") is not None
            and lo <= r["consensus_rank"] <= hi
            and k in latest and latest[k].get("consensus_rank") is not None
            # Symmetry with enrollment: an active-MLB retained call-up's consensus
            # is an eligibility artifact (boards delist call-ups), and because the
            # artifact drags his "catch-up" negative, letting him be a CONTROL
            # would inflate control_lift in ValuCast's favor. Exclude stamped rows
            # on either end of the control window (no-op before 7/4 stamps).
            and not r.get("in_mlb") and not latest[k].get("in_mlb")
        ]
        pool.sort(key=lambda r: abs(r["consensus_rank"] - c["consensus_then"]))
        for r in pool[:CONTROLS_PER_CALL]:
            used_controls.add(r["identity_key"])
            ctrl_catch = r["consensus_rank"] - latest[r["identity_key"]]["consensus_rank"]
            control_entries.append({
                "consensus_catch_up": ctrl_catch,
                "bucket": _classify_move(ctrl_catch, c["initial_gap"]),
                "days_tracked": c["days_tracked"],
            })

    open_rates = _bucket_rates(open_calls)
    matured_rates = _bucket_rates(matured_calls)
    control_rates = _bucket_rates(control_entries)
    control_matured_rates = _bucket_rates(
        [c for c in control_entries if c["days_tracked"] >= MATURITY_DAYS]
    )
    # Registered maturity rule (frozen 2026-07-02): "headline cohort = calls at
    # least 14 days old". Lift compares matured open calls against matured
    # controls -- like with like. Compliance fix 2026-07-12, disclosed
    # pre-publish: this previously divided ALL open calls by ALL controls,
    # contradicting the registered rule (all-calls read 1.36x; matured 1.31x).
    control_lift = (
        round(matured_rates["toward_rate"] / control_matured_rates["toward_rate"], 2)
        if matured_rates and control_matured_rates and control_matured_rates["toward_rate"]
        else None
    )

    # --- decided-rate headline: wins over every MATURED call that went
    # SOMEWHERE. Retreats sit in the denominator; flats/undecided are excluded;
    # decided calls younger than MATURITY_DAYS surface in immature_decided until
    # they mature -- excluded from the rate, never hidden. (Same compliance fix:
    # previously counted all calls, 29/118 = 24.6%; matured 29/101 = 28.7%.) ---
    decided_statuses = {"open_toward", "closed_caught_up", "open_away", "retired_we_backed_off"}
    decided_all = [c for c in calls if c["status"] in decided_statuses]
    decided_mature = [c for c in decided_all if c["days_tracked"] >= MATURITY_DAYS]
    wins = sum(1 for c in decided_mature if c["status"] in ("open_toward", "closed_caught_up"))
    decided = len(decided_mature)
    decided_rate = round(wins / decided, 3) if decided else None
    immature_decided = len(decided_all) - decided

    first_call_date = min((e["date"] for e in earliest.values()), default=today)
    horizon_days = _days_between(first_call_date, latest_date)
    publishable = horizon_days >= MIN_PUBLISH_HORIZON_DAYS and decided >= MIN_PUBLISH_RESOLVED

    calls.sort(key=lambda c: (c["consensus_catch_up"] is None, -(c["consensus_catch_up"] or 0)))

    return {
        "artifact": ARTIFACT_NAME,
        "signal_version": SIGNAL_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "status": "candidate_ready" if files else "blocked",
        "source_policy": {
            "kind": "valucast_ahead_of_consensus_scorecard",
            "inputs": "valucast_prospect_rank_v1_dated_archive",
            # Post-freeze eligibility refinement, disclosed in-artifact: from
            # 2026-07-04, a call can only OPEN (and a control only be drawn)
            # while the player is in the minors. Calls enrolled before the
            # archive stamp existed keep their full lifecycle, chipped in_mlb.
            "enrollment_excludes_active_mlb_from": "2026-07-04",
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
                else "accruing: " + str(horizon_days) + "d horizon / " + str(decided)
                + " decided (need " + str(MIN_PUBLISH_HORIZON_DAYS) + "d and "
                + str(MIN_PUBLISH_RESOLVED) + ")"
            ),
        },
        "definitions": {
            "noise_floor": "max(" + str(NOISE_FLOOR_SPOTS) + " spots, "
                + str(int(NOISE_FLOOR_GAP_FRAC * 100)) + "% of the call's initial gap)",
            "maturity_days": MATURITY_DAYS,
            "control_band": list(CONTROL_BAND),
            "controls_per_call": CONTROLS_PER_CALL,
            "decided_rate": "wins (open_toward + closed_caught_up) / (wins + open_away + retired_we_backed_off), matured cohort only",
            "headline_cohort": "calls at least " + str(MATURITY_DAYS) + " days old (registered maturity rule); younger decided calls surface in summary.immature_decided",
            "retreat_attribution": "divergence closes -> whichever side moved more; ties count against ValuCast",
            "one_sided_note": "conservative: only credits the field coming toward ValuCast, never widening-right calls",
            "frozen": "2026-07-02, pre-registered before the publish gate",
            "compliance_fix_2026_07_12": "pre-publish, disclosed: headline decided_rate/control_lift had been computed on the all-calls cohort, contradicting the registered maturity rule; pinned to the matured cohort before first publish (that day: decided rate 24.6% -> 28.7%, lift 1.36x -> 1.31x)",
        },
        "targets": {
            "decided_rate": TARGET_DECIDED_RATE,
            "control_lift": TARGET_CONTROL_LIFT,
            "usage": "pre-registered accountability targets, display-only; the model never optimizes toward this scorecard",
        },
        "funnel": funnel,
        "summary": {
            "ever_flagged": len(earliest),
            "decided_count": decided,
            "wins": wins,
            "decided_rate": decided_rate,
            "immature_decided": immature_decided,
            "open_count": len(open_calls),
            "open_rates": open_rates,
            "matured_open_rates": matured_rates,
            "control_rates": control_rates,
            "control_matured_rates": control_matured_rates,
            "control_lift": control_lift,
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
        "decided": payload["summary"]["decided_count"],
        "decided_rate": payload["summary"]["decided_rate"],
        "control_lift": payload["summary"]["control_lift"],
        "horizon_days": payload["summary"]["horizon_days"],
    }


def main() -> int:
    r = run_scorecard()
    print(
        "ahead-of-consensus scorecard: "
        f"publishable={r['publishable']} decided={r['decided']} "
        f"decided_rate={r['decided_rate']} lift={r['control_lift']} "
        f"horizon={r['horizon_days']}d -> {r['artifact_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
