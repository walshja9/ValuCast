"""Build the research-only Stage 1 outcome proof artifact and report."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.stage1_outcome_proof import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    build_stage1_outcome_proof,
    render_markdown,
)

INPUTS = {
    "oof": ROOT / "data/models/valucast_outcome_oof_scores.json",
    "reliability": ROOT / "data/models/valucast_probability_reliability.json",
    "backtest": ROOT / "data/models/valucast_prospect_dynasty_backtest.json",
    "scorecard": ROOT / "data/models/valucast_ahead_of_consensus_scorecard.json",
}
OUTPUT_JSON = ROOT / "data/validation/valucast_stage1_outcome_proof.json"
OUTPUT_REPORT = ROOT / "docs/stage1-outcome-proof.md"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def run(
    *,
    output_json: Path = OUTPUT_JSON,
    output_report: Path = OUTPUT_REPORT,
    seed: int = BOOTSTRAP_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
    write: bool = True,
) -> dict:
    inputs = {key: _load(path) for key, path in INPUTS.items()}
    generated_at = max(str(payload.get("generated_at") or "") for payload in inputs.values())
    payload = build_stage1_outcome_proof(
        oof_payload=inputs["oof"],
        reliability_payload=inputs["reliability"],
        backtest_payload=inputs["backtest"],
        scorecard_payload=inputs["scorecard"],
        sources={
            key: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha(path),
            }
            for key, path in INPUTS.items()
        },
        generated_at=generated_at,
        seed=seed,
        resamples=resamples,
    )
    if write:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_report.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        output_report.write_text(render_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--resamples", type=int, default=BOOTSTRAP_RESAMPLES)
    args = parser.parse_args()
    payload = run(seed=args.seed, resamples=args.resamples)
    print(
        f"wrote {OUTPUT_JSON} ("
        f"{sum(role['sample_size'] for role in payload['historical']['roles'].values())} OOF rows)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
