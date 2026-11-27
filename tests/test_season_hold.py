"""The pipeline stays on CONTEXT_SEASON when the calendar moves past it."""
from __future__ import annotations

import json
import sys
from datetime import date

import pytest

import mlb.availability
import mlb.dynasty
import mlb.track_record
import scraper.season
from mlb import roster_status
from mlb.playing_time_role import _season_pace_factor
from prospects.raw_input_builder import _age_for_current_context, _sanitize_current_row
from scraper.season import context_season
from scripts import fetch_statcast_percentiles, validate_public_data_freshness


class _Jan2027(date):
    @classmethod
    def today(cls):
        return cls(2027, 1, 2)


@pytest.fixture
def jan_2027(monkeypatch):
    monkeypatch.setattr(scraper.season, "date", _Jan2027)


def test_context_season_caps_at_the_served_season(jan_2027):
    assert context_season() == 2026
    assert context_season(2027) == 2026
    assert context_season(2026) == 2026
    assert context_season(2025) == 2025


@pytest.mark.parametrize(
    "module", [mlb.availability, mlb.dynasty, mlb.track_record, roster_status]
)
def test_generated_at_cannot_move_the_season_past_the_served_one(module):
    assert module._season_from_generated_at("2027-01-02T12:00:00Z") == 2026
    assert module._season_from_generated_at("2026-11-02T12:00:00Z") == 2026
    assert module._season_from_generated_at("2025-06-01T12:00:00Z") == 2025


def _staleness(sample_season, fetched_date):
    row = _sanitize_current_row(
        {"mlbam_id": 1, "name": "Prospect", "age": 20},
        "hitter",
        {},
        sample_season=sample_season,
        fetched_date=fetched_date,
        source_artifact="milb_season_stats",
        source_kind="current_season",
        availability_by_key={},
    )
    return row["sample_staleness_years"]


def test_prospect_staleness_holds_across_jan_1():
    assert _staleness(2026, "2027-01-02") == 0
    assert _staleness(2025, "2027-01-02") == 1
    assert _staleness(2026, "2026-11-02") == 0
    assert _staleness(2025, "2026-11-02") == 1


def test_prospect_age_holds_across_jan_1():
    assert _age_for_current_context(20, 2026, "2027-01-02") == 20
    assert _age_for_current_context(20, 2025, "2027-01-02") == 21
    assert _age_for_current_context(20, 2025, "2026-11-02") == 21


def test_pace_only_annualizes_inside_the_season():
    assert _season_pace_factor("2026-06-26") == pytest.approx(185 / 93)
    assert _season_pace_factor("2026-09-27") == 4.0
    assert _season_pace_factor("2026-03-01") == 1.0
    assert _season_pace_factor("2026-11-02") == 1.0
    assert _season_pace_factor("2027-05-01") == 1.0


def test_statcast_default_year_holds_on_jan_1(jan_2027, monkeypatch):
    years = []

    def stop(_kind, year):
        years.append(year)
        raise InterruptedError

    monkeypatch.setattr(fetch_statcast_percentiles, "_fetch_csv", stop)
    monkeypatch.setattr(sys, "argv", ["fetch_statcast_percentiles.py"])
    with pytest.raises(InterruptedError):
        fetch_statcast_percentiles.main()
    assert years == [2026]


@pytest.mark.parametrize(
    "expected_date, season, ok",
    [
        ("2027-01-02", 2026, True),
        ("2027-01-02", 2025, False),
        ("2026-11-02", 2026, True),
        ("2026-11-02", 2025, False),
    ],
)
def test_freshness_season_check_uses_the_served_season(monkeypatch, expected_date, season, ok):
    fresh = validate_public_data_freshness
    monkeypatch.delenv("VALUCAST_ACTUALS_SEASON", raising=False)
    monkeypatch.setattr(
        fresh,
        "_load",
        lambda path: (
            {"as_of": expected_date, "season": season}
            if path == fresh.REDRAFT_METADATA
            else {}
        ),
    )
    problems = [p for p in fresh.validate_public_data(expected_date) if f"season={season}" in p]
    assert not problems if ok else problems


def _degraded_run(tmp_path, monkeypatch, games_final):
    """Run the roster build with six teams refetching empty over a warm cache."""
    teams = [{"id": 100 + i, "name": f"Team {i}", "abbreviation": f"T{i}"} for i in range(6)]
    prior_rows = {
        team["id"]: [
            {
                "person": {"id": 9000 + team["id"] * 100 + n, "fullName": f"Prior {n}"},
                "position": {"abbreviation": "SS"},
                "status": {"code": "A", "description": "Active"},
            }
            for n in range(2)
        ]
        for team in teams
    }
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "queries": {
                    f"team:{team_id}:rosterType=active": {
                        "fetched_at": "2026-11-01T12:00:00Z",
                        "rows": rows,
                    }
                    for team_id, rows in prior_rows.items()
                },
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def schedule(start, end):
        calls.append((start, end))
        if isinstance(games_final, Exception):
            raise games_final
        return games_final

    monkeypatch.setattr(roster_status, "regular_season_games_final", schedule)
    result = roster_status.run_mlb_roster_status(
        tmp_path / "metadata.json",
        tmp_path / "artifact.json",
        cache_path,
        tmp_path / "archive",
        generated_at="2026-12-15T12:00:00Z",
        season=2026,
        teams_fetcher=lambda _season: teams,
        roster_fetcher=lambda _team_id: [],
        refresh=True,
    )
    return result, calls, tmp_path / "artifact.json"


def test_rosters_hold_when_the_feed_empties_with_no_games(tmp_path, monkeypatch, capsys):
    result, calls, artifact = _degraded_run(tmp_path, monkeypatch, games_final=0)
    assert calls == [("2026-12-08", "2026-12-15")]
    assert result["roster_feed_status"] == "held"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["roster_feed_status"] == "held"
    assert payload["validation"]["active_roster_profile_count"] == 12
    assert "::warning::" in capsys.readouterr().out


def test_rosters_still_refuse_when_games_are_being_played(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="statsapi outage"):
        _degraded_run(tmp_path, monkeypatch, games_final=5)


def test_schedule_failure_is_not_treated_as_no_games(tmp_path, monkeypatch):
    with pytest.raises(OSError):
        _degraded_run(tmp_path, monkeypatch, games_final=OSError("schedule down"))
