"""Validate the shadow ValuCast prospect buy signals artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BUY_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
from web.valucast_buy_store import validate_valucast_buy_payload  # noqa: E402


def validate_file(path: Path = BUY_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]
    return payload, validate_valucast_buy_payload(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=BUY_PATH)
    args = parser.parse_args()

    payload, problems = validate_file(args.path)
    if problems:
        print(f"VALUCAST BUYS VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    validation = payload.get("validation") or {}
    print(
        "valucast buys: "
        f"rows={validation.get('row_count')} "
        f"eligible={validation.get('eligible_count')} "
        f"history_limited={validation.get('history_limited_count')} "
        f"ready_for_live_consumers={validation.get('ready_for_live_consumers')}"
    )
    for blocker in validation.get("blockers") or []:
        print(f"  blocker: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
