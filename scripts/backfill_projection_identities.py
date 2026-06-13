"""Backfill ValuCast identity facts for current projection MLBAM IDs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from league_values.playing_time import filter_by_playing_time  # noqa: E402
from mlb.dynasty import MIN_HITTER_PA, MIN_RP_IP, MIN_SP_IP  # noqa: E402
from projections.data.identity import fetch_identities, load_identity_store  # noqa: E402
from web.projection_store import ProjectionStore  # noqa: E402

PROJECTION_PATH = ROOT / "data" / "projections" / "current.json"
IDENTITY_DATA_DIR = ROOT / "projections" / "data"


def projection_mlbam_ids(path: Path = PROJECTION_PATH) -> list[str]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    ids = set()
    for row in rows:
        metadata = row.get("metadata") or {}
        mlbam_id = metadata.get("mlbam_id") or row.get("mlbam_id")
        if mlbam_id in (None, ""):
            continue
        ids.add(str(mlbam_id))
    return sorted(ids)


def eligible_projection_mlbam_ids(path: Path = PROJECTION_PATH) -> list[str]:
    store = ProjectionStore(path)
    eligible = filter_by_playing_time(
        store.get_all(),
        hitter_pa=MIN_HITTER_PA,
        sp_ip=MIN_SP_IP,
        rp_ip=MIN_RP_IP,
    )
    ids = {
        str(player.metadata.get("mlbam_id"))
        for player in eligible
        if player.metadata.get("mlbam_id") not in (None, "")
    }
    return sorted(ids)


def _identity_path(data_dir: Path) -> Path:
    return data_dir / "identity.json"


def _write_identities(identities: dict[str, dict], data_dir: Path) -> None:
    path = _identity_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(identities, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def missing_identity_ids(
    projected_ids: list[str],
    identities: dict[str, dict],
) -> list[str]:
    return [
        mlbam_id
        for mlbam_id in projected_ids
        if not (identities.get(mlbam_id) or {}).get("birth_date")
    ]


def backfill_projection_identities(
    projection_path: Path = PROJECTION_PATH,
    identity_data_dir: Path = IDENTITY_DATA_DIR,
    fetcher: Callable[[list[str]], dict[str, dict]] = fetch_identities,
    eligible_only: bool = True,
) -> dict:
    projected_ids = (
        eligible_projection_mlbam_ids(projection_path)
        if eligible_only
        else projection_mlbam_ids(projection_path)
    )
    existing = load_identity_store(identity_data_dir)
    missing_before = missing_identity_ids(projected_ids, existing)

    fetched: dict[str, dict] = {}
    if missing_before:
        fetched = fetcher(missing_before)
        if fetched:
            merged = dict(existing)
            merged.update({str(key): value for key, value in fetched.items()})
            _write_identities(merged, identity_data_dir)
        existing = load_identity_store(identity_data_dir)

    missing_after = missing_identity_ids(projected_ids, existing)
    return {
        "projected_id_count": len(projected_ids),
        "existing_identity_count": len(existing),
        "missing_before": len(missing_before),
        "fetched_count": len(fetched),
        "missing_after": len(missing_after),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection-path", type=Path, default=PROJECTION_PATH)
    parser.add_argument("--identity-data-dir", type=Path, default=IDENTITY_DATA_DIR)
    parser.add_argument(
        "--all-projection-ids",
        action="store_true",
        help="Backfill every projected MLBAM ID instead of MLB-layer eligible IDs.",
    )
    args = parser.parse_args()

    result = backfill_projection_identities(
        projection_path=args.projection_path,
        identity_data_dir=args.identity_data_dir,
        eligible_only=not args.all_projection_ids,
    )
    print(
        "projection identities: "
        f"projected={result['projected_id_count']} "
        f"missing_before={result['missing_before']} "
        f"fetched={result['fetched_count']} "
        f"missing_after={result['missing_after']} "
        f"identity_count={result['existing_identity_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
