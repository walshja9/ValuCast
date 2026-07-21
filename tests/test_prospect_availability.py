"""Tests for the ValuCast prospect availability/risk layer."""
import json

from prospects.availability import (
    MAX_IL_RISK_DISCOUNT,
    MAX_RISK_DISCOUNT,
    apply_availability_adjustment,
    build_prospect_availability,
    run_prospect_availability,
)
from scripts.validate_prospect_availability import validate_prospect_availability


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


def _official_il_profile(
    mlbam_id=30,
    status="injured",
    active_injury_risk=True,
    description="60-day IL: Tommy John surgery.",
):
    return {
        "mlbam_id": mlbam_id,
        "status": status,
        "active_injury_risk": active_injury_risk,
        "list_type": "60-day IL",
        "description": description,
        "effective_date": "2026-03-27",
        "name": "Thin AAA Starter",
        "team": "MIA",
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
    assert thin["risk_basis"] == "current_sample_size"
    assert thin["status"] == "thin_current_sample"
    assert "thin_starter_workload_under_30_ip" in thin["signals"]
    assert payload["summary"]["risk_basis_counts"]["current_sample_size"] == 2
    assert payload["validation"]["duplicate_level_rows_collapsed"] == 1
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["source_policy"]["external_rankings_used"] is False


def test_availability_uses_newest_sample_season_when_prior_history_is_present():
    contract = _input_contract()
    contract["current"]["pitchers"] = [
        {
            "mlbam_id": 40,
            "name": "Current Starter",
            "role": "pitcher",
            "level": "AAA",
            "team": "Current Club",
            "innings_pitched": 25.333,
            "games_started": 6,
            "is_starter": True,
            "sample_season": 2026,
            "sample_fetched_date": "2026-06-13",
            "sample_staleness_years": 0,
            "source_kind": "current_season",
        },
        {
            "mlbam_id": 40,
            "name": "Current Starter",
            "role": "pitcher",
            "level": "AAA",
            "team": "Old Club",
            "innings_pitched": 79.0,
            "games_started": 18,
            "is_starter": True,
            "sample_season": 2024,
            "sample_fetched_date": "2026-06-13",
            "sample_staleness_years": 2,
            "source_kind": "latest_milb_history",
        },
    ]

    payload = build_prospect_availability(contract)
    pitcher = next(row for row in payload["profiles"] if row["mlbam_id"] == 40)

    assert pitcher["sample"] == 25.333
    assert pitcher["team"] == "Current Club"
    assert pitcher["source_kind"] == "current_season"
    assert pitcher["active_row_count"] == 1
    assert pitcher["risk_basis"] == "current_sample_size"
    assert pitcher["status"] == "thin_current_sample"
    assert "prior_season_sample" not in pitcher["signals"]


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
                    "age": 24,
                }
            ]
        },
    )

    hitter = next(row for row in payload["profiles"] if row["mlbam_id"] == 10)

    assert hitter["status"] == "injured"
    assert hitter["risk_discount"] == MAX_IL_RISK_DISCOUNT
    assert hitter["risk_basis"] == "manual_override"
    assert hitter["risk_level"] == "high"
    assert hitter["age"] == 24
    assert hitter["availability_note"] == "Verified manual test status."
    assert payload["validation"]["manual_override_count"] == 1


def test_manual_override_discount_uses_il_cap():
    payload = build_prospect_availability(
        _input_contract(),
        overrides={
            "overrides": [
                {
                    "mlbam_id": 10,
                    "role": "hitter",
                    "status": "injured",
                    "note": "Severe manual injury override.",
                    "risk_discount": 0.30,
                }
            ]
        },
    )

    hitter = next(row for row in payload["profiles"] if row["mlbam_id"] == 10)

    assert hitter["risk_discount"] == 0.30
    assert hitter["risk_basis"] == "manual_override"


def test_manual_available_override_clears_stale_injury_and_validates(tmp_path):
    payload = build_prospect_availability(
        _input_contract(),
        overrides={
            "overrides": [
                {
                    "mlbam_id": 10,
                    "role": "hitter",
                    "status": "available",
                    "note": "Activated after an early-season injury.",
                    "risk_discount": 0.05,
                }
            ]
        },
    )
    hitter = next(row for row in payload["profiles"] if row["mlbam_id"] == 10)
    artifact_path = tmp_path / "availability.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    assert hitter["status"] == "available"
    assert hitter["risk_basis"] == "manual_override"
    assert hitter["risk_discount"] == 0.05
    assert validate_prospect_availability(artifact_path)[1] == []


def test_availability_applies_upstream_factual_roster_status():
    contract = _input_contract()
    contract["current"]["pitchers"][2]["availability_status"] = "injured"
    contract["current"]["pitchers"][2]["roster_status"] = "Inj Res"
    contract["current"]["pitchers"][2]["availability_source"] = "fantrax_roster_status"
    contract["current"]["pitchers"][2]["availability_note"] = (
        "Fantrax roster status is Inj Res."
    )

    payload = build_prospect_availability(contract)
    pitcher = next(row for row in payload["profiles"] if row["mlbam_id"] == 30)

    assert pitcher["status"] == "injured"
    assert pitcher["risk_discount"] == MAX_RISK_DISCOUNT
    assert pitcher["risk_basis"] == "upstream_factual_status"
    assert pitcher["risk_level"] == "high"
    assert "fantrax_roster_status_override" in pitcher["signals"]
    assert pitcher["availability_note"] == "Fantrax roster status is Inj Res."
    assert payload["validation"]["upstream_status_count"] == 1


def test_official_mlb_il_injured_prospect_overrides_stale_sample():
    contract = _input_contract()
    contract["current"]["pitchers"][2]["sample_staleness_years"] = 1

    payload = build_prospect_availability(
        contract,
        il_lookup={"30": _official_il_profile()},
    )
    pitcher = next(row for row in payload["profiles"] if row["mlbam_id"] == 30)

    assert pitcher["status"] == "injured"
    assert pitcher["risk_basis"] == "official_mlb_il"
    assert pitcher["risk_discount"] == 0.30
    assert pitcher["signals"] == ["official_mlb_il_override"]
    assert pitcher["availability_note"] == "60-day IL: Tommy John surgery."


def test_official_mlb_short_term_il_uses_short_discount():
    payload = build_prospect_availability(
        _input_contract(),
        il_lookup={
            "30": _official_il_profile(
                description="10-day IL: right shoulder inflammation.",
            )
            | {"list_type": "10-day injured list"}
        },
    )
    pitcher = next(row for row in payload["profiles"] if row["mlbam_id"] == 30)

    assert pitcher["status"] == "injured"
    assert pitcher["risk_basis"] == "official_mlb_il"
    assert pitcher["risk_discount"] == 0.12
    assert pitcher["signals"] == ["official_mlb_il_override"]


def test_manual_override_wins_over_official_mlb_il():
    payload = build_prospect_availability(
        _input_contract(),
        overrides={
            "overrides": [
                {
                    "mlbam_id": 30,
                    "role": "pitcher",
                    "status": "injured",
                    "note": "Manual status remains authoritative.",
                    "risk_discount": 0.09,
                }
            ]
        },
        il_lookup={"30": _official_il_profile()},
    )
    pitcher = next(row for row in payload["profiles"] if row["mlbam_id"] == 30)

    assert pitcher["status"] == "injured"
    assert pitcher["risk_basis"] == "manual_override"
    assert pitcher["risk_discount"] == 0.09
    assert "manual_status_override" in pitcher["signals"]
    assert "official_mlb_il_override" not in pitcher["signals"]
    assert pitcher["availability_note"] == "Manual status remains authoritative."


def test_official_mlb_rehab_status_does_not_trigger_il_join():
    payload = build_prospect_availability(
        _input_contract(),
        il_lookup={"20": _official_il_profile(mlbam_id=20, status="rehab")},
    )
    pitcher = next(row for row in payload["profiles"] if row["mlbam_id"] == 20)

    assert pitcher["status"] == "available"
    assert pitcher["risk_basis"] == "none"
    assert pitcher["risk_discount"] == 0.0
    assert "official_mlb_il_override" not in pitcher["signals"]


def test_prospect_absent_from_official_mlb_il_lookup_is_unaffected():
    payload = build_prospect_availability(
        _input_contract(),
        il_lookup={"999": _official_il_profile(mlbam_id=999)},
    )
    pitcher = next(row for row in payload["profiles"] if row["mlbam_id"] == 30)

    assert pitcher["status"] == "thin_current_sample"
    assert pitcher["risk_basis"] == "current_sample_size"
    assert pitcher["risk_discount"] == 0.06
    assert "official_mlb_il_override" not in pitcher["signals"]


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
    assert components["availability"]["risk_basis"] is None


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
    assert payload["artifact_version"] == "0.3.0"
    assert payload["summary"]["profile_count"] == 3
    assert validate_prospect_availability(artifact_path)[1] == []


def test_availability_validator_rejects_mislabeled_risk_basis(tmp_path):
    payload = build_prospect_availability(_input_contract())
    thin = next(row for row in payload["profiles"] if row["mlbam_id"] == 30)
    thin["risk_basis"] = "none"
    artifact_path = tmp_path / "availability.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_prospect_availability(artifact_path)

    assert "profiles[2].status is inconsistent with risk_basis" in problems
    assert "profiles[2].risk_basis=none requires zero risk_discount" in problems


def test_availability_validator_rejects_unknown_risk_basis(tmp_path):
    payload = build_prospect_availability(_input_contract())
    payload["profiles"][0]["risk_basis"] = "market_rank"
    artifact_path = tmp_path / "availability.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_prospect_availability(artifact_path)

    assert "profiles[0].risk_basis is invalid" in problems
