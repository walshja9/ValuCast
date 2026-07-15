"""Validate the committed ordinal-calibration OOF design."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.ordinal_calibration_power import (
        OOF_ARTIFACT_PATH,
        validate_oof_score_artifact,
    )

    payload = json.loads(OOF_ARTIFACT_PATH.read_text(encoding="utf-8"))
    problems = validate_oof_score_artifact(payload)
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"ordinal OOF scores: valid rows={len(payload['rows'])}")
