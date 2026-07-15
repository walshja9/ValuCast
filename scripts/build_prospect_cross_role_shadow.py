"""Build the observe-only prospect cross-role validation shadow."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.cross_role_shadow import run_cross_role_shadow

    result = run_cross_role_shadow()
    print(
        "prospect cross-role shadow: "
        f"status={result['status']} "
        f"failed_checks={result['failed_checks']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
