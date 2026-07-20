from copy import deepcopy

from prospects.realized_value_readiness import audit_realized_value_readiness


def _contract() -> dict:
    return {
        "historical": {
            "rows": [
                {
                    "cohort_year": 2018,
                    "mlbam_id": 10,
                    "role": "hitter",
                    "outcome": "role",
                },
                {
                    "cohort_year": 2018,
                    "mlbam_id": 20,
                    "role": "pitcher",
                    "outcome": "star",
                },
            ]
        },
        "historical_mlb_seasons": {
            "10_hitter": [
                {
                    "year": 2019,
                    "pa": 500,
                    "r": 70,
                    "hr": 20,
                    "rbi": 75,
                    "sb": 8,
                    "avg": 0.270,
                    "ops": 0.800,
                    "so": 120,
                }
            ],
            "20_pitcher": [
                {
                    "year": 2019,
                    "ip": 150,
                    "so": 170,
                    "sv": 0,
                    "hld": 0,
                    "era": 3.50,
                    "whip": 1.20,
                    "k_bb": 3.2,
                    "l": 8,
                }
            ],
        },
    }


def _model() -> dict:
    return {
        "impact_target_contract": {
            "canonical_hitter_categories": [
                "r",
                "hr",
                "rbi",
                "sb",
                "avg",
                "ops",
                "so",
            ],
            "canonical_pitcher_categories": [
                "so",
                "qs",
                "sv_hld",
                "era",
                "whip",
                "k_bb",
                "l",
            ],
            "direct_7x7": False,
            "missing_hitter_categories": [],
            "missing_pitcher_categories": ["qs"],
        }
    }


def test_missing_qs_blocks_realized_value_regret():
    report = audit_realized_value_readiness(_contract(), _model())
    assert report["status"] == "blocked"
    assert report["replay"]["realized_value_regret_ready"] is False
    assert report["category_coverage"]["pitcher"]["missing"] == ["qs"]
    assert "missing_pitcher_category:qs" in report["blockers"]


def test_conflicting_same_cohort_roles_fail_that_cohort_closed():
    contract = _contract()
    contract["historical"]["rows"].append(
        {"cohort_year": 2018, "mlbam_id": 20, "role": "hitter", "outcome": "role"}
    )
    report = audit_realized_value_readiness(contract, _model())
    assert report["cohorts"]["2018"]["identity_status"] == "blocked"
    assert report["identity_audit"]["conflicting_cohort_roles"] == ["2018:20"]


def test_later_role_change_is_disclosed_without_relabeling_prior_cohort():
    contract = _contract()
    contract["historical"]["rows"].append(
        {"cohort_year": 2019, "mlbam_id": 20, "role": "hitter", "outcome": "role"}
    )
    report = audit_realized_value_readiness(contract, _model())
    assert report["identity_audit"]["later_role_changes"] == [
        {"mlbam_id": "20", "roles_by_cohort": {"2018": "pitcher", "2019": "hitter"}}
    ]
    assert (
        report["identity_policy"]["historical_role"]
        == "frozen_from_cohort_cutoff_row"
    )


def test_zero_opportunity_is_counted_not_promoted_to_success():
    contract = deepcopy(_contract())
    contract["historical_mlb_seasons"]["10_hitter"] = []
    report = audit_realized_value_readiness(contract, _model())
    assert report["cohorts"]["2018"]["zero_opportunity"]["hitter"] == 1
