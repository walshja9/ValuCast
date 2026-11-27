"""Reproducible sensitivity scorecard for the Prospect Rank model.

The methodology page publishes "if we change one tuned constant, how far does
the board move?" numbers. Those numbers MUST be reproducible from a genuinely
executed experiment (brand ethos: signal, not reputation) -- so this script
re-runs the REAL board build against the REAL committed artifacts, perturbing
one live constant at a time, and writes the measured movements to
data/validation/sensitivity_scorecard.json. The /methodology route renders the
page from that artifact, so the published figures always match a re-runnable
computation against the current board -- not hand-transcribed prose.

Two of the four levers (outcome-vs-impact weight, thin-sample penalty) act at
rank time on already-scored players, so perturbing them only re-runs
build_prospect_rank_v1. The other two (sample regression, stale-line pull) act
at scoring time, so perturbing them re-runs score_current on the committed
trained models (no retrain -- the coefficients are unchanged) and then re-ranks.

Run: python -m scripts.build_sensitivity_scorecard
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects import model as model_mod
from prospects import rank_v1 as rank_mod
from prospects.rank_v1 import identity_key, load_milb_history_index

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "validation" / "sensitivity_scorecard.json"

# Movement thresholds we report on, matching the methodology page's language.
BIG_MOVE = 25
NOTABLE_MOVE = 10
TOP_BAND = 100


def _load_inputs() -> dict:
    """Loads exactly what run_prospect_rank_v1 loads, once, as raw JSON."""
    read = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    return {
        "universe": read(rank_mod.PROSPECT_UNIVERSE_PATH),
        "layer": read(rank_mod.DYNASTY_LAYER_PATH),
        "model": read(rank_mod.PROSPECT_MODEL_PATH),
        "input_contract": read(rank_mod.INPUT_CONTRACT_PATH),
        "availability": read(rank_mod.AVAILABILITY_PATH)
        if rank_mod.AVAILABILITY_PATH and Path(rank_mod.AVAILABILITY_PATH).exists()
        else None,
        "roster": read(rank_mod.MLB_ROSTER_STATUS_PATH)
        if rank_mod.MLB_ROSTER_STATUS_PATH and Path(rank_mod.MLB_ROSTER_STATUS_PATH).exists()
        else None,
        "milb": load_milb_history_index(),
        # The model's own validated input contract, used to re-score current players.
        "score_contract": model_mod.load_input_contract(),
    }


def _rank_board(inputs: dict, prospect_model: dict) -> dict[tuple, int]:
    """Runs the real board build and returns {identity_key: rank}. Deep-copies
    the mutable artifacts so repeated builds never accumulate normalization state."""
    payload = rank_mod.build_prospect_rank_v1(
        copy.deepcopy(inputs["universe"]),
        copy.deepcopy(inputs["layer"]),
        copy.deepcopy(prospect_model),
        copy.deepcopy(inputs["input_contract"]),
        prospect_availability=copy.deepcopy(inputs["availability"]),
        milb_history_by_key=inputs["milb"],
        mlb_roster_status=copy.deepcopy(inputs["roster"]),
        require_mlb_roster_status=True,
    )
    board = payload.get("board") or []
    ranks = {}
    for row in board:
        key = identity_key(row.get("mlbam_id"), row.get("role"))
        if key is not None and row.get("rank") is not None:
            ranks[key] = int(row["rank"])
    if not ranks:
        raise RuntimeError("Board build produced no ranked rows")
    return ranks


def _rescored_model(inputs: dict, base_model: dict) -> dict:
    """Re-scores current players on the committed trained models (constants are
    read live inside score_current, so patch them BEFORE calling this) and
    returns a model artifact with a fresh `ranked` list."""
    role_models = base_model["roles"]
    impact_models = base_model["impact_roles"]
    ranked = model_mod.score_current(inputs["score_contract"], role_models, impact_models)
    return {**base_model, "ranked": ranked}


def _measure(baseline: dict[tuple, int], variant: dict[tuple, int]) -> dict:
    """Movement of every player present in BOTH boards. Added/dropped players are
    counted separately rather than treated as an infinite move."""
    common = [k for k in baseline if k in variant]
    moves = [(k, variant[k] - baseline[k]) for k in common]
    abs_moves = [abs(d) for _, d in moves]
    big = [(k, d) for k, d in moves if abs(d) >= BIG_MOVE]
    top_band_big = sum(
        1 for k, d in moves if baseline[k] <= TOP_BAND and abs(d) >= BIG_MOVE
    )
    big_down = sum(1 for _, d in big if d > 0)   # larger rank number == worse == "down"
    big_up = sum(1 for _, d in big if d < 0)
    big_pitchers = sum(1 for k, _ in big if k[1] == "pitcher")
    big_hitters = sum(1 for k, _ in big if k[1] == "hitter")
    return {
        "common_players": len(common),
        "added": sum(1 for k in variant if k not in baseline),
        "dropped": sum(1 for k in baseline if k not in variant),
        "moved_25plus": len(big),
        "moved_10plus": sum(1 for d in abs_moves if d >= NOTABLE_MOVE),
        "avg_abs_move": round(sum(abs_moves) / len(abs_moves), 1) if abs_moves else 0.0,
        "max_move": max(abs_moves) if abs_moves else 0,
        "top_100_moved_25plus": top_band_big,
        "big_move_direction": {"up": big_up, "down": big_down},
        "big_move_role": {"hitter": big_hitters, "pitcher": big_pitchers},
    }


def _with_patched(target, attr, value, fn):
    """Set target.attr = value, run fn(), always restore. For dict constants pass
    the whole replacement dict; the original object is restored verbatim."""
    original = getattr(target, attr)
    try:
        setattr(target, attr, value)
        return fn()
    finally:
        setattr(target, attr, original)


def build_sensitivity_scorecard(*, generated_at: str | None = None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    inputs = _load_inputs()
    base_model = inputs["model"]

    baseline = _rank_board(inputs, base_model)
    board_size = len(baseline)

    levers = []

    # 1) Outcome-vs-impact weighting (rank-time). 0.58/0.42 -> 0.50/0.50.
    def outcome_variant():
        new_weights = {"expected_outcome_score": 0.50, "expected_category_impact_score": 0.50}
        ranks = _with_patched(
            rank_mod, "MODEL_COMPONENT_WEIGHTS", new_weights,
            lambda: _rank_board(inputs, base_model),
        )
        return _measure(baseline, ranks)

    levers.append({
        "key": "outcome_vs_impact",
        "label": "Outcome-vs-impact weighting",
        "plain": "how much a prospect's odds of reaching the majors matter vs. his fantasy value once there",
        "live_value": "0.58 / 0.42",
        "variants": [{"value": "0.50 / 0.50", **outcome_variant()}],
    })

    # 2) Thin-sample confidence penalty (rank-time). 28 -> 20 (looser) / 35 (tighter).
    thin_variants = []
    for value, tag in ((20.0, "20 (looser)"), (35.0, "35 (tighter)")):
        ranks = _with_patched(
            rank_mod, "THIN_SAMPLE_CONFIDENCE_PENALTY_MAX", value,
            lambda: _rank_board(inputs, base_model),
        )
        thin_variants.append({"value": tag, **_measure(baseline, ranks)})
    levers.append({
        "key": "thin_sample_penalty",
        "label": "Thin-sample confidence penalty",
        "plain": "how far an unproven hot streak should sort behind a proven line",
        "live_value": "28",
        "variants": thin_variants,
    })

    # 3) Sample regression strength (score-time, hitter). 200 -> 150 / 300.
    regression_variants = []
    for value, tag in ((150.0, "150 (trust thin samples more)"), (300.0, "300 (regress harder)")):
        new_reg = {**model_mod.SAMPLE_REGRESSION, "hitter": value}
        ranks = _with_patched(
            model_mod, "SAMPLE_REGRESSION", new_reg,
            lambda: _rank_board(inputs, _rescored_model(inputs, base_model)),
        )
        regression_variants.append({"value": tag, **_measure(baseline, ranks)})
    levers.append({
        "key": "sample_regression",
        "label": "Sample regression strength",
        "plain": "how many PA/IP before a hot line is trusted",
        "live_value": "200",
        "variants": regression_variants,
    })

    # 4) Stale-line pull weight (score-time). 0.40/0.60 -> 0.50/0.75.
    def stale_variant():
        def run():
            return _with_patched(
                model_mod, "STALE_PULL_CAP", 0.75,
                lambda: _rank_board(inputs, _rescored_model(inputs, base_model)),
            )
        ranks = _with_patched(model_mod, "STALE_PULL_FLOOR", 0.50, run)
        return _measure(baseline, ranks)

    levers.append({
        "key": "stale_line_pull",
        "label": "Stale-line pull weight",
        "plain": "how hard a bad current-season line overrides an inflated prior year",
        "live_value": "0.40 / 0.60",
        "variants": [{"value": "0.50 / 0.75", **stale_variant()}],
    })

    return {
        "artifact": "valucast_sensitivity_scorecard",
        "generated_at": generated_at,
        "board_size": board_size,
        "big_move_spots": BIG_MOVE,
        "notable_move_spots": NOTABLE_MOVE,
        "top_band": TOP_BAND,
        "method": (
            "Each lever is perturbed one at a time; the full board is re-scored and "
            "re-ranked against the same committed inputs, and movements are measured "
            "against an in-process baseline build. A live re-scoring of the real model, "
            "not a simulation."
        ),
        "source_policy": {"feeds_live_valucast_rank": False, "display_only": True},
        "levers": levers,
    }


def run(*, artifact_path: Path = ARTIFACT_PATH, generated_at: str | None = None) -> dict:
    payload = build_sensitivity_scorecard(generated_at=generated_at)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return payload


if __name__ == "__main__":
    result = run()
    print(f"board_size={result['board_size']}")
    for lever in result["levers"]:
        print(f"\n{lever['label']} (live {lever['live_value']}):")
        for v in lever["variants"]:
            print(
                f"  {v['value']:32s} 25+:{v['moved_25plus']:>4}  10+:{v['moved_10plus']:>4}"
                f"  avg:{v['avg_abs_move']:>5}  top100_25+:{v['top_100_moved_25plus']:>3}"
                f"  dir(u/d):{v['big_move_direction']['up']}/{v['big_move_direction']['down']}"
                f"  role(h/p):{v['big_move_role']['hitter']}/{v['big_move_role']['pitcher']}"
            )
