"""Tests for the ValuCast public model quality governor."""

import json
from pathlib import Path

import pytest

from prospects.rank_v1 import _model_lookup, _model_score
from quality.valucast_governor import (
    _prospect_transition_continuity,
    evaluate_quality_governor,
    load_previous_prospect_rank,
)

QUALITY_GOVERNOR_PATH = Path("data/models/valucast_quality_governor.json")
PROSPECT_TOP50_BUCKET_SHAPE_CHECK_ID = "prospect_top50_bucket_shape"


def _assert_prospect_top50_bucket_shape_passed(governor):
    check = next(
        (
            check
            for check in governor.get("checks", [])
            if check.get("id") == PROSPECT_TOP50_BUCKET_SHAPE_CHECK_ID
        ),
        None,
    )
    assert check is not None
    assert "thin_upper_level_pitcher_count" in check.get("metrics", {})
    assert check.get("status") == "passed", check
    return check


def _mlb_row(mlbam_id, name, role, rank, value, positions=None):
    return {
        "id": f"vc_mlb_{mlbam_id}_{role}",
        "player_type": "mlb",
        "mlbam_id": mlbam_id,
        "name": name,
        "role": role,
        "positions": positions or (["SP"] if role == "pitcher" else ["SS"]),
        "rank": rank,
        "value": value,
    }


def _prospect_row(
    index,
    source="prospect_model_v0_6",
    team="BOS",
    neutral=False,
    confidence="medium",
    level="AA",
    role="hitter",
):
    return {
        "id": f"vc_prospect_{10_000 + index}_{role}",
        "player_type": "prospect",
        "mlbam_id": 10_000 + index,
        "name": f"Prospect {index}",
        "role": role,
        "rank": index,
        "prospect_rank": index,
        "value": 55.0 - index * 0.1,
        "value_source": source,
        "score": 55.0 - index * 0.1,
        "score_source": source,
        "mlb_team": team,
        "level": level,
        "confidence": confidence,
        "positions": ["SP"] if role == "pitcher" else ["SS"],
        "components": {
            "factual_investment_missing_uses_neutral": neutral,
            "factual_current_context": {
                "version": "0.1.0",
                "role": role,
                "level": level,
                "sample": 54.0 if role == "pitcher" else 224.0,
                "sample_unit": "IP" if role == "pitcher" else "PA",
                "skill_band": "starter_volume" if role == "pitcher" else "impact",
            },
            "availability": {
                "present": True,
                "status": "available",
                "risk_level": "clear",
                "risk_discount": 0.0,
                "level": level,
                "signals": [],
            },
        },
    }


def _prospect_rank(rows):
    return {
        "generated_at": "2026-06-13T12:00:00+00:00",
        "board": rows,
    }


def _transition_rank_row(
    *,
    mlbam_id=800522,
    name="Josue Briceno",
    role="hitter",
    level="A",
    status="available",
    starter_role=False,
    score=50.0,
    rank=10,
    model_score=50.0,
    bucket=None,
    bucket_adjustment=0.0,
):
    components = {
        "availability": {"status": status},
        "factual_current_context": {"starter_role": starter_role},
        "model_score": model_score,
    }
    if bucket is not None:
        components["bucket_calibration"] = {
            "adjustment": bucket_adjustment,
            "rules": [{"bucket": bucket, "adjustment": bucket_adjustment}],
        }
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        "role": role,
        "level": level,
        "score": score,
        "rank": rank,
        "components": components,
    }


def _transition_rank_payload(date_str, rows):
    return {
        "date": date_str,
        "generated_at": f"{date_str}T12:00:00+00:00",
        "board": rows,
    }


def _transition_check(current_row, prior_row=None):
    current = _transition_rank_payload("2026-07-18", [current_row])
    prior = (
        _transition_rank_payload("2026-07-17", [prior_row])
        if prior_row is not None
        else None
    )
    return _prospect_transition_continuity(current, prior)


def test_transition_continuity_blocks_new_material_thin_sample_cliff():
    prior = _transition_rank_row()
    current = _transition_rank_row(
        level="AA",
        status="thin_current_sample",
        score=42.0,
        model_score=49.8,
        bucket="thin_current_sample_confidence",
        bucket_adjustment=-7.0,
    )

    check = _transition_check(current, prior)

    assert check["status"] == "blocked"
    assert check["metrics"]["incident_count"] == 1
    assert check["metrics"]["hitter_count"] == 1
    assert check["metrics"]["pitcher_count"] == 0


def test_transition_continuity_blocks_pitcher_starter_role_transition():
    prior = _transition_rank_row(role="pitcher", starter_role=False)
    current = _transition_rank_row(
        role="pitcher",
        starter_role=True,
        score=42.0,
        model_score=49.8,
        bucket="thin_current_sample_confidence",
        bucket_adjustment=-7.0,
    )

    check = _transition_check(current, prior)

    assert check["status"] == "blocked"
    assert check["metrics"]["pitcher_count"] == 1
    assert check["metrics"]["samples"][0]["transition_signals"] == ["starter_role"]


def test_transition_continuity_allows_transition_without_new_thin_rule():
    check = _transition_check(
        _transition_rank_row(level="AA", score=42.0, bucket="other", bucket_adjustment=-7.0),
        _transition_rank_row(),
    )

    assert check["status"] == "passed"


def test_transition_continuity_allows_real_underlying_model_move():
    check = _transition_check(
        _transition_rank_row(
            level="AA",
            score=42.0,
            model_score=48.9,
            bucket="thin_current_sample_confidence",
            bucket_adjustment=-7.0,
        ),
        _transition_rank_row(),
    )

    assert check["status"] == "passed"


def test_transition_continuity_allows_exactly_six_point_bucket_move():
    check = _transition_check(
        _transition_rank_row(
            level="AA",
            score=44.0,
            bucket="thin_current_sample_confidence",
            bucket_adjustment=-6.0,
        ),
        _transition_rank_row(),
    )

    assert check["status"] == "passed"


def test_transition_continuity_allows_continuing_thin_sample_rule():
    prior = _transition_rank_row(
        status="thin_current_sample",
        bucket="thin_current_sample_confidence",
        bucket_adjustment=-7.0,
    )
    current = _transition_rank_row(
        level="AA",
        status="thin_current_sample",
        score=42.0,
        bucket="thin_current_sample_confidence",
        bucket_adjustment=-14.0,
    )

    assert _transition_check(current, prior)["status"] == "passed"


def test_transition_continuity_allows_non_declining_final_score():
    check = _transition_check(
        _transition_rank_row(
            level="AA",
            score=50.0,
            bucket="thin_current_sample_confidence",
            bucket_adjustment=-7.0,
        ),
        _transition_rank_row(),
    )

    assert check["status"] == "passed"


def test_transition_continuity_cold_start_is_not_a_blocker():
    check = _transition_check(_transition_rank_row(), None)

    assert check["status"] == "passed"
    assert check["metrics"]["sample_ready"] is False


def test_load_previous_prospect_rank_ignores_same_day_archive(tmp_path):
    previous = _transition_rank_payload("2026-07-17", [_transition_rank_row()])
    (tmp_path / "2026-07-17.json").write_text(json.dumps(previous), encoding="utf-8")
    (tmp_path / "2026-07-18.json").write_text("not-json", encoding="utf-8")

    selected = load_previous_prospect_rank(
        _transition_rank_payload("2026-07-18", []),
        tmp_path,
    )

    assert selected == previous


def test_load_previous_prospect_rank_rejects_malformed_selected_archive(tmp_path):
    (tmp_path / "2026-07-17.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="2026-07-17.json"):
        load_previous_prospect_rank(_transition_rank_payload("2026-07-18", []), tmp_path)


def test_transition_continuity_replays_briceno_july_17_to_18():
    archive_dir = Path("data/prediction_archive/valucast_prospect_rank_v1")
    previous = json.loads((archive_dir / "2026-07-17.json").read_text(encoding="utf-8"))
    current = json.loads((archive_dir / "2026-07-18.json").read_text(encoding="utf-8"))

    check = _prospect_transition_continuity(current, previous)
    briceno = next(
        sample for sample in check["metrics"]["samples"]
        if sample["name"] == "Josue Briceno"
    )

    assert check["status"] == "blocked"
    assert (briceno["old_level"], briceno["new_level"]) == ("A", "AA")
    assert briceno["model_score_delta"] == -0.09
    assert briceno["bucket_adjustment_delta"] == -17.57
    assert briceno["final_score_delta"] == -19.66


def test_transition_continuity_does_not_change_buy_surface_readiness():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    previous_rows = json.loads(json.dumps(prospects))
    prospects[0].update({"level": "AAA", "score": 40.0})
    prospects[0]["components"].update(
        {
            "model_score": 50.0,
            "bucket_calibration": {
                "adjustment": -7.0,
                "rules": [{"bucket": "thin_current_sample_confidence"}],
            },
        }
    )
    previous_rows[0]["components"]["model_score"] = 50.0
    payload = evaluate_quality_governor(
        [
            _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
            _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
            *prospects,
        ],
        prospect_rank=_transition_rank_payload("2026-07-18", prospects),
        previous_prospect_rank=_transition_rank_payload("2026-07-17", previous_rows),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-07-18T12:00:00+00:00",
    )

    check = next(
        check for check in payload["checks"]
        if check["id"] == "prospect_transition_continuity"
    )
    assert check["status"] == "blocked"
    assert check["message"] not in payload["surface_blockers"]["buys"]


def _buy_signals(
    ready=False,
    history_limited_count=0,
    row_count=40,
    top_board_quality=None,
    board=None,
):
    return {
        "generated_at": "2026-06-13T12:00:00+00:00",
        "validation": {
            "ready_for_live_consumers": ready,
            "history_limited_count": history_limited_count,
            "row_count": row_count,
            "top_board_quality": top_board_quality or {},
        },
        "board": board or [],
    }


def _coverage_audit(elite_fallback_top200=0):
    samples = []
    if elite_fallback_top200:
        samples.append(
            {
                "rank": 75,
                "name": "Elite Raw Fallback",
                "mlbam_id": 999001,
                "role": "pitcher",
                "score_source": "universal_fallback",
                "factual_investment_context": 98.5,
            }
        )
    return {
        "artifact": "valucast_prospect_coverage_audit",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "status": "blocked" if elite_fallback_top200 else "candidate_ready",
        "metrics": {
            "elite_factual_raw_fallback_top_200_count": elite_fallback_top200,
        },
        "elite_factual_raw_fallback_misses": samples,
    }


def test_prospect_rank_model_lookup_quantile_normalizes_scores_across_roles():
    prospect_model = {
        "ranked": [
            {
                "mlbam_id": 1,
                "role": "hitter",
                "expected_outcome_score": 0.10,
                "expected_category_impact_score": 0.05,
            },
            {
                "mlbam_id": 2,
                "role": "hitter",
                "expected_outcome_score": 0.20,
                "expected_category_impact_score": 0.15,
            },
            {
                "mlbam_id": 3,
                "role": "hitter",
                "expected_outcome_score": 0.30,
                "expected_category_impact_score": 0.25,
            },
            {
                "mlbam_id": 4,
                "role": "hitter",
                "expected_outcome_score": 0.60,
                "expected_category_impact_score": 0.55,
            },
            {
                "mlbam_id": 11,
                "role": "pitcher",
                "expected_outcome_score": 0.05,
                "expected_category_impact_score": 0.04,
            },
            {
                "mlbam_id": 12,
                "role": "pitcher",
                "expected_outcome_score": 0.25,
                "expected_category_impact_score": 0.20,
            },
            {
                "mlbam_id": 13,
                "role": "pitcher",
                "expected_outcome_score": 0.40,
                "expected_category_impact_score": 0.35,
            },
            {
                "mlbam_id": 14,
                "role": "pitcher",
                "expected_outcome_score": 0.99,
                "expected_category_impact_score": 0.88,
            },
        ]
    }

    lookup = _model_lookup(prospect_model)
    top_hitter = lookup[("4", "hitter")]
    top_pitcher = lookup[("14", "pitcher")]
    second_hitter = lookup[("2", "hitter")]
    second_pitcher = lookup[("12", "pitcher")]

    assert top_hitter["expected_outcome_score"] == 0.60
    assert top_hitter["expected_category_impact_score"] == 0.55
    assert top_hitter["expected_outcome_score_role_percentile"] == 0.8
    assert top_hitter["expected_outcome_score_role_quantile_normalized"] == 0.52
    assert top_hitter["expected_category_impact_score_role_quantile_normalized"] == 0.47
    assert top_pitcher["expected_outcome_score_role_percentile"] == 0.8
    assert top_pitcher["expected_outcome_score_role_quantile_normalized"] == 0.52
    assert top_pitcher["expected_category_impact_score_role_quantile_normalized"] == 0.47
    assert (
        second_hitter["expected_outcome_score_role_quantile_normalized"]
        == second_pitcher["expected_outcome_score_role_quantile_normalized"]
    )
    assert _model_score(top_hitter) == _model_score(top_pitcher)


def test_quality_governor_passes_clean_synthetic_board_but_keeps_buys_separate():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is True
    assert payload["ready_for_buys_promotion"] is False
    assert payload["surface_readiness"] == {
        "dynasty": True,
        "prospects": True,
        "buys": False,
        "movers": False,
    }
    assert payload["surface_blockers"] == {
        "dynasty": [],
        "prospects": [],
        "buys": [
            "ValuCast-owned Buy signals are not approved for public promotion.",
        ],
        "movers": [
            "ValuCast Prospect Movers artifact is missing or not native.",
        ],
    }
    assert payload["blockers"] == []
    assert payload["buy_blockers"] == [
        "ValuCast-owned Buy signals are not approved for public promotion."
    ]
    assert payload["mover_blockers"] == [
        "ValuCast Prospect Movers artifact is missing or not native."
    ]


def test_quality_governor_allows_reviewed_neutral_momentum_buy_launch():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=True, history_limited_count=40, row_count=40),
        buy_review={
            "review_status": "candidate_ready",
            "source_policy": {"history_launch_approved": True},
            "promotion_decision": {"neutral_momentum_launch_approved": True},
        },
        generated_at="2026-06-13T12:00:00+00:00",
    )

    buy_check = next(
        check for check in payload["checks"] if check["id"] == "buy_promotion_gate"
    )
    assert payload["ready_for_public_snapshot"] is True
    assert payload["ready_for_buys_promotion"] is True
    assert payload["surface_readiness"]["buys"] is True
    assert payload["buy_blockers"] == []
    assert buy_check["metrics"]["history_ready"] is True
    assert buy_check["metrics"]["history_launch_approved"] is True


def test_quality_governor_blocks_ready_buys_with_bad_top_board_shape():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(
            ready=True,
            top_board_quality={
                "low_confidence_rate": 0.5,
                "pedigree_rate": 0.2,
            },
        ),
        buy_review={
            "review_status": "candidate_ready",
            "source_policy": {"history_launch_approved": True},
        },
        generated_at="2026-06-13T12:00:00+00:00",
    )

    buy_check = next(
        check for check in payload["checks"] if check["id"] == "buy_promotion_gate"
    )
    assert payload["ready_for_public_snapshot"] is True
    assert payload["ready_for_buys_promotion"] is False
    assert buy_check["metrics"]["low_confidence_rate"] == 0.5


def test_quality_governor_blocks_obvious_public_board_quality_failures():
    prospects = []
    for index in range(1, 51):
        prospects.append(
            _prospect_row(
                index,
                source="universal_fallback" if index <= 8 else "prospect_model_v0_6",
                team="" if index in {12, 18} else "BOS",
                neutral=index <= 11,
            )
        )
    players = [
        _mlb_row(1, "Spike Pitcher", "pitcher", 1, 99.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 77.0),
        _mlb_row(660271, "Shohei Ohtani", "hitter", 20, 60.0),
        _mlb_row(660271, "Shohei Ohtani", "pitcher", 90, 40.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=True),
        buy_review={"review_status": "candidate_ready"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    assert payload["ready_for_buys_promotion"] is False
    assert payload["surface_readiness"]["dynasty"] is False
    assert payload["surface_readiness"]["prospects"] is False
    assert payload["surface_readiness"]["buys"] is False
    assert "Top MLB dynasty value is too far above the second row for public promotion." in payload["blockers"]
    assert "Top public rows split two-way identities without a combined-value policy." in payload["blockers"]
    assert "Top prospect board uses too many fallback-scored rows for public promotion." in payload["blockers"]
    assert "Top prospect board leans too heavily on neutral draft/signing context." in payload["blockers"]
    assert "Top prospect board has missing MLB-org display coverage." in payload["blockers"]
    assert (
        "Top MLB dynasty value is too far above the second row for public promotion."
        in payload["surface_blockers"]["dynasty"]
    )
    assert (
        "Top public rows split two-way identities without a combined-value policy."
        in payload["surface_blockers"]["dynasty"]
    )
    assert (
        "Top prospect board uses too many fallback-scored rows for public promotion."
        not in payload["surface_blockers"]["dynasty"]
    )
    assert (
        "Top prospect board uses too many fallback-scored rows for public promotion."
        in payload["surface_blockers"]["prospects"]
    )


def test_quality_governor_blocks_elite_factual_raw_fallback_audit():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(elite_fallback_top200=1),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    assert "Elite factual lower-minors prospects remain on raw fallback scoring." in payload["blockers"]


def test_quality_governor_blocks_suppressed_top_rank_rows():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        *prospects[1:],
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    assert "Top Prospect Rank v1 rows are missing from the public prospect surface." in payload["blockers"]


def test_quality_governor_allows_top_rank_rows_graduated_to_mlb_surface():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        _mlb_row(10001, "Prospect 1", "hitter", 200, 12.0),
        *prospects[1:],
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    surface_check = next(
        check for check in payload["checks"] if check["id"] == "prospect_rank_surface_suppression"
    )

    assert payload["ready_for_public_snapshot"] is True
    assert "Top Prospect Rank v1 rows are missing from the public prospect surface." not in payload["blockers"]
    assert surface_check["metrics"]["suppressed_count"] == 0
    assert surface_check["metrics"]["graduated_to_mlb_count"] == 1


def test_quality_governor_allows_top_rank_rows_graduated_by_active_roster():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        *prospects[1:],
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
        graduated_prospect_ids={"10001"},
    )

    surface_check = next(
        check for check in payload["checks"] if check["id"] == "prospect_rank_surface_suppression"
    )

    assert payload["ready_for_public_snapshot"] is True
    assert "Top Prospect Rank v1 rows are missing from the public prospect surface." not in payload["blockers"]
    assert surface_check["metrics"]["suppressed_count"] == 0
    assert surface_check["metrics"]["graduated_to_mlb_count"] == 1
    assert surface_check["metrics"]["graduated_samples"][0]["graduation_surface"] == "active_mlb_roster"


def test_quality_governor_blocks_extreme_mlb_outlier_without_stability_adjustment():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    outlier = _mlb_row(1, "Current Spike", "pitcher", 1, 92.0)
    outlier["context"] = {
        "components": {
            "projection_stability": {
                "current_season_category_value": 24.0,
                "ros_category_value": 11.0,
                "ros_stability_weight": 0.7,
            }
        }
    }
    players = [
        outlier,
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    assert "Top MLB rows retain extreme current-over-ROS projection outliers after stability adjustment." in payload["blockers"]


def test_quality_governor_allows_extreme_raw_mlb_outlier_after_stability_adjustment():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    outlier = _mlb_row(1, "Adjusted Spike", "pitcher", 1, 92.0)
    outlier["context"] = {
        "components": {
            "projection_stability": {
                "current_season_category_value": 24.0,
                "ros_category_value": 11.0,
                "stability_adjusted_category_value": 15.0,
                "ros_stability_weight": 0.7,
            }
        }
    }
    players = [
        outlier,
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is True
    assert payload["blockers"] == []


def test_quality_governor_blocks_pitcher_heavy_top_dynasty_board():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    players = [
        *[
            _mlb_row(index, f"Pitcher {index}", "pitcher", index, 90.0 - index, positions=["SP"])
            for index in range(1, 11)
        ],
        _mlb_row(50, "Closer One", "pitcher", 11, 70.0, positions=["RP"]),
        _mlb_row(51, "Closer Two", "pitcher", 12, 69.0, positions=["RP"]),
        _mlb_row(60, "MLB Bat", "hitter", 13, 68.0, positions=["OF"]),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    assert "Top MLB dynasty board is too pitcher/reliever-heavy for public promotion." in payload["blockers"]


def test_quality_governor_blocks_pitcher_heavy_top_prospect_board():
    balanced_prospects = [
        _prospect_row(
            index,
            role="pitcher" if index <= 5 or 31 <= index <= 40 else "hitter",
        )
        for index in range(1, 51)
    ]
    crowded_prospects = [
        _prospect_row(index, role="pitcher" if index <= 8 else "hitter")
        for index in range(1, 51)
    ]

    def evaluate(prospects):
        return evaluate_quality_governor(
            [
                _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
                _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
                *prospects,
            ],
            prospect_rank=_prospect_rank(prospects),
            prospect_coverage_audit=_coverage_audit(),
            buy_signals=_buy_signals(ready=False),
            buy_review={"review_status": "blocked"},
            generated_at="2026-06-13T12:00:00+00:00",
        )

    balanced_payload = evaluate(balanced_prospects)
    balanced_check = next(
        check
        for check in balanced_payload["checks"]
        if check["id"] == "prospect_top_board_role_shape"
    )
    assert balanced_payload["ready_for_public_snapshot"] is True
    assert balanced_check["status"] == "passed"
    assert (
        balanced_check["message"]
        == "Current prospect cross-role calibration is within the publication range."
    )
    assert balanced_check["metrics"]["top25_pitcher_count"] == 5
    assert balanced_check["metrics"]["top50_pitcher_rate"] == 0.3

    crowded_payload = evaluate(crowded_prospects)
    crowded_check = next(
        check
        for check in crowded_payload["checks"]
        if check["id"] == "prospect_top_board_role_shape"
    )
    assert crowded_payload["ready_for_public_snapshot"] is False
    assert crowded_payload["surface_readiness"]["dynasty"] is True
    assert crowded_payload["surface_readiness"]["prospects"] is False
    assert crowded_check["status"] == "blocked"
    assert crowded_check["metrics"]["top25_pitcher_count"] == 8
    assert (
        "Pitcher representation exceeds the publication range. Rankings remain visible, but the current evidence cannot justify either a cross-role score adjustment or relaxing the publication gate."
        in crowded_payload["blockers"]
    )
    assert (
        "Pitcher representation exceeds the publication range. Rankings remain visible, but the current evidence cannot justify either a cross-role score adjustment or relaxing the publication gate."
        not in crowded_payload["surface_blockers"]["dynasty"]
    )
    assert crowded_payload["surface_blockers"]["prospects"] == [
        "Pitcher representation exceeds the publication range. Rankings remain visible, but the current evidence cannot justify either a cross-role score adjustment or relaxing the publication gate."
    ]


def test_buy_gate_ignores_only_prospect_pitcher_shape_failure():
    prospects = [
        _prospect_row(index, role="pitcher" if index <= 8 else "hitter")
        for index in range(1, 51)
    ]
    payload = evaluate_quality_governor(
        [
            _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
            _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
            *prospects,
        ],
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=True),
        buy_review={"review_status": "candidate_ready"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    blocker = "Pitcher representation exceeds the publication range. Rankings remain visible, but the current evidence cannot justify either a cross-role score adjustment or relaxing the publication gate."
    assert payload["ready_for_public_snapshot"] is False
    assert payload["ready_for_buys_promotion"] is True
    assert blocker in payload["blockers"]
    assert blocker in payload["surface_blockers"]["prospects"]
    assert blocker not in payload["buy_blockers"]


def test_buy_gate_decoupled_from_prospect_board_freshness_and_shape():
    # The pitcher-shape lean AND the top-50 card freshness audit are PROSPECT-board
    # checks (the freshness one can fire on a single non-buy prospect, e.g. an injured
    # player on a prior-year line). They block the prospects surface / public snapshot,
    # but NOT the buys, which are a separate corroboration-filtered list gated on their
    # own quality.
    prospects = [
        _prospect_row(index, role="pitcher" if index <= 8 else "hitter")
        for index in range(1, 51)
    ]
    payload = evaluate_quality_governor(
        [
            _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
            _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
            *prospects,
        ],
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=True),
        buy_review={"review_status": "candidate_ready"},
        milb_stat_freshness_audit={
            "status": "blocked",
            "generated_at": "2026-06-13T12:00:00+00:00",
            "metrics": {"top50_history_fallback_count": 1},
            "blockers": ["top-50 prospect card context uses latest_milb_history fallback"],
        },
        generated_at="2026-06-13T12:00:00+00:00",
    )

    shape_blocker = "Pitcher representation exceeds the publication range. Rankings remain visible, but the current evidence cannot justify either a cross-role score adjustment or relaxing the publication gate."
    freshness_blocker = "MiLB prospect-card stat freshness audit blocks public promotion."
    # Both block the prospects surface and the public snapshot ...
    assert payload["ready_for_public_snapshot"] is False
    assert shape_blocker in payload["surface_blockers"]["prospects"]
    assert freshness_blocker in payload["surface_blockers"]["prospects"]
    # ... but neither blocks the buys surface (decoupled).
    assert payload["ready_for_buys_promotion"] is True
    assert shape_blocker not in payload["buy_blockers"]
    assert freshness_blocker not in payload["buy_blockers"]


def test_quality_governor_blocks_pedigree_only_top50_crowding():
    prospects = []
    for index in range(1, 51):
        source = "prospect_pedigree_v0_7" if index <= 18 else "prospect_model_v0_6"
        prospects.append(_prospect_row(index, source=source))
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    assert "Top prospect board leans too heavily on pedigree-only scoring." in payload["blockers"]


def test_quality_governor_blocks_risky_prospect_bucket_shape():
    prospects = []
    for index in range(1, 51):
        if index <= 5:
            row = _prospect_row(index, role="pitcher", level="AAA")
            row["components"]["availability"] = {
                "present": True,
                "status": "thin_current_sample",
                "risk_level": "medium",
                "risk_discount": 0.06,
                "signals": ["thin_starter_workload_under_30_ip"],
                "sample": 24.2,
                "sample_unit": "IP",
            }
        else:
            row = _prospect_row(index)
        prospects.append(row)
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(3, "MLB Core", "pitcher", 3, 70.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    bucket_check = next(
        check for check in payload["checks"] if check["id"] == "prospect_top50_bucket_shape"
    )
    assert payload["ready_for_public_snapshot"] is False
    assert "Top prospect board has a risky bucket concentration." in payload["blockers"]
    assert bucket_check["metrics"]["thin_upper_level_pitcher_count"] == 5


def test_quality_governor_blocks_exact_pedigree_cap_plateau():
    prospects = []
    for index in range(1, 51):
        row = _prospect_row(index)
        if index <= 4:
            row["score_source"] = "prospect_pedigree_v0_7"
            row["value_source"] = "prospect_pedigree_v0_7"
            row["score"] = 49.0
            row["value"] = 49.0
            row["components"]["pedigree_score_cap"] = 49.0
        prospects.append(row)
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    assert "Top prospect board has too many exact pedigree-cap ties." in payload["blockers"]


def test_quality_governor_blocks_missing_prospect_availability_pricing():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    prospects[0]["components"].pop("availability")
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    assert "Top prospect board is missing availability/risk pricing." in payload["blockers"]


def test_quality_governor_blocks_missing_factual_current_context():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    prospects[0]["components"].pop("factual_current_context")
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    assert "Top prospect board is missing factual current-sample context." in payload["blockers"]


def test_quality_governor_blocks_crowded_caution_factual_context():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    for row in prospects[:9]:
        row["components"]["factual_current_context"]["skill_band"] = "low_impact"
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    check = next(
        check for check in payload["checks"]
        if check["id"] == "prospect_top50_factual_context_shape"
    )
    assert payload["ready_for_public_snapshot"] is False
    assert (
        "Top prospect board has too many thin or low-impact current-sample reads."
        in payload["blockers"]
    )
    assert check["metrics"]["caution_factual_context_count"] == 9


def test_quality_governor_accepts_thin_current_rows_with_best_single_level_read():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    for row in prospects[:9]:
        row["components"]["factual_current_context"].update(
            {
                "skill_band": "thin",
                "sample": 12.0,
                "sample_unit": "PA",
            }
        )
        row["best_single_level_stat_line"] = {
            "level": "AA",
            "sample": 240,
            "sample_unit": "PA",
            "ops": 0.812,
            "iso": 0.175,
            "reason": "current_level_too_thin_best_prior_level",
        }
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    check = next(
        check for check in payload["checks"]
        if check["id"] == "prospect_top50_factual_context_shape"
    )
    assert payload["ready_for_public_snapshot"] is True
    assert check["status"] == "passed"
    assert check["metrics"]["caution_factual_context_count"] == 0
    assert check["metrics"]["best_single_level_covered_count"] == 9


def test_quality_governor_still_counts_low_impact_even_with_best_single_level_read():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    for row in prospects[:9]:
        row["components"]["factual_current_context"]["skill_band"] = "low_impact"
        row["best_single_level_stat_line"] = {
            "level": "AA",
            "sample": 240,
            "sample_unit": "PA",
            "ops": 0.650,
            "iso": 0.080,
            "reason": "current_level_too_thin_best_prior_level",
        }
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    check = next(
        check for check in payload["checks"]
        if check["id"] == "prospect_top50_factual_context_shape"
    )
    assert payload["ready_for_public_snapshot"] is False
    assert check["metrics"]["caution_factual_context_count"] == 9
    assert check["metrics"]["best_single_level_covered_count"] == 0


def test_quality_governor_blocks_stale_current_stat_context():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    prospects[0]["components"]["factual_current_context"].update(
        {
            "source_kind": "current_season",
            "sample_season": 2026,
            "sample": 225.0,
        }
    )
    prospects[0]["context"] = {
        "stat_line_source": "valucast_input_contract",
        "stat_line_source_kind": "latest_milb_history",
        "stat_line_sample": 420.0,
        "stat_line_sample_season": 2024,
    }
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    check = next(
        check for check in payload["checks"]
        if check["id"] == "prospect_top50_current_stat_context_alignment"
    )
    assert payload["ready_for_public_snapshot"] is False
    assert (
        "Top prospect board has stale or mismatched current stat context."
        in payload["blockers"]
    )
    assert check["metrics"]["current_stat_context_mismatch_count"] == 1


def test_quality_governor_blocks_failed_milb_stat_freshness_audit():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        milb_stat_freshness_audit={
            "status": "blocked",
            "generated_at": "2026-06-13T12:00:00+00:00",
            "metrics": {
                "current_row_count": 100,
                "current_season_row_count": 95,
                "targeted_row_refresh_count": 0,
                "top50_history_fallback_count": 1,
                "top50_stat_context_mismatch_count": 0,
                "top200_history_fallback_count": 8,
            },
            "blockers": [
                "top-50 prospect card context uses latest_milb_history fallback"
            ],
        },
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    check = next(
        check for check in payload["checks"] if check["id"] == "milb_stat_freshness_audit"
    )
    assert check["status"] == "blocked"
    assert check["metrics"]["top50_history_fallback_count"] == 1


def test_quality_governor_blocks_labeled_availability_risk_without_discount():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    prospects[0]["components"]["availability"] = {
        "present": True,
        "status": "thin_current_sample",
        "risk_level": "medium",
        "risk_discount": 0.0,
        "signals": ["thin_starter_workload_under_30_ip"],
    }
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    assert payload["ready_for_public_snapshot"] is False
    assert "Top prospect board has unpriced availability risk." in payload["blockers"]


def test_quality_governor_blocks_availability_level_mismatch():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    prospects[0]["level"] = "A+"
    prospects[0]["components"]["availability"]["level"] = "AA"
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    check = next(
        check for check in payload["checks"]
        if check["id"] == "prospect_top50_availability_level_alignment"
    )
    assert payload["ready_for_public_snapshot"] is False
    assert (
        "Top prospect board level labels disagree with availability-selected current level."
        in payload["blockers"]
    )
    assert check["metrics"]["level_mismatch_count"] == 1


def test_quality_governor_allows_active_callup_bridge_availability_level_mismatch():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    prospects[0]["level"] = "MLB"
    prospects[0]["active_mlb_callup_bridge"] = True
    prospects[0]["context"] = {
        "graduation_context": {
            "status": "active_mlb_callup",
            "graduated": True,
            "surface": "active_mlb_roster_bridge",
            "previous_level": "AA",
            "reason": "official_mlb_active_roster_without_mlb_projection_row",
        }
    }
    prospects[0]["components"]["availability"]["level"] = "AA"
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=False),
        buy_review={"review_status": "blocked"},
        generated_at="2026-06-13T12:00:00+00:00",
    )

    check = next(
        check for check in payload["checks"]
        if check["id"] == "prospect_top50_availability_level_alignment"
    )
    assert payload["ready_for_public_snapshot"] is True
    assert check["metrics"]["level_mismatch_count"] == 0


def test_quality_governor_blocks_buy_surface_identity_level_and_team_drift():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        _mlb_row(10003, "Prospect 3", "hitter", 300, 8.0),
        *prospects[:2],
        *prospects[3:],
    ]
    buy_board = [
        {
            "rank": 1,
            "name": "Prospect 1",
            "mlbam_id": 10001,
            "role": "hitter",
            "level": "A+",
            "team": "BOS",
        },
        {
            "rank": 2,
            "name": "Prospect 2",
            "mlbam_id": 10002,
            "role": "hitter",
            "level": "AA",
            "team": "NYY",
        },
        {
            "rank": 3,
            "name": "Prospect 3",
            "mlbam_id": 10003,
            "role": "hitter",
            "level": "AAA",
            "team": "BOS",
        },
        {
            "rank": 4,
            "name": "Missing Prospect",
            "mlbam_id": 99999,
            "role": "hitter",
            "level": "AA",
            "team": "BOS",
        },
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=True, board=buy_board),
        buy_review={
            "review_status": "candidate_ready",
            "source_policy": {"history_launch_approved": True},
        },
        generated_at="2026-06-13T12:00:00+00:00",
    )

    check = next(
        check for check in payload["checks"]
        if check["id"] == "buy_top40_public_surface_alignment"
    )
    assert payload["ready_for_public_snapshot"] is True
    assert payload["ready_for_buys_promotion"] is False
    assert (
        "ValuCast Buy rows have stale level/team/graduation or availability context."
        in payload["buy_blockers"]
    )
    assert check["metrics"]["level_mismatch_count"] == 1
    assert check["metrics"]["team_mismatch_count"] == 1
    assert check["metrics"]["graduated_or_mlb_count"] == 1
    assert check["metrics"]["missing_public_prospect_count"] == 1


def test_quality_governor_blocks_buy_surface_undisclosed_availability_risk():
    prospects = [_prospect_row(index) for index in range(1, 51)]
    prospects[0]["components"]["availability"].update(
        {
            "status": "injured",
            "risk_level": "high",
            "risk_discount": 0.1,
            "signals": ["manual_injury_override"],
        }
    )
    players = [
        _mlb_row(1, "MLB Star", "hitter", 1, 90.0),
        _mlb_row(2, "MLB Anchor", "hitter", 2, 80.0),
        *prospects,
    ]
    buy_board = [
        {
            "rank": 1,
            "name": "Prospect 1",
            "mlbam_id": 10001,
            "role": "hitter",
            "level": "AA",
            "team": "BOS",
        }
    ]

    payload = evaluate_quality_governor(
        players,
        prospect_rank=_prospect_rank(prospects),
        prospect_coverage_audit=_coverage_audit(),
        buy_signals=_buy_signals(ready=True, board=buy_board),
        buy_review={
            "review_status": "candidate_ready",
            "source_policy": {"history_launch_approved": True},
        },
        generated_at="2026-06-13T12:00:00+00:00",
    )

    check = next(
        check for check in payload["checks"]
        if check["id"] == "buy_top40_public_surface_alignment"
    )
    assert payload["ready_for_public_snapshot"] is True
    assert payload["ready_for_buys_promotion"] is False
    assert check["metrics"]["undisclosed_availability_risk_count"] == 1
    assert check["metrics"]["samples"]["undisclosed_availability_risk"][0]["public_status"] == "injured"


def test_dd_score_source_audit_blocks_dd_derived_value():
    rows = [_prospect_row(1), _prospect_row(2)]
    rows[0]["value_source"] = "dd_dynasty_value"

    payload = evaluate_quality_governor(rows)
    check = next(c for c in payload["checks"] if c["id"] == "dd_score_source_audit")
    assert check["status"] == "blocked"
    assert check["metrics"]["offender_count"] >= 1
    assert payload["ready_for_public_snapshot"] is False


def test_dd_score_source_audit_passes_valucast_owned_board():
    rows = [_prospect_row(1), _prospect_row(2)]

    payload = evaluate_quality_governor(rows)
    check = next(c for c in payload["checks"] if c["id"] == "dd_score_source_audit")
    assert check["status"] == "passed"


def test_public_quality_governor_prospect_top50_bucket_shape_passes_current_artifact():
    governor = json.loads(QUALITY_GOVERNOR_PATH.read_text())

    _assert_prospect_top50_bucket_shape_passed(governor)


def test_public_quality_governor_prospect_top50_bucket_shape_guard_flags_breach():
    governor = {
        "checks": [
            {
                "id": PROSPECT_TOP50_BUCKET_SHAPE_CHECK_ID,
                "message": "Top prospect board has a risky bucket concentration.",
                "status": "blocked",
                "metrics": {"thin_upper_level_pitcher_count": 5},
            }
        ]
    }

    failed = False
    try:
        _assert_prospect_top50_bucket_shape_passed(governor)
    except AssertionError:
        failed = True

    assert failed
