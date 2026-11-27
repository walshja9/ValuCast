"""Validate the committed probability-reliability artifact (R4)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.probability_reliability import (
        ARTIFACT_PATH,
        validate_probability_reliability,
    )

    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    problems = validate_probability_reliability(payload)
    if problems:
        raise SystemExit("\n".join(problems))
    roles = payload["roles"]
    summary = " ".join(
        f"{role}(n={roles[role]['sample_size']},ece={roles[role]['expected_calibration_error']})"
        for role in sorted(roles)
    )
    print(f"probability reliability: valid {summary}")
