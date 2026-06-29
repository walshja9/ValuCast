"""Combine ValuCast hitter + pitcher projection rows into one immutable H+P run,
with a per-leg provenance manifest. Single-pool runs are rejected (a broken
half-publish must not masquerade as 'ValuCast has no pitchers')."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

AS_OF_SEASON = 2026
_PITCHER_POOLS = {"starter", "reliever", "pitcher"}


def write_valucast_hp_run(
    hitter_rows: list[dict],
    pitcher_rows: list[dict],
    runs_dir: Path,
    version: int,
    hitter_meta: dict,
    pitcher_meta: dict,
) -> str:
    """Write projections.json (hitters + pitchers) + run_manifest.json. Immutable:
    identical re-write is a no-op, changed content raises. Returns run_id."""
    if not hitter_rows:
        raise ValueError("ValuCast H+P run has zero hitter rows; refusing to write.")
    if not pitcher_rows:
        raise ValueError("ValuCast H+P run has zero pitcher rows; refusing to write.")
    # Validate ACTUAL pools, not argument names — a caller could pass hitters in both
    # lists and write a malformed single-pool run that passes the nonempty checks.
    bad_h = [r["id"] for r in hitter_rows if r.get("pool") != "hitter"]
    if bad_h:
        raise ValueError(f"hitter_rows contains non-hitter pools (e.g. {bad_h[0]}).")
    bad_p = [r["id"] for r in pitcher_rows if r.get("pool") not in _PITCHER_POOLS]
    if bad_p:
        raise ValueError(f"pitcher_rows contains non-pitcher pools (e.g. {bad_p[0]}).")

    run_id = f"valucast_hp_{AS_OF_SEASON}_v{version}"
    run_path = runs_dir / run_id
    proj_path = run_path / "projections.json"
    combined = list(hitter_rows) + list(pitcher_rows)

    if proj_path.exists():
        if json.loads(proj_path.read_text(encoding="utf-8")) == combined:
            return run_id
        raise ValueError(f"Refusing to overwrite archived run {run_id}: contents differ.")

    run_path.mkdir(parents=True, exist_ok=True)
    proj_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "run_id": run_id,
        "source_name": "valucast",
        "as_of_season": AS_OF_SEASON,
        "generated_at": generated_at,
        "hitter_count": len(hitter_rows),
        "pitcher_count": len(pitcher_rows),
        "components": {
            "hitters": {"inputs": "consumes Savant xBA/xSLG (not our own xBA)", **hitter_meta},
            "pitchers": {"inputs": "fully in-house, no Statcast", **pitcher_meta},
        },
    }
    (run_path / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (run_path / "metadata.json").write_text(
        json.dumps({"as_of": generated_at}, indent=2, sort_keys=True), encoding="utf-8")
    return run_id
