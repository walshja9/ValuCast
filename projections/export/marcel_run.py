"""Assemble a Marcel hitting run and archive it immutably."""
from __future__ import annotations

import json
from pathlib import Path

from projections.constants import MIN_EVAL_PA
from projections.data.historical import load_season
from projections.data.identity import age_for
from projections.models.league_rates import compute_league_rates
from projections.models.marcel_hitter import project_hitter
from projections.models.marcel_params import MarcelParams

# Engine-native export contract: every stats dict carries these keys.
EXPORT_KEYS = (
    "PA", "AB", "H", "1B", "2B", "3B", "HR", "R", "RBI", "SB", "CS",
    "BB", "SO", "HBP", "SF", "TB", "NSB", "AVG", "OBP", "SLG", "OPS",
)


def build_marcel_projections(
    target_season: int,
    data_dir: Path,
    params: MarcelParams,
    identities: dict[str, dict],
) -> list[dict]:
    """Project all hitters with >=1 prior season, using data < target_season.

    `identities` maps mlbam_id -> {name, birth_date, ...}; it supplies real
    names and the per-target-season age (age_for resolves age as of season T).
    """
    prior_years = [target_season - 1, target_season - 2, target_season - 3]
    snaps: list[list[dict]] = []
    for yr in prior_years:
        try:
            snaps.append(load_season(yr, data_dir))
        except FileNotFoundError:
            snaps.append([])

    weights = params.season_weights[: len(snaps)]
    league = compute_league_rates(snaps, weights=weights, pa_floor=MIN_EVAL_PA)

    # Offset-aligned priors: index 0 = T-1, 1 = T-2, 2 = T-3. Missing = None,
    # so weights/PA roles stay pinned to the correct year (see project_hitter).
    index_maps = [{r["mlbam_id"]: r for r in snap} for snap in snaps]
    all_ids = {pid for m in index_maps for pid in m}

    rows: list[dict] = []
    for mlbam_id in all_ids:
        prior_seasons = [m.get(mlbam_id) for m in index_maps]
        if all(s is None for s in prior_seasons):
            continue
        ident = identities.get(mlbam_id, {})
        age = age_for(ident.get("birth_date"), target_season)
        proj = project_hitter(prior_seasons, league, age, params)
        stats = {k: round(float(proj.get(k, 0.0)), 4) for k in EXPORT_KEYS}
        rows.append({
            "id": f"mlbam_{mlbam_id}_H",
            "name": ident.get("name") or mlbam_id,
            "pool": "hitter",
            "positions": [],
            "stats": stats,
            "sources": ["marcel"],
            "metadata": {
                "mlbam_id": mlbam_id,
                "base_id": f"mlbam_{mlbam_id}",
                "source": "marcel",
                "model": "valucast_marcel",
                "model_version": 1,
                "as_of_season": target_season,
                "age_unknown": age is None,
            },
        })
    return rows


def write_run(
    rows: list[dict],
    runs_dir: Path,
    model: str,
    as_of_season: int,
    version: int,
) -> str:
    run_id = f"{model}_{as_of_season}_v{version}"
    run_path = runs_dir / run_id
    proj_path = run_path / "projections.json"
    if proj_path.exists():
        # Archived runs are immutable: identical re-write is a no-op; differing
        # contents under the same run_id must bump the version, not overwrite.
        if json.loads(proj_path.read_text(encoding="utf-8")) == rows:
            return run_id
        raise ValueError(
            f"Refusing to overwrite archived run {run_id}: contents differ."
        )
    run_path.mkdir(parents=True, exist_ok=True)
    proj_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (run_path / "run_manifest.json").write_text(
        json.dumps({
            "run_id": run_id,
            "model": model,
            "model_version": version,
            "as_of_season": as_of_season,
            "row_count": len(rows),
        }, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return run_id
