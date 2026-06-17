"""Validate the advisory MLB projection-source comparison artifact.

Key invariant: the comparison cannot claim a Marcel win before enough forward horizon and
sample exist, and it must never advertise an automatic live-source flip.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlb.projection_source_comparison import ARTIFACT_PATH, validate_comparison  # noqa: E402


def main() -> int:
    if not ARTIFACT_PATH.exists():
        print(f"FAIL: {ARTIFACT_PATH} missing")
        return 1
    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    problems = validate_comparison(payload)
    if problems:
        print("MLB PROJECTION-SOURCE COMPARISON VALIDATION FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    gate = payload.get("gate", {})
    basis = payload.get("comparison_basis", {})
    print(
        "mlb projection-source comparison: "
        f"gate={gate.get('status')} horizon={basis.get('horizon_days')}d "
        f"scoreable={basis.get('scoreable_players')} "
        f"marcel_beats_steamer={payload.get('marcel_beats_steamer')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
