"""Tests for ValuCast-owned prospect buy signals."""
import json
from copy import deepcopy
from types import SimpleNamespace

from prospects.buys import build_buy_signals, buy_window_score
from scripts.review_valucast_buys import build_review
from web import buy_score
from web.valucast_buy_store import (
    ValuCastBuyStore,
    validate_valucast_buy_payload,
)


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
    assert payload["validation"]["buy_review_ready"] is False
    assert payload["promotion"]["feeds_live_buys"] is False
    assert validate_valucast_buy_payload(payload) == []


def test_build_buy_signals_can_be_candidate_ready_after_review():
    review = {"review_status": "candidate_ready"}
    rows = [_row(index, f"Buy {index}", index + 30, 55.0) for index in range(1, 45)]
    history = [
        {
            "date": "2026-06-12",
            "board": [
                {"mlbam_id": index, "role": "hitter", "score": 53.0}
                for index in range(1, 45)
            ],
        }
    ]

    payload = build_buy_signals(
        _rank_payload(rows),
        history,
        promotion_review=review,
    )

    assert payload["validation"]["ready_for_live_consumers"] is True
    assert payload["validation"]["history_limited_rate"] <= 0.5
    assert payload["promotion"]["live_consumer"] == "candidate_ready"
    assert payload["promotion"]["feeds_live_buys"] is True


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


def test_raw_fallback_rows_are_excluded_from_promotable_buy_board():
    rows = [
        _row(1, "Model Buy", 80, 58.0),
        _row(2, "Pedigree Buy", 90, 48.0, source="prospect_pedigree_v0_7"),
        _row(3, "Raw Fallback", 85, 45.0, source="universal_fallback"),
    ]

    payload = build_buy_signals(_rank_payload(rows), _history())

    assert [row["name"] for row in payload["board"]] == ["Model Buy", "Pedigree Buy"]
    assert payload["validation"]["eligible_count"] == 2
    assert payload["validation"]["excluded_score_source_count"] == 1
    assert payload["validation"]["top_board_quality"]["raw_fallback_count"] == 0


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

    assert "source_policy.dd_values_used must be false" in validate_valucast_buy_payload(payload)


def test_valucast_buy_store_loads_shadow_artifact(tmp_path):
    payload = build_buy_signals(_rank_payload(), _history())
    path = tmp_path / "buys.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    store = ValuCastBuyStore(path)

    assert store.is_available is True
    assert store.ready_for_live_consumers is False
    assert store.generated_at == payload["generated_at"]
    assert len(store.get_all()) == 3


def test_build_valucast_board_formats_existing_template_shape():
    payload = build_buy_signals(_rank_payload(), _history())
    board = buy_score.build_valucast_board(payload["board"], n=1)

    assert len(board) == 1
    assert board[0]["id"].startswith("vc_prospect_")
    assert board[0]["headshot_url"].endswith("/headshot/67/current")
    assert "momentum" in board[0]["terms"]
    assert "valucast_terms" in board[0]


def test_buy_selector_keeps_dd_until_valucast_ready_and_snapshot_active():
    from app import _select_buy_source

    dd = SimpleNamespace(is_available=True)
    blocked = SimpleNamespace(is_available=True, ready_for_live_consumers=False)
    ready = SimpleNamespace(is_available=True, ready_for_live_consumers=True)

    selected, source = _select_buy_source(
        dd,
        blocked,
        use_valucast_buys=True,
        public_snapshot_active=True,
    )
    assert selected is dd
    assert source == "dd_feed"

    selected, source = _select_buy_source(
        dd,
        ready,
        use_valucast_buys=True,
        public_snapshot_active=False,
    )
    assert selected is dd
    assert source == "dd_feed"

    selected, source = _select_buy_source(
        dd,
        ready,
        use_valucast_buys=True,
        public_snapshot_active=True,
    )
    assert selected is ready
    assert source == "valucast_buys"


def test_review_artifact_reports_low_overlap_but_blocks_only_history_and_approval():
    payload = build_buy_signals(_rank_payload(), _history())
    valucast = buy_score.build_valucast_board(payload["board"])
    dd = [
        {"rank": 1, "name": "Different One", "score": 80.0, "level": "AA", "age": 22, "reason": "Breakout"},
        {"rank": 2, "name": "Different Two", "score": 79.0, "level": "A+", "age": 21, "reason": "Rank gap"},
    ]
    store = SimpleNamespace(validation={"history_limited_count": 40, "row_count": 40})

    review = build_review(dd, valucast, store)

    assert review["review_status"] == "blocked"
    assert review["metrics"]["top40_name_overlap_count"] == 0
    assert review["metrics"]["dd_overlap_context_only"] is True
    assert review["metrics"]["history_limited_rate"] == 1.0
    assert not any("overlap" in blocker for blocker in review["blockers"])
    assert any("history-limited" in blocker for blocker in review["blockers"])
    assert any("Human review" in blocker for blocker in review["blockers"])


def test_review_artifact_can_be_candidate_ready_with_manual_approval():
    rows = [_row(index, f"Match {index}", index, 55.0) for index in range(1, 7)]
    payload = build_buy_signals(_rank_payload(rows), _history())
    valucast = buy_score.build_valucast_board(payload["board"])
    dd = [
        {
            "rank": index,
            "name": f"Match {index}",
            "score": 80.0 - index,
            "level": "AA",
            "age": 21,
            "reason": "Review match",
        }
        for index in range(1, 7)
    ]
    store = SimpleNamespace(validation={"history_limited_count": 0, "row_count": 40})

    review = build_review(dd, valucast, store, manual_approval=True)

    assert review["review_status"] == "candidate_ready"
    assert review["blockers"] == []
    assert review["source_policy"]["manual_approval_recorded"] is True
    assert review["source_policy"]["approval_kind"] == "human_review"
    assert review["promotion_decision"]["neutral_momentum_launch_approved"] is False


def test_review_manual_approval_can_launch_with_neutral_momentum_history():
    payload = build_buy_signals(_rank_payload(), _history())
    valucast = buy_score.build_valucast_board(payload["board"])
    store = SimpleNamespace(validation={"history_limited_count": 40, "row_count": 40})

    review = build_review([], valucast, store, manual_approval=True)

    assert review["review_status"] == "candidate_ready"
    assert review["source_policy"]["history_launch_approved"] is True
    assert review["source_policy"]["approval_kind"] == "neutral_momentum_launch"
    assert review["promotion_decision"]["neutral_momentum_launch_approved"] is True
    assert review["promotion_decision"]["requires_route_gate"] is True
    assert review["blockers"] == []


def test_ready_buy_payload_can_use_reviewed_neutral_momentum_launch():
    review = {
        "review_status": "candidate_ready",
        "source_policy": {"history_launch_approved": True},
    }
    payload = build_buy_signals(
        _rank_payload([_row(index, f"Buy {index}", index + 30, 55.0) for index in range(1, 45)]),
        history_payloads=[],
        promotion_review=review,
    )

    assert payload["validation"]["ready_for_live_consumers"] is True
    assert payload["validation"]["history_ready"] is False
    assert payload["validation"]["history_launch_approved"] is True
    assert validate_valucast_buy_payload(payload) == []


def test_ready_buy_payload_rejects_top_board_raw_fallback():
    review = {"review_status": "candidate_ready"}
    payload = build_buy_signals(_rank_payload(), _history(), promotion_review=review)
    payload["validation"]["ready_for_live_consumers"] = True
    payload["validation"]["top_board_quality"]["raw_fallback_count"] = 1

    assert (
        "ready buy signals must not include raw fallback rows in the top board"
        in validate_valucast_buy_payload(payload)
    )
