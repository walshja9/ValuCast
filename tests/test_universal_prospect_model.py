"""Contract tests for ValuCast's rank-free universal prospect model."""
import inspect
import json

import pytest

from prospects.gate import validate_gate
from prospects.universal import (
    TARGET_SPECS,
    _raw_target,
    _representative_season,
    _target_rows,
    _validation_score,
    archive_predictions,
    build_shadow_model,
    run_model,
)


def _historical(role, year, mlbam_id):
    row = {
        "cohort_year": year,
        "mlbam_id": mlbam_id,
        "name": f"Player {mlbam_id}",
        "role": role,
        "level": "AA" if mlbam_id % 2 else "AAA",
        "age": 21 + mlbam_id % 4,
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
    return row


def _contract(n_per_role=72):
    rows = []
    seasons = {}
    for role in ("hitter", "pitcher"):
        offset = 0 if role == "hitter" else 10000
        for index in range(1, n_per_role + 1):
            mlbam_id = index + offset
            row = _historical(role, 2014 + index % 6, mlbam_id)
            rows.append(row)
            established = index % 3 != 0
            if not established:
                seasons[f"{mlbam_id}_{role}"] = []
            elif role == "hitter":
                pa = 500 if index % 2 else 350
                seasons[f"{mlbam_id}_hitter"] = [
                    {
                        "year": row["cohort_year"] + 1,
                        "pa": pa,
                        "avg": 0.240 + index % 5 * 0.005,
                        "ops": 0.700 + index % 5 * 0.02,
                        "hr": 10 + index % 15,
                        "r": 60 + index % 30,
                        "rbi": 55 + index % 35,
                        "sb": 4 + index % 12,
                        "so": 80 + index % 40,
                    }
                ]
            else:
                ip = 140 if index % 2 else 75
                seasons[f"{mlbam_id}_pitcher"] = [
                    {
                        "year": row["cohort_year"] + 1,
                        "ip": ip,
                        "era": 3.5 + index % 5 * 0.15,
                        "whip": 1.1 + index % 4 * 0.05,
                        "so": 80 + index % 90,
                        "k_bb": 2.5 + index % 5 * 0.4,
                        "qs": 10 + index % 15,
                        "sv": 0 if index % 3 else 12,
                        "hld": 0 if index % 4 else 15,
                        "l": 4 + index % 8,
                    }
                ]
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
                    "mlbam_id": 90001,
                    "name": "Current Hitter",
                    "normalized_name": "current hitter",
                    "role": "hitter",
                    "position": "SS",
                    "team": "AAA Club",
                    "level": "AAA",
                    "age": 21,
                    "plate_appearances": 180,
                    "iso": 0.220,
                    "k_pct": 20.0,
                    "bb_pct": 11.0,
                    "ops": 0.850,
                }
            ],
            "pitchers": [
                {
                    "mlbam_id": 90002,
                    "name": "Current Pitcher",
                    "normalized_name": "current pitcher",
                    "role": "pitcher",
                    "position": "P",
                    "team": "AA Club",
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
            {"mlbam_id": 90001, "role": "hitter", "graduated": False},
            {"mlbam_id": 90002, "role": "pitcher", "graduated": False},
        ],
    }


def test_universal_module_has_no_rank_or_fantasy_value_target():
    import prospects.universal as universal

    source = inspect.getsource(universal).lower()
    forbidden = (
        "pipeline_rank",
        "get_dynasty_value",
        "category_impact",
        "valucast_prospect_rank",
        "valucast_impact_rank",
    )
    assert not any(token in source for token in forbidden)


def test_representative_season_is_highest_volume_not_best_category():
    row = {"mlbam_id": 1, "cohort_year": 2018}
    seasons = {
        "1_hitter": [
            {"year": 2019, "pa": 320, "hr": 40},
            {"year": 2020, "pa": 600, "hr": 12},
        ]
    }
    assert _representative_season(row, "hitter", seasons)["year"] == 2020
    assert _raw_target(row, "hitter", "representative_hr_per_600", seasons) == 12


def test_probability_targets_include_non_established_players_but_conditionals_do_not():
    contract = _contract()
    probabilities = _target_rows(
        contract["historical"]["rows"],
        contract["historical_mlb_seasons"],
        "hitter",
        "established_probability",
    )
    conditionals = _target_rows(
        contract["historical"]["rows"],
        contract["historical_mlb_seasons"],
        "hitter",
        "representative_ops",
    )
    assert len(probabilities) == 72
    assert len(conditionals) == 48
    assert {row["target"] for row in probabilities} == {0.0, 1.0}


def test_probability_gate_uses_brier_while_continuous_targets_use_mae():
    predictions = [0.2, 0.6]
    targets = [0.0, 1.0]
    assert _validation_score(predictions, targets, "probability") == pytest.approx(0.1)
    assert _validation_score(predictions, targets, "conditional") == pytest.approx(0.3)


def test_shadow_output_is_rank_free_and_independently_gated():
    payload = build_shadow_model(_contract(), now="2026-06-12T00:00:00+00:00")
    assert payload["status"] == "shadow_only"
    assert payload["research_status"] == "mixed_evidence"
    assert payload["target_contract"]["rank_free"] is True
    assert payload["target_contract"]["league_scoring_independent"] is True
    assert payload["candidate_count"] == 2
    assert all("rank" not in profile for profile in payload["profiles"])
    assert {
        "representative_r_per_600",
        "representative_rbi_per_600",
    } <= set(payload["roles"]["hitter"])
    assert {
        "representative_qs_per_180",
        "representative_sv_hld_per_60",
        "representative_l_per_180",
    } <= set(payload["roles"]["pitcher"])
    for role, targets in payload["roles"].items():
        assert set(targets) == set(TARGET_SPECS[role])
        for target in targets.values():
            assert validate_gate(target["gate"])
            assert target["transform"]["kind"] in {
                "identity_clamped_0_1",
                "fixed_linear_clamped_0_1",
            }
            assert target["prediction_source"] in {
                "ridge",
                "level_age_prior",
                "historical_neighbors_25",
                "canonical_historical_neighbors_25",
            }


def test_v11_contract_accepts_lower_minors_and_expanded_factual_sources():
    contract = _contract()
    contract["schema_version"] = "1.1"
    contract["source_policy"]["sources"] = [
        "valucast_universal_prospect_dataset",
        "milb_season_stats",
        "fantrax_mlb_actuals",
        "mlb_prospect_seasons_cache",
        "mlb_statsapi_draft",
    ]
    lower = contract["historical"]["rows"][0]
    lower.update(
        {
            "level": "A",
            "plate_appearances": 300,
            "avg": 0.270,
            "obp": 0.360,
            "slg": 0.450,
            "babip": 0.320,
            "home_runs": 15,
            "stolen_bases": 20,
            "draft_record_known": True,
            "rule4_drafted": True,
            "draft_pick_number": 25,
            "signing_bonus": 3_000_000,
            "school_type": "college",
        }
    )
    rows = _target_rows(
        contract["historical"]["rows"],
        contract["historical_mlb_seasons"],
        "hitter",
        "established_probability",
    )
    selected = next(row for row in rows if row["mlbam_id"] == lower["mlbam_id"])
    assert selected["level"] == "A"
    assert len(selected["features"]) == len(
        build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")["roles"][
            "hitter"
        ]["established_probability"]["feature_names"]
    )
    assert len(selected["features"]) > len(selected["baseline_features"])


def test_missing_service_fact_fails_closed():
    contract = _contract()
    contract["mlb_service"] = []
    payload = build_shadow_model(contract, now="2026-06-12T00:00:00+00:00")
    assert payload["profiles"] == []


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


def test_run_model_writes_separate_artifact_and_archive(tmp_path):
    input_path = tmp_path / "inputs.json"
    input_path.write_text(json.dumps(_contract()), encoding="utf-8")
    result = run_model(
        input_path=input_path,
        artifact_path=tmp_path / "universal.json",
        archive_dir=tmp_path / "archive",
        now="2026-06-12T00:00:00+00:00",
    )
    assert result["research_status"] == "mixed_evidence"
    assert result["candidates"] == 2
    assert set(result["target_status_counts"]) == {
        "active",
        "fallback",
        "failed",
        "insufficient_sample",
    }
    assert (tmp_path / "universal.json").exists()
    assert (tmp_path / "archive" / "2026-06-12.json").exists()
