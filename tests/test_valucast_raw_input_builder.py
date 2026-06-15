"""Contract tests for ValuCast's native factual prospect-input producer."""
import inspect
import json

import pytest

from prospects import raw_input_builder as exporter


def _historical():
    return {
        "cohorts": [2019],
        "omitted_cohorts": [
            {
                "year": 2020,
                "reason": "no affiliated Minor League Baseball season",
            }
        ],
        "rows": [{
            "cohort_year": 2019,
            "mlbam_id": 101,
            "name": "Clean Hitter",
            "role": "hitter",
            "level": "AAA",
            "age": 22,
            "iso": 0.220,
            "k_pct": 20.0,
            "bb_pct": 11.0,
            "ops": 0.850,
            "outcome": "star",
            "source_ranks": {"cfr": 1},
            "dynasty_value": 99,
        }],
    }


def _current():
    return {
        "season": 2026,
        "fetched_date": "2026-06-12",
        "hitters": [{
            "mlbam_id": 101,
            "name": "Clean Hitter",
            "role": "hitter",
            "level": "AAA",
            "age": 22,
            "position": "SS",
            "plate_appearances": 200,
            "iso": 0.220,
            "k_pct": 20.0,
            "bb_pct": 11.0,
            "ops": 0.850,
            "prospect_rank": 1,
        }],
        "pitchers": [],
    }


def _mlb_seasons():
    return {
        "101_hitter": [{
            "year": 2025,
            "pa": 500,
            "r": 90,
            "ops": 0.850,
            "hr": 25,
            "rbi": 95,
            "sb": 15,
            "avg": 0.280,
            "so": 120,
            "dynasty_value": 90,
        }],
        "202_pitcher": [{
            "year": 2025,
            "ip": 160.0,
            "era": 3.20,
            "whip": 1.10,
            "so": 180,
            "sv": 0,
            "hld": 0,
            "l": 8,
            "k_bb": 4.0,
            "qs": 20,
            "projection": {"qs": 22},
        }],
    }


def test_contract_strips_rank_projection_and_value_fields():
    payload = exporter.build_contract(
        dataset=_historical(),
        current=_current(),
        mlb_seasons=_mlb_seasons(),
        generated_at="2026-06-12T00:00:00+00:00",
    )
    serialized = json.dumps(payload)
    assert "source_ranks" not in serialized
    assert "prospect_rank" not in serialized
    assert "dynasty_value" not in payload["historical"]["rows"][0]
    assert "dynasty_value" not in payload["current"]["hitters"][0]
    assert "dynasty_value" not in payload["historical_mlb_seasons"]["101_hitter"][0]
    assert payload["historical_mlb_seasons"]["101_hitter"][0]["rbi"] == 95
    assert payload["historical_mlb_seasons"]["202_pitcher"][0]["qs"] == 20
    assert "projection" not in payload["historical_mlb_seasons"]["202_pitcher"][0]
    assert payload["source_policy"]["kind"] == "factual_only"
    assert payload["source_policy"]["external_rankings_used"] is False
    assert payload["schema_version"] == "1.2"
    assert "mlb_statsapi_draft" in payload["source_policy"]["sources"]
    assert "fantrax_roster_status" in payload["source_policy"]["sources"]
    assert payload["producer"]["owner"] == "valucast"
    assert payload["producer"]["upstream_kind"] == "valucast_raw_ingestion"
    assert payload["producer"]["upstream_model_score_effect"] == "none"
    assert payload["historical"]["omitted_cohorts"] == [
        {
            "year": 2020,
            "reason": "no affiliated Minor League Baseball season",
        }
    ]


def test_source_policy_validator_rejects_new_forbidden_keys():
    payload = {
        "schema_version": "1.1",
        "generated_at": "2026-06-12T00:00:00+00:00",
        "historical": {"rows": [{"mlbam_id": 101, "model_rank": 1}]},
        "historical_mlb_seasons": {},
        "current": {"hitters": [], "pitchers": []},
        "mlb_service": [],
    }

    with pytest.raises(ValueError, match="model_rank"):
        exporter._source_policy_for_payload(payload)


def test_source_policy_validator_rejects_forbidden_source_families():
    payload = {
        "schema_version": "1.1",
        "generated_at": "2026-06-12T00:00:00+00:00",
        "historical": {"rows": []},
        "historical_mlb_seasons": {},
        "current": {
            "hitters": [{
                "mlbam_id": 101,
                "source_artifact": "external_rank_feed",
            }],
            "pitchers": [],
        },
        "mlb_service": [],
    }

    with pytest.raises(ValueError, match="external_rank_feed"):
        exporter._source_policy_for_payload(payload)


def test_contract_exports_sanitized_draft_facts_and_lower_minors():
    current = _current()
    current["hitters"][0]["level"] = "A"
    payload = exporter.build_contract(
        dataset=_historical(),
        current=current,
        mlb_seasons=_mlb_seasons(),
        draft_facts={
            "101": {
                "draft_record_known": True,
                "rule4_drafted": True,
                "draft_pick_number": 12,
                "signing_bonus": 4_000_000,
                "scouting_report": "must not cross the boundary",
            }
        },
        generated_at="2026-06-12T00:00:00+00:00",
    )
    historical = payload["historical"]["rows"][0]
    current_row = payload["current"]["hitters"][0]
    assert historical["draft_pick_number"] == 12
    assert current_row["signing_bonus"] == 4_000_000
    assert "scouting_report" not in json.dumps(payload)
    assert payload["mlb_service"][0]["mlbam_id"] == 101


def test_contract_exports_verified_fantrax_injury_status():
    current = _current()
    current["hitters"][0]["age"] = 22
    payload = exporter.build_contract(
        dataset=_historical(),
        current=current,
        mlb_seasons=_mlb_seasons(),
        fantrax_availability={
            ("clean hitter", "hitter"): {
                "name": "Clean Hitter",
                "role": "hitter",
                "age": 22,
                "roster_status": "Inj Res",
            }
        },
        generated_at="2026-06-12T00:00:00+00:00",
    )

    row = payload["current"]["hitters"][0]
    assert row["roster_status"] == "Inj Res"
    assert row["availability_status"] == "injured"
    assert row["availability_source"] == "fantrax_roster_status"
    assert row["availability_fetched_date"] == "2026-06-12"
    assert "dynasty" not in json.dumps(row).lower()


def test_contract_drops_fantrax_injury_status_when_identity_age_conflicts():
    current = _current()
    current["hitters"][0]["age"] = 22
    payload = exporter.build_contract(
        dataset=_historical(),
        current=current,
        mlb_seasons=_mlb_seasons(),
        fantrax_availability={
            ("clean hitter", "hitter"): {
                "name": "Clean Hitter",
                "role": "hitter",
                "age": 34,
                "roster_status": "Inj Res",
            }
        },
        generated_at="2026-06-12T00:00:00+00:00",
    )

    row = payload["current"]["hitters"][0]
    assert "availability_status" not in row
    assert "roster_status" not in row


def test_contract_backfills_latest_milb_history_when_current_sample_is_missing():
    current = {
        "season": 2026,
        "fetched_date": "2026-06-12",
        "hitters": [],
        "pitchers": [{
            "mlbam_id": 202,
            "name": "Thin Current Pitcher",
            "role": "pitcher",
            "level": "AAA",
            "age": 22,
            "position": "P",
            "innings_pitched": 10.0,
            "k_per_9": 12.0,
            "bb_per_9": 2.0,
            "k_bb_pct": 30.0,
            "era": 2.00,
            "whip": 0.90,
        }],
    }
    history = {
        "players": {
            "missing hitter": [{
                "mlbam_id": 303,
                "role": "hitter",
                "season": 2025,
                "level": "AA",
                "age": 20,
                "team": "AA Club",
                "plate_appearances": 300,
                "iso": 0.200,
                "k_pct": 18.0,
                "bb_pct": 12.0,
                "avg": 0.280,
                "obp": 0.370,
                "slg": 0.480,
            }],
            "thin current pitcher": [{
                "mlbam_id": 202,
                "role": "pitcher",
                "season": 2025,
                "level": "AA",
                "age": 21,
                "team": "AA Club",
                "innings_pitched": 55.0,
                "k_per_9": 11.0,
                "bb_per_9": 3.0,
                "k_bb_pct": 22.0,
                "era": 3.10,
                "whip": 1.08,
                "is_starter": True,
            }],
        }
    }
    mlb_seasons = _mlb_seasons()
    mlb_seasons["303_hitter"] = []
    payload = exporter.build_contract(
        dataset=_historical(),
        current=current,
        milb_history=history,
        mlb_seasons=mlb_seasons,
        draft_facts={
            "303": {
                "draft_record_known": True,
                "rule4_drafted": True,
                "draft_pick_number": 20,
            }
        },
        generated_at="2026-06-12T00:00:00+00:00",
    )

    hitter = next(row for row in payload["current"]["hitters"] if row["mlbam_id"] == 303)
    pitcher_rows = [
        row for row in payload["current"]["pitchers"] if row["mlbam_id"] == 202
    ]
    assert hitter["source_kind"] == "latest_milb_history"
    assert hitter["source_artifact"] == "milb_card_history"
    assert hitter["sample_season"] == 2025
    assert hitter["sample_staleness_years"] == 1
    assert hitter["name"] == "Missing Hitter"
    assert hitter["ops"] == 0.850
    assert hitter["draft_pick_number"] == 20
    assert len(pitcher_rows) == 2
    assert any(row["source_kind"] == "current_season" for row in pitcher_rows)
    assert any(row["source_kind"] == "latest_milb_history" for row in pitcher_rows)
    service_ids = {(row["mlbam_id"], row["role"]) for row in payload["mlb_service"]}
    assert (303, "hitter") in service_ids
    assert (202, "pitcher") in service_ids


def test_contract_hides_draft_facts_not_known_by_cohort():
    historical = _historical()
    historical["rows"][0]["cohort_year"] = 2018
    payload = exporter.build_contract(
        dataset=historical,
        current=_current(),
        mlb_seasons=_mlb_seasons(),
        draft_facts={
            "101": {
                "draft_record_known": True,
                "rule4_drafted": True,
                "draft_year": 2019,
                "draft_pick_number": 12,
                "signing_bonus": 4_000_000,
            }
        },
        generated_at="2026-06-12T00:00:00+00:00",
    )
    row = payload["historical"]["rows"][0]
    assert row["draft_record_known"] is True
    assert row["rule4_drafted"] is False
    assert row["draft_pick_number"] is None
    assert row["signing_bonus"] is None


def test_contract_exports_mlbam_keyed_service_facts():
    payload = exporter.build_contract(
        dataset=_historical(),
        current=_current(),
        mlb_seasons=_mlb_seasons(),
        generated_at="2026-06-12T00:00:00+00:00",
    )
    assert payload["mlb_service"] == [{
        "mlbam_id": 101,
        "role": "hitter",
        "pa": 500.0,
        "ab": 500.0,
        "ip": 0.0,
        "graduated": True,
    }]


def test_contract_fails_closed_when_service_cache_missing_current_candidate():
    with pytest.raises(ValueError, match="MLB service cache is missing"):
        exporter.build_contract(
            dataset=_historical(),
            current=_current(),
            mlb_seasons={},
            generated_at="2026-06-12T00:00:00+00:00",
        )


def test_refresh_mlb_service_cache_fetches_missing_mlbam_keys(monkeypatch, tmp_path):
    calls = []

    def fake_fetch(mlbam_id, role):
        calls.append((mlbam_id, role))
        return [{
            "year": 2026,
            "pa": 140,
            "ab": 132,
            "r": 10,
            "hr": 1,
            "rbi": 8,
            "sb": 0,
            "avg": 0.250,
            "ops": 0.700,
            "so": 30,
        }]

    monkeypatch.setattr(exporter, "_statsapi_service_seasons", fake_fetch)
    cache_path = tmp_path / "mlb_service_cache.json"
    current = _current()

    result = exporter.refresh_mlb_service_cache(
        current=current,
        mlb_seasons={},
        cache_path=cache_path,
        max_workers=1,
    )

    assert result["fetched"] == 1
    assert result["failed"] == 0
    assert calls == [(101, "hitter")]
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["101_hitter"][0]["ab"] == 132


def test_write_contract_round_trips(tmp_path):
    payload = exporter.build_contract(
        dataset=_historical(),
        current=_current(),
        mlb_seasons=_mlb_seasons(),
        generated_at="2026-06-12T00:00:00+00:00",
    )
    path = exporter.write_contract(payload, tmp_path / "inputs.json")
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_exporter_has_no_rank_or_valuation_dependencies():
    source = inspect.getsource(exporter).lower()
    forbidden = (
        "prospects_ranked.json",
        "get_dynasty_value",
        "import valuation",
        "dd_dynasty_feed",
        "get_career_stats_with_current",
        "get_player_season_stats",
    )
    assert not any(token in source for token in forbidden)


def test_native_paths_live_under_valucast_prospect_raw_data():
    assert exporter.RAW_DIR.parts[-3:] == ("data", "prospects", "raw")
    assert exporter.OUTPUT_PATH.parts[-3:] == (
        "data",
        "prospects",
        "prospect_model_inputs.json",
    )
