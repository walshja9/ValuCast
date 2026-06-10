#!/usr/bin/env python3
"""Build data/validation/methodology_scorecard.json deterministically from the
committed historical backbone + the rolling-origin harnesses.

- Hitting: ValuCast de-noised Marcel (alpha_contact/alpha_power from the shipped run
  manifest) vs CLASSIC Marcel, via vs_classic over the statcast-era scoring seasons.
- Pitching: role-routed Marcel vs persistence, via rolling_origin_pitching.

Fails LOUDLY if required season files are missing — never retains stale numbers.
The methodology page renders from this artifact; drift-lock tests pin page<->artifact
and page<->params.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from projections.backtest.harness import rolling_origin, vs_classic
from projections.backtest.pitching_harness import rolling_origin_pitching
from projections.constants import PITCHER_HEADLINE_SKILL, HEADLINE_STATS
from projections.models.marcel_params import MarcelParams
from projections.models.pitcher_params import PitcherMarcelParams

# Loaders append "historical/"/"pitching/" themselves, so data_dir is projections/data.
DATA = ROOT / "projections" / "data"
IDENTITY = DATA / "identity.json"
RUN_MANIFEST = ROOT / "projections" / "runs" / "valucast_hp_2026_v1" / "run_manifest.json"

# Canonical held-out SCORING block (disjoint from the 2018-19 de-noise tuning block),
# matching the Rung-3 hitting verdict and the pitching-foundation verdict.
HIT_SEASONS = list(range(2020, 2026))
PIT_SEASONS = list(range(2020, 2026))


def _require(path: Path):
    if not path.exists():
        raise SystemExit(f"FAIL: required data missing: {path}")


def _shipped_alphas() -> dict:
    man = json.loads(RUN_MANIFEST.read_text(encoding="utf-8"))
    # The hitter leg manifest carries the shipped de-noise knobs.
    s = json.dumps(man)
    m = json.loads(s)
    # search for alpha_contact/alpha_power anywhere in the manifest
    found = {}
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("alpha_contact", "alpha_power") and isinstance(v, (int, float)):
                    found[k] = v
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(m)
    if "alpha_contact" not in found or "alpha_power" not in found:
        raise SystemExit("FAIL: shipped alpha_contact/alpha_power not in run manifest")
    return found


def _per_stat_vs_classic(candidate_seasons, classic_seasons):
    """Per-stat candidate-vs-classic MAE ratio (where de-noise helps: AVG/OBP/SLG < 1.0,
    counting stats ~ 1.0). Mirrors vs_classic's per-stat comparison."""
    by_stat = {}
    for cs, ks in zip(candidate_seasons, classic_seasons):
        for stat, cm in cs["per_stat"].items():
            km = ks["per_stat"].get(stat)
            if not cm or not km or km["marcel_mae"] == 0:
                continue
            by_stat.setdefault(stat, []).append(cm["marcel_mae"] / km["marcel_mae"])
    return {st: round(sum(v) / len(v), 3) for st, v in by_stat.items()}


def _agg(seasons, skill_only=False):
    """Aggregate per-stat MAE ratios + corr-win-rate across seasons."""
    by_stat = {}
    corr_w = corr_t = 0
    for s in seasons:
        for stat, m in s["per_stat"].items():
            if not m:
                continue
            if skill_only and not m.get("is_skill"):
                continue
            by_stat.setdefault(stat, []).append(m["mae_ratio"])
            corr_t += 1
            if m["marcel_corr"] > m["persistence_corr"]:
                corr_w += 1
    per_stat = {st: round(sum(v) / len(v), 3) for st, v in by_stat.items()}
    return per_stat, round(corr_w / corr_t, 3) if corr_t else 0.0


def main():
    for yr in HIT_SEASONS:
        _require(DATA / "historical" / f"hitting_{yr}.json")
        _require(DATA / "historical" / f"hitting_{yr - 1}.json")
    for yr in PIT_SEASONS:
        _require(DATA / "pitching" / f"pitching_{yr}.json")
        _require(DATA / "pitching" / f"pitching_{yr - 1}.json")
    _require(IDENTITY)

    identities = json.loads(IDENTITY.read_text(encoding="utf-8"))
    alphas = _shipped_alphas()

    # --- Hitting: de-noised candidate vs classic Marcel ---
    classic = MarcelParams()
    candidate = MarcelParams(alpha_contact=alphas["alpha_contact"], alpha_power=alphas["alpha_power"])
    cand_run = rolling_origin(HIT_SEASONS, DATA, candidate, identities)
    clsc_run = rolling_origin(HIT_SEASONS, DATA, classic, identities)
    vc = vs_classic(cand_run["seasons"], clsc_run["seasons"])
    hit_per_stat = _per_stat_vs_classic(cand_run["seasons"], clsc_run["seasons"])  # vs classic
    hit_corr = round(vc["corr_win_rate"], 3)
    hit_sample = sum(s["eval_n"] for s in cand_run["seasons"])

    # --- Pitching: role-routed Marcel vs persistence (skill stats) ---
    pit_run = rolling_origin_pitching(PIT_SEASONS, DATA, PitcherMarcelParams())
    pit_per_stat, pit_corr = _agg(pit_run["seasons"], skill_only=True)
    pit_sample = sum(s["eval_n"] for s in pit_run["seasons"])

    artifact = {
        "as_of": "2026-06",
        "version": "ValuCast H+P v1",
        "hitting": {
            "baseline": "classic Marcel",
            "aggregate_mae_ratio": round(vc["mean_ratio_vs_classic"], 3),
            "per_stat_mae_ratio": hit_per_stat,
            "concentrated_in": ["AVG", "OBP", "SLG", "OPS"],
            "seasons": HIT_SEASONS,
            "eligibility": "qualified hitters (>= MIN_EVAL_PA actual PA, projectable, has prior season)",
            "sample_size": hit_sample,
            "correlation_win_rate": hit_corr,
            "denoise_alphas": alphas,
        },
        "pitching": {
            "baseline": "persistence",
            "aggregate_mae_ratio": round(pit_run["mean_skill_mae_ratio"], 3),
            "per_stat_mae_ratio": pit_per_stat,
            "stats": list(PITCHER_HEADLINE_SKILL),
            "neutral_stats": ["IP", "K"],
            "seasons": PIT_SEASONS,
            "eligibility": "qualified pitchers (role-specific IP floor, projectable, has prior season)",
            "sample_size": pit_sample,
            "correlation_win_rate": pit_corr,
        },
        "not_shipped": [
            {"name": "reliability-weighted regression", "verdict": "tie"},
            {"name": "in-house expected-stat model (own xBA)", "verdict": "shortfall"},
        ],
    }

    out = ROOT / "data" / "validation" / "methodology_scorecard.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print("HITTING vs classic:", artifact["hitting"]["aggregate_mae_ratio"],
          "| per-stat:", hit_per_stat, "| n:", hit_sample, "| corr_win:", hit_corr)
    print("PITCHING vs persistence (skill):", artifact["pitching"]["aggregate_mae_ratio"],
          "| per-stat:", pit_per_stat, "| n:", pit_sample, "| corr_win:", pit_corr)
    print("wrote", out)


if __name__ == "__main__":
    main()
