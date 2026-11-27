from __future__ import annotations

from copy import deepcopy

from prospects.impact_oof import (
    build_impact_oof_report,
    cohort_player_bootstrap,
    fold_local_impact_oof,
    validate_impact_oof_report,
)


def _row(role: str, cohort_year: int, mlbam_id: int) -> dict:
    row = {
        "mlbam_id": mlbam_id,
        "role": role,
        "cohort_year": cohort_year,
        "level": "AA" if mlbam_id % 2 else "AAA",
        "age": 21 + mlbam_id % 3,
    }
    if role == "hitter":
        row.update(
            {
                "iso": 0.12 + (mlbam_id % 5) * 0.02,
                "k_pct": 27.0 - mlbam_id % 7,
                "bb_pct": 7.0 + mlbam_id % 5,
                "ops": 0.68 + (mlbam_id % 6) * 0.03,
            }
        )
    else:
        row.update(
            {
                "k_per_9": 7.0 + mlbam_id % 5,
                "bb_per_9": 4.5 - (mlbam_id % 3) * 0.4,
                "k_bb_pct": 7.0 + mlbam_id % 8,
                "era": 4.8 - (mlbam_id % 5) * 0.25,
                "whip": 1.45 - (mlbam_id % 4) * 0.06,
                "is_starter": mlbam_id % 3 != 0,
            }
        )
    return row


def _season(role: str, year: int, strength: int) -> dict:
    if role == "hitter":
        return {
            "year": year,
            "pa": 500,
            "r": 55 + strength,
            "hr": 8 + strength,
            "rbi": 50 + strength,
            "sb": 4 + strength,
            "avg": 0.230 + strength / 1000,
            "ops": 0.690 + strength / 500,
            "so": 130 - strength,
        }
    return {
        "year": year,
        "ip": 120,
        "so": 100 + strength,
        "qs": 8 + strength // 4,
        "sv": 0,
        "hld": strength // 3,
        "era": 4.50 - strength / 100,
        "whip": 1.40 - strength / 200,
        "k_bb": 2.0 + strength / 20,
        "l": 10 - strength // 4,
    }


def _contract() -> dict:
    rows = []
    seasons = {}
    for role, offset in (("hitter", 0), ("pitcher", 1000)):
        for cohort_year in range(2014, 2019):
            for slot in range(4):
                mlbam_id = offset + (cohort_year - 2014) * 10 + slot + 1
                rows.append(_row(role, cohort_year, mlbam_id))
                key = f"{mlbam_id}_{role}"
                seasons[key] = []
                if slot:
                    seasons[key].append(
                        _season(role, cohort_year + 1, strength=slot * 5)
                    )
    return {
        "historical": {"rows": rows},
        "historical_mlb_seasons": seasons,
    }


def _fold(report: dict, role: str, year: int) -> dict:
    return next(
        fold
        for fold in report["folds"]
        if fold["role"] == role and fold["test_cohort"] == year
    )


def test_fold_references_exclude_test_identities_and_ignore_outside_mutations():
    contract = _contract()
    first = build_impact_oof_report(
        contract,
        generated_at="2026-07-21T12:00:00+00:00",
        bootstrap_seed=72127,
        bootstrap_resamples=100,
    )

    for fold in first["folds"]:
        assert set(fold["test_ids"]).isdisjoint(fold["reference_ids"])
        assert fold["train_cohort_max"] < fold["test_cohort"]
        assert fold["reference_player_count"] == len(fold["reference_ids"])

    mutated = deepcopy(contract)
    test_key = next(
        key
        for key in mutated["historical_mlb_seasons"]
        if key.startswith("1042_")
    )
    mutated["historical_mlb_seasons"][test_key][0]["so"] = 9999
    training_key = next(
        key
        for key in mutated["historical_mlb_seasons"]
        if key.startswith("1_")
    )
    below_reference_minimum = _season("hitter", 2016, strength=100)
    below_reference_minimum["pa"] = 149
    mutated["historical_mlb_seasons"][training_key].append(
        below_reference_minimum
    )
    mutated["historical_mlb_seasons"][training_key].append(
        _season("hitter", 2035, strength=100)
    )
    second = build_impact_oof_report(
        mutated,
        generated_at="2026-07-21T12:00:00+00:00",
        bootstrap_seed=72127,
        bootstrap_resamples=100,
    )

    assert _fold(first, "pitcher", 2018)["reference_sha256"] == _fold(
        second, "pitcher", 2018
    )["reference_sha256"]
    assert [fold["reference_sha256"] for fold in first["folds"]] == [
        fold["reference_sha256"] for fold in second["folds"]
    ]


def test_oof_rows_preserve_exact_role_and_test_cohort_identities():
    contract = _contract()
    report = build_impact_oof_report(
        contract,
        generated_at="2026-07-21T12:00:00+00:00",
        bootstrap_seed=72127,
        bootstrap_resamples=100,
    )

    actual = {
        (row["mlbam_id"], row["role"], row["test_cohort"])
        for row in report["rows"]
    }
    expected = {
        (row["mlbam_id"], row["role"], row["cohort_year"])
        for row in contract["historical"]["rows"]
        if row["cohort_year"] >= 2016
    }
    assert actual == expected
    assert len(actual) == len(report["rows"])


def test_fold_local_oof_can_extend_maturity_without_changing_default():
    contract = _contract()
    for role, offset in (("hitter", 0), ("pitcher", 1000)):
        mlbam_id = offset + 999
        contract["historical"]["rows"].append(_row(role, 2021, mlbam_id))
        contract["historical_mlb_seasons"][f"{mlbam_id}_{role}"] = [
            _season(role, 2022, strength=10)
        ]

    assert not any(
        row["test_cohort"] == 2021
        for row in fold_local_impact_oof(
            contract["historical"]["rows"],
            contract["historical_mlb_seasons"],
            "hitter",
        )["rows"]
    )
    assert any(
        row["test_cohort"] == 2021
        for row in fold_local_impact_oof(
            contract["historical"]["rows"],
            contract["historical_mlb_seasons"],
            "hitter",
            mature_through=2021,
        )["rows"]
    )


def test_cohort_then_player_bootstrap_is_deterministic_and_cohort_weighted():
    rows = [
        {"test_cohort": 2016, "model_error": 0.1, "baseline_error": 0.3},
        {"test_cohort": 2016, "model_error": 0.2, "baseline_error": 0.3},
        {"test_cohort": 2017, "model_error": 0.5, "baseline_error": 0.4},
    ]

    first = cohort_player_bootstrap(
        rows,
        baseline_error_key="baseline_error",
        seed=72127,
        resamples=250,
    )
    second = cohort_player_bootstrap(
        rows,
        baseline_error_key="baseline_error",
        seed=72127,
        resamples=250,
    )

    assert first == second
    assert first["point"] == 0.025
    assert first["cohorts"] == 2
    assert first["players"] == 3
    assert first["low"] <= first["point"] <= first["high"]


def test_report_is_research_only_and_validator_recomputes_evidence():
    report = build_impact_oof_report(
        _contract(),
        generated_at="2026-07-21T12:00:00+00:00",
        bootstrap_seed=72127,
        bootstrap_resamples=100,
    )

    assert report["research_only"] is True
    assert report["claim_authorized"] is False
    assert report["public_claim_eligible"] is False
    assert report["affects_live_outputs"] is False
    assert validate_impact_oof_report(report) == []
    source_hash = report["source"]["source_file_sha256"]
    assert validate_impact_oof_report(
        report, source_file_sha256=source_hash
    ) == []
    assert "source_file_hash_mismatch" in validate_impact_oof_report(
        report, source_file_sha256="0" * 64
    )


    bad_error = deepcopy(report)
    bad_error["rows"][0]["model_error"] += 0.1
    assert "row_error_mismatch" in validate_impact_oof_report(bad_error)

    bad_serving = deepcopy(report)
    bad_serving["affects_live_outputs"] = True
    assert "research_boundary_violation" in validate_impact_oof_report(bad_serving)

    nested_serving = deepcopy(report)
    nested_serving["evaluation"]["production_import"] = "prospect_rank_v1"
    assert "research_boundary_violation" in validate_impact_oof_report(nested_serving)
