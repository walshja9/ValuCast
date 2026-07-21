"""Contract tests for ValuCast's independent prospect model."""
import inspect
import json

import pytest

from prospects.gate import validate_gate
from prospects.model import (
    OUTCOME_FEATURE_NAMES,
    _active_impact_categories,
    _canonical_impact_feature_vector,
    _category_value,
    _feature_vector,
    _fit_prediction_model,
    _historical_rows,
    _historical_impact_rows,
    _impact_references,
    _impact_target,
    _outcome_feature_vector,
    _prediction_drivers,
    _predict_model,
    _regress_current_features,
    _select_current_records,
    _walk_forward,
    archive_predictions,
    build_shadow_model,
    load_input_contract,
    refresh_impact_drivers,
    run_model,
    score_current,
    train_role,
    train_impact_role,
    validate_input_contract,
)


def _historical(role, year, mlbam_id, outcome, **overrides):
    row = {
        "cohort_year": year,
        "mlbam_id": mlbam_id,
        "name": f"Player {mlbam_id}",
        "role": role,
        "level": "AA" if mlbam_id % 2 else "AAA",
        "age": 21 + mlbam_id % 4,
        "outcome": outcome,
    }
    if role == "hitter":
        row.update(
            {
                "iso": 0.12 + (mlbam_id % 8) * 0.02,
                "k_pct": 30 - mlbam_id % 12,
                "bb_pct": 6 + mlbam_id % 8,
                "ops": 0.68 + (mlbam_id % 10) * 0.03,
            }
        )
    else:
        row.update(
            {
                "k_per_9": 7 + mlbam_id % 6,
                "bb_per_9": 5 - (mlbam_id % 4) * 0.5,
                "k_bb_pct": 6 + mlbam_id % 14,
                "era": 5 - (mlbam_id % 8) * 0.3,
                "whip": 1.5 - (mlbam_id % 6) * 0.08,
                "is_starter": mlbam_id % 3 != 0,
            }
        )
    row.update(overrides)
    return row


def _contract(n_per_role=420):
    rows = []
    outcomes = ("bust", "role", "star")
    for role in ("hitter", "pitcher"):
        offset = 0 if role == "hitter" else 10000
        for index in range(1, n_per_role + 1):
            rows.append(
                _historical(
                    role,
                    2014 + index % 6,
                    index + offset,
                    outcomes[index % len(outcomes)],
                )
            )
    seasons = {}
    for row in rows:
        if row["outcome"] == "bust":
            seasons[f"{row['mlbam_id']}_{row['role']}"] = []
        elif row["role"] == "hitter":
            star = row["outcome"] == "star"
            seasons[f"{row['mlbam_id']}_hitter"] = [{
                "year": row["cohort_year"] + 1,
                "pa": 600 if star else 320,
                "ops": 0.900 if star else 0.730,
                "hr": 30 if star else 12,
                "sb": 20 if star else 5,
            }]
        else:
            star = row["outcome"] == "star"
            seasons[f"{row['mlbam_id']}_pitcher"] = [{
                "year": row["cohort_year"] + 1,
                "ip": 170 if star else 90,
                "era": 3.10 if star else 4.30,
                "so": 190 if star else 85,
                "sv": 0,
            }]
    return {
        "schema_version": "1.2",
        "generated_at": "2026-06-12T00:00:00+00:00",
        "source_policy": {
            "kind": "factual_only",
            "sources": [
                "valucast_universal_prospect_dataset",
                "milb_season_stats",
                "fantrax_mlb_actuals",
                "mlb_prospect_seasons_cache",
                "mlb_statsapi_draft",
                "fantrax_roster_status",
            ],
            "external_rankings_used": False,
            "external_projections_used": False,
            "market_values_used": False,
            "dynasty_values_used": False,
        },
        "historical": {"rows": rows},
        "historical_mlb_seasons": seasons,
        "current": {
            "hitters": [
                {
                    "mlbam_id": 1,
                    "name": "Hitter One",
                    "normalized_name": "hitter one",
                    "team": "AAA Club",
                    "role": "hitter",
                    "position": "SS",
                    "level": "AAA",
                    "age": 21,
                    "plate_appearances": 180,
                    "iso": 0.24,
                    "k_pct": 18.0,
                    "bb_pct": 12.0,
                    "ops": 0.910,
                }
            ],
            "pitchers": [
                {
                    "mlbam_id": 2,
                    "name": "Pitcher Two",
                    "normalized_name": "pitcher two",
                    "team": "AA Club",
                    "role": "pitcher",
                    "position": "P",
                    "level": "AA",
                    "age": 22,
                    "innings_pitched": 42,
                    "k_per_9": 11.0,
                    "bb_per_9": 2.5,
                    "k_bb_pct": 22.0,
                    "era": 2.80,
                    "whip": 1.05,
                    "is_starter": True,
                }
            ],
        },
        "mlb_service": [
            {"mlbam_id": 1, "role": "hitter", "ab": 0, "ip": 0, "graduated": False},
            {"mlbam_id": 2, "role": "pitcher", "ab": 0, "ip": 0, "graduated": False},
        ],
    }


def test_model_module_has_no_external_rank_or_valuation_dependencies():
    import prospects.model as model

    source = inspect.getsource(model).lower()
    forbidden = (
        "pipeline_rank",
        "get_dynasty_value",
        "import valuation",
        "dd_dynasty_feed",
    )
    assert not any(token in source for token in forbidden)


def test_contract_rejects_non_factual_inputs():
    contract = _contract()
    contract["source_policy"]["external_rankings_used"] = True
    with pytest.raises(ValueError, match="external_rankings_used"):
        validate_input_contract(contract)


def test_contract_rejects_unexpected_source_even_when_flags_are_false():
    contract = _contract()
    contract["source_policy"]["sources"].append("external_rank")
    with pytest.raises(ValueError, match="sources"):
        validate_input_contract(contract)


def test_historical_rows_deduplicate_player_before_walk_forward():
    rows = [
        _historical("hitter", 2015, 1, "star", level="AA"),
        _historical("hitter", 2015, 1, "star", level="AAA"),
        _historical("hitter", 2016, 1, "star", level="AAA"),
    ]
    out = _historical_rows(rows, "hitter")
    assert len(out) == 1
    assert out[0]["cohort_year"] == 2015
    assert out[0]["level"] == "AAA"


def test_historical_outcome_rows_keep_original_neighbor_baseline_features():
    rows = [_historical("hitter", 2015, 1, "star", level="A+", age=20)]

    out = _historical_rows(rows, "hitter")

    assert out[0]["level"] == "A+"
    assert "baseline_features" in out[0]
    assert len(out[0]["features"]) > len(out[0]["baseline_features"])


def test_walk_forward_is_player_grouped_and_never_trains_on_future_cohorts():
    rows = _historical_rows(_contract()["historical"]["rows"], "hitter")
    validation = _walk_forward(rows)
    assert validation["folds"]
    for fold in validation["folds"]:
        assert fold["train_year_max"] < fold["test_year"]
        assert set(fold["train_ids"]).isdisjoint(fold["test_ids"])


def test_current_record_selection_prefers_larger_sample():
    current = _contract()["current"]
    current["hitters"].append(
        {
            **current["hitters"][0],
            "level": "AA",
            "plate_appearances": 240,
            "ops": 0.850,
        }
    )
    selected = _select_current_records(current, "hitter")
    assert len(selected) == 1
    assert selected[0]["plate_appearances"] == 240


def test_partial_season_features_regress_toward_training_mean():
    role_model = {"means": [0.15, 24.0, 9.0, 0.75, 0.0, 0.5]}
    raw = [0.30, 12.0, 18.0, 1.10, 2.0, 1.0]
    low, low_reliability = _regress_current_features(raw, role_model, "hitter", 50)
    high, high_reliability = _regress_current_features(raw, role_model, "hitter", 500)
    assert low_reliability < high_reliability
    assert abs(low[0] - role_model["means"][0]) < abs(high[0] - role_model["means"][0])
    assert low[4:] == raw[4:]


def test_rich_outcome_features_regress_toward_mean_on_small_samples():
    # Regression guard for the A-ball saturation bug: every performance-derived
    # feature in the RICH scoring vector (not just the 6 base stats) must shrink
    # toward the model mean by sample reliability. A small-sample discipline
    # outlier like bb_to_k_ratio otherwise sails in raw and saturates the score
    # (Bruin Agbayani ranked #2 on 51 PA at Single-A before this).
    names = OUTCOME_FEATURE_NAMES["hitter"]
    role_model = {"feature_names": list(names), "means": [0.0] * len(names)}
    raw = [5.0] * len(names)

    low, low_reliability = _regress_current_features(raw, role_model, "hitter", 50)
    high, high_reliability = _regress_current_features(raw, role_model, "hitter", 2000)
    assert low_reliability < high_reliability

    for rich in ("bb_to_k_ratio", "bb_minus_k_pct", "obp", "ops_x_youth"):
        idx = names.index(rich)
        assert low[idx] < raw[idx], f"{rich} not shrunk"
        assert abs(low[idx]) < abs(high[idx]), f"{rich} small sample not pulled harder"

    # Structural facts stay fixed regardless of sample size.
    for structural in ("youth", "level"):
        idx = names.index(structural)
        assert low[idx] == raw[idx] == high[idx]


def test_role_training_emits_valid_honest_gate():
    result = train_role("hitter", _contract()["historical"]["rows"], now="2026-06-12")
    assert validate_gate(result["gate"])
    assert result["validation_sample"] >= 250
    assert result["gate"]["baseline"] in {
        "level_age_prior",
        "historical_neighbors_25",
    }
    assert result["model_kind"] == "hurdle_ridge"
    assert result["prediction_model"]["model_kind"] == "hurdle_ridge"


def _stale_arm(draft_year, cohort_year=2021, **overrides):
    return _historical(
        "pitcher", cohort_year, 11, "bust",
        draft_year=draft_year, draft_pick_number=10, draft_round=1,
        signing_bonus=4_000_000, pick_value=8.0, **overrides,
    )


def test_pitcher_pedigree_decay_is_flag_gated_and_stale_zeroes_magnitudes(monkeypatch):
    """C1 lever (plan 028 amendment 2): flag off = byte-identical baseline;
    flag on zeroes exactly the four pedigree magnitude features at >= 5 years
    since draft, touching nothing else."""
    from prospects import model

    record = _stale_arm(draft_year=2016)  # 5 years stale in the 2021 cohort
    off = _outcome_feature_vector(record, "pitcher")
    monkeypatch.setattr(model, "PITCHER_STALE_PEDIGREE_DECAY_ENABLED", True)
    on = _outcome_feature_vector(record, "pitcher")

    diffs = [i for i, (a, b) in enumerate(zip(off, on)) if a != b]
    assert len(diffs) == 4
    assert all(on[i] == 0.0 for i in diffs)
    assert all(off[i] > 0.0 for i in diffs)
    # pick_value 8.0 and 1/draft_round 1.0 are among the zeroed features.
    assert {8.0, 1.0} <= {off[i] for i in diffs}


def test_pitcher_pedigree_decay_fresh_and_midpoint_and_unknown(monkeypatch):
    from prospects import model

    monkeypatch.setattr(model, "PITCHER_STALE_PEDIGREE_DECAY_ENABLED", True)
    fresh = _stale_arm(draft_year=2020)  # 1 year: factor 1.0
    monkeypatch.setattr(model, "PITCHER_STALE_PEDIGREE_DECAY_ENABLED", False)
    fresh_off = _outcome_feature_vector(fresh, "pitcher")
    monkeypatch.setattr(model, "PITCHER_STALE_PEDIGREE_DECAY_ENABLED", True)
    assert _outcome_feature_vector(fresh, "pitcher") == fresh_off

    mid = _stale_arm(draft_year=2018)  # 3 years: factor (5-3)/(5-2) = 2/3
    vector = _outcome_feature_vector(mid, "pitcher")
    assert any(abs(value - 8.0 * (2 / 3)) < 1e-9 for value in vector)

    unknown = _stale_arm(draft_year=None)
    monkeypatch.setattr(model, "PITCHER_STALE_PEDIGREE_DECAY_ENABLED", False)
    unknown_off = _outcome_feature_vector(unknown, "pitcher")
    monkeypatch.setattr(model, "PITCHER_STALE_PEDIGREE_DECAY_ENABLED", True)
    assert _outcome_feature_vector(unknown, "pitcher") == unknown_off


def test_pitcher_pedigree_decay_uses_sample_season_for_current_rows(monkeypatch):
    from prospects import model

    monkeypatch.setattr(model, "PITCHER_STALE_PEDIGREE_DECAY_ENABLED", True)
    current = _stale_arm(draft_year=2020)
    del current["cohort_year"]
    current["sample_season"] = 2026  # 6 years since draft -> fully decayed
    vector = _outcome_feature_vector(current, "pitcher")
    assert 8.0 not in vector  # pick_value zeroed


def test_pitcher_pedigree_decay_never_touches_hitters(monkeypatch):
    from prospects import model

    hitter = _historical(
        "hitter", 2021, 12, "role",
        draft_year=2015, draft_pick_number=5, signing_bonus=6_000_000,
    )
    off = _outcome_feature_vector(hitter, "hitter")
    monkeypatch.setattr(model, "PITCHER_STALE_PEDIGREE_DECAY_ENABLED", True)
    assert _outcome_feature_vector(hitter, "hitter") == off


def test_role_training_servable_when_validation_infeasible():
    """Walk-forward needs >= 3 training cohorts to emit a validation fold.
    Fold-local backtest training (rank-gate v1) can have fewer: the model must
    still be servable, with None metrics and an insufficient-sample gate --
    never a crash."""
    single_cohort = [
        _historical("hitter", 2014, mlbam_id, ("bust", "role", "star")[mlbam_id % 3])
        for mlbam_id in range(1, 40)
    ]
    result = train_role("hitter", single_cohort, now="2026-06-12")
    assert result["prediction_model"]
    assert result["validation_sample"] == 0
    assert result["model_mae"] is None
    assert result["rank_concordance"] is None
    assert result["gate"]["status"] == "insufficient_sample"


def test_partial_impact_axis_values_reliever_season_without_starter_volume():
    seasons = {
        "99_pitcher": [{
            "year": 2019,
            "ip": 62,
            "era": 2.40,
            "so": 90,
            "sv": 28,
        }]
    }
    references = _impact_references(seasons)
    record = {"mlbam_id": 99, "cohort_year": 2018}
    assert _impact_target(record, "pitcher", seasons, references) > 0


def test_category_impact_uses_canonical_save_plus_hold_category():
    seasons = {
        "99_pitcher": [{
            "year": 2019,
            "ip": 62,
            "era": 2.40,
            "so": 90,
            "sv": 18,
            "hld": 10,
        }]
    }
    references = _impact_references(seasons)
    assert _category_value(seasons["99_pitcher"][0], "sv_hld") == 28
    assert "sv_hld" in _active_impact_categories(references, "pitcher")
    assert "sv" not in _active_impact_categories(references, "pitcher")


def test_pitcher_impact_uses_better_applicable_sp_or_rp_category_group():
    seasons = {
        "98_pitcher": [{
            "year": 2019,
            "ip": 180,
            "so": 200,
            "qs": 20,
            "sv": 0,
            "hld": 0,
            "era": 3.00,
            "whip": 1.00,
            "k_bb": 4.0,
            "l": 8,
        }],
        "99_pitcher": [{
            "year": 2019,
            "ip": 62,
            "so": 100,
            "qs": 0,
            "sv": 30,
            "hld": 10,
            "era": 2.50,
            "whip": 0.90,
            "k_bb": 5.0,
            "l": 3,
        }],
    }
    references = _impact_references(seasons)
    record = {"mlbam_id": 99, "cohort_year": 2018}
    assert _impact_target(record, "pitcher", seasons, references) == pytest.approx(
        2 / 3
    )


def test_impact_target_ignores_seasons_past_the_outcome_horizon():
    # cohort 2018 + 4-year horizon closes at 2022; a 2024 season is post-fold
    # look-ahead and must not seal the training label. Regression lock for the F4
    # walk-forward leak (labels were sealed with results after the fold year).
    elite = {
        "year": 2024,
        "ip": 200,
        "so": 240,
        "qs": 25,
        "sv": 0,
        "hld": 0,
        "era": 2.20,
        "whip": 0.90,
        "k_bb": 6.0,
        "l": 4,
    }
    record = {"mlbam_id": 77, "cohort_year": 2018}
    seasons_out = {"77_pitcher": [elite]}
    assert (
        _impact_target(record, "pitcher", seasons_out, _impact_references(seasons_out))
        == 0.0
    )
    seasons_in = {"77_pitcher": [dict(elite, year=2021)]}
    assert (
        _impact_target(record, "pitcher", seasons_in, _impact_references(seasons_in))
        > 0
    )


def test_partial_impact_training_emits_valid_gate():
    contract = _contract()
    references = _impact_references(contract["historical_mlb_seasons"])
    result = train_impact_role(
        "pitcher",
        contract["historical"]["rows"],
        contract["historical_mlb_seasons"],
        references,
        now="2026-06-12",
    )
    assert validate_gate(result["gate"])
    assert result["gate"]["metric"] == "category_impact_mae"
    assert result["gate"]["baseline"] in {
        "level_age_prior",
        "historical_neighbors_25",
        "canonical_historical_neighbors_25",
    }


def test_hitter_impact_uses_hurdle_model_and_preserves_canonical_baseline():
    contract = _contract()
    references = _impact_references(contract["historical_mlb_seasons"])
    rows = _historical_impact_rows(
        contract["historical"]["rows"],
        "hitter",
        contract["historical_mlb_seasons"],
        references,
    )
    assert rows[0]["features"] != rows[0]["baseline_features"]
    result = train_impact_role(
        "hitter",
        contract["historical"]["rows"],
        contract["historical_mlb_seasons"],
        references,
        now="2026-06-12",
    )
    assert result["model_kind"] == "hurdle_ridge"
    assert result["canonical_neighbor_mae"] > 0


def test_hurdle_prediction_multiplies_arrival_and_conditional_impact():
    rows = [
        {"features": [0.0], "target": 0.0},
        {"features": [1.0], "target": 0.5},
        {"features": [2.0], "target": 1.0},
    ]
    model = _fit_prediction_model(rows, "hurdle_ridge", ridge_lambda=3.0)
    prediction = _predict_model(model, [1.0])
    assert prediction == pytest.approx(
        _predict_model(
            {"model_kind": "ridge", **model["arrival_model"]},
            [1.0],
        )
        * _predict_model(
            {"model_kind": "ridge", **model["conditional_model"]},
            [1.0],
        )
    )


def test_prediction_drivers_use_hurdle_score_and_group_aaa_translation():
    model = {
        "model_kind": "hurdle_ridge",
        "arrival_model": {
            "weights": [0.5, 0.2, -0.3, 0.4],
            "means": [0.0, 0.0, 0.0],
            "stds": [1.0, 1.0, 1.0],
        },
        "conditional_model": {
            "weights": [0.5, -0.1, 0.2, 0.1],
            "means": [0.0, 0.0, 0.0],
            "stds": [1.0, 1.0, 1.0],
        },
    }
    features = [1.0, 1.0, 1.0]
    drivers = _prediction_drivers(
        model,
        features,
        ("ops", "level", "ops_x_level"),
        {"aaa_translation": ("level", "ops_x_level")},
    )
    by_name = {driver["feature"]: driver["contribution"] for driver in drivers}
    neutral = [1.0, 0.0, 0.0]
    assert by_name["aaa_translation"] == pytest.approx(
        _predict_model(model, features) - _predict_model(model, neutral)
    )
    assert "level" not in by_name
    assert "ops_x_level" not in by_name


def test_impact_rows_train_on_rich_features_with_canonical_knn_baseline():
    record = _historical("hitter", 2015, 1, "star", level="A+", age=20)
    refs = _impact_references({})

    rows = _historical_impact_rows([record], "hitter", {}, refs)

    # The impact axis now trains on the same rich factual vector as the outcome
    # axis, so the validated predictor and the shipped predictor share inputs.
    assert rows[0]["features"] == _outcome_feature_vector(record, "hitter")
    # The simple fixed-interaction vector is preserved, distinct and smaller,
    # as the canonical kNN baseline the impact gate must still beat.
    assert rows[0]["baseline_features"] == _canonical_impact_feature_vector(
        _feature_vector(record, "hitter"), "hitter"
    )
    assert len(rows[0]["baseline_features"]) < len(rows[0]["features"])


def test_shadow_output_is_valucast_owned_and_service_gated():
    contract = _contract()
    contract["mlb_service"][1]["graduated"] = True
    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    assert payload["status"] == "shadow_only"
    assert payload["model_name"] == "ValuCast Prospect Model"
    assert payload["release_contract"] == {
        "artifact_status_semantics": "provenance_label_not_serving_status",
        "consumer": "prospect_rank_v1",
        "feeds_live_valucast_rank": True,
        "model_score_weight": 0.76,
        "standalone_public_board": False,
    }
    assert not any(
        "never consumed by the live prospect board" in limitation
        for limitation in payload["limitations"]
    )
    assert any(
        "full-store percentile references" in limitation
        and "fold-local replay" in limitation
        for limitation in payload["limitations"]
    )
    assert payload["input_contract"]["source_policy"]["external_rankings_used"] is False
    assert validate_gate(payload["board_gate"])
    assert validate_gate(payload["impact_board_gate"])
    assert payload["impact_target_contract"]["direct_7x7"] is False
    assert [row["mlbam_id"] for row in payload["ranked"]] == [1]
    assert payload["ranked"][0]["valucast_prospect_rank"] == 1
    assert "expected_category_impact_score" in payload["ranked"][0]
    assert {row["valucast_impact_rank"] for row in payload["ranked"]} == {1}


def test_missing_service_fact_fails_closed():
    contract = _contract()
    contract["mlb_service"] = []
    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    assert payload["ranked"] == []


def test_impact_drivers_do_not_use_plain_ridge_driver_weights():
    contract = _contract()
    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    before = score_current(contract, payload["roles"], payload["impact_roles"])
    for role_model in payload["impact_roles"].values():
        role_model["weights"] = [999.0 for _ in role_model["weights"]]
    after = score_current(contract, payload["roles"], payload["impact_roles"])
    assert [
        (row["expected_category_impact_score"], row["impact_drivers"])
        for row in after
    ] == [
        (row["expected_category_impact_score"], row["impact_drivers"])
        for row in before
    ]


def test_outcome_scores_use_validated_prediction_model_not_driver_weights():
    contract = _contract()
    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    before = score_current(contract, payload["roles"], payload["impact_roles"])
    for role_model in payload["roles"].values():
        role_model["weights"] = [999.0 for _ in role_model["weights"]]
    after = score_current(contract, payload["roles"], payload["impact_roles"])
    assert [row["expected_outcome_score"] for row in after] == [
        row["expected_outcome_score"] for row in before
    ]


def test_stale_current_correction_pulls_prior_only_when_current_is_worse():
    # W2.4 stale-current comparator: a prior-year line is the largest sample (so the
    # model selects it), but a current-season line exists. The score is pulled DOWN
    # toward a WORSE current line; a player with no current line is untouched; a
    # player already scored on a current line is untouched.
    contract = _contract()
    cur = contract["current"]

    def hitter(mid, **kw):
        base = {
            "mlbam_id": mid, "name": f"H{mid}", "normalized_name": f"h{mid}",
            "team": "Club", "role": "hitter", "position": "OF", "level": "AA",
            "age": 21, "iso": 0.20, "k_pct": 18.0, "bb_pct": 11.0, "ops": 0.880,
        }
        base.update(kw)
        return base

    cur["hitters"] += [
        # 3: good prior (300 PA) + thin/bad current (40 PA) -> pull DOWN
        hitter(3, plate_appearances=300, ops=0.900, iso=0.24,
               sample_season=2025, source_kind="latest_milb_history"),
        hitter(3, plate_appearances=40, ops=0.500, iso=0.05, k_pct=34.0, bb_pct=4.0,
               sample_season=2026, source_kind="current_season"),
        # 4: prior only, no current line -> untouched (no comparator)
        hitter(4, plate_appearances=300, ops=0.900, iso=0.24,
               sample_season=2025, source_kind="latest_milb_history"),
        # 5: current-selected line clears the floor -> untouched
        hitter(5, plate_appearances=200, ops=0.880,
               sample_season=2026, source_kind="current_season"),
    ]
    for mid in (3, 4, 5):
        contract["mlb_service"].append(
            {"mlbam_id": mid, "role": "hitter", "ab": 0, "ip": 0, "graduated": False}
        )

    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    rows = {
        r["mlbam_id"]: r
        for r in score_current(contract, payload["roles"], payload["impact_roles"])
    }

    # prior selected + worse current -> corrected DOWN, pull within the
    # floored/capped band [STALE_PULL_FLOOR, STALE_PULL_CAP] = [0.40, 0.60]
    # (floored so a thin-but-damning current line still corrects a stale score).
    sc = rows[3].get("stale_current_correction")
    assert sc is not None
    assert rows[3]["expected_outcome_score"] < sc["raw_outcome"]
    assert 0.40 <= sc["pull_weight"] <= 0.60
    # prior with no current line -> untouched
    assert "stale_current_correction" not in rows[4]
    # current-selected -> untouched
    assert "stale_current_correction" not in rows[5]


def test_stale_current_correction_skips_tiny_but_good_current_line():
    # The bad-line guard: a good prior + a TINY but GOOD current line must NOT pull.
    # Small-sample regression makes the current model score low, but the factual line
    # is fine, so it is not "worse" (the Andrew Sears case).
    contract = _contract()

    def hitter(mid, **kw):
        base = {
            "mlbam_id": mid, "name": f"H{mid}", "normalized_name": f"h{mid}",
            "team": "Club", "role": "hitter", "position": "OF", "level": "AA",
            "age": 21, "iso": 0.20, "k_pct": 18.0, "bb_pct": 11.0, "ops": 0.880,
        }
        base.update(kw)
        return base

    contract["current"]["hitters"] += [
        hitter(6, plate_appearances=300, ops=0.900, iso=0.24,
               sample_season=2025, source_kind="latest_milb_history"),
        # tiny (40 PA) but strong line: good ops/iso, elite discipline -> guard blocks
        hitter(6, plate_appearances=40, ops=0.920, iso=0.25, k_pct=16.0, bb_pct=12.0,
               sample_season=2026, source_kind="current_season"),
        # 9: good prior + 1 PA .000 OPS -- egregious-looking but pure noise -> no pull
        hitter(9, plate_appearances=300, ops=0.900, iso=0.24,
               sample_season=2025, source_kind="latest_milb_history"),
        hitter(9, plate_appearances=1, ops=0.000, iso=0.000, k_pct=100.0, bb_pct=0.0,
               sample_season=2026, source_kind="current_season"),
    ]
    for mid in (6, 9):
        contract["mlb_service"].append(
            {"mlbam_id": mid, "role": "hitter", "ab": 0, "ip": 0, "graduated": False}
        )

    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    rows = {
        r["mlbam_id"]: r
        for r in score_current(contract, payload["roles"], payload["impact_roles"])
    }
    assert "stale_current_correction" not in rows[6]
    assert "stale_current_correction" not in rows[9]  # 1 PA egregious -> floored out


def test_stale_current_correction_pitcher_tiny_sample_guard():
    # A tiny current pitcher line (<10 IP) must NOT pull regardless of how egregious --
    # symmetric with the hitter floor, guarding the Eriq Swan / Blake Burkhalter false
    # positives (sub-floor egregious is covered by INV-BADLINE-1). An egregious collapse
    # AT the 10-IP floor does pull.
    contract = _contract()

    def pitcher(mid, **kw):
        base = {
            "mlbam_id": mid, "name": f"P{mid}", "normalized_name": f"p{mid}",
            "team": "Club", "role": "pitcher", "position": "P", "level": "AA",
            "age": 22, "k_per_9": 10.0, "bb_per_9": 2.5, "k_bb_pct": 18.0,
            "era": 2.80, "whip": 1.10, "is_starter": True,
        }
        base.update(kw)
        return base

    contract["current"]["pitchers"] += [
        # 7: good prior (80 IP) + tiny fine current (8 IP, mixed ratios) -> NO pull
        pitcher(7, level="A+", innings_pitched=80, sample_season=2025,
                source_kind="latest_milb_history"),
        pitcher(7, innings_pitched=8, era=4.20, whip=1.40, k_bb_pct=15.0,
                sample_season=2026, source_kind="current_season"),
        # 8: good prior + egregious current AT the 10-IP floor -> pull
        pitcher(8, level="A+", innings_pitched=80, sample_season=2025,
                source_kind="latest_milb_history"),
        pitcher(8, innings_pitched=10, era=9.00, whip=2.10, k_bb_pct=3.0,
                sample_season=2026, source_kind="current_season"),
    ]
    for mid in (7, 8):
        contract["mlb_service"].append(
            {"mlbam_id": mid, "role": "pitcher", "ab": 0, "ip": 0, "graduated": False}
        )

    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    rows = {
        r["mlbam_id"]: r
        for r in score_current(contract, payload["roles"], payload["impact_roles"])
    }
    assert "stale_current_correction" not in rows[7]  # tiny fine current -> no pull
    assert rows[8].get("stale_current_correction") is not None  # egregious at floor -> pull


def test_driver_refresh_preserves_every_non_driver_model_output():
    contract = _contract()
    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    expected_drivers = [
        row["impact_drivers"]
        for row in payload["ranked"]
    ]
    for row in payload["ranked"]:
        row["impact_drivers"] = [{"feature": "legacy_surrogate", "contribution": 9.0}]
    before_stable = [
        {key: value for key, value in row.items() if key != "impact_drivers"}
        for row in payload["ranked"]
    ]

    refreshed, changed = refresh_impact_drivers(payload, contract)

    assert changed == len(payload["ranked"])
    assert refreshed["board_gate"] == payload["board_gate"]
    assert refreshed["impact_board_gate"] == payload["impact_board_gate"]
    assert [
        {key: value for key, value in row.items() if key != "impact_drivers"}
        for row in refreshed["ranked"]
    ] == before_stable
    assert [row["impact_drivers"] for row in refreshed["ranked"]] == expected_drivers


def test_driver_refresh_fails_closed_if_a_score_changes():
    contract = _contract()
    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    contract["current"]["hitters"][0]["ops"] = 0.500
    with pytest.raises(ValueError, match="non-driver field"):
        refresh_impact_drivers(payload, contract)


def test_archive_is_deterministic(tmp_path):
    payload = build_shadow_model(_contract(), now="2026-06-12T00:00:00+00:00")
    path, changed = archive_predictions(payload, "2026-06-12", tmp_path / "archive")
    first = path.read_text(encoding="utf-8")
    same_path, changed_again = archive_predictions(
        payload, "2026-06-12", tmp_path / "archive"
    )
    assert path == same_path
    assert changed is True
    assert changed_again is False
    assert same_path.read_text(encoding="utf-8") == first


def test_run_model_writes_artifact_and_archive(tmp_path):
    input_path = tmp_path / "inputs.json"
    input_path.write_text(json.dumps(_contract()), encoding="utf-8")
    result = run_model(
        input_path=input_path,
        artifact_path=tmp_path / "model.json",
        archive_dir=tmp_path / "archive",
        now="2026-06-12T00:00:00+00:00",
    )
    assert result["candidates"] == 2
    assert result["impact_gate"] in {"active", "fallback"}
    assert (tmp_path / "model.json").exists()
    assert (tmp_path / "archive" / "2026-06-12.json").exists()


def test_load_contract_validates_schema(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": "0"}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        load_input_contract(path)


def test_pedigree_features_are_real_pitcher_outcome_features():
    from prospects.model import PITCHER_PEDIGREE_FEATURES

    # A typo'd/stale name here would make the pedigree-shrink shadow a silent
    # no-op (the also_shrink lookup in _regress_current_features matches by name
    # against role_model["feature_names"], which mirrors OUTCOME_FEATURE_NAMES).
    assert PITCHER_PEDIGREE_FEATURES <= set(OUTCOME_FEATURE_NAMES["pitcher"])


def test_also_shrink_pulls_named_features_toward_mean_but_leaves_others_fixed():
    from prospects.model import PITCHER_PEDIGREE_FEATURES

    feature_names = OUTCOME_FEATURE_NAMES["pitcher"]
    means = [0.0] * len(feature_names)
    role_model = {"feature_names": feature_names, "means": means}
    # A high-pedigree, bad-performance line: performance features far from the
    # (zero) mean, pedigree features also far from the mean.
    features = [10.0] * len(feature_names)
    sample = 30.0  # thin -> low reliability, so shrinkage is substantial either way

    default_out, reliability = _regress_current_features(
        features, role_model, "pitcher", sample
    )
    pedigree_out, _ = _regress_current_features(
        features, role_model, "pitcher", sample, also_shrink=PITCHER_PEDIGREE_FEATURES
    )
    assert 0.0 < reliability < 1.0
    for index, name in enumerate(feature_names):
        if name in PITCHER_PEDIGREE_FEATURES:
            # Shrunk in the pedigree-shadow pass...
            assert pedigree_out[index] == pytest.approx(reliability * 10.0)
            # ...but NOT in the default (served-score) pass -- the fix must never
            # change what's actually served.
            assert default_out[index] == 10.0
        else:
            # Every non-pedigree feature is identical in both passes.
            assert pedigree_out[index] == default_out[index]
