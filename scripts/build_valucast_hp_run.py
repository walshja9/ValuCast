#!/usr/bin/env python3
"""Build the live ValuCast H+P projection run or a dated historical snapshot."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from projections.data.identity import load_identity_store  # noqa: E402
from projections.export.marcel_run import build_marcel_projections  # noqa: E402
from projections.export.valucast_enrich import build_eligibility, enrich_rows  # noqa: E402
from projections.export.valucast_hp_run import AS_OF_SEASON  # noqa: E402
from projections.models.marcel_params import MarcelParams  # noqa: E402
from projections.models.marcel_pitcher import build_pitcher_projections, compute_cfip  # noqa: E402
from projections.models.pitcher_params import PitcherMarcelParams  # noqa: E402
from projections.data.pitching_historical import load_pitching_season  # noqa: E402

DATA_DIR = ROOT / "projections" / "data"
CURRENT_PROJECTION_PATH = ROOT / "data" / "projections" / "current.json"
CURRENT_ACTUALS_PATH = ROOT / "data" / "actuals" / "current.json"
LIVE_RUN_DIR = ROOT / "projections" / "runs" / f"valucast_hp_{AS_OF_SEASON}_v2"
HP_SNAPSHOT_DIR = ROOT / "data" / "prediction_archive" / "valucast_hp_snapshot"

PITCHER_POOLS = {"starter", "reliever", "pitcher"}
HITTER_COUNTING = ("PA", "AB", "1B", "2B", "3B", "HR", "R", "RBI", "SB", "CS", "BB", "SO", "HBP", "SF")
PITCHER_COUNTING = ("IP", "ER", "BB", "H_ALLOWED", "K", "W", "L", "SV", "HLD", "GS", "G", "QS")
HITTER_PARAMS = MarcelParams(alpha_contact=0.75, alpha_power=0.5)
PITCHER_PARAMS = PitcherMarcelParams()
PRIOR_SEASONS = (AS_OF_SEASON - 3, AS_OF_SEASON - 2, AS_OF_SEASON - 1)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, payload, *, indent: int = 2) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=indent, sort_keys=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def _mlbam_id(row: dict) -> str | None:
    value = (row.get("metadata") or {}).get("mlbam_id", row.get("mlbam_id"))
    return None if value in (None, "") else str(value)


def _role(row: dict) -> str:
    return "pitcher" if row.get("pool") in PITCHER_POOLS else "hitter"


def _safe(stats: dict, key: str) -> float:
    return float(stats.get(key, 0) or 0)


def _actuals_by_key(actual_rows: list[dict]) -> dict[tuple[str, str], dict]:
    out = {}
    for row in actual_rows:
        mlbam_id = _mlbam_id(row)
        if mlbam_id:
            out[(mlbam_id, _role(row))] = row
    return out


def _subtract(projected: float, actual: float) -> float:
    # ponytail: clamp at zero; revisit with playing-time redistribution if this becomes live-critical.
    return max(0.0, projected - actual)


def _remaining_hitter_stats(proj: dict, actual: dict) -> dict:
    stats = dict(proj)
    actual_stats = actual.get("stats") or {}
    for key in HITTER_COUNTING:
        stats[key] = _subtract(_safe(stats, key), _safe(actual_stats, key))
    stats["H"] = stats["1B"] + stats["2B"] + stats["3B"] + stats["HR"]
    stats["TB"] = stats["1B"] + 2 * stats["2B"] + 3 * stats["3B"] + 4 * stats["HR"]
    stats["NSB"] = stats["SB"] - stats["CS"]
    ab = stats["AB"]
    pa_denom = ab + stats["BB"] + stats["HBP"] + stats["SF"]
    stats["AVG"] = round(stats["H"] / ab, 3) if ab > 0 else 0.0
    stats["OBP"] = round((stats["H"] + stats["BB"] + stats["HBP"]) / pa_denom, 3) if pa_denom > 0 else 0.0
    stats["SLG"] = round(stats["TB"] / ab, 3) if ab > 0 else 0.0
    stats["OPS"] = round(stats["OBP"] + stats["SLG"], 3)
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()}


def _remaining_pitcher_stats(proj: dict, actual: dict) -> dict:
    stats = dict(proj)
    actual_stats = actual.get("stats") or {}
    for key in PITCHER_COUNTING:
        stats[key] = _subtract(_safe(stats, key), _safe(actual_stats, key))
    stats["SV_HLD"] = stats["SV"] + stats["HLD"]
    ip = stats["IP"]
    stats["ERA"] = round(9 * stats["ER"] / ip, 3) if ip > 0 else 0.0
    stats["WHIP"] = round((stats["BB"] + stats["H_ALLOWED"]) / ip, 3) if ip > 0 else 0.0
    stats["K_9"] = round(9 * stats["K"] / ip, 3) if ip > 0 else 0.0
    stats["BB_9"] = round(9 * stats["BB"] / ip, 3) if ip > 0 else 0.0
    stats["K_BB"] = round(stats["K"] / stats["BB"], 3) if stats["BB"] > 0 else 0.0
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in stats.items()}


def apply_actuals_to_remaining(rows: list[dict], actual_rows: list[dict], actuals_as_of: str) -> list[dict]:
    actuals = _actuals_by_key(actual_rows)
    out = []
    for row in rows:
        role = _role(row)
        actual = actuals.get((_mlbam_id(row) or "", role))
        row2 = dict(row)
        row2["metadata"] = dict(row.get("metadata") or {})
        row2["metadata"]["projection_scope"] = "rest_of_season"
        row2["metadata"]["actuals_as_of"] = actuals_as_of
        opportunity_key = "IP" if role == "pitcher" else "PA"
        row2["metadata"]["actuals_applied"] = actual is not None
        row2["metadata"]["remaining_opportunity_clamped"] = bool(
            actual
            and _safe(actual.get("stats") or {}, opportunity_key)
            > _safe(row.get("stats") or {}, opportunity_key)
        )
        if actual:
            if role == "hitter":
                row2["stats"] = _remaining_hitter_stats(row.get("stats") or {}, actual)
            else:
                row2["stats"] = _remaining_pitcher_stats(row.get("stats") or {}, actual)
        out.append(row2)
    return out


def _actuals_as_of(actual_rows: list[dict], generated_at: str) -> str:
    for row in actual_rows:
        as_of = (row.get("metadata") or {}).get("as_of")
        if as_of:
            return str(as_of)[:10]
    return generated_at[:10]


def _cfip_for_manifest() -> float | None:
    snaps = [load_pitching_season(year, DATA_DIR) for year in (AS_OF_SEASON - 1, AS_OF_SEASON - 2, AS_OF_SEASON - 3)]
    cfip = compute_cfip(snaps)
    return round(cfip, 4) if cfip is not None else None


def build_valucast_hp_rows(
    *,
    actuals_path: Path = CURRENT_ACTUALS_PATH,
    projection_universe_path: Path = CURRENT_PROJECTION_PATH,
    generated_at: str | None = None,
) -> list[dict]:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    universe = _load_json(projection_universe_path)
    actuals = _load_json(actuals_path)
    eligibility = build_eligibility(universe)
    identities = load_identity_store(DATA_DIR)

    hitter_rows = build_marcel_projections(AS_OF_SEASON, DATA_DIR, HITTER_PARAMS, identities)
    pitcher_rows = build_pitcher_projections(AS_OF_SEASON, DATA_DIR, PITCHER_PARAMS)
    hitters = enrich_rows(hitter_rows, eligibility["hitters"])
    pitchers = enrich_rows(pitcher_rows, eligibility["pitchers"])
    return apply_actuals_to_remaining(hitters + pitchers, actuals, _actuals_as_of(actuals, generated_at))


def build_manifest(rows: list[dict], generated_at: str, actuals_as_of: str) -> dict:
    hitters = [row for row in rows if row.get("pool") == "hitter"]
    pitchers = [row for row in rows if row.get("pool") in PITCHER_POOLS]
    remaining_diagnostics = {}
    for label, role_rows, opportunity_key in (
        ("hitters", hitters, "PA"), ("pitchers", pitchers, "IP"),
    ):
        remaining_diagnostics[label] = {
            "rows": len(role_rows),
            "actuals_matched": sum(bool((row.get("metadata") or {}).get("actuals_applied")) for row in role_rows),
            "zero_remaining": sum(_safe(row.get("stats") or {}, opportunity_key) <= 0 for row in role_rows),
            "clamped_to_zero": sum(bool((row.get("metadata") or {}).get("remaining_opportunity_clamped")) for row in role_rows),
        }
    clamped = sum(role["clamped_to_zero"] for role in remaining_diagnostics.values())
    zero_remaining = sum(role["zero_remaining"] for role in remaining_diagnostics.values())
    skill_gate = {
        "status": "held" if clamped or zero_remaining else "display_only_eligible",
        "affects_live_outputs": False,
        "reason": (
            "remaining-opportunity clamping is present" if clamped
            else "zero remaining opportunity is present" if zero_remaining
            else "remaining-opportunity inputs have positive coverage"
        ),
    }
    pitcher_meta = {
        "model": "valucast_pitching_marcel",
        "model_version": 1,
        "n_reg": PITCHER_PARAMS.n_reg,
        "era_method": "projected_fip_plus_cfip",
        "prior_seasons": list(PRIOR_SEASONS),
        "verdict": "held-out 2020-25 skill mean MAE ratio 0.821 vs persistence",
    }
    cfip = _cfip_for_manifest()
    if cfip is not None:
        pitcher_meta["cfip_2026"] = cfip
    return {
        "run_id": f"valucast_hp_{AS_OF_SEASON}_v2",
        "source_name": "valucast",
        "as_of_season": AS_OF_SEASON,
        "generated_at": generated_at,
        "projection_scope": "rest_of_season",
        "actuals_as_of": actuals_as_of,
        "hitter_count": len(hitters),
        "pitcher_count": len(pitchers),
        "remaining_opportunity_diagnostics": remaining_diagnostics,
        "public_skill_metric_gate": skill_gate,
        "eligibility_source": (
            "current.json (Steamer outlook) used for names/teams/positions + active-player universe; "
            "NO projection stats copied"
        ),
        "components": {
            "hitters": {
                "inputs": "consumes Savant xBA/xSLG (not our own xBA)",
                "model": "valucast_marcel_statcast",
                "model_version": 1,
                "alpha_contact": HITTER_PARAMS.alpha_contact,
                "alpha_power": HITTER_PARAMS.alpha_power,
                "gamma": HITTER_PARAMS.gamma,
                "prior_seasons": list(PRIOR_SEASONS),
                "verdict": "held-out 2020-25 mean MAE ratio 0.979; AVG/OBP/SLG/OPS 4-6% lift; HR neutral",
            },
            "pitchers": {
                "inputs": "fully in-house, no Statcast",
                **pitcher_meta,
            },
        },
    }


def _validate_rows(rows: list[dict]) -> None:
    hitters = [row for row in rows if row.get("pool") == "hitter"]
    pitchers = [row for row in rows if row.get("pool") in PITCHER_POOLS]
    if not hitters:
        raise ValueError("ValuCast H+P run has zero hitter rows; refusing to write.")
    if not pitchers:
        raise ValueError("ValuCast H+P run has zero pitcher rows; refusing to write.")


def write_live_hp_run(rows: list[dict], manifest: dict, run_dir: Path = LIVE_RUN_DIR) -> dict:
    _validate_rows(rows)
    changed = _atomic_json(run_dir / "projections.json", rows, indent=2)
    changed = _atomic_json(run_dir / "run_manifest.json", manifest, indent=2) or changed
    changed = _atomic_json(run_dir / "metadata.json", {"as_of": manifest["generated_at"]}, indent=2) or changed
    return {"changed": changed, "row_count": len(rows), "run_dir": str(run_dir)}


def write_historical_hp_snapshot(
    as_of: str,
    *,
    actuals_path: Path,
    projection_universe_path: Path = CURRENT_PROJECTION_PATH,
    archive_dir: Path = HP_SNAPSHOT_DIR,
) -> dict:
    rows = build_valucast_hp_rows(
        actuals_path=actuals_path,
        projection_universe_path=projection_universe_path,
        generated_at=f"{as_of}T00:00:00+00:00",
    )
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{as_of}.json"
    changed = _atomic_json(path, rows, indent=2)
    return {"archive_path": str(path), "archive_changed": changed, "row_count": len(rows)}


def build_live_run(
    *,
    actuals_path: Path = CURRENT_ACTUALS_PATH,
    projection_universe_path: Path = CURRENT_PROJECTION_PATH,
    run_dir: Path = LIVE_RUN_DIR,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    rows = build_valucast_hp_rows(
        actuals_path=actuals_path,
        projection_universe_path=projection_universe_path,
        generated_at=generated_at,
    )
    actuals_as_of = (rows[0].get("metadata") or {}).get("actuals_as_of", generated_at[:10])
    manifest = build_manifest(rows, generated_at, actuals_as_of)
    return write_live_hp_run(rows, manifest, run_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-date", help="Write data/prediction_archive/valucast_hp_snapshot/YYYY-MM-DD.json.")
    parser.add_argument("--actuals-path", type=Path, default=CURRENT_ACTUALS_PATH)
    parser.add_argument("--projection-universe-path", type=Path, default=CURRENT_PROJECTION_PATH)
    parser.add_argument("--archive-dir", type=Path, default=HP_SNAPSHOT_DIR)
    parser.add_argument("--run-dir", type=Path, default=LIVE_RUN_DIR)
    args = parser.parse_args()

    if args.historical_date:
        result = write_historical_hp_snapshot(
            args.historical_date,
            actuals_path=args.actuals_path,
            projection_universe_path=args.projection_universe_path,
            archive_dir=args.archive_dir,
        )
        print(
            "ValuCast H+P historical snapshot: "
            f"rows={result['row_count']} changed={result['archive_changed']} -> {result['archive_path']}"
        )
        return 0

    result = build_live_run(
        actuals_path=args.actuals_path,
        projection_universe_path=args.projection_universe_path,
        run_dir=args.run_dir,
    )
    print(
        "ValuCast H+P live run: "
        f"rows={result['row_count']} changed={result['changed']} -> {result['run_dir']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
