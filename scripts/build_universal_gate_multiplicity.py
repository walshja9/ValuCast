"""Build the universal-gate multiplicity report (audit repair R3)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.universal_gate_multiplicity import run_gate_multiplicity

    print(json.dumps(run_gate_multiplicity(), indent=2, sort_keys=True))
