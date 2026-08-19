"""Validate the shadow ValuCast public dynasty snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
GOVERNOR_ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_quality_governor.json"

from web.public_snapshot_store import validate_public_snapshot_payload  # noqa: E402


def validate_snapshot(path: Path = SNAPSHOT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]
    return payload, validate_public_snapshot_payload(payload)


def _canonical_digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True).encode("utf-8")
    ).hexdigest()


def governor_consistency_problems(
    payload: dict, governor_path: Path = GOVERNOR_ARTIFACT_PATH
) -> list[str]:
    """Plan 036 R3: one durable verdict, not a build-order accident.

    The snapshot's embedded governor must be the exact committed artifact
    (hash equality) and must match its validation-block copy; a snapshot
    still carrying the pending-injection placeholder fails the refresh.
    """
    problems: list[str] = []
    embedded = payload.get("quality_governor") or {}
    if embedded.get("status") == "pending_injection" or not embedded:
        problems.append(
            "quality governor verdict was never injected into the snapshot"
        )
        return problems
    validation_copy = (payload.get("validation") or {}).get("quality_governor")
    if validation_copy != embedded:
        problems.append(
            "validation.quality_governor differs from the embedded verdict"
        )
    try:
        artifact = json.loads(governor_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        problems.append(f"{governor_path} unreadable: {exc}")
        return problems
    if _canonical_digest(embedded) != _canonical_digest(artifact):
        problems.append(
            "embedded quality governor verdict does not hash-match the "
            "committed artifact"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=SNAPSHOT_PATH)
    parser.add_argument(
        "--governor-path", type=Path, default=GOVERNOR_ARTIFACT_PATH
    )
    args = parser.parse_args()

    payload, problems = validate_snapshot(args.path)
    if payload is not None:
        problems = problems + governor_consistency_problems(
            payload, args.governor_path
        )
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
        f"quality_governor_ready={validation.get('quality_governor_ready')} "
        f"ready_for_live_consumers={validation.get('ready_for_live_consumers')}"
    )
    for blocker in validation.get("blockers") or []:
        print(f"  blocker: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
