"""Contract tests for ValuCast's native factual prospect-input producer."""
import inspect
import io
import json

import pytest

from prospects import raw_input_builder as exporter
from scripts import refresh_milb_card_history as history_builder


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


def _forbid_input_read(*args, **kwargs):
    raise AssertionError("Fully supplied contract inputs must not read local files")


def test_contract_respects_fully_injected_draft_facts(monkeypatch):
    for name in ("_load_json", "_load_optional_json", "_fantrax_availability_from_csv"):
        monkeypatch.setattr(exporter, name, _forbid_input_read)
    for facts, expected_pick in (({}, None), ({"101": {"draft_pick_number": 42}}, 42)):
        payload = exporter.build_contract(
            dataset=_historical(), current=_current(), milb_history={},
            mlb_seasons=_mlb_seasons(), draft_facts=facts, fantrax_availability={},
            generated_at="2026-06-12T00:00:00+00:00",
        )
        assert payload["current"]["hitters"][0].get("draft_pick_number") == expected_pick


def test_draft_backfill_uses_resolved_facts_and_preserves_existing_values(monkeypatch):
    for name in ("_load_json", "_load_optional_json", "_fantrax_availability_from_csv"):
        monkeypatch.setattr(exporter, name, _forbid_input_read)
    current_rows = {
        "hitters": [{"mlbam_id": 101, "draft_pick_number": 7, "signing_bonus": None}],
        "pitchers": [{"mlbam_id": 202, "draft_pick_number": None}],
    }
    monkeypatch.setattr(exporter, "_current_rows", lambda *args: current_rows)
    exporter.build_contract(
        dataset={"rows": []}, current=_current(), milb_history={}, mlb_seasons={},
        draft_facts={"101": {"draft_pick_number": 42, "signing_bonus": 0},
                     "202": {"draft_pick_number": 88}},
        fantrax_availability={}, generated_at="2026-06-12T00:00:00+00:00",
    )
    assert current_rows["hitters"][0]["draft_pick_number"] == 7
    assert current_rows["hitters"][0]["signing_bonus"] == 0
    assert current_rows["pitchers"][0]["draft_pick_number"] == 88


def test_history_producer_fields_survive_fully_injected_contract(monkeypatch):
    for name in ("_load_json", "_load_optional_json", "_fantrax_availability_from_csv"):
        monkeypatch.setattr(exporter, name, _forbid_input_read)
    fields = ("batters_faced", "games_played", "hits", "home_runs", "walks")
    for values in ((0.321, 237, 23, 48, 7, 19), (0.0, 0, 0, 0, 0, 0), (None,) * 6):
        hitter = {"mlbam_id": 101, "normalized_name": "synthetic hitter", "role": "hitter",
                  "level": "AA", "age": 20, "plate_appearances": 200, "babip": values[0]}
        pitcher = {"mlbam_id": 202, "normalized_name": "synthetic pitcher", "role": "pitcher",
                   "level": "AAA", "age": 21, "innings_pitched": 60.0, **dict(zip(fields, values[1:]))}
        history = history_builder.build_card_history(
            [{"season": 2025, "hitters": [hitter], "pitchers": [pitcher]}],
            {"players": [{"normalized_name": "synthetic hitter"}, {"normalized_name": "synthetic pitcher"}]},
        )
        payload = exporter.build_contract(
            dataset={"rows": []},
            current={"season": 2026, "fetched_date": "2026-06-12", "hitters": [], "pitchers": []},
            milb_history=history, mlb_seasons={"101_hitter": [], "202_pitcher": []},
            draft_facts={}, fantrax_availability={}, generated_at="2026-06-12T00:00:00+00:00",
        )
        hitter_row = payload["current"]["hitters"][0]
        pitcher_row = payload["current"]["pitchers"][0]
        assert (hitter_row["babip"], *(pitcher_row[field] for field in fields)) == values
        assert hitter_row["source_kind"] == pitcher_row["source_kind"] == "latest_milb_history"
        assert hitter_row["sample_season"] == pitcher_row["sample_season"] == 2025


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
    assert hitter["age"] == 21
    assert hitter["name"] == "Missing Hitter"
    assert hitter["ops"] == 0.850
    assert hitter["draft_pick_number"] == 20
    assert len(pitcher_rows) == 2
    assert any(row["source_kind"] == "current_season" for row in pitcher_rows)
    assert any(row["source_kind"] == "latest_milb_history" for row in pitcher_rows)
    service_ids = {(row["mlbam_id"], row["role"]) for row in payload["mlb_service"]}
    assert (303, "hitter") in service_ids
    assert (202, "pitcher") in service_ids


def test_history_backfill_excludes_profiles_that_age_out_in_current_context():
    current = {
        "season": 2026,
        "fetched_date": "2026-06-15",
        "hitters": [],
        "pitchers": [],
    }
    history = {
        "players": {
            "aged out hitter": [{
                "mlbam_id": 404,
                "name": "Aged Out Hitter",
                "role": "hitter",
                "season": 2025,
                "level": "AAA",
                "age": 25,
                "team": "AAA Club",
                "plate_appearances": 200,
                "iso": 0.200,
                "k_pct": 18.0,
                "bb_pct": 12.0,
                "avg": 0.280,
                "obp": 0.370,
                "slg": 0.480,
            }]
        }
    }

    payload = exporter.build_contract(
        dataset=_historical(),
        current=current,
        milb_history=history,
        mlb_seasons={},
        generated_at="2026-06-15T00:00:00+00:00",
    )

    assert all(row["mlbam_id"] != 404 for row in payload["current"]["hitters"])


def test_fresh_age_ineligible_row_blocks_stale_history_fallback():
    current = {
        "season": 2026,
        "fetched_date": "2026-06-15",
        "hitters": [],
        "pitchers": [{
            "mlbam_id": 680951,
            "name": "Doug Nikhazy",
            "role": "pitcher",
            "level": "AAA",
            "age": 26,
            "position": "P",
            "innings_pitched": 33.0,
            "k_per_9": 9.3,
            "bb_per_9": 6.8,
            "k_bb_pct": 5.5,
            "era": 9.00,
            "whip": 2.03,
        }],
    }
    history = {
        "players": {
            "doug nikhazy": [{
                "mlbam_id": 680951,
                "name": "Doug Nikhazy",
                "role": "pitcher",
                "season": 2025,
                "level": "AAA",
                "age": 25,
                "team": "Columbus Clippers",
                "innings_pitched": 86.0,
                "k_per_9": 10.8,
                "bb_per_9": 3.5,
                "k_bb_pct": 18.0,
                "era": 3.40,
                "whip": 1.18,
            }]
        }
    }

    payload = exporter.build_contract(
        dataset=_historical(),
        current=current,
        milb_history=history,
        mlb_seasons={},
        generated_at="2026-06-15T00:00:00+00:00",
    )

    rows = [
        row
        for row in payload["current"]["pitchers"]
        if row["mlbam_id"] == 680951
    ]
    assert len(rows) == 1
    assert rows[0]["source_kind"] == "current_season"
    assert rows[0]["age"] == 26
    assert not payload["mlb_service"]


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


def test_statsapi_innings_parse_baseball_outs_for_graduation_service():
    assert exporter._statsapi_innings("25.1") == pytest.approx(25 + 1 / 3)
    assert exporter._statsapi_innings("25.2") == pytest.approx(25 + 2 / 3)
    assert exporter._statsapi_innings("25.0") == 25.0


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


def test_refresh_mlb_service_cache_updates_stale_cached_entries(monkeypatch, tmp_path):
    """Already-cached players MUST be refetched: current-season MLB lines keep
    growing, and fetch-only-missing froze them at their first snapshot (the
    Bolte 87-AB / missed-graduation bug)."""

    def fake_fetch(mlbam_id, role):
        return [{"year": 2026, "pa": 202, "ab": 176, "r": 20, "hr": 5, "rbi": 20,
                 "sb": 3, "avg": 0.260, "ops": 0.750, "so": 50}]

    monkeypatch.setattr(exporter, "_statsapi_service_seasons", fake_fetch)
    cache_path = tmp_path / "mlb_service_cache.json"
    stale = {"101_hitter": [{"year": 2026, "pa": 100, "ab": 87}]}

    result = exporter.refresh_mlb_service_cache(
        current=_current(),
        mlb_seasons=stale,
        cache_path=cache_path,
        max_workers=1,
    )

    assert result["missing_before"] == 0
    assert result["fetched"] == 1
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["101_hitter"][0]["ab"] == 176


def test_refresh_mlb_service_cache_keeps_prior_entry_on_fetch_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(exporter, "_statsapi_service_seasons", lambda m, r: None)
    cache_path = tmp_path / "mlb_service_cache.json"
    prior = {"101_hitter": [{"year": 2026, "pa": 100, "ab": 87}]}

    result = exporter.refresh_mlb_service_cache(
        current=_current(),
        mlb_seasons=prior,
        cache_path=cache_path,
        max_workers=1,
    )

    assert result["failed"] == 1
    assert result["written"] is False
    assert prior["101_hitter"][0]["ab"] == 87
    assert not cache_path.exists()


def test_malformed_service_json_preserves_prior_cache(monkeypatch, tmp_path):
    bad_payloads = (
        {}, None, [], {"stats": None}, {"stats": {}}, {"stats": [None]},
        {"stats": [{}]}, {"stats": [{"splits": None}]}, {"stats": [{"splits": {}}]},
        {"stats": [{"splits": [None]}]}, {"stats": [{"splits": [{}]}]},
        {"stats": [{"splits": [{"sport": {"id": 1}, "season": "bad", "stat": {}}]}]},
        {"stats": [{"splits": [{"sport": {"id": 1}, "season": "2026", "stat": None}]}]},
    )
    for index, bad in enumerate(bad_payloads):
        monkeypatch.setattr(exporter.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps(bad).encode()))
        cache_path = tmp_path / f"malformed_{index}.json"
        prior = {"101_hitter": [{"year": 2026, "pa": 100, "ab": 87}]}
        result = exporter.refresh_mlb_service_cache(
            current=_current(), mlb_seasons=prior, cache_path=cache_path, max_workers=1,
        )
        assert result["fetched"] == 0 and result["failed"] == 1, "Malformed response counted as a successful fetch"
        assert result["written"] is False and not cache_path.exists()
        assert prior == {"101_hitter": [{"year": 2026, "pa": 100, "ab": 87}]}


def test_verified_empty_service_json_can_refresh_cache(monkeypatch, tmp_path):
    for index, empty in enumerate(({"stats": []}, {"stats": [{"splits": []}]})):
        monkeypatch.setattr(exporter.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps(empty).encode()))
        cache_path = tmp_path / f"verified_empty_{index}.json"
        prior = {"101_hitter": [{"year": 2026, "pa": 100, "ab": 87}]}
        result = exporter.refresh_mlb_service_cache(
            current=_current(), mlb_seasons=prior, cache_path=cache_path, max_workers=1,
        )
        assert result["fetched"] == 1 and result["failed"] == 0
        assert json.loads(cache_path.read_text(encoding="utf-8")) == {"101_hitter": []}


def test_service_json_does_not_require_optional_statistics(monkeypatch):
    for role, stat in (
        ("hitter", {"plateAppearances": 0, "atBats": 0}),
        ("hitter", {"plateAppearances": "10", "atBats": "8"}),
        ("pitcher", {"inningsPitched": "0.0"}),
        ("pitcher", {"inningsPitched": "25.1"}),
        ("pitcher", {"inningsPitched": "25.2"}),
    ):
        payload = {"stats": [{"splits": [{"sport": {"id": 1}, "season": "2026", "stat": stat}]}]}
        monkeypatch.setattr(exporter.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()))
        seasons = exporter._statsapi_service_seasons(101, role)
        assert len(seasons) == 1 and seasons[0]["year"] == 2026
        if role == "hitter":
            assert seasons[0]["pa"] == int(stat["plateAppearances"])
            assert seasons[0]["ab"] == int(stat["atBats"])
        else:
            whole, outs = stat["inningsPitched"].split(".")
            assert abs(seasons[0]["ip"] - (int(whole) + int(outs) / 3)) < 1e-12


def _assert_unverified_service_counts_preserve_cache(monkeypatch, tmp_path, role):
    required = {"plateAppearances": 10, "atBats": 8} if role == "hitter" else {"inningsPitched": "25.1"}
    invalid = (None, True, False, "not numeric", "1 extra", [], {}, float("nan"), float("inf"), -1, 1.5)
    cases = [{}]
    for field in required:
        cases.append({key: value for key, value in required.items() if key != field})
        cases.extend({**required, field: value} for value in invalid)
    if role == "pitcher":
        cases.extend({"inningsPitched": value} for value in ("25.3", "25.12", "25.1 IP"))
    else:
        cases.append({"plateAppearances": 0, "atBats": 1})
    candidate = {"mlbam_id": 101, "role": role, "level": "AA", "age": 22,
                 "plate_appearances": 200, "innings_pitched": 60.0}
    current = {"hitters": [candidate] if role == "hitter" else [],
               "pitchers": [candidate] if role == "pitcher" else []}
    prior_seasons = [{"year": 2026, "pa": 100, "ab": 87}] if role == "hitter" else [{"year": 2026, "ip": 25.0}]
    for index, stat in enumerate(cases):
        payload = {"stats": [{"splits": [{"sport": {"id": 1}, "season": "2026", "stat": stat}]}]}
        monkeypatch.setattr(exporter.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode()))
        cache_path = tmp_path / f"unverified_{role}_{index}.json"
        prior = {f"101_{role}": [dict(season) for season in prior_seasons]}
        result = exporter.refresh_mlb_service_cache(
            current=current, mlb_seasons=prior, cache_path=cache_path, max_workers=1,
        )
        assert result["fetched"] == 0 and result["failed"] == 1, "Unverified service counts counted as a successful fetch"
        assert result["written"] is False and not cache_path.exists()
        assert prior == {f"101_{role}": prior_seasons}


def test_unverified_hitter_service_counts_preserve_prior_cache(monkeypatch, tmp_path):
    _assert_unverified_service_counts_preserve_cache(monkeypatch, tmp_path, "hitter")


def test_unverified_pitcher_service_counts_preserve_prior_cache(monkeypatch, tmp_path):
    _assert_unverified_service_counts_preserve_cache(monkeypatch, tmp_path, "pitcher")


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
