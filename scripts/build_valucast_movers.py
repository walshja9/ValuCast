"""Build the ValuCast-owned prospect movers artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.movers import run_movers_board  # noqa: E402


def _print_side(label: str, rows: list[dict]) -> None:
    if not rows:
        print(f"{label}: sparse (0 movers passed clean-tail and +/-2.0 filters)")
        return
    print(f"{label}:")
    for row in rows:
        print(f"  - {row.get('name')}: {row.get('movement_label')}")


def main() -> None:
    result = run_movers_board()
    print(
        "ValuCast prospect movers: "
        f"rising={result['rising_count']} "
        f"cooling={result['cooling_count']} "
        f"step_guard_excluded={result['excluded_step_guard_count']} "
        f"-> {result['artifact_path']}"
    )
    _print_side("RISING", result["rising"])
    _print_side("COOLING", result["cooling"])


if __name__ == "__main__":
    main()
