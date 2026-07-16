"""Register today's forward-ledger cohort (plan 030, S1).

Reads the LATEST committed daily rank archive, builds a frozen cohort via
`prospects.forward_cohort.build_cohort`, and appends it to two artifacts:

  data/models/valucast_forward_cohort_registry.json          - append-only registry
      (all cohorts, keyed by registration_date)
  data/prediction_archive/valucast_forward_cohorts/<date>.json - per-registration
      frozen snapshot

**No back-dating.** The default registration always dates the cohort TODAY and
reads the newest archive on disk (recording `archive_date` separately — it may lag
`registration_date` by a day). Earlier archive dates are never used to synthesize
older cohorts: public-board coverage jumped 2->5 boards between 6/13 and 6/30, so
pre-6/30 cohorts would be non-comparable, and back-dating is precisely the practice
this benchmark exists to reject.

**Immutability.** A registered cohort is frozen. Re-running on the same
registration_date is a hash-identical no-op; if the recomputed body differs from
the committed one, that is a hard error (drift), never a silent overwrite. Writes
are atomic (tmp + os.replace), cloning the `gaps_claim_ledger` idiom.

**--dev-run** builds a cohort from ANY archive date to a temp `--out` path for
testing. It NEVER touches anything under data/ — no registry, no snapshot.

ponytail: stdlib only, deterministic, network-free.
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

from prospects.forward_cohort import PROTOCOL_VERSION, build_cohort  # noqa: E402

RANK_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
REGISTRY_PATH = ROOT / "data" / "models" / "valucast_forward_cohort_registry.json"
COHORT_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_forward_cohorts"

ARTIFACT_NAME = "valucast_forward_cohort_registry"


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _latest_archive_date(archive_dir: Path = RANK_ARCHIVE_DIR) -> str | None:
    """Newest committed <YYYY-MM-DD>.json in the rank archive dir, by filename."""
    dates = sorted(p.stem for p in archive_dir.glob("*.json"))
    return dates[-1] if dates else None


def _load_board(archive_date: str, archive_dir: Path = RANK_ARCHIVE_DIR) -> list[dict]:
    path = archive_dir / f"{archive_date}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    board = payload.get("board")
    if not isinstance(board, list):
        raise ValueError(f"{path} has no board list")
    return board


def _atomic_write_json(payload: dict | list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _load_registry(path: Path) -> dict:
    if not path.exists():
        return {
            "artifact": ARTIFACT_NAME,
            "protocol_version": PROTOCOL_VERSION,
            "cohorts": {},
        }
    registry = json.loads(path.read_text(encoding="utf-8"))
    registry.setdefault("cohorts", {})
    return registry


def register_cohort(
    *,
    registration_date: str,
    archive_date: str,
    board: list[dict],
    registry_path: Path = REGISTRY_PATH,
    cohort_archive_dir: Path = COHORT_ARCHIVE_DIR,
) -> dict:
    """Freeze + persist the cohort for `registration_date`. Immutability-asserted.

    Returns the frozen cohort payload. On a re-run whose recomputed body is
    hash-identical to the committed cohort it is a no-op; on drift it raises."""
    cohort = build_cohort(
        board=board,
        registration_date=registration_date,
        archive_date=archive_date,
    )

    registry = _load_registry(registry_path)
    existing = registry["cohorts"].get(registration_date)
    if existing is not None:
        # A registered cohort is IMMUTABLE. Identical body -> no-op; drift -> error.
        if existing.get("content_sha256") != cohort["content_sha256"]:
            raise SystemExit(
                f"IMMUTABILITY VIOLATION: cohort {registration_date} already registered "
                f"with hash {existing.get('content_sha256')} but rebuild yields "
                f"{cohort['content_sha256']} — a frozen cohort is never recomputed."
            )
        return cohort  # already committed, byte-identical — nothing to write

    registry["cohorts"][registration_date] = cohort
    _atomic_write_json(registry, registry_path)
    _atomic_write_json(cohort, cohort_archive_dir / f"{registration_date}.json")
    return cohort


def _print_counts(cohort: dict, label: str) -> None:
    counts = cohort["counts"]
    print(
        f"{label}: registration_date={cohort['registration_date']} "
        f"archive_date={cohort['archive_date']} "
        f"eligible_total={counts['eligible_total']} "
        f"consensus_covered={counts['consensus_covered']} "
        f"rank_only={counts['rank_only']} deduped={counts['deduped']} "
        f"sha256={cohort['content_sha256']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Register today's forward-ledger cohort.")
    parser.add_argument(
        "--dev-run",
        metavar="ARCHIVE_DATE",
        help="Build a cohort from this archive date to --out; never touches data/.",
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
            parser.error("--dev-run --out must be OUTSIDE data/ (it never touches the registry)")
        board = _load_board(args.dev_run)
        # dev-run dates the cohort by the archive it reads (no registry, no freeze).
        cohort = build_cohort(board=board, registration_date=args.dev_run, archive_date=args.dev_run)
        _atomic_write_json(cohort, out)
        _print_counts(cohort, "dev-run")
        print("wrote", out)
        return 0

    registration_date = _today_iso()
    archive_date = _latest_archive_date()
    if archive_date is None:
        print("no committed rank archive found — cannot register a cohort", file=sys.stderr)
        return 1
    board = _load_board(archive_date)
    cohort = register_cohort(
        registration_date=registration_date, archive_date=archive_date, board=board
    )
    _print_counts(cohort, "registered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
