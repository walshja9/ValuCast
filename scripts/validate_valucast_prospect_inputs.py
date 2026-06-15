"""Validate ValuCast's canonical prospect input contract."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.input_contract import VALUCAST_INPUT_PATH  # noqa: E402
from prospects.input_contract import validate_factual_contract  # noqa: E402


def validate_valucast_prospect_inputs(
    path: Path = VALUCAST_INPUT_PATH,
) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems = validate_factual_contract(payload)
    producer = payload.get("producer") or {}
    if producer.get("owner") != "valucast":
        problems.append("producer.owner must be valucast")
    if producer.get("kind") != "canonical_factual_prospect_input_contract":
        problems.append("producer.kind must be canonical_factual_prospect_input_contract")
    if producer.get("upstream_model_score_effect") != "none":
        problems.append("producer.upstream_model_score_effect must be none")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=VALUCAST_INPUT_PATH)
    args = parser.parse_args()

    payload, problems = validate_valucast_prospect_inputs(args.path)
    if problems:
        print(f"VALUCAST PROSPECT INPUT VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    current = payload.get("current") or {}
    print(
        "valucast prospect inputs: "
        f"historical={len((payload.get('historical') or {}).get('rows') or [])} "
        f"current={len(current.get('hitters') or []) + len(current.get('pitchers') or [])} "
        f"producer={(payload.get('producer') or {}).get('owner')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
