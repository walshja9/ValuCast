"""Rebuild the immutable ValuCast H+P run, bumping the version, with pitcher ERA
derived from projected FIP (raw FIP + leakage-safe league cFIP) instead of the old
ER-rate prior.

Why this exists
---------------
The opt-in `?source=valucast` board reads ONE frozen, immutable run
(`projections/runs/valucast_hp_2026_vN/projections.json`). When commit 060cca1 shipped
FIP-based pitcher ERA in `projections/models/marcel_pitcher.py`
(`PitcherMarcelParams.era_from_fip`, default True), the already-archived v1 run kept its
old ER-rate ERAs. The live model changed; the frozen artifact did not. The absence of a
committed builder is why bumping it was a manual chore.

Safe, deterministic transform (NOT a fresh model run)
-----------------------------------------------------
ONLY the ERA derivation changed in the model -- none of the projected components
(K/BB/HBP/HR/IP/...) moved. So instead of re-running the whole pipeline (which would be
sensitive to data/seed drift), this script:

  1. Loads the prior run rows + manifest.
  2. Keeps every HITTER row BYTE-IDENTICAL (untouched object, same order).
  3. For each PITCHER row with IP > 0, recomputes ONLY ERA and ER from the row's own
     already-projected FIP components, using the same identity the model now uses:
         raw_fip = (13*HR + 3*(BB + HBP) - 2*K) / IP
         ERA     = max(0, raw_fip + cFIP)
         ER      = ERA * IP / 9        (keeps the 9*ER/IP == ERA identity)
     Rows with IP <= 0 are left unchanged. All other stats fields are untouched.
  4. Writes the next version via the project's own `write_valucast_hp_run`, which
     enforces immutability and pool integrity. v1 stays intact.

cFIP is computed exactly as `build_pitcher_projections` does: from the three prior
pre-target seasons (2025, 2024, 2023), so it is leakage-safe and matches the live model.

Re-runnable: pass --version to target a specific bump; default is prior_version + 1.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # allow `python scripts/build_valucast_hp_run.py`

from projections.data.pitching_historical import load_pitching_season
from projections.export.valucast_hp_run import AS_OF_SEASON, write_valucast_hp_run
from projections.models.marcel_pitcher import compute_cfip

RUNS_DIR = ROOT / "projections" / "runs"
DATA_DIR = ROOT / "projections" / "data"

_PITCHER_POOLS = {"starter", "reliever", "pitcher"}
_PRIOR_SEASONS = (AS_OF_SEASON - 1, AS_OF_SEASON - 2, AS_OF_SEASON - 3)  # 2025, 2024, 2023


def compute_cfip_for_target() -> float:
    """Leakage-safe league cFIP over the three prior pre-target seasons (matches the
    live model's `build_pitcher_projections`)."""
    snaps = [load_pitching_season(y, DATA_DIR) for y in _PRIOR_SEASONS]
    cfip = compute_cfip(snaps)
    if cfip is None:
        raise RuntimeError("compute_cfip returned None (no IP in prior seasons).")
    return cfip


def patch_pitcher_era(row: dict, cfip: float) -> dict:
    """Return a copy of a pitcher row with ERA/ER re-derived from projected FIP.
    Rows with IP <= 0 are returned unchanged. No other stats field is touched."""
    out = copy.deepcopy(row)
    stats = out["stats"]
    ip = float(stats.get("IP", 0) or 0.0)
    if ip <= 0:
        return out
    raw_fip = (13.0 * stats["HR"] + 3.0 * (stats["BB"] + stats["HBP"]) - 2.0 * stats["K"]) / ip
    era = max(0.0, raw_fip + cfip)
    stats["ER"] = round(era * ip / 9.0, 4)   # match the model's 4-dp rounding on stats
    stats["ERA"] = round(era, 3)
    return out


def _meta_from_manifest_component(component: dict) -> dict:
    """Strip the 'inputs' key (the writer re-adds it) and return the rest as meta."""
    return {k: v for k, v in component.items() if k != "inputs"}


def build(prior_version: int, version: int) -> str:
    prior_id = f"valucast_hp_{AS_OF_SEASON}_v{prior_version}"
    prior_run = RUNS_DIR / prior_id
    rows = json.loads((prior_run / "projections.json").read_text(encoding="utf-8"))
    manifest = json.loads((prior_run / "run_manifest.json").read_text(encoding="utf-8"))

    hitters = [r for r in rows if r.get("pool") == "hitter"]
    pitchers = [r for r in rows if r.get("pool") in _PITCHER_POOLS]
    leftover = [r for r in rows if r.get("pool") not in ({"hitter"} | _PITCHER_POOLS)]
    if leftover:
        raise RuntimeError(f"Unexpected pools in {prior_id}: {sorted({r.get('pool') for r in leftover})}")

    cfip = compute_cfip_for_target()
    patched_pitchers = [patch_pitcher_era(r, cfip) for r in pitchers]

    components = manifest.get("components", {})
    hitter_meta = _meta_from_manifest_component(components.get("hitters", {}))
    pitcher_meta = _meta_from_manifest_component(components.get("pitchers", {}))
    pitcher_meta["era_method"] = "projected_fip_plus_cfip"
    pitcher_meta["cfip_2026"] = round(cfip, 4)

    run_id = write_valucast_hp_run(
        hitter_rows=hitters,
        pitcher_rows=patched_pitchers,
        runs_dir=RUNS_DIR,
        version=version,
        hitter_meta=hitter_meta,
        pitcher_meta=pitcher_meta,
    )

    # The writer intentionally does not emit `eligibility_source` (it is hand-authored
    # provenance, not a per-leg component). Carry it forward from the prior manifest so
    # v2 documents the same eligibility universe v1 did (a quality test asserts its
    # presence). Re-write with the writer's own formatting (indent=2, sort_keys).
    eligibility = manifest.get("eligibility_source")
    if eligibility is not None:
        v2_manifest_path = RUNS_DIR / run_id / "run_manifest.json"
        v2_manifest = json.loads(v2_manifest_path.read_text(encoding="utf-8"))
        if "eligibility_source" not in v2_manifest:
            v2_manifest["eligibility_source"] = eligibility
            v2_manifest_path.write_text(
                json.dumps(v2_manifest, indent=2, sort_keys=True), encoding="utf-8")

    print(f"wrote {run_id} | hitters {len(hitters)} | pitchers {len(patched_pitchers)} "
          f"| cfip {round(cfip, 4)}")
    return run_id


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prior-version", type=int, default=1,
                    help="Version of the run to transform (default 1).")
    ap.add_argument("--version", type=int, default=None,
                    help="Version to write (default: prior-version + 1).")
    args = ap.parse_args()
    version = args.version if args.version is not None else args.prior_version + 1
    build(args.prior_version, version)


if __name__ == "__main__":
    main()
