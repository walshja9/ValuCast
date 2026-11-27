"""Build the research-only prospect challenger readiness artifact."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.challenger_readiness import build_plan034_readiness  # noqa: E402
from prospects.input_contract import VALUCAST_INPUT_PATH  # noqa: E402

PLAN_PATH = ROOT / "plans" / "034-post-2026-prospect-challenger-epoch.md"
AAA_PATH = ROOT / "data" / "models" / "valucast_aaa_statcast_features.json"
OUTPUT_PATH = ROOT / "data" / "validation" / "prospect_challenger_readiness.json"
REGISTRATION_RE = re.compile(
    r"post-2026-challenger-registration:start.*?```json\s*(\{.*?\})\s*```.*?post-2026-challenger-registration:end",
    re.DOTALL,
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _registration(path: Path) -> dict:
    match = REGISTRATION_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError("Plan 034 registration block not found")
    return json.loads(match.group(1))


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=VALUCAST_INPUT_PATH)
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    parser.add_argument("--aaa", type=Path, default=AAA_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()

    aaa = _load_json(args.aaa) if args.aaa.exists() else None
    payload = build_plan034_readiness(
        _load_json(args.input),
        _registration(args.plan),
        aaa,
        as_of=args.as_of,
    )
    _write_atomic(args.output, payload)
    print(
        f"prospect challenger readiness: status={payload['status']} "
        f"rows={payload['identity_audit']['row_count']} "
        f"outer_scoring_authorized={payload['outer_scoring_authorized']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
