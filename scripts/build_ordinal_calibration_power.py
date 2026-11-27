"""Run the registered ordinal-calibration simulation power study."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if __name__ == "__main__":
    from prospects.ordinal_calibration_power import run_power_artifact

    def progress(name: str, done: int, total: int, rejected: int) -> None:
        print(f"{name}: {done}/{total} rejections={rejected}", flush=True)

    print(json.dumps(run_power_artifact(progress=progress), indent=2, sort_keys=True))
