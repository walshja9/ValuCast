"""Validate the Model Verdicts registry: every verdict is artifact-backed and
non-overclaiming. Run in the daily build's VALIDATE_STEPS so a renamed/removed
evidence artifact fails the build instead of shipping a verdict with no evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "models" / "valucast_model_registry.json"
VERDICTS = {"VALIDATED", "PROVISIONAL", "DEPRECATED", "REJECTED"}
# An artifact carrying one of these build-statuses is NOT yet proven -> a
# VALIDATED verdict over it is an overclaim.
NOT_PROVEN = {"shadow_only", "insufficient_sample", "needs_review", "candidate_ready"}


def validate(registry_path: Path = REGISTRY) -> list[str]:
    """Return a list of error strings; empty means the registry is valid."""
    try:
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"registry did not parse: {exc}"]
    errs: list[str] = []
    for entry in reg.get("entries", []):
        eid = entry.get("id", "?")
        if entry.get("verdict") not in VERDICTS:
            errs.append(f"{eid}: bad verdict {entry.get('verdict')!r}")
        evidence = entry.get("evidence")
        ev_path = ROOT / evidence if evidence else None
        if not evidence or not ev_path.exists():
            errs.append(f"{eid}: missing evidence artifact {evidence!r}")
        source_module = entry.get("source_module")
        if not source_module or not (ROOT / source_module).exists():
            errs.append(f"{eid}: missing source_module {source_module!r}")
        # Overclaim guard: VALIDATED must not cite a not-yet-proven artifact.
        if entry.get("verdict") == "VALIDATED" and ev_path and ev_path.exists():
            try:
                status = (json.loads(ev_path.read_text(encoding="utf-8")) or {}).get("status")
            except (OSError, ValueError):
                status = None
            if status in NOT_PROVEN:
                errs.append(
                    f"{eid}: VALIDATED over not-yet-proven artifact status {status!r}"
                )
    return errs


def main() -> int:
    errs = validate()
    if errs:
        print("MODEL REGISTRY INVALID:\n  " + "\n  ".join(errs))
        return 1
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    print(f"OK: model registry {len(reg.get('entries', []))} entries, all artifact-backed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
