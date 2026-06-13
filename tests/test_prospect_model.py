"""Contract tests for ValuCast's independent prospect model."""
import inspect
import json

import pytest

from prospects.gate import validate_gate
from prospects.model import (
    _active_impact_categories,
    _canonical_impact_feature_vector,
    _category_value,
    _fit_prediction_model,
    _historical_rows,
    _historical_impact_rows,
    _impact_feature_vector,
    _impact_references,
    _impact_target,
    _predict_model,
    _regress_current_features,
    _select_current_records,
    _walk_forward,
    archive_predictions,
    build_shadow_model,
    load_input_contract,
    run_model,
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
        "schema_version": "1.0",
        "generated_at": "2026-06-12T00:00:00+00:00",
        "source_policy": {
            "kind": "factual_only",
            "sources": [
                "prospect_outcome_dataset",
                "milb_season_stats",
                "fantrax_mlb_actuals",
                "mlb_prospect_seasons_cache",
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
    with pytest.raises(ValueError, match="prohibited"):
        validate_input_contract(contract)


def test_contract_rejects_unexpected_source_even_when_flags_are_false():
    contract = _contract()
    contract["source_policy"]["sources"].append("external_rank")
    with pytest.raises(ValueError, match="unexpected source"):
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


def test_role_training_emits_valid_honest_gate():
    result = train_role("hitter", _contract()["historical"]["rows"], now="2026-06-12")
    assert validate_gate(result["gate"])
    assert result["validation_sample"] >= 250
    assert result["gate"]["baseline"] in {
        "level_age_prior",
        "historical_neighbors_25",
    }


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


def test_hitter_translation_interactions_do_not_change_canonical_features():
    base = [0.2, 20.0, 10.0, 0.8, 1.0, 1.0]
    canonical = _canonical_impact_feature_vector(base, "hitter")
    expanded = _impact_feature_vector(base, "hitter")
    assert expanded[: len(canonical)] == canonical
    assert len(expanded) > len(canonical)


def test_shadow_output_is_valucast_owned_and_service_gated():
    contract = _contract()
    contract["mlb_service"][1]["graduated"] = True
    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    assert payload["status"] == "shadow_only"
    assert payload["model_name"] == "ValuCast Prospect Model"
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
    with pytest.raises(ValueError, match="Unsupported"):
        load_input_contract(path)
