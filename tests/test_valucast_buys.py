"""Tests for ValuCast-owned prospect buy signals."""
from copy import deepcopy

from prospects.buys import build_buy_signals, buy_window_score
from scripts.validate_valucast_buys import validate_payload


def _row(
    mlbam_id,
    name,
    rank,
    score,
    age=20,
    level="AA",
    source="prospect_model_v0_6",
    confidence="medium",
):
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        "role": "hitter",
        "positions": ["SS"],
        "mlb_team": "BOS",
        "age": age,
        "level": level,
        "eta": 2027,
        "rank": rank,
        "score": score,
        "score_source": source,
        "confidence": confidence,
        "components": {
            "sample_reliability": 60.0,
            "model_score": score,
            "universal_outcome_index": 45.0,
        },
        "drivers": ["ops +0.10"],
        "context_only": {
            "dd_dynasty_rank": 1,
            "dd_dynasty_value": 99.0,
            "source_ranks": {"pipeline": 1, "hkb": 1},
        },
    }


def _rank_payload(rows=None):
    return {
        "status": "candidate_shadow",
        "rank_version": "0.1.0",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "ranked_count": len(rows or []),
        "board": rows
        or [
            _row(1, "Window Sweet Spot", 80, 58.0, age=20, level="AA"),
            _row(2, "Obvious Elite", 4, 60.0, age=19, level="AA"),
            _row(3, "Older Low Signal", 500, 25.0, age=24, level="AAA"),
        ],
    }


def _history():
    return [
        {
            "date": "2026-06-12",
            "board": [
                {"mlbam_id": 1, "role": "hitter", "score": 53.0},
                {"mlbam_id": 2, "role": "hitter", "score": 60.0},
            ],
        }
    ]


def test_buy_window_curve_favors_sweet_spot_not_obvious_elite():
    assert buy_window_score(4) < buy_window_score(80)
    assert buy_window_score(80) == 1.0
    assert buy_window_score(500) < buy_window_score(80)


def test_build_buy_signals_is_shadow_only_and_valucast_owned():
    payload = build_buy_signals(_rank_payload(), _history())

    assert payload["status"] == "shadow_only"
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["source_policy"]["dd_context_used"] is False
    assert payload["source_policy"]["public_source_ranks_used"] is False
    assert payload["validation"]["row_count"] == 3
    assert payload["validation"]["ready_for_live_consumers"] is False
    assert payload["promotion"]["feeds_live_buys"] is False
    assert validate_payload(payload) == []


def test_context_only_and_public_ranks_do_not_change_scores():
    base = _rank_payload()
    changed = deepcopy(base)
    changed["board"][0]["context_only"] = {
        "dd_dynasty_rank": 999,
        "dd_dynasty_value": 1.0,
        "source_ranks": {"pipeline": 999, "hkb": 999},
    }

    original = build_buy_signals(base, _history())
    mutated = build_buy_signals(changed, _history())

    assert original["board"][0]["score"] == mutated["board"][0]["score"]
    assert original["board"][0]["terms"] == mutated["board"][0]["terms"]


def test_history_drives_momentum_from_valucast_scores():
    payload = build_buy_signals(_rank_payload(), _history())
    row = next(item for item in payload["board"] if item["mlbam_id"] == 1)

    assert row["terms"]["momentum"] > 0.4
    assert row["score_history"] == [("2026-06-12", 53.0), ("2026-06-13", 58.0)]


def test_excludes_mlb_level_and_duplicate_identities():
    rows = [
        _row(1, "Kept", 80, 58.0),
        _row(2, "MLB Debut", 20, 60.0, level="MLB"),
        _row(1, "Duplicate", 81, 57.0),
    ]
    payload = build_buy_signals(_rank_payload(rows), [])

    assert payload["validation"]["row_count"] == 1
    assert payload["validation"]["duplicate_identity_count"] == 1
    assert payload["board"][0]["name"] == "Kept"


def test_validator_rejects_dd_usage_flag():
    payload = build_buy_signals(_rank_payload(), _history())
    payload["source_policy"]["dd_values_used"] = True

    assert "source_policy.dd_values_used must be false" in validate_payload(payload)
