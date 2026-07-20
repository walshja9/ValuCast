#!/usr/bin/env python3
"""Archive immutable daily observations from the canonical MiLB input contract."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prospects.universe import MINOR_TEAM_MLB_AFFILIATES  # noqa: E402

INPUT_PATH = ROOT / "data" / "prospects" / "prospect_model_inputs.json"
OUTPUT_DIR = ROOT / "data" / "milb_observation_archive"

HITTER_FIELDS = ("iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip")
PITCHER_FIELDS = ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")
ROLE_CONFIGS = (
    ("hitter", "hitters", "plate_appearances", "PA", HITTER_FIELDS),
    ("pitcher", "pitchers", "innings_pitched", "IP", PITCHER_FIELDS),
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _project_current(current: dict) -> dict:
    projected = {
        "fetched_date": current["fetched_date"],
        "season": current["season"],
    }
    for role, plural, sample_key, _unit, fields in ROLE_CONFIGS:
        source_fields = (
            "mlbam_id",
            "team",
            "level",
            "source_kind",
            "age",
            sample_key,
            *fields,
        )
        if role == "pitcher":
            source_fields += ("games_started", "is_starter")
        sources = [
            {
                field: int(source[field]) if field == "mlbam_id" else source.get(field)
                for field in source_fields
            }
            for source in current.get(plural) or []
        ]
        projected[plural] = sorted(sources, key=_canonical_json)
    return projected


def build_snapshot(contract: dict) -> dict:
    current = _project_current(contract["current"])
    rows = []
    for role, plural, sample_key, unit, fields in ROLE_CONFIGS:
        for source in current.get(plural) or []:
            team = source.get("team")
            organization = MINOR_TEAM_MLB_AFFILIATES.get(team)
            row = {
                "mlbam_id": int(source["mlbam_id"]),
                "role": role,
                "organization": organization,
                "organization_status": "known" if organization else "unknown",
                "minor_team": team,
                "level": source.get("level"),
                "source_kind": source.get("source_kind"),
                "observation_date": current["fetched_date"],
                "season": current["season"],
                "age": source.get("age"),
                "sample": source.get(sample_key),
                "sample_unit": unit,
                "rates": {field: source.get(field) for field in fields},
            }
            if role == "pitcher":
                row["role_facts"] = {
                    "games_started": source.get("games_started"),
                    "is_starter": source.get("is_starter"),
                }
            rows.append(row)

    rows.sort(key=lambda row: (row["role"], row["mlbam_id"], _canonical_json(row)))
    snapshot = {
        "artifact": "valucast_milb_observation_archive",
        "schema_version": 1,
        "observation_date": current["fetched_date"],
        "season": current["season"],
        "source": "data/prospects/prospect_model_inputs.json#current",
        "input_sha256": _canonical_hash(current),
        "rows": rows,
        "content_sha256": "",
    }
    snapshot["content_sha256"] = _canonical_hash(
        {key: value for key, value in snapshot.items() if key != "content_sha256"}
    )
    return snapshot


def write_snapshot(snapshot: dict, output_dir: Path) -> tuple[Path, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{snapshot['observation_date']}.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) == snapshot:
            return path, "unchanged"
        raise ValueError("sealed date changed")

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path, "created"


def main() -> int:
    contract = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    snapshot = build_snapshot(contract)
    path, status = write_snapshot(snapshot, OUTPUT_DIR)
    print(f"MiLB observation archive: rows={len(snapshot['rows'])} {status} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
