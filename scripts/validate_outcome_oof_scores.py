"""Validate the committed per-player outcome-score OOF artifact (R6)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.outcome_oof import (
        ARTIFACT_PATH,
        validate_outcome_oof_artifact,
    )

    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    problems = validate_outcome_oof_artifact(payload)
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"outcome-score OOF: valid rows={len(payload['rows'])}")
