"""Validate the committed ordinal-calibration power artifact."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.ordinal_calibration_power import (
        EFFECT_ANCHOR_ARTIFACT_PATH,
        OOF_ARTIFACT_PATH,
        POWER_ARTIFACT_PATH,
        RANK_ARTIFACT_PATH,
        validate_power_artifact,
    )

    payload = json.loads(POWER_ARTIFACT_PATH.read_text(encoding="utf-8"))
    problems = validate_power_artifact(
        payload,
        oof_bytes=OOF_ARTIFACT_PATH.read_bytes(),
        effect_anchor_bytes=EFFECT_ANCHOR_ARTIFACT_PATH.read_bytes(),
        rank_bytes=RANK_ARTIFACT_PATH.read_bytes(),
    )
    if problems:
        raise SystemExit("\n".join(problems))
    print(
        "ordinal calibration power: "
        f"status={payload['status']} scenarios={payload['scenarios']}"
    )
