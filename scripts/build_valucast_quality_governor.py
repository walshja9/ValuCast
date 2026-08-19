"""Build the ValuCast quality-governor artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quality.valucast_governor import run_quality_governor  # noqa: E402


def main() -> None:
    result = run_quality_governor()
    # Plan 036 R3: this script is the single authoritative evaluation; the
    # exact artifact it wrote is injected into the committed snapshot so the
    # embedded and standalone verdicts cannot diverge.
    from scripts.build_public_dynasty_snapshot import inject_quality_governor

    injected = inject_quality_governor()
    readiness = (injected.get("validation") or {}).get("surface_readiness") or {}
    print(
        "ValuCast quality governor: "
        f"snapshot_ready={result['ready_for_public_snapshot']} "
        f"buys_ready={result['ready_for_buys_promotion']} "
        f"movers_ready={result['ready_for_movers']} "
        f"blockers={result['blocker_count']} "
        f"buy_blockers={result['buy_blocker_count']} "
        f"mover_blockers={result['mover_blocker_count']} "
        f"-> {result['artifact_path']}; injected into snapshot "
        f"(surface_readiness={readiness})"
    )


if __name__ == "__main__":
    main()
