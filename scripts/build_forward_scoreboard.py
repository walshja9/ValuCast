"""Build the forward-ledger scoreboard artifact (plan 030, S2).

Reads the committed claim ledger + the dated rank archive (+ the S1 cohort registry
when present) and rolls them up into `data/models/valucast_forward_scoreboard.json`
via `prospects.forward_scoreboard.build_scoreboard`.

The default path writes the real artifact atomically (tmp + os.replace). **This
session does NOT generate the real artifact under data/** — the orchestrator runs
the default path after the in-flight daily-public-data CI run lands a fresh archive.
Use `--dev-run --out <path>` to build against the current committed inputs to a temp
path OUTSIDE data/ and print the current numbers.

ponytail: stdlib + numpy only, deterministic (frozen resample seed), network-free.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.forward_scoreboard import build_scoreboard  # noqa: E402

RANK_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
LEDGER_PATH = ROOT / "data" / "models" / "valucast_gaps_claim_ledger.json"
REGISTRY_PATH = ROOT / "data" / "models" / "valucast_forward_cohort_registry.json"
SCOREBOARD_PATH = ROOT / "data" / "models" / "valucast_forward_scoreboard.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _load_archive(archive_dir: Path = RANK_ARCHIVE_DIR) -> dict[str, list[dict]]:
    """date -> board rows across every committed <YYYY-MM-DD>.json snapshot. Needed
    for the A4 adverse-movement consensus recompute; loaded whole so any claim's
    claim_date / expiry / retraction date can be looked up."""
    archive: dict[str, list[dict]] = {}
    for path in sorted(archive_dir.glob("*.json")):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        board = payload.get("board")
        if isinstance(board, list):
            archive[path.stem] = board
    return archive


def _atomic_write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _build(generated_at: str) -> dict:
    ledger = _load_json(LEDGER_PATH)
    if not isinstance(ledger, dict):
        raise SystemExit(f"claim ledger not found or unreadable at {LEDGER_PATH}")
    archive = _load_archive()
    registry = _load_json(REGISTRY_PATH)  # None until cohort #1 is registered
    return build_scoreboard(
        ledger=ledger, archive=archive, registry=registry, generated_at=generated_at
    )


def _print_summary(scoreboard: dict, label: str) -> None:
    headline = scoreboard["anticipation_score"]
    funnel = scoreboard["funnel"]
    retraction = funnel["self_retraction_rate"]
    print(
        f"{label}: pool_size={headline['pool_size']} "
        f"median_lead_days={headline['median_lead_days']} "
        f"ci=({headline['ci_low']}, {headline['ci_high']}) "
        f"provisional={headline['provisional']} label={headline['label']!r}"
    )
    print(
        f"  funnel: total={funnel['total_claims']} wins={funnel['wins']} "
        f"losses={funnel['losses']} excluded={funnel['excluded_from_pool']} "
        f"open={funnel['open']}"
    )
    print(f"  buckets: {funnel['buckets']}")
    print(
        f"  self_retraction_rate: {retraction['retracted']}/{retraction['total']} "
        f"= {retraction['rate']}"
    )
    print(f"  cohorts: {scoreboard['cohorts']['status']} ({scoreboard['cohorts']['cohort_count']})")
    print(f"  content_sha256: {scoreboard['content_sha256']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the forward-ledger scoreboard.")
    parser.add_argument(
        "--dev-run",
        action="store_true",
        help="Build against committed inputs to --out; never touches data/.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Output path for --dev-run (required with --dev-run; must be outside data/).",
    )
    args = parser.parse_args()

    if args.dev_run:
        if args.out is None:
            parser.error("--dev-run requires --out")
        out = args.out.resolve()
        if (ROOT / "data") in out.parents or out == (ROOT / "data"):
            parser.error("--dev-run --out must be OUTSIDE data/ (it never writes the real artifact)")
        scoreboard = _build(generated_at=_now_iso())
        _atomic_write_json(scoreboard, out)
        _print_summary(scoreboard, "dev-run")
        print("wrote", out)
        return 0

    scoreboard = _build(generated_at=_now_iso())
    _atomic_write_json(scoreboard, SCOREBOARD_PATH)
    _print_summary(scoreboard, "built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
