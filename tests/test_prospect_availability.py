"""Tests for the ValuCast prospect availability/risk layer."""
import json

from prospects.availability import (
    MAX_RISK_DISCOUNT,
    apply_availability_adjustment,
    build_prospect_availability,
    run_prospect_availability,
)


def _input_contract():
    return {
        "schema_version": "1.1",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "source_policy": {
            "dynasty_values_used": False,
            "external_rankings_used": False,
        },
        "current": {
            "hitters": [
                {
                    "mlbam_id": 10,
                    "name": "Upper Hitter",
                    "role": "hitter",
                    "level": "AA",
                    "team": "Portland",
                    "plate_appearances": 90,
                    "sample_fetched_date": "2026-06-13",
                    "sample_staleness_years": 0,
                    "source_kind": "current_season",
                }
            ],
            "pitchers": [
                {
                    "mlbam_id": 20,
                    "name": "Split Starter",
                    "role": "pitcher",
                    "level": "A",
                    "team": "Low Club",
                    "innings_pitched": 28.0,
                    "games_started": 6,
                    "is_starter": True,
                    "sample_fetched_date": "2026-06-13",
                    "sample_staleness_years": 0,
                    "source_kind": "current_season",
                },
                {
                    "mlbam_id": 20,
                    "name": "Split Starter",
                    "role": "pitcher",
                    "level": "A+",
                    "team": "High Club",
                    "innings_pitched": 21.667,
                    "games_started": 5,
                    "is_starter": True,
                    "sample_fetched_date": "2026-06-13",
                    "sample_staleness_years": 0,
                    "source_kind": "current_season",
                },
                {
                    "mlbam_id": 30,
                    "name": "Thin AAA Starter",
                    "role": "pitcher",
                    "level": "AAA",
                    "team": "Jacksonville",
                    "innings_pitched": 29.0,
                    "games_started": 6,
                    "is_starter": True,
                    "sample_fetched_date": "2026-06-13",
                    "sample_staleness_years": 0,
                    "source_kind": "current_season",
                },
            ],
        },
    }


def test_availability_collapses_multi_level_samples_before_pricing_risk():
    payload = build_prospect_availability(_input_contract())

    split = next(row for row in payload["profiles"] if row["mlbam_id"] == 20)
    thin = next(row for row in payload["profiles"] if row["mlbam_id"] == 30)

    assert split["sample"] == 49.667
    assert split["level"] == "A+"
    assert split["risk_discount"] == 0.0
    assert split["status"] == "available"
    assert thin["sample"] == 29.0
    assert thin["risk_discount"] == 0.06
    assert thin["status"] == "thin_current_sample"
    assert "thin_starter_workload_under_30_ip" in thin["signals"]
    assert payload["validation"]["duplicate_level_rows_collapsed"] == 1
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["source_policy"]["external_rankings_used"] is False


def test_availability_applies_manual_status_overrides_with_bounded_discount():
    payload = build_prospect_availability(
        _input_contract(),
        overrides={
            "overrides": [
                {
                    "mlbam_id": 10,
                    "role": "hitter",
                    "status": "injured",
                    "note": "Verified manual test status.",
                    "risk_discount": 0.40,
                }
            ]
        },
    )

    hitter = next(row for row in payload["profiles"] if row["mlbam_id"] == 10)

    assert hitter["status"] == "injured"
    assert hitter["risk_discount"] == MAX_RISK_DISCOUNT
    assert hitter["risk_level"] == "high"
    assert hitter["availability_note"] == "Verified manual test status."
    assert payload["validation"]["manual_override_count"] == 1


def test_apply_availability_adjustment_keeps_original_score_explainable():
    score, components = apply_availability_adjustment(
        50.0,
        {"model_score": 60.0},
        {
            "present": True,
            "status": "thin_current_sample",
            "risk_level": "medium",
            "risk_discount": 0.06,
            "availability_note": "Thin sample.",
            "signals": ["thin_starter_workload_under_30_ip"],
            "sample": 29.0,
            "sample_unit": "IP",
            "sample_fetched_date": "2026-06-13",
            "sample_staleness_days": 0,
        },
    )

    assert score == 47.0
    assert components["score_before_availability_adjustment"] == 50.0
    assert components["availability_risk_discount"] == 0.06
    assert components["availability_adjusted"] is True
    assert components["availability"]["status"] == "thin_current_sample"


def test_run_prospect_availability_writes_artifact(tmp_path):
    input_path = tmp_path / "inputs.json"
    artifact_path = tmp_path / "availability.json"
    input_path.write_text(json.dumps(_input_contract()), encoding="utf-8")

    result = run_prospect_availability(
        input_contract_path=input_path,
        overrides_path=None,
        artifact_path=artifact_path,
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert result["profile_count"] == 3
    assert result["risk_profile_count"] == 2
    assert payload["artifact"] == "valucast_prospect_availability"
