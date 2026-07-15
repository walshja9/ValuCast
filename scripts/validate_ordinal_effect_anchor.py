"""Validate the committed outcome-blind ordinal effect anchor."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.ordinal_calibration_power import (
        EFFECT_ANCHOR_ARTIFACT_PATH,
        OOF_ARTIFACT_PATH,
        RANK_ARTIFACT_PATH,
        validate_effect_anchor_artifact,
    )

    payload = json.loads(EFFECT_ANCHOR_ARTIFACT_PATH.read_text(encoding="utf-8"))
    problems = validate_effect_anchor_artifact(
        payload,
        oof_bytes=OOF_ARTIFACT_PATH.read_bytes(),
        rank_bytes=RANK_ARTIFACT_PATH.read_bytes(),
    )
    if problems:
        raise SystemExit("\n".join(problems))
    print(
        "ordinal effect anchor: "
        f"relative_reduction={payload['derivation']['relative_reduction']} "
        f"top25_pitchers={payload['derivation']['before_pitcher_count']}->"
        f"{payload['derivation']['after_pitcher_count']}"
    )
