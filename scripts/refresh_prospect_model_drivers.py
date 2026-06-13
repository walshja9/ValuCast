"""Refresh ValuCast prospect impact-driver explanations without retraining."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.model import (
        ARCHIVE_DIR,
        ARTIFACT_PATH,
        INPUT_PATH,
        archive_predictions,
        refresh_impact_drivers,
        write_artifact,
    )

    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    contract = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    refreshed, changed = refresh_impact_drivers(payload, contract)
    write_artifact(refreshed, ARTIFACT_PATH)
    archive_path, archive_changed = archive_predictions(
        refreshed,
        archive_dir=ARCHIVE_DIR,
    )
    print(
        f"Refreshed {changed} impact-driver rows -> {ARTIFACT_PATH}; "
        f"archive={archive_path} changed={archive_changed}"
    )


if __name__ == "__main__":
    main()
