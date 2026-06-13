"""Validate the shadow ValuCast public dynasty snapshot."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"

from web.public_snapshot_store import validate_public_snapshot_payload  # noqa: E402


def validate_snapshot(path: Path = SNAPSHOT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]
    return payload, validate_public_snapshot_payload(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=SNAPSHOT_PATH)
    args = parser.parse_args()

    payload, problems = validate_snapshot(args.path)
    if problems:
        print(f"PUBLIC DYNASTY SNAPSHOT VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    validation = payload.get("validation") or {}
    print(
        "public snapshot: "
        f"rows={validation.get('row_count')} "
        f"mlb={validation.get('mlb_count')} "
        f"prospects={validation.get('prospect_count')} "
        f"duplicate_identity_count={validation.get('duplicate_identity_count')} "
        f"required_fields_complete={validation.get('required_fields_complete')} "
        f"same_day_freshness={validation.get('same_day_freshness')} "
        f"ready_for_live_consumers={validation.get('ready_for_live_consumers')}"
    )
    for blocker in validation.get("blockers") or []:
        print(f"  blocker: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
