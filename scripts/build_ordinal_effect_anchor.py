"""Build the registered outcome-blind ordinal effect anchor."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.ordinal_calibration_power import run_effect_anchor_artifact

    print(
        json.dumps(
            run_effect_anchor_artifact(),
            indent=2,
            sort_keys=True,
        )
    )
