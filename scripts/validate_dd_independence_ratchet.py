#!/usr/bin/env python3
"""Ratchet: residual DD factual-fallback counts may only decrease, never grow.

Reads `validation.dd_factual_fallback` from the ValuCast prospect rank artifact and
compares the residual DD display-path counts against a committed ceiling. The score
path is already DD-clean (enforced by the public-snapshot validator + governor); this
guards the remaining DISPLAY fallback (translated peripherals / mlb_stat_line) so it
can only shrink as ValuCast ownership rolls out.

Two honest accommodations:
- DORMANT when `dd_factual_fallback` is absent (a stale artifact that predates the
  emit). There is nothing to ratchet yet, so it passes.
- SELF-SEEDS the baseline from the first build that emits the counts, rather than
  hardcoding a ceiling we cannot derive without real provenance-tagged data.
  # ponytail: self-seed instead of guessing a baseline; tighten via the file later.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
BASELINE_PATH = ROOT / "data" / "models" / "dd_independence_baseline.json"

RATCHET_KEYS = ("mlb_stat_line_from_dd_feed", "translated_dd_feed_fallback")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_ratchet(
    rank_path: Path = RANK_PATH, baseline_path: Path = BASELINE_PATH
) -> tuple[list[str], dict]:
    try:
        rank = _load(rank_path)
    except Exception as exc:  # noqa: BLE001
        return [f"{rank_path} unreadable: {exc}"], {"status": "error"}

    fallback = (rank.get("validation") or {}).get("dd_factual_fallback") or {}
    if not fallback:
        return [], {"status": "dormant", "reason": "dd_factual_fallback not emitted yet"}

    current = {key: int(fallback.get(key) or 0) for key in RATCHET_KEYS}

    if not baseline_path.exists():
        seed = {
            "artifact": "dd_independence_baseline",
            "note": (
                "Ratchet ceiling. These residual DD display-fallback counts may only "
                "DECREASE. Lower a value when the build legitimately reduces it; never "
                "raise."
            ),
        }
        seed.update({f"max_{key}": current[key] for key in RATCHET_KEYS})
        baseline_path.write_text(json.dumps(seed, indent=2), encoding="utf-8")
        return [], {"status": "seeded", "baseline": seed}

    baseline = _load(baseline_path)
    problems: list[str] = []
    for key in RATCHET_KEYS:
        ceiling = int(baseline.get(f"max_{key}") or 0)
        if current[key] > ceiling:
            problems.append(
                f"dd_factual_fallback.{key}={current[key]} exceeds baseline ceiling "
                f"{ceiling} (ValuCast-owned factual path regressed toward DD)"
            )
    return problems, {"status": "enforced", "current": current}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rank-path", type=Path, default=RANK_PATH)
    parser.add_argument("--baseline-path", type=Path, default=BASELINE_PATH)
    args = parser.parse_args()

    problems, info = validate_ratchet(args.rank_path, args.baseline_path)
    if problems:
        print("DD INDEPENDENCE RATCHET FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"DD independence ratchet OK: {info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
