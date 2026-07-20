import json
import importlib
import importlib.util
from pathlib import Path

import pytest

from prospects import challenger_eval
from prospects.challenger_eval import (
    FORBIDDEN_SEEDS,
    HITTER_RATE_FIELDS,
    REGISTERED_SEED,
    fold_local_contract,
    normalize_rows,
    prepare_fold,
)


def _row(player, *, year=2018, role="hitter", level="AA", iso=.100):
    return {
        "mlbam_id": player,
        "cohort_year": year,
        "role": role,
        "level": level,
        "iso": iso,
        "k_pct": 20.0,
        "bb_pct": 8.0,
        "ops": .700,
        "avg": .250,
        "obp": .320,
        "slg": .380,
        "babip": .300,
    }


def test_leave_one_out_quantile_is_tie_aware_and_non_affine():
    rows = [
        _row(1, iso=.100),
        _row(2, iso=.200),
        _row(3, iso=.200),
        _row(4, iso=.900),
    ]
    normalized, diagnostics = normalize_rows(
        rows, same_level_min=2, role_season_min=3
    )
    by_id = {row["mlbam_id"]: row for row in normalized}
    assert by_id[2]["iso"] == by_id[3]["iso"]
    assert [by_id[i]["iso"] for i in (1, 2, 4)] != [.1, .2, .9]
    assert diagnostics["unavailable"] == 0


def test_sparse_level_backs_off_and_sparse_role_season_is_unavailable():
    rows = [
        _row(i, level="AA" if i == 1 else "AAA", iso=i / 10)
        for i in range(1, 6)
    ]
    normalized, diagnostics = normalize_rows(
        rows, same_level_min=2, role_season_min=3
    )
    assert diagnostics["backoff_rows"] >= 1
    _, blocked = normalize_rows(rows[:2], same_level_min=2, role_season_min=3)
    assert blocked["unavailable"] == 2


def test_blank_level_never_forms_a_same_level_reference_cell():
    for level in ("", None):
        normalized, diagnostics = normalize_rows(
            [_row(player, level=level) for player in range(1, 27)],
            same_level_min=25,
            role_season_min=25,
        )
        assert len(normalized) == 26
        assert diagnostics["same_level_rows"] == 0
        assert diagnostics["backoff_rows"] == 26
        assert diagnostics["unavailable"] == 0


def test_current_rows_use_sample_season_and_missing_season_fails_closed():
    rows = []
    for player in range(1, 5):
        row = _row(player)
        row.pop("cohort_year")
        row["sample_season"] = 2026
        rows.append(row)
    missing_season = _row(5)
    missing_season.pop("cohort_year")
    rows.append(missing_season)
    normalized, diagnostics = normalize_rows(
        rows, same_level_min=3, role_season_min=3
    )
    assert {row["mlbam_id"] for row in normalized} == {1, 2, 3, 4}
    assert diagnostics["unavailable"] == 1
    assert (
        diagnostics["reference_years"]["2026"]["hitter"]["exercised_coverage"]
        == 1.0
    )
    assert diagnostics["reference_years"]["unknown"]["hitter"]["unavailable"] == 1


def test_outcome_mutation_cannot_change_normalized_inputs():
    rows = [_row(i, iso=i / 100) | {"outcome": "bust"} for i in range(1, 30)]
    first = normalize_rows(rows, same_level_min=25, role_season_min=250)
    mutated = [dict(row, outcome="star") for row in rows]
    second = normalize_rows(mutated, same_level_min=25, role_season_min=250)
    first_rates = [
        tuple(row[field] for field in HITTER_RATE_FIELDS) for row in first[0]
    ]
    second_rates = [
        tuple(row[field] for field in HITTER_RATE_FIELDS) for row in second[0]
    ]
    assert first_rates == second_rates
    assert first[1] == second[1]


def test_test_cohort_seasons_never_enter_fold_local_impact_references():
    contract = {
        "historical": {
            "rows": [
                {"mlbam_id": 1, "role": "hitter", "cohort_year": 2014},
                {"mlbam_id": 2, "role": "hitter", "cohort_year": 2018},
            ]
        },
        "historical_mlb_seasons": {
            "1_hitter": [
                {"year": 2015, "pa": 500, "hr": 10},
                {"year": 2020, "pa": 500, "hr": 40},
            ],
            "2_hitter": [{"year": 2019, "pa": 500, "hr": 99}],
        },
    }
    fold = fold_local_contract(contract, test_year=2018)
    assert set(fold["historical_mlb_seasons"]) == {"1_hitter"}
    assert [
        season["year"] for season in fold["historical_mlb_seasons"]["1_hitter"]
    ] == [2015]


def test_invalid_training_row_cannot_bypass_final_horizon_clip():
    invalid = _row(1, year=2014) | {"age": 99}
    fold = fold_local_contract(
        {
            "historical": {"rows": [invalid]},
            "historical_mlb_seasons": {
                "1_hitter": [{"year": 2015}, {"year": 2030}],
            },
        },
        test_year=2018,
    )
    assert [
        season["year"] for season in fold["historical_mlb_seasons"]["1_hitter"]
    ] == [2015]


def test_prepare_fold_keeps_exact_available_identities_and_reports_role_coverage():
    rows = [_row(player) for player in range(1, 28)]
    rows[0].pop("iso")
    missing_season = _row(28)
    missing_season.pop("cohort_year")
    rows.append(missing_season)
    prepared = prepare_fold(
        {
            "historical": {"rows": rows},
            "historical_mlb_seasons": {},
        },
        test_year=2018,
    )
    expected = {(2018, player, "hitter") for player in range(2, 28)}
    for name in ("control_contract", "candidate_contract"):
        assert {
            (row["cohort_year"], row["mlbam_id"], row["role"])
            for row in prepared[name]["historical"]["rows"]
        } == expected
    assert {
        tuple(identity) for identity in prepared["common_identities"]["hitter"]
    } == expected
    assert prepared["common_identities"]["pitcher"] == []
    assert prepared["coverage"]["hitter"]["rows"] == 27
    assert prepared["coverage"]["hitter"]["unavailable"] == 1
    assert prepared["coverage"]["hitter"]["exercised_coverage"] == 26 / 27


def test_registered_seed_is_fresh_and_forbidden_seeds_stay_forbidden():
    assert REGISTERED_SEED == 33021
    assert REGISTERED_SEED not in FORBIDDEN_SEEDS
    assert FORBIDDEN_SEEDS == {28013, 28017, 29001, 31013, 31017}


def test_registered_fold_keys_are_not_inferred_from_observed_years():
    observed = (2000, 2014, 2015, 2016, 2017, 2018, 2019, 2021)
    _, diagnostics = normalize_rows(
        [_row(player, year=year) for player, year in enumerate(observed, 1)],
        same_level_min=1,
        role_season_min=1,
    )
    assert tuple(diagnostics["folds"]) == (
        "2016",
        "2017",
        "2018",
        "2019",
        "2021",
        "2022",
    )
    assert set(diagnostics["reference_years"]) == {str(year) for year in observed}
    assert diagnostics["folds"]["2022"]["hitter"]["rows"] == 0
    assert diagnostics["folds"]["2022"]["hitter"]["exercised_coverage"] == 0.0


def test_real_input_exercises_challenger_without_outcome_values():
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "data/prospects/prospect_model_inputs.json")
        .read_text(encoding="utf-8")
    )
    rows = [
        {key: value for key, value in row.items() if key != "outcome"}
        for row in payload["historical"]["rows"]
    ]
    _, diagnostics = normalize_rows(rows)
    assert diagnostics["overall"]["rows"] == 6756
    assert diagnostics["overall"]["available"] == 6756
    assert set(diagnostics["reference_years"]) == {
        "2014",
        "2015",
        "2016",
        "2017",
        "2018",
        "2019",
        "2021",
        "2022",
    }
    assert set(diagnostics["folds"]) == {
        "2016",
        "2017",
        "2018",
        "2019",
        "2021",
        "2022",
    }
    for fold in diagnostics["folds"].values():
        for role in ("hitter", "pitcher"):
            assert fold[role]["exercised_coverage"] >= 0.90
            counts = fold[role]["reference_counts"]["role_season"]
            assert (
                336
                <= counts["cell_size"]["minimum"]
                <= counts["cell_size"]["maximum"]
                <= 410
            )
            assert (
                335
                <= counts["other_peers"]["minimum"]
                <= counts["other_peers"]["maximum"]
                <= 409
            )


def _fixture_registration(
    *, reference_years=(2018,), scored_years=(2018,)
) -> dict:
    return {
        "registered_at": "2026-07-20",
        "reference_fold_years": list(reference_years),
        "scored_fold_years": list(scored_years),
        "minimum_exercised_coverage": 0.90,
        "adjudication": {
            "build_track_criteria": {
                "minimum_cohorts": 3,
                "minimum_unique_players": 250,
                "minimum_outcome_coverage": 0.90,
                "minimum_relative_improvement_pct": 5.0,
                "maximum_single_cohort_regression_pct": 5.0,
                "maximum_segment_regression_pct": 5.0,
                "top_k": 25,
                "bootstrap_seed": 33021,
                "bootstrap_resamples": 10_000,
            }
        },
        "hitter_position_audit": {
            "minimum_non_null_coverage_each_fold": 0.90,
            "allowed_raw_labels": [
                "C",
                "1B",
                "2B",
                "3B",
                "SS",
                "LF",
                "CF",
                "RF",
                "OF",
                "DH",
            ],
            "reject_delimiters": ["/", ",", ";"],
        },
        "final_artifact_status_contract": {
            "top_level_status_mapping": {
                "research_only": "research_only",
                "validated_underperformance": "validated_underperformance",
                "no_significant_difference": "no_significant_difference",
                "collecting": "collecting",
            },
            "statistical_status_mapping": {
                "validated_superiority": "research_success",
                "validated_underperformance": "validated_underperformance",
                "no_significant_difference": "no_significant_difference",
                "collecting": "collecting",
            },
            "allowed_final_status_values": [
                "research_only",
                "research_success",
                "validated_underperformance",
                "no_significant_difference",
                "collecting",
            ],
            "forbidden_final_status_values": ["validated_superiority"],
            "claim_authorized": False,
            "public_claim_eligible": False,
        },
        "public_claim_eligible": False,
    }


def _prepared(coverage: float, year: int = 2018) -> dict:
    rows = [
        {
            "mlbam_id": 1,
            "cohort_year": year,
            "role": "hitter",
            "age": 18,
            "level": "AA",
            "position": "SS",
        },
        {
            "mlbam_id": 2,
            "cohort_year": year,
            "role": "pitcher",
            "age": 20,
            "level": "AAA",
            "position": "P",
        },
    ]
    return {
        "control_contract": {"variant": "control", "historical": {"rows": rows}},
        "candidate_contract": {
            "variant": "normalized_production",
            "historical": {"rows": rows},
        },
        "common_identities": {
            "hitter": [[year, 1, "hitter"]],
            "pitcher": [[year, 2, "pitcher"]],
        },
        "coverage": {
            "hitter": {"exercised_coverage": coverage},
            "pitcher": {"exercised_coverage": coverage},
        },
    }


def _fixture_fold() -> dict:
    return {
        "scores": {("1", "hitter"): 0.8, ("2", "pitcher"): 0.7},
        "tiers": {("1", "hitter"): 1.0, ("2", "pitcher"): 0.5},
    }


def test_eligible_fold_years_uses_maturity_training_and_omission_contract():
    contract = {
        "historical": {
            "cohorts": [2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022],
            "omitted_cohorts": {"year": 2020},
        }
    }
    assert challenger_eval.eligible_fold_years(contract) == [2018, 2019, 2021]


def test_all_reference_fold_coverage_is_checked_before_any_score(monkeypatch):
    calls = []
    years = (2016, 2017, 2018, 2019, 2021, 2022)
    monkeypatch.setattr(challenger_eval, "eligible_fold_years", lambda _contract: [2018, 2019, 2021])
    monkeypatch.setattr(
        challenger_eval,
        "prepare_fold",
        lambda _contract, year: _prepared(0.89 if year == 2022 else 1.0, year),
    )
    monkeypatch.setattr(
        challenger_eval,
        "_fold_board_scores",
        lambda *_args, **_kwargs: calls.append(1),
    )
    report = challenger_eval.run_registered_replay(
        {}, _fixture_registration(reference_years=years, scored_years=(2018, 2019, 2021))
    )
    assert report["status"] == "invalid_coverage"
    assert report["registered_look_spent"] is False
    assert set(report["coverage"]) == {str(year) for year in years}
    assert calls == []


def test_control_and_candidate_use_identical_fold_identities(monkeypatch):
    monkeypatch.setattr(challenger_eval, "eligible_fold_years", lambda _contract: [2018])
    monkeypatch.setattr(challenger_eval, "prepare_fold", lambda _contract, year: _prepared(1.0, year))
    monkeypatch.setattr(
        challenger_eval,
        "_fold_board_scores",
        lambda _contract, _year: (_fixture_fold(), {}),
    )
    report = challenger_eval.run_registered_replay({}, _fixture_registration())
    assert report["identity_set_equal"] is True
    assert report["registered_look_spent"] is True
    assert report["claim_authorized"] is False
    assert report["public_claim_eligible"] is False


def test_registered_replay_uses_nested_criteria_and_final_status_mappings(monkeypatch):
    seen = []
    monkeypatch.setattr(challenger_eval, "eligible_fold_years", lambda _contract: [2018])
    monkeypatch.setattr(challenger_eval, "prepare_fold", lambda _contract, year: _prepared(1.0, year))
    monkeypatch.setattr(
        challenger_eval,
        "_fold_board_scores",
        lambda _contract, _year: (_fixture_fold(), {}),
    )

    def fake_track(_cohorts, _outcomes, criteria):
        seen.append(criteria)
        return {
            "status": "research_only",
            "statistical_status": "validated_superiority",
            "claim_authorized": False,
            "primary": {"valucast_error": 0.1, "competitor_error": 0.2},
        }

    monkeypatch.setattr(challenger_eval, "build_track", fake_track)
    registration = _fixture_registration()
    report = challenger_eval.run_registered_replay(
        {"historical_mlb_seasons": {"1_hitter": []}}, registration
    )
    assert seen == [
        registration["adjudication"]["build_track_criteria"],
        registration["adjudication"]["build_track_criteria"],
    ]
    for result in report["role_results"].values():
        assert result["status"] == "research_only"
        assert result["statistical_status"] == "research_success"
        assert result["claim_authorized"] is False
        assert result["public_claim_eligible"] is False
        assert result["primary"] == {
            "normalized_production_error": 0.1,
            "control_error": 0.2,
        }
    assert "validated_superiority" not in json.dumps(report)


def test_post_score_identity_mismatch_is_rejected(monkeypatch):
    monkeypatch.setattr(challenger_eval, "eligible_fold_years", lambda _contract: [2018])
    monkeypatch.setattr(challenger_eval, "prepare_fold", lambda _contract, year: _prepared(1.0, year))

    def score(contract, _year):
        fold = _fixture_fold()
        if contract["variant"] == "normalized_production":
            fold["scores"] = {("1", "hitter"): 0.8}
            fold["tiers"] = {("1", "hitter"): 1.0}
        return fold, {}

    monkeypatch.setattr(challenger_eval, "_fold_board_scores", score)
    with pytest.raises(
        challenger_eval.RegisteredLookSpentError,
        match="identity sets differ after scoring",
    ) as error:
        challenger_eval.run_registered_replay({}, _fixture_registration())
    assert error.value.report["registered_look_spent"] is True
    assert error.value.report["identity_set_equal"] is False
    assert error.value.report["role_results"] == {}


def test_adjudicator_error_after_scoring_records_the_spent_state(monkeypatch):
    monkeypatch.setattr(challenger_eval, "eligible_fold_years", lambda _contract: [2018])
    monkeypatch.setattr(challenger_eval, "prepare_fold", lambda _contract, year: _prepared(1.0, year))
    monkeypatch.setattr(
        challenger_eval,
        "_fold_board_scores",
        lambda _contract, _year: (_fixture_fold(), {}),
    )
    monkeypatch.setattr(
        challenger_eval,
        "build_track",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(challenger_eval.RegisteredLookSpentError, match="boom") as error:
        challenger_eval.run_registered_replay({}, _fixture_registration())
    assert error.value.report["registered_look_spent"] is True
    assert error.value.report["failure"] == "post_score_evaluation_error"


def test_current_variants_normalize_history_and_current_separately(monkeypatch):
    calls = []
    contract = {
        "historical": {"rows": [{"mlbam_id": 1, "cohort_year": 2018, "role": "hitter"}]},
        "current": {
            "fetched_date": "2026-07-20",
            "hitters": [
                {"mlbam_id": 10, "sample_season": 2026, "role": "hitter"},
                {"mlbam_id": 11, "sample_season": 2026, "role": "hitter"},
            ],
            "pitchers": [],
        },
    }

    def normalize(rows):
        calls.append(list(rows))
        kept = rows if "cohort_year" in rows[0] else rows[:1]
        return [dict(row, normalized=True) for row in kept], {"available": len(kept)}

    def build(model_contract, now):
        assert now == "2026-07-20T23:59:59+00:00"
        row = model_contract["current"]["hitters"][0]
        return {
            "ranked": [
                {
                    "mlbam_id": row["mlbam_id"],
                    "role": row["role"],
                    "valucast_prospect_rank": 1,
                }
            ]
        }

    monkeypatch.setattr(challenger_eval, "normalize_rows", normalize)
    monkeypatch.setattr(challenger_eval, "build_shadow_model", build)
    control, candidate, coverage = challenger_eval.score_current_variants(contract)
    assert len(calls) == 2
    assert control == candidate == {"10": 1}
    assert coverage["unavailable_current_identities"] == ["11"]


def _aaa_fixture():
    control = {"10": 1, "20": 2, "30": 3, "40": 4}
    candidate = {"10": 2, "20": 1, "30": 3, "40": 4}
    aaa = {
        "gates": {"min_pitcher_pitches": 250, "min_hitter_bip": 100},
        "hitters": {"10": {"n_pitches": 500, "n_bip": 120, "avg_ev": 90.0}},
        "pitchers": {
            "20": {"n_pitches": 400, "overall": {"whiff_pct": 30.0}, "pitch_types": {}},
            "30": {"n_pitches": 300, "overall": {"whiff_pct": 25.0}, "pitch_types": {}},
        },
    }
    current = [
        {"mlbam_id": 10, "role": "hitter", "level": "AAA"},
        {"mlbam_id": 20, "role": "pitcher", "level": "AAA", "is_starter": True},
        {"mlbam_id": 30, "role": "pitcher", "level": "AAA", "is_starter": False},
        {"mlbam_id": 40, "role": "hitter", "level": "AAA"},
    ]
    return control, candidate, aaa, current


def test_missing_aaa_players_are_excluded_never_zero_filled():
    report = challenger_eval.build_aaa_disagreement(*_aaa_fixture())
    assert report["missing_statcast_count"] == 1
    assert all(
        row["components"]
        for group in report["groups"].values()
        for row in group["rows"]
    )
    assert report["missing_ids"] == ["40"]
    assert '\"mlbam_id\": 40' not in json.dumps(report["groups"])
    assert "composite" not in json.dumps(report).lower()


def test_pitcher_aaa_groups_do_not_mix_starters_and_relievers():
    report = challenger_eval.build_aaa_disagreement(*_aaa_fixture())
    starter_ids = {
        row["mlbam_id"] for row in report["groups"]["pitcher_starter"]["rows"]
    }
    reliever_ids = {
        row["mlbam_id"] for row in report["groups"]["pitcher_reliever"]["rows"]
    }
    assert starter_ids == {20}
    assert reliever_ids == {30}
    assert starter_ids.isdisjoint(reliever_ids)


def _runner():
    name = "scripts.run_prospect_normalized_production_gate"
    assert importlib.util.find_spec(name) is not None
    return importlib.import_module(name)


def test_one_shot_runner_pins_all_five_authoritative_blobs():
    runner = _runner()
    assert runner.EXPECTED_GIT_BLOBS == {
        "data/prospects/prospect_model_inputs.json": "4ce139871ae456b5289c68dad1e15d8191ff7ef5",
        "data/models/valucast_aaa_statcast_features.json": "37533ad816d86bcf392ccce75bb15f0b745f0f74",
        "data/models/valucast_prospect_model.json": "7a9b9d12ae0866ae3b460f3f02395a0e30949844",
        "data/models/valucast_prospect_rank_v1.json": "4ed3f2603b93e5ecf319f501519303f6ff7c18fa",
        "prospects/competition_benchmark.py": "85a1c2ff43ee7c050da75f43ae1f3382058d1ed3",
    }


def test_runner_validates_the_sealed_readiness_contract():
    runner = _runner()
    registration = {
        "realized_value_readiness": {
            "required_status": "blocked",
            "required_ready": False,
            "required_blockers": [
                "missing_pitcher_category:qs",
                "impact_target_not_direct_7x7",
                "exact_prospective_replay_not_reconstructable",
            ],
        }
    }
    readiness = {
        "status": "blocked",
        "replay": {"realized_value_regret_ready": False},
        "blockers": registration["realized_value_readiness"]["required_blockers"],
    }
    readiness["content_sha256"] = runner._content_sha256(readiness)
    runner._validate_readiness(readiness, registration)
    readiness["blockers"] = readiness["blockers"][:-1]
    with pytest.raises(ValueError, match="readiness artifact seal"):
        runner._validate_readiness(readiness, registration)


def test_runner_refuses_a_nonidentical_existing_artifact(tmp_path):
    runner = _runner()
    output = tmp_path / "gate.json"
    output.write_text('{"different":true}\n', encoding="utf-8")
    payload = runner._seal({"schema": "fixture"})
    with pytest.raises(ValueError, match="existing output artifact is not identical"):
        runner._write_once(output, payload)


def test_runner_final_artifact_forbids_raw_superiority_status():
    runner = _runner()
    artifact = {
        "status": "research_only",
        "claim_authorized": False,
        "public_claim_eligible": False,
        "role_results": {
            "hitter": {
                "status": "research_only",
                "statistical_status": "research_success",
                "claim_authorized": False,
                "public_claim_eligible": False,
            }
        },
    }
    runner._validate_final_artifact(artifact)
    artifact["role_results"]["hitter"]["statistical_status"] = "validated_superiority"
    with pytest.raises(ValueError, match="forbidden final status"):
        runner._validate_final_artifact(artifact)


def test_runner_reservation_is_atomic_and_spent_state_is_durable(tmp_path):
    runner = _runner()
    output = tmp_path / "gate.json"
    reservation = runner._seal(
        {
            "status": "collecting",
            "registered_look_spent": False,
            "run_completed": False,
            "phase": "pre_score_reserved",
            "claim_authorized": False,
            "public_claim_eligible": False,
        }
    )
    runner._reserve_output(output, reservation)
    with pytest.raises(ValueError, match="already exists"):
        runner._reserve_output(output, reservation)

    spent = runner._seal(
        reservation
        | {
            "registered_look_spent": True,
            "phase": "outcome_scoring_started",
        }
    )
    runner._replace_reserved(output, spent)
    assert json.loads(output.read_text(encoding="utf-8"))["registered_look_spent"] is True

    invalid_final = spent | {"public_claim_eligible": True, "run_completed": True}
    with pytest.raises(ValueError, match="public_claim_eligible"):
        runner._finalize_reserved(output, invalid_final)
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["registered_look_spent"] is True
    assert persisted["phase"] == "outcome_scoring_started"
