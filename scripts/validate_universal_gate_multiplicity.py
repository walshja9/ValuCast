"""Validate the committed universal-gate multiplicity report (R3)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.universal_gate_multiplicity import (
        ARTIFACT_PATH,
        validate_gate_multiplicity,
    )

    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    problems = validate_gate_multiplicity(payload)
    if problems:
        raise SystemExit("\n".join(problems))
    family = payload["family"]
    print(
        "universal gate multiplicity: "
        f"family_size={family['family_size']} "
        f"served_active={family['served_active_gates']} "
        f"bonferroni_significant={family['bonferroni_significant_gates']}"
    )
