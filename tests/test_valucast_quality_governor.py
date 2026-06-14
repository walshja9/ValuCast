"""Tests for the ValuCast public model quality governor."""

from quality.valucast_governor import evaluate_quality_governor


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


def _prospect_row(index, source="prospect_model_v0_6", team="BOS", neutral=False):
    return {
        "id": f"vc_prospect_{10_000 + index}_hitter",
        "player_type": "prospect",
        "mlbam_id": 10_000 + index,
        "name": f"Prospect {index}",
        "role": "hitter",
        "rank": index,
        "prospect_rank": index,
        "value": 55.0 - index * 0.1,
        "value_source": source,
        "score": 55.0 - index * 0.1,
        "score_source": source,
        "mlb_team": team,
        "components": {
            "factual_investment_missing_uses_neutral": neutral,
            "availability": {
                "present": True,
                "status": "available",
                "risk_level": "clear",
                "risk_discount": 0.0,
                "signals": [],
            },
        },
    }


def _prospect_rank(rows):
    return {
        "generated_at": "2026-06-13T12:00:00+00:00",
        "board": rows,
    }


def _buy_signals(ready=False, history_limited_count=0, row_count=40):
    return {
        "generated_at": "2026-06-13T12:00:00+00:00",
        "validation": {
            "ready_for_live_consumers": ready,
            "history_limited_count": history_limited_count,
            "row_count": row_count,
        },
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
    }
    assert payload["blockers"] == []
    assert payload["buy_blockers"] == [
        "ValuCast-owned Buy signals are not approved for public promotion."
    ]


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
    assert payload["surface_readiness"]["buys"] is False
    assert "Top MLB dynasty value is too far above the second row for public promotion." in payload["blockers"]
    assert "Top public rows split two-way identities without a combined-value policy." in payload["blockers"]
    assert "Top prospect board uses too many fallback-scored rows for public promotion." in payload["blockers"]
    assert "Top prospect board leans too heavily on neutral draft/signing context." in payload["blockers"]
    assert "Top prospect board has missing MLB-org display coverage." in payload["blockers"]


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
