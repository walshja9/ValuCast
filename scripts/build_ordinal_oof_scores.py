"""Build the registered fold-trained ordinal-calibration OOF design."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.ordinal_calibration_power import run_oof_score_artifact

    print(json.dumps(run_oof_score_artifact(), indent=2, sort_keys=True))
