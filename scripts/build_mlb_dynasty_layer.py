"""Build the shadow ValuCast MLB dynasty value layer."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from mlb.dynasty import run_mlb_dynasty_layer  # noqa: E402


VALUCAST_HP_PATH = ROOT / "projections" / "runs" / "valucast_hp_2026_v2" / "projections.json"
# Manual, default-OFF live-source flip. The daily live build calls this with no source arg,
# so the live MLB dynasty layer reads Steamer (`current`) until someone explicitly sets the
# env flag to `valucast-hp` after reviewing the advisory projection-source comparison. The
# Marcel shadow build passes --projection-source explicitly, so the env never affects it.
LIVE_SOURCE_ENV = "VALUCAST_MLB_LIVE_PROJECTION_SOURCE"
PROJECTION_SOURCES = ("current", "valucast-hp")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--projection-source",
        choices=PROJECTION_SOURCES,
        default=None,
        help=(
            "Projection artifact to feed into the MLB dynasty layer. Defaults to the "
            f"${LIVE_SOURCE_ENV} env flag, or 'current' (Steamer) when unset."
        ),
    )
    parser.add_argument(
        "--artifact-path",
        type=Path,
        default=None,
        help="Optional output artifact path. Defaults to the production MLB layer path.",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="Optional archive directory. Use for shadow runs to avoid production archive churn.",
    )
    return parser.parse_args()


def _resolve_source(arg: str | None) -> str:
    source = arg or os.environ.get(LIVE_SOURCE_ENV, "current")
    return source if source in PROJECTION_SOURCES else "current"


def main() -> None:
    args = _parse_args()
    source = _resolve_source(args.projection_source)
    kwargs = {}
    if source == "valucast-hp":
        kwargs.update(
            {
                "projection_path": VALUCAST_HP_PATH,
                "projection_source": "projections/runs/valucast_hp_2026_v2/projections.json",
                "projection_source_kind": "valucast_hp_projection_run",
            }
        )
    if args.artifact_path is not None:
        kwargs["artifact_path"] = args.artifact_path
    if args.archive_dir is not None:
        kwargs["archive_dir"] = args.archive_dir

    result = run_mlb_dynasty_layer(**kwargs)
    print(
        "ValuCast MLB dynasty layer: "
        f"projection_source={source} "
        f"rows={result['row_count']} "
        f"missing_mlbam={result['missing_mlbam_count']} "
        f"availability_adjusted={result['availability_adjusted_count']} "
        f"ready={result['ready_for_live_consumers']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
