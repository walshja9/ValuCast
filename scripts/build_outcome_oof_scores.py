"""Build the per-player outcome-score OOF artifact (audit repair R6)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.outcome_oof import run_outcome_oof_artifact

    print(json.dumps(run_outcome_oof_artifact(), indent=2, sort_keys=True))
