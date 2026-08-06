"""Validate the ValuCast quality-governor artifact shape."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOVERNOR_PATH = ROOT / "data" / "models" / "valucast_quality_governor.json"


def validate_governor(path: Path = GOVERNOR_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems = []
    if payload.get("artifact") != "valucast_quality_governor":
        problems.append("artifact must be valucast_quality_governor")
    if not payload.get("governor_version"):
        problems.append("governor_version is required")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    if payload.get("status") not in {"blocked", "candidate_ready"}:
        problems.append("status must be blocked or candidate_ready")
    if not isinstance(payload.get("checks"), list) or not payload.get("checks"):
        problems.append("checks must be a non-empty list")
    if not isinstance(payload.get("surface_readiness"), dict):
        problems.append("surface_readiness must be an object")
    transition_veto = next(
        (
            check
            for check in payload.get("checks") or []
            if check.get("id") == "prospect_transition_continuity"
            and check.get("status") == "blocked"
        ),
        None,
    )
    if transition_veto:
        details = []
        for sample in (transition_veto.get("metrics") or {}).get("samples") or []:
            parts = [str(sample.get("name") or "unknown")]
            if sample.get("mlbam_id"):
                parts.append(f"mlbam={sample.get('mlbam_id')}")
            if sample.get("role"):
                parts.append(f"role={sample.get('role')}")
            if sample.get("transition_signals"):
                parts.append("signals=" + ",".join(str(v) for v in sample.get("transition_signals") or []))
            if sample.get("old_level") or sample.get("new_level"):
                parts.append(f"level={sample.get('old_level')}->{sample.get('new_level')}")
            if sample.get("old_availability") or sample.get("new_availability"):
                parts.append(f"availability={sample.get('old_availability')}->{sample.get('new_availability')}")
            if sample.get("old_starter_role") or sample.get("new_starter_role"):
                parts.append(f"starter_role={sample.get('old_starter_role')}->{sample.get('new_starter_role')}")
            for key, label in (
                ("model_score_delta", "model_delta"),
                ("bucket_adjustment_delta", "bucket_delta"),
                ("final_score_delta", "final_delta"),
            ):
                if sample.get(key) is not None:
                    parts.append(f"{label}={sample.get(key)}")
            if sample.get("old_rank") or sample.get("new_rank"):
                parts.append(f"rank={sample.get('old_rank')}->{sample.get('new_rank')}")
            details.append(" [" + "; ".join(parts) + "]")
        problems.append(
            "prospect transition continuity veto blocks daily publication"
            + (":" + "".join(details) if details else "")
        )
    # Shape-valid but content-blocked must still fail this gate for surfaces the
    # live app actually serves gated on that flag: the daily commit is atomic
    # (actuals, dynasty, buys, movers, scouting all land in one push), and
    # "blocked" was previously an accepted status value, so a governor-rejected
    # board could publish with no error anywhere.
    #
    # Scoped to dynasty/buys/movers, NOT prospects: app.py's _select_dynasty_store
    # gates live serving on surface_readiness["dynasty"] only (both /?mode=dd_dynasty
    # and /?mode=prospects read the same dd_store) -- the "prospects" flag isn't
    # consulted by any live route (deliberately decoupled in 75e2878 so prospect
    # model issues can't false-stale the dynasty board). Blocking the ENTIRE day's
    # actuals/dynasty/buys/movers refresh over a prospects-only content issue (e.g.
    # top-board pitcher tilt) throws away real, ready data for zero live-serving
    # safety benefit. Prospects-surface blockers still print below and remain
    # visible via surface_blockers on the internal Launch Stability view.
    surface_readiness = payload.get("surface_readiness") or {}
    surface_blockers = payload.get("surface_blockers") or {}
    gating_surfaces = {"dynasty": "Dynasty board", "buys": "Buys", "movers": "Movers"}
    failed = [
        label for key, label in gating_surfaces.items()
        if surface_readiness.get(key) is False
    ]
    if failed:
        details = []
        for key, label in gating_surfaces.items():
            if surface_readiness.get(key) is False:
                blockers = surface_blockers.get(key) or []
                detail = f" ({'; '.join(str(b) for b in blockers[:3])})" if blockers else ""
                details.append(f"{label}{detail}")
        problems.append(
            "quality governor blocks a live-serving surface: " + "; ".join(details)
        )
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=GOVERNOR_PATH)
    args = parser.parse_args()

    payload, problems = validate_governor(args.path)
    if problems:
        print(f"VALUCAST QUALITY GOVERNOR VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    print(
        "quality governor: "
        f"status={payload.get('status')} "
        f"snapshot_ready={payload.get('ready_for_public_snapshot')} "
        f"buys_ready={payload.get('ready_for_buys_promotion')} "
        f"movers_ready={payload.get('ready_for_movers')}"
    )
    for blocker in payload.get("blockers") or []:
        print(f"  blocker: {blocker}")
    for blocker in payload.get("buy_blockers") or []:
        if blocker not in (payload.get("blockers") or []):
            print(f"  buy blocker: {blocker}")
    for blocker in payload.get("mover_blockers") or []:
        print(f"  mover blocker: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
