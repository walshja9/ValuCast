"""No-outcome tests for the registered prospect challenger readiness gate."""
from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from prospects.challenger_readiness import (
    assert_no_outer_scoring,
    build_plan034_readiness,
    development_density_features,
    position_value_features,
)

ROOT = Path(__file__).resolve().parents[1]


def _row(mlbam_id=1, role="hitter"):
    return {
        "cohort_year": 2019,
        "mlbam_id": mlbam_id,
        "role": role,
        "age": 20.5,
        "level": "AA",
        "position": "SS" if role == "hitter" else "P",
        "plate_appearances": 500 if role == "hitter" else None,
        "innings_pitched": 150 if role == "pitcher" else None,
        "games_played": 100,
        "outcome": "role",
    }


def _contract(two_way=False):
    rows = [_row()]
    if two_way:
        rows.append(_row(role="pitcher"))
    return {
        "schema_version": "1.1",
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source_policy": {
            "kind": "factual_only",
            "sources": [
                "fantrax_mlb_actuals",
                "mlb_prospect_seasons_cache",
                "mlb_statsapi_draft",
                "milb_season_stats",
                "valucast_universal_prospect_dataset",
            ],
            "external_rankings_used": False,
            "external_projections_used": False,
            "market_values_used": False,
            "dynasty_values_used": False,
        },
        "historical": {"rows": rows},
        "current": {"hitters": [], "pitchers": []},
        "mlb_service": [],
    }


def _registration():
    return {
        "protocol": "prospect-model-challenger-epoch-v1",
        "look_spent": False,
        "execution_authorized": False,
        "execution_trigger": {
            "not_before": "2027-01-01",
            "requires_2026_mlb_season_complete": True,
            "requires_2022_cohort_four_year_horizon_complete": True,
            "requires_reviewed_implementation_amendment": True,
        },
    }


def test_plan034_readiness_refuses_outer_scoring_before_trigger():
    report = build_plan034_readiness(
        _contract(), _registration(), None, as_of="2026-08-03"
    )

    assert report["status"] == "waiting_for_vintage"
    assert report["outer_scoring_authorized"] is False
    assert "not_before:2027-01-01" in report["blockers"]
    assert_no_outer_scoring(report)


def test_assert_no_outer_scoring_rejects_authorized_report():
    with pytest.raises(RuntimeError, match="outer scoring"):
        assert_no_outer_scoring({"outer_scoring_authorized": True})


def test_plan034_readiness_blocks_duplicate_cohort_role_identity():
    contract = _contract()
    contract["historical"]["rows"].append(
        dict(contract["historical"]["rows"][0])
    )

    report = build_plan034_readiness(
        contract, _registration(), None, as_of="2026-08-03"
    )

    assert report["identity_audit"]["duplicates"] == ["2019:1:hitter"]
    assert report["outer_scoring_authorized"] is False


def test_plan034_readiness_preserves_two_way_roles_and_null_aaa_fields():
    aaa = {
        "rows": [
            {
                "mlbam_id": 1,
                "role": "hitter",
                "avg_exit_velocity": None,
            }
        ]
    }

    report = build_plan034_readiness(
        _contract(two_way=True), _registration(), aaa, as_of="2026-08-03"
    )

    assert report["identity_audit"]["role_counts"] == {"hitter": 1, "pitcher": 1}
    assert report["aaa_statcast"]["missing_by_field"]["avg_exit_velocity"] == 1
    assert report["aaa_statcast"]["zero_filled_count"] == 0


def test_development_density_matches_registration():
    row = {"plate_appearances": 500, "games_played": 100, "innings_pitched": 150}
    assert development_density_features(row, "hitter") == (5.0, 100 / 132)
    assert development_density_features(row, "pitcher") == (1.5,)
    assert development_density_features({}, "hitter") == (0.0, 0.0)


def test_position_value_x_matches_registration():
    assert position_value_features({"position": "SS", "level": "AA", "age": 20.5}) == (
        0.95,
        1.9,
        0.0,
    )
    assert position_value_features({"position": "OF", "level": "X", "age": 20}) == (
        0.5,
        0.0,
        0.0,
    )


def test_registered_context_challengers_are_implemented_but_unspent():
    report = build_plan034_readiness(
        _contract(), _registration(), None, as_of="2026-08-03"
    )
    challengers = report["registered_context_challengers"]

    assert challengers["development_density"]["feature_width"] == {
        "hitter": 2,
        "pitcher": 1,
    }
    assert challengers["position_value_x"]["feature_width"] == {"hitter": 3}
    assert challengers["confirmatory_scoring_authorized"] is False
    assert challengers["registered_look_spent"] is False


def test_context_readiness_is_invariant_to_outcome_mutation():
    contract = _contract(two_way=True)
    first = build_plan034_readiness(
        contract, _registration(), None, as_of="2026-08-03"
    )
    changed = deepcopy(contract)
    for row in changed["historical"]["rows"]:
        row["outcome"] = "star"
    second = build_plan034_readiness(
        changed, _registration(), None, as_of="2026-08-03"
    )

    assert first["registered_context_challengers"] == second[
        "registered_context_challengers"
    ]


def test_readiness_cli_writes_research_only_artifact(tmp_path):
    output = tmp_path / "readiness.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_prospect_challenger_readiness.py",
            "--output",
            str(output),
            "--as-of",
            "2026-08-03",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["outer_scoring_authorized"] is False
    assert payload["source_policy"]["feeds_rank_or_value"] is False
