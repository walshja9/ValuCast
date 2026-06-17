"""Build the ValuCast shadow-model promotion report (accountability harness)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.shadow_promotion import run_shadow_promotion  # noqa: E402


def main() -> int:
    result = run_shadow_promotion()
    print(
        "shadow promotion: "
        f"models={result['model_count']} active={result['active_count']} ready={result['ready']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
