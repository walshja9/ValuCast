"""Tests for ValuCast-owned prospect buy signals."""
import json
from copy import deepcopy
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from prospects.buys import (
    PROSPECT_BUYS_EPOCH_DATE,
    build_buy_signals,
    buy_window_score,
)
from scripts.review_valucast_buys import _load_prior_approval, build_review
from web import buy_score
from web.valucast_buy_store import (
    ValuCastBuyStore,
    validate_valucast_buy_payload,
)

# Epoch-relative fixture dates: buys momentum floors history at the scoring
# epoch (_score_history drops any point before PROSPECT_BUYS_EPOCH_DATE), so
# fixtures must sit on/after the epoch. Deriving offsets from the epoch keeps
# these tests correct across future epoch bumps. _d(0) == the epoch floor.
_EPOCH = date.fromisoformat(PROSPECT_BUYS_EPOCH_DATE)


def _d(offset):
    return (_EPOCH + timedelta(days=offset)).isoformat()


def _row(
    mlbam_id,
    name,
    rank,
    score,
    age=20,
    level="AA",
    source="prospect_model_v0_6",
    confidence="medium",
    role="hitter",
    source_ranks=None,
):
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        "role": role,
        "positions": ["SP"] if role == "pitcher" else ["SS"],
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
            "availability": {
                "status": "available",
                "risk_level": "clear",
                "risk_discount": 0.0,
                "level": level,
            },
        },
        "drivers": ["ops +0.10"],
        "context_only": {
            "dd_dynasty_rank": 1,
            "dd_dynasty_value": 99.0,
            "source_ranks": source_ranks
            if source_ranks is not None
            else {"pipeline": 1, "hkb": 1, "sts": 1},
        },
    }


def _rank_payload(rows=None):
    return {
        "status": "candidate_shadow",
        "rank_version": "0.1.0",
        "generated_at": f"{_d(1)}T12:00:00+00:00",
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
            "date": _d(0),
            "board": [
                {"mlbam_id": 1, "role": "hitter", "score": 53.0},
                {"mlbam_id": 2, "role": "hitter", "score": 60.0},
            ],
        }
    ]


def _mlb_roster_status(active_ids=None, ready=True):
    active_ids = active_ids or [999999]
    return {
        "artifact": "valucast_mlb_roster_status",
        "contract_version": "0.1.0",
        "validation": {"ready_for_public_snapshot": ready},
        "profiles": [
            {"mlbam_id": mlbam_id, "active_mlb_roster": True}
            for mlbam_id in active_ids
        ],
    }


def _qualified_buy_review(history_launch=False):
    store = SimpleNamespace(validation={"history_limited_count": 40 if history_launch else 0, "row_count": 40})
    return build_review([], [], store, manual_approval=True, generated_at=_rank_payload()["generated_at"])


def test_buy_window_curve_favors_sweet_spot_not_obvious_elite():
    assert buy_window_score(4) < buy_window_score(80)
    assert buy_window_score(80) == 1.0
    assert buy_window_score(500) < buy_window_score(80)


def test_build_buy_signals_is_shadow_only_and_valucast_owned():
    payload = build_buy_signals(_rank_payload(), _history())

    assert payload["status"] == "shadow_only"
    assert payload["signal_version"] == "1.0.0"
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["source_policy"]["dd_context_used"] is False
    assert payload["source_policy"]["public_source_ranks_used"] is True
    assert payload["validation"]["row_count"] == 3
    assert payload["validation"]["ready_for_live_consumers"] is False
    assert payload["validation"]["buy_review_ready"] is False
    assert payload["validation"]["mlb_roster_status_required"] is True
    assert payload["score_contract"]["contract_status"] == "blocked"
    assert payload["release_contract"]["release_status"] == "blocked"
    assert payload["release_contract"]["frozen_score_contract"] is False
    assert payload["promotion"]["feeds_live_buys"] is False
    assert validate_valucast_buy_payload(payload) == []


def test_buy_board_requires_three_public_board_ranks_and_reports_count():
    rows = [
        _row(
            1,
            "Corroborated Buy",
            80,
            58.0,
            source_ranks={
                "pipeline": 120,
                "hkb": 180,
                "sts": 220,
                "milb_perf": 1,
                "cfr": 2,
            },
        ),
        _row(
            2,
            "Thin Buy",
            81,
            57.0,
            source_ranks={
                "pipeline": 120,
                "hkb": 180,
                "sts": 800,
                "milb_breakout": 1,
            },
        ),
    ]

    payload = build_buy_signals(_rank_payload(rows), _history())

    assert [row["name"] for row in payload["board"]] == ["Corroborated Buy"]
    assert payload["board"][0]["board_count"] == 3
    assert payload["validation"]["row_count"] == 1


def test_buy_promotion_blocks_pitcher_heavy_corroborated_top25():
    review = _qualified_buy_review(history_launch=True)
    rows = [
        _row(
            index,
            f"Buy {index}",
            index + 30,
            55.0,
            role="pitcher" if index <= 11 else "hitter",
        )
        for index in range(1, 45)
    ]

    payload = build_buy_signals(
        _rank_payload(rows),
        history_payloads=[],
        promotion_review=review,
        mlb_roster_status=_mlb_roster_status(),
        require_mlb_roster_status=True,
    )

    assert payload["validation"]["ready_for_live_consumers"] is False
    assert payload["validation"]["top_board_quality"]["top25_pitcher_count"] == 11
    assert payload["validation"]["top_board_quality"]["top25_pitcher_rate"] == 0.44
    assert payload["validation"]["top_board_quality"]["max_top25_pitcher_rate"] == 0.40
    assert any(
        "pitcher-heavy" in blocker for blocker in payload["validation"]["blockers"]
    )


def test_build_buy_signals_can_be_candidate_ready_after_review():
    review = _qualified_buy_review()
    rows = [_row(index, f"Buy {index}", index + 30, 55.0) for index in range(1, 45)]
    history = [
        {
            "date": _d(0),
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
        mlb_roster_status=_mlb_roster_status(),
        require_mlb_roster_status=True,
    )

    assert payload["validation"]["ready_for_live_consumers"] is True
    assert payload["validation"]["history_limited_rate"] <= 0.5
    assert payload["score_contract"]["contract_status"] == "v1_locked"
    assert payload["release_contract"]["release"] == "valucast_prospect_buys_v1"
    assert payload["release_contract"]["release_status"] == "locked"
    assert payload["release_contract"]["frozen_score_contract"] is True
    assert payload["promotion"]["live_consumer"] == "candidate_ready"
    assert payload["promotion"]["feeds_live_buys"] is True
    assert payload["promotion"]["next_allowed_step"] == (
        "monitor_forward_results_and_recalibrate_by_bucket"
    )
    assert validate_valucast_buy_payload(payload) == []


def test_context_only_and_public_ranks_do_not_change_scores():
    base = _rank_payload()
    changed = deepcopy(base)
    changed["board"][0]["context_only"] = {
        "dd_dynasty_rank": 999,
        "dd_dynasty_value": 1.0,
        "source_ranks": {"pipeline": 500, "hkb": 550, "sts": 590},
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
    assert row["score_history"] == [(_d(0), 53.0), (_d(1), 58.0)]


def test_neutral_momentum_does_not_become_the_headline_reason():
    rows = [_row(9, "Neutral Momentum", 700, 20.0, age=24, level="AAA", confidence="low")]
    rows[0]["components"]["sample_reliability"] = 0.0

    payload = build_buy_signals(_rank_payload(rows), [])
    row = payload["board"][0]

    assert row["terms"]["momentum"] == 0.4
    assert row["reason"] != "ValuCast score momentum"


def test_buy_signals_carry_availability_disclosure():
    rows = [_row(1, "Injury Buy", 80, 58.0)]
    rows[0]["components"]["availability"] = {
        "status": "injured",
        "risk_level": "high",
        "risk_discount": 0.1,
        "level": "AA",
    }

    payload = build_buy_signals(_rank_payload(rows), _history())
    row = payload["board"][0]

    assert row["availability_status"] == "injured"
    assert row["availability_risk_level"] == "high"
    assert row["availability_risk_discount"] == 0.1
    assert row["availability_level"] == "AA"
    assert validate_valucast_buy_payload(payload) == []


def test_valucast_buy_graphic_surfaces_availability_risk():
    rows = [_row(1, "Injury Buy", 80, 58.0)]
    rows[0]["components"]["availability"] = {
        "status": "injured",
        "risk_level": "high",
        "risk_discount": 0.1,
        "level": "AA",
    }

    payload = build_buy_signals(_rank_payload(rows), _history())
    board = buy_score.build_valucast_board(payload["board"], n=1)

    assert board[0]["reason"] == "Injury risk priced"
    assert board[0]["label"] == "Injury risk priced"


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


def test_excludes_active_mlb_roster_identities_from_buy_board():
    rows = [
        _row(1, "Kept", 80, 58.0),
        _row(2, "Active MLB Graduate", 20, 60.0, level="AAA"),
    ]

    payload = build_buy_signals(
        _rank_payload(rows),
        [],
        mlb_roster_status=_mlb_roster_status([2]),
        require_mlb_roster_status=True,
    )

    assert payload["validation"]["active_mlb_roster_excluded_count"] == 1
    assert payload["validation"]["active_mlb_roster_overlap_count"] == 0
    assert payload["validation"]["mlb_roster_status_ready"] is True
    assert payload["validation"]["row_count"] == 1
    assert payload["board"][0]["name"] == "Kept"


def test_validator_rejects_dd_usage_flag():
    payload = build_buy_signals(_rank_payload(), _history())
    payload["source_policy"]["dd_values_used"] = True

    assert "source_policy.dd_values_used must be false" in validate_valucast_buy_payload(payload)


def test_validator_rejects_ready_board_with_active_mlb_roster_overlap():
    review = _qualified_buy_review()
    payload = build_buy_signals(
        _rank_payload([_row(index, f"Buy {index}", index + 30, 55.0) for index in range(1, 45)]),
        _history(),
        promotion_review=review,
        mlb_roster_status=_mlb_roster_status(),
        require_mlb_roster_status=True,
    )
    payload["validation"]["ready_for_live_consumers"] = True
    payload["validation"]["active_mlb_roster_overlap_count"] = 1

    assert (
        "validation reports active MLB roster overlap"
        in validate_valucast_buy_payload(payload)
    )


def test_validator_rejects_ready_v1_payload_without_locked_release_contract():
    review = _qualified_buy_review()
    rows = [_row(index, f"Buy {index}", index + 30, 55.0) for index in range(1, 45)]
    history = [
        {
            "date": _d(0),
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
        mlb_roster_status=_mlb_roster_status(),
        require_mlb_roster_status=True,
    )
    payload["release_contract"] = {
        "release": "draft_buy_signal",
        "release_status": "blocked",
        "frozen_score_contract": False,
    }

    problems = validate_valucast_buy_payload(payload)

    assert "ready v1 buy signals must declare the locked release" in problems
    assert "ready v1 buy signals must have release_status=locked" in problems
    assert "ready v1 buy signals must freeze the score contract" in problems


def test_validator_rejects_ready_legacy_signal_version_even_with_ready_flags():
    review = _qualified_buy_review()
    rows = [_row(index, f"Buy {index}", index + 30, 55.0) for index in range(1, 45)]
    history = [
        {
            "date": _d(0),
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
        mlb_roster_status=_mlb_roster_status(),
        require_mlb_roster_status=True,
    )
    payload["signal_version"] = "0.2.2"

    problems = validate_valucast_buy_payload(payload)

    assert "ready buy signals must use locked v1 signal_version" in problems


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
    assert board[0]["headshot_url"].endswith("/headshot/milb/current")
    assert "momentum" in board[0]["terms"]
    assert "valucast_terms" in board[0]
    assert board[0]["value_history"] == ()


def test_build_valucast_board_exposes_spark_history_after_real_history_accumulates():
    payload = build_buy_signals(_rank_payload(), _history())
    payload["board"][0]["score_history"] = [
        ("2026-06-11", 52.0),
        ("2026-06-12", 53.0),
        ("2026-06-13", 55.0),
        ("2026-06-14", 58.0),
    ]

    board = buy_score.build_valucast_board(payload["board"], n=1)

    assert board[0]["value_history"] == payload["board"][0]["score_history"]


def test_build_valucast_board_window_days_widens_displayed_curve():
    # Plan 013: the /buys window pills were inert — build_valucast_board never
    # passed window_days to clean_tail, capping every curve at 14 days. A wider
    # window must now re-span the displayed history.
    payload = build_buy_signals(_rank_payload(), _history())
    long_history = [
        (f"2026-05-{day:02d}", 50.0 + (day - 24) * 0.1)
        for day in range(24, 32)
    ] + [
        (f"2026-06-{day:02d}", 50.8 + day * 0.1)
        for day in range(1, 17)
    ]
    payload["board"][0]["score_history"] = long_history

    default_board = buy_score.build_valucast_board(payload["board"], n=1)
    wide_board = buy_score.build_valucast_board(
        payload["board"], n=1, window_days=30)

    assert len(wide_board[0]["value_history"]) > len(
        default_board[0]["value_history"])
    assert default_board[0]["value_history"][0][0] == "2026-06-02"
    assert wide_board[0]["value_history"][0][0] == "2026-05-24"


def test_build_valucast_board_spark_history_excludes_epoch_steps():
    # 7/3 review: the sparkline must show the SAME cleaned series the momentum
    # term scores — a 14-pt re-baseline step was rendering as a fake green
    # "UP +15" surge on the public share graphic while momentum read neutral.
    payload = build_buy_signals(_rank_payload(), _history())
    payload["board"][0]["score_history"] = [
        ("2026-06-11", 40.0),
        ("2026-06-12", 41.0),
        ("2026-06-13", 55.0),  # epoch step > STEP_THRESHOLD
        ("2026-06-14", 55.5),
        ("2026-06-15", 56.0),
        ("2026-06-16", 56.5),
    ]

    board = buy_score.build_valucast_board(payload["board"], n=1)

    dates = [d for d, _ in board[0]["value_history"]]
    assert dates == ["2026-06-13", "2026-06-14", "2026-06-15", "2026-06-16"]


def test_buy_selector_serves_valucast_buys_or_unavailable_never_dd(monkeypatch):
    import app as app_module

    blocked = SimpleNamespace(is_available=True, ready_for_live_consumers=False)
    ready = SimpleNamespace(is_available=True, ready_for_live_consumers=True)
    monkeypatch.delenv("VALUCAST_USE_VALUCAST_BUYS", raising=False)
    monkeypatch.setattr(app_module, "AHEAD_OF_THE_CURVE_HOLD", False)
    monkeypatch.setattr(app_module, "dd_store", SimpleNamespace(surface_readiness={"buys": True}))
    _select_buy_source = app_module._select_buy_source

    # Buys not ready -> unavailable, never DD.
    selected, source = _select_buy_source(
        blocked, use_valucast_buys=True, public_snapshot_active=True
    )
    assert source == "unavailable"
    assert selected.is_available is False

    # Dynasty board not on the ValuCast snapshot -> unavailable, never DD.
    selected, source = _select_buy_source(
        ready, use_valucast_buys=True, public_snapshot_active=False
    )
    assert source == "unavailable"

    # Ready + snapshot active -> ValuCast buys.
    selected, source = _select_buy_source(
        ready, use_valucast_buys=True, public_snapshot_active=True
    )
    assert selected is ready
    assert source == "valucast_buys"

    # Default (env unset) + snapshot active -> ValuCast buys.
    selected, source = _select_buy_source(ready, public_snapshot_active=True)
    assert selected is ready
    assert source == "valucast_buys"

    # Rollout disabled -> unavailable, never DD.
    monkeypatch.setenv("VALUCAST_USE_VALUCAST_BUYS", "0")
    selected, source = _select_buy_source(ready, public_snapshot_active=True)
    assert source == "unavailable"
    assert selected.is_available is False

    # Public AOTC hold overrides ready data and keeps the public surface dark.
    monkeypatch.setattr(app_module, "AHEAD_OF_THE_CURVE_HOLD", True)
    selected, source = _select_buy_source(
        ready, use_valucast_buys=True, public_snapshot_active=True
    )
    assert source == "unavailable"
    assert selected.is_available is False


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


def test_review_can_reuse_prior_human_approval_after_buys_are_promoted():
    payload = build_buy_signals(_rank_payload(), _history())
    valucast = buy_score.build_valucast_board(payload["board"])
    store = SimpleNamespace(validation={"history_limited_count": 0, "row_count": 40})
    original = build_review([], valucast, store, manual_approval=True)

    review = build_review([], valucast, store, prior_review=original, generated_at="2026-11-27T00:00:00+00:00")

    assert review["review_status"] == "candidate_ready"
    assert review["source_policy"]["manual_approval_recorded"] is True
    assert review["source_policy"]["prior_approval_reused"] is True
    assert review["source_policy"]["approval_kind"] == "human_review"
    assert review["blockers"] == []
    assert review["approval_receipt"] == original["approval_receipt"]


def _legacy_buy_approval_review():
    return {
        "review_status": "candidate_ready",
        "generated_at": "2026-11-23T00:00:00+00:00",
        "source_policy": {"manual_approval_recorded": True, "history_launch_approved": True},
        "promotion_decision": {"neutral_momentum_launch_approved": True},
    }


def test_review_approval_explicit_input_records_current_scoped_receipt():
    store = SimpleNamespace(validation={"history_limited_count": 0, "row_count": 40})
    review = build_review([], [], store, manual_approval=True, generated_at="2020-01-01T00:00:00+00:00")
    receipt = review["approval_receipt"]

    assert set(receipt) == {"schema_version", "origin", "scope", "approved_at"}
    assert receipt["schema_version"] == "1.0.0"
    assert receipt["origin"] == "explicit_manual_input"
    assert receipt["scope"] == "valucast_owned_buys_promotion_v1"
    assert datetime.fromisoformat(receipt["approved_at"]).tzinfo is not None
    assert receipt["approved_at"] != review["generated_at"]


def test_review_approval_absent_or_nonboolean_manual_input_cannot_authorize():
    store = SimpleNamespace(validation={"history_limited_count": 0, "row_count": 40})
    for manual in (False, None, 1, "1"):
        review = build_review([], [], store, manual_approval=manual)
        assert review["review_status"] == "blocked"
        assert review["approval_receipt"] is None
        assert any("Human review" in blocker for blocker in review["blockers"])


def test_review_approval_legacy_origin_stays_unknown_across_retries():
    store = SimpleNamespace(validation={"history_limited_count": 0, "row_count": 40})
    prior = _legacy_buy_approval_review()
    for _ in range(2):
        review = build_review([], [], store, prior_review=prior)
        assert review["review_status"] == "blocked"
        assert review["approval_receipt"] is None
        assert review["source_policy"]["legacy_approval_origin_unknown"] is True
        assert review["source_policy"]["manual_approval_recorded"] is False
        assert review["source_policy"]["prior_approval_reused"] is False
        assert review["source_policy"]["history_launch_approved"] is False
        assert any("origin" in blocker.lower() for blocker in review["blockers"])
        prior = review


def test_review_approval_explicit_continuation_does_not_relabel_legacy_consent():
    store = SimpleNamespace(validation={"history_limited_count": 0, "row_count": 40})
    legacy = _legacy_buy_approval_review()
    before = deepcopy(legacy)
    review = build_review([], [], store, prior_review=legacy, manual_approval=True)

    assert review["review_status"] == "candidate_ready"
    assert review["source_policy"]["legacy_approval_origin_unknown"] is True
    assert review["source_policy"]["prior_approval_reused"] is False
    assert review["approval_receipt"]["origin"] == "explicit_manual_input"
    assert legacy == before


def test_review_approval_invalid_receipts_never_qualify():
    store = SimpleNamespace(validation={"history_limited_count": 0, "row_count": 40})
    original = build_review([], [], store, manual_approval=True)
    valid = original["approval_receipt"]
    bad_receipts = [None, [], {}, {**valid, "extra": "unsupported"}]
    for field, value in (
        ("schema_version", "2.0.0"), ("origin", "schedule"), ("scope", "different_scope"),
        ("approved_at", "not-a-date"), ("approved_at", "2026-11-26"), ("approved_at", True),
    ):
        bad_receipts.append({**valid, field: value})
    for receipt in bad_receipts:
        prior = {**original, "approval_receipt": receipt}
        review = build_review([], [], store, prior_review=prior)
        assert review["review_status"] == "blocked"
        assert review["source_policy"]["prior_approval_reused"] is False
        assert review["source_policy"]["legacy_approval_origin_unknown"] is True


def test_review_approval_survives_quality_failure_without_bypassing_it():
    ready = SimpleNamespace(validation={"history_limited_count": 0, "row_count": 40})
    limited = SimpleNamespace(validation={"history_limited_count": 40, "row_count": 40})
    original = build_review([], [], ready, manual_approval=True)
    blocked = build_review([], [], limited, prior_review=original)

    assert blocked["review_status"] == "blocked"
    assert blocked["approval_receipt"] == original["approval_receipt"]
    assert blocked["source_policy"]["prior_approval_reused"] is True
    assert any("history-limited" in blocker for blocker in blocked["blockers"])
    recovered = build_review([], [], ready, prior_review=blocked)
    assert recovered["review_status"] == "candidate_ready"
    assert recovered["approval_receipt"] == original["approval_receipt"]


def test_review_approval_neutral_launch_keeps_existing_threshold_and_flag_semantics():
    ready = SimpleNamespace(validation={"history_limited_count": 20, "row_count": 40})
    limited = SimpleNamespace(validation={"history_limited_count": 21, "row_count": 40})
    first = build_review([], [], limited, manual_approval=True)
    reused = build_review([], [], limited, prior_review=first)
    assert reused["review_status"] == "candidate_ready"
    assert reused["source_policy"]["history_launch_approved"] is True
    assert reused["approval_receipt"] == first["approval_receipt"]
    history_ready = build_review([], [], ready, prior_review=reused)
    assert history_ready["review_status"] == "candidate_ready"
    assert history_ready["source_policy"]["history_launch_approved"] is False
    limited_again = build_review([], [], limited, prior_review=history_ready)
    assert limited_again["review_status"] == "blocked"
    assert limited_again["source_policy"]["history_launch_approved"] is False
    assert limited_again["approval_receipt"] == first["approval_receipt"]
    legacy = build_review([], [], limited, prior_review=_legacy_buy_approval_review())
    assert legacy["review_status"] == "blocked"
    assert legacy["promotion_decision"]["neutral_momentum_launch_approved"] is False


def test_review_approval_loader_preserves_context_and_rejects_invalid_json(tmp_path):
    path = tmp_path / "synthetic-review.json"
    legacy = _legacy_buy_approval_review()
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert _load_prior_approval(path) == legacy
    path.write_text("[]", encoding="utf-8")
    assert _load_prior_approval(path) == {}
    path.write_text("{", encoding="utf-8")
    assert _load_prior_approval(path) == {}
    assert _load_prior_approval(tmp_path / "missing-review.json") == {}


def test_review_approval_main_preserves_legacy_retry_and_explicit_continuation(tmp_path):
    from scripts import review_valucast_buys as reviewer

    path = tmp_path / "synthetic-main-review.json"
    path.write_text(json.dumps(_legacy_buy_approval_review()), encoding="utf-8")
    loader = reviewer._load_prior_approval
    writer = reviewer.write_review
    store = SimpleNamespace(is_available=True, generated_at="2026-11-26T00:00:00+00:00",
                            validation={"history_limited_count": 0, "row_count": 40}, get_all=lambda: [])
    with patch.object(reviewer, "ValuCastBuyStore", return_value=store), \
         patch.object(reviewer.buy_score, "build_valucast_board", return_value=[]), \
         patch.object(reviewer, "_load_prior_approval", side_effect=lambda: loader(path)), \
         patch.object(reviewer, "write_review", side_effect=lambda payload: writer(payload, path)), \
         patch.object(reviewer.sys, "argv", ["review_valucast_buys.py"]), \
         patch.dict(reviewer.os.environ, {"VALUCAST_BUYS_REVIEW_APPROVED": "0"}):
        reviewer.main()
        reviewer.main()
        blocked = json.loads(path.read_text(encoding="utf-8"))
        assert blocked["review_status"] == "blocked"
        assert blocked["source_policy"]["legacy_approval_origin_unknown"] is True
        with patch.object(reviewer.sys, "argv", ["review_valucast_buys.py", "--approve-neutral-momentum-launch"]):
            reviewer.main()
        continued = json.loads(path.read_text(encoding="utf-8"))
        assert continued["review_status"] == "candidate_ready"
        assert continued["approval_receipt"]["origin"] == "explicit_manual_input"
        assert continued["source_policy"]["legacy_approval_origin_unknown"] is True


def test_review_approval_consumer_rejects_legacy_without_changing_numbers():
    rows = [_row(index, f"Buy {index}", index + 30, 55.0) for index in range(1, 45)]
    rank = _rank_payload(rows)
    history = [{"date": _d(0), "board": [
        {"mlbam_id": index, "role": "hitter", "score": 53.0} for index in range(1, 45)
    ]}]
    kwargs = {"mlb_roster_status": _mlb_roster_status(), "require_mlb_roster_status": True}
    qualified = build_buy_signals(rank, history, promotion_review=_qualified_buy_review(), **kwargs)
    assert qualified["validation"]["ready_for_live_consumers"] is True
    for status in ("candidate_ready", "approved"):
        legacy = {**_legacy_buy_approval_review(), "generated_at": rank["generated_at"], "review_status": status}
        blocked = build_buy_signals(rank, history, promotion_review=legacy, **kwargs)
        assert blocked["validation"]["ready_for_live_consumers"] is False
        assert blocked["validation"]["buy_review_ready"] is False
        assert blocked["validation"]["history_launch_approved"] is False
        assert blocked["board"] == qualified["board"]
        assert blocked["validation"]["top_board_quality"] == qualified["validation"]["top_board_quality"]


def test_review_approval_consumer_rejects_bad_receipts_and_blocked_neutral_flags():
    rank = _rank_payload([_row(index, f"Buy {index}", index + 30, 55.0) for index in range(1, 45)])
    review = _qualified_buy_review(history_launch=True)
    kwargs = {"mlb_roster_status": _mlb_roster_status(), "require_mlb_roster_status": True}
    qualified = build_buy_signals(rank, [], promotion_review=review, **kwargs)
    assert qualified["validation"]["ready_for_live_consumers"] is True
    assert qualified["validation"]["history_ready"] is False
    assert qualified["validation"]["history_launch_approved"] is True
    for receipt in (None, [], {}, {**review["approval_receipt"], "scope": "other_scope"},
                    {**review["approval_receipt"], "approved_at": "invalid"}):
        blocked = build_buy_signals(rank, [], promotion_review={**review, "approval_receipt": receipt}, **kwargs)
        assert blocked["validation"]["ready_for_live_consumers"] is False
        assert blocked["validation"]["buy_review_ready"] is False
        assert blocked["validation"]["history_launch_approved"] is False
        assert blocked["board"] == qualified["board"]
    blocked = build_buy_signals(rank, [], promotion_review={**review, "review_status": "blocked"}, **kwargs)
    assert blocked["validation"]["history_launch_approved"] is False


def test_review_approval_build_cli_requires_qualified_same_day_review(tmp_path):
    from prospects import buys as buys_module
    from scripts import build_valucast_buys as builder

    rank = _rank_payload([_row(index, f"Buy {index}", index + 30, 55.0) for index in range(1, 45)])
    rank["generated_at"] = "2026-11-26T00:00:00+00:00"
    rank_path = tmp_path / "synthetic-consumer-rank.json"
    review_path = tmp_path / "synthetic-consumer-review.json"
    roster_path = tmp_path / "synthetic-consumer-roster.json"
    output_path = tmp_path / "synthetic-consumer-output.json"
    history_dir = tmp_path / "synthetic-empty-history"
    history_dir.mkdir(exist_ok=True)
    archive_dir = tmp_path / "synthetic-consumer-archive"
    rank_path.write_text(json.dumps(rank), encoding="utf-8")
    roster_path.write_text(json.dumps(_mlb_roster_status()), encoding="utf-8")
    legacy = {**_legacy_buy_approval_review(), "generated_at": rank["generated_at"]}
    legacy_bytes = json.dumps(legacy).encode("utf-8")
    review_path.write_bytes(legacy_bytes)
    run = buys_module.run_buy_signals

    def run_synthetic(*, promotion_review_path):
        return run(rank_path=rank_path, rank_archive_dir=history_dir, artifact_path=output_path,
                   archive_dir=archive_dir, promotion_review_path=promotion_review_path,
                   mlb_roster_status_path=roster_path)

    with patch.object(builder, "BUY_REVIEW_PATH", review_path), \
         patch.object(builder, "run_buy_signals", side_effect=run_synthetic), \
         patch.object(builder.sys, "argv", ["build_valucast_buys.py", "--with-review"]):
        builder.main()
        blocked = json.loads(output_path.read_text(encoding="utf-8"))
        assert blocked["validation"]["ready_for_live_consumers"] is False
        assert blocked["validation"]["buy_review_ready"] is False
        assert review_path.read_bytes() == legacy_bytes
        qualified = _qualified_buy_review(history_launch=True)
        qualified["generated_at"] = rank["generated_at"]
        review_path.write_text(json.dumps(qualified), encoding="utf-8")
        builder.main()
        ready = json.loads(output_path.read_text(encoding="utf-8"))
        assert ready["validation"]["ready_for_live_consumers"] is True
        assert ready["board"] == blocked["board"]
        qualified["generated_at"] = "2026-11-25T00:00:00+00:00"
        review_path.write_text(json.dumps(qualified), encoding="utf-8")
        builder.main()
        stale = json.loads(output_path.read_text(encoding="utf-8"))
        assert stale["validation"]["ready_for_live_consumers"] is False
        assert stale["validation"]["buy_review_ready"] is False


def test_ready_buy_payload_can_use_reviewed_neutral_momentum_launch():
    review = _qualified_buy_review(history_launch=True)
    payload = build_buy_signals(
        _rank_payload([_row(index, f"Buy {index}", index + 30, 55.0) for index in range(1, 45)]),
        history_payloads=[],
        promotion_review=review,
        mlb_roster_status=_mlb_roster_status(),
        require_mlb_roster_status=True,
    )

    assert payload["validation"]["ready_for_live_consumers"] is True
    assert payload["validation"]["history_ready"] is False
    assert payload["validation"]["history_launch_approved"] is True
    assert validate_valucast_buy_payload(payload) == []


def test_ready_buy_payload_rejects_top_board_raw_fallback():
    review = _qualified_buy_review()
    payload = build_buy_signals(_rank_payload(), _history(), promotion_review=review)
    payload["validation"]["ready_for_live_consumers"] = True
    payload["validation"]["top_board_quality"]["raw_fallback_count"] = 1

    assert (
        "ready buy signals must not include raw fallback rows in the top board"
        in validate_valucast_buy_payload(payload)
    )


def test_buy_promotion_blocks_low_confidence_top_board_crowding():
    review = _qualified_buy_review()
    rows = [
        _row(index, f"Buy {index}", index + 30, 55.0, confidence="low")
        for index in range(1, 45)
    ]
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

    assert payload["validation"]["ready_for_live_consumers"] is False
    assert payload["validation"]["top_board_quality"]["low_confidence_rate"] == 1.0
    assert any("low-confidence" in blocker for blocker in payload["validation"]["blockers"])

    payload["validation"]["ready_for_live_consumers"] = True
    assert (
        "ready buy signals exceed low-confidence threshold"
        in validate_valucast_buy_payload(payload)
    )


def test_buy_promotion_blocks_pedigree_only_top_board_crowding():
    review = _qualified_buy_review()
    rows = [
        _row(index, f"Buy {index}", index + 30, 55.0, source="prospect_pedigree_v0_7")
        for index in range(1, 45)
    ]
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

    assert payload["validation"]["ready_for_live_consumers"] is False
    assert payload["validation"]["top_board_quality"]["pedigree_rate"] == 1.0
    assert any("pedigree-only" in blocker for blocker in payload["validation"]["blockers"])

    payload["validation"]["ready_for_live_consumers"] = True
    assert (
        "ready buy signals exceed pedigree-only threshold"
        in validate_valucast_buy_payload(payload)
    )
