"""Build the predicted-outcome-probability reliability artifact (audit repair R4)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.probability_reliability import run_probability_reliability

    print(json.dumps(run_probability_reliability(), indent=2, sort_keys=True))
