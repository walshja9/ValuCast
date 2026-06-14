"""Validate the ValuCast quality-governor artifact shape."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOVERNOR_PATH = ROOT / "data" / "models" / "valucast_quality_governor.json"


def validate_governor(path: Path = GOVERNOR_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems = []
    if payload.get("artifact") != "valucast_quality_governor":
        problems.append("artifact must be valucast_quality_governor")
    if not payload.get("governor_version"):
        problems.append("governor_version is required")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    if payload.get("status") not in {"blocked", "candidate_ready"}:
        problems.append("status must be blocked or candidate_ready")
    if not isinstance(payload.get("checks"), list) or not payload.get("checks"):
        problems.append("checks must be a non-empty list")
    if not isinstance(payload.get("surface_readiness"), dict):
        problems.append("surface_readiness must be an object")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=GOVERNOR_PATH)
    args = parser.parse_args()

    payload, problems = validate_governor(args.path)
    if problems:
        print(f"VALUCAST QUALITY GOVERNOR VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    print(
        "quality governor: "
        f"status={payload.get('status')} "
        f"snapshot_ready={payload.get('ready_for_public_snapshot')} "
        f"buys_ready={payload.get('ready_for_buys_promotion')}"
    )
    for blocker in payload.get("blockers") or []:
        print(f"  blocker: {blocker}")
    for blocker in payload.get("buy_blockers") or []:
        if blocker not in (payload.get("blockers") or []):
            print(f"  buy blocker: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

