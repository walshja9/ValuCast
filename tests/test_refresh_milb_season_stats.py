import json

import pytest

from scripts import refresh_milb_season_stats as refresh


def _hitter_split():
    return {
        "season": "2026",
        "stat": {
            "age": 20,
            "gamesPlayed": 50,
            "runs": 44,
            "doubles": 14,
            "triples": 1,
            "homeRuns": 12,
            "strikeOuts": 32,
            "baseOnBalls": 18,
            "hits": 61,
            "avg": ".318",
            "atBats": 192,
            "obp": ".397",
            "slg": ".579",
            "ops": ".976",
            "stolenBases": 8,
            "plateAppearances": 224,
            "rbi": 48,
            "sacFlies": 2,
            "babip": ".349",
        },
        "team": {"id": 506, "name": "Portland Sea Dogs"},
        "player": {"id": 800001, "fullName": "Franklin Arias"},
        "sport": {"id": 12, "abbreviation": "AA"},
        "position": {"abbreviation": "SS"},
    }


def _pitcher_split():
    return {
        "season": "2026",
        "stat": {
            "age": 22,
            "gamesPlayed": 12,
            "gamesStarted": 11,
            "runs": 29,
            "homeRuns": 6,
            "strikeOuts": 77,
            "baseOnBalls": 36,
            "hits": 52,
            "era": "4.67",
            "inningsPitched": "52.0",
            "wins": 3,
            "losses": 4,
            "earnedRuns": 27,
            "whip": "1.40",
            "battersFaced": 226,
            "gamesPitched": 12,
            "strikeoutsPer9Inn": "13.33",
            "walksPer9Inn": "6.23",
            "numberOfPitches": 913,
            "strikes": 601,
        },
        "team": {"id": 494, "name": "Charlotte Knights"},
        "player": {"id": 800002, "fullName": "Hagen Smith"},
        "sport": {"id": 11, "abbreviation": "AAA"},
        "position": {"abbreviation": "P"},
    }


def test_build_milb_season_stats_converts_official_rows(monkeypatch):
    def fake_fetch(group, sport_id, season):
        if group == "hitting" and sport_id == 12:
            return [_hitter_split()]
        if group == "pitching" and sport_id == 11:
            return [_pitcher_split()]
        return []

    monkeypatch.setattr(refresh, "_fetch_splits", fake_fetch)

    payload = refresh.build_milb_season_stats(
        season=2026,
        fetched_date="2026-06-15",
    )

    assert payload["season"] == 2026
    assert payload["fetched_date"] == "2026-06-15"

    hitter = payload["hitters"][0]
    assert hitter["mlbam_id"] == 800001
    assert hitter["normalized_name"] == "franklin arias"
    assert hitter["level"] == "AA"
    assert hitter["sport_id"] == 12
    assert hitter["sample_fetched_date"] == "2026-06-15"
    assert hitter["plate_appearances"] == 224
    assert hitter["iso"] == 0.261
    assert hitter["k_pct"] == 14.3
    assert hitter["bb_pct"] == 8.0

    pitcher = payload["pitchers"][0]
    assert pitcher["mlbam_id"] == 800002
    assert pitcher["level"] == "AAA"
    assert pitcher["sample_fetched_date"] == "2026-06-15"
    assert pitcher["innings_pitched"] == 52.0
    assert pitcher["k_per_9"] == 13.33
    assert pitcher["bb_per_9"] == 6.23
    assert pitcher["k_bb_pct"] == 18.1
    assert pitcher["is_starter"] is True
    assert pitcher["pitches"] == 913
    assert pitcher["strikes"] == 601


def test_pitcher_pitch_counts_absent_when_api_omits_them(monkeypatch):
    def fake_fetch(group, sport_id, season):
        if group == "pitching" and sport_id == 11:
            split = _pitcher_split()
            split["stat"].pop("numberOfPitches")
            split["stat"].pop("strikes")
            return [split]
        return []

    monkeypatch.setattr(refresh, "_fetch_splits", fake_fetch)

    payload = refresh.build_milb_season_stats(season=2026, fetched_date="2026-06-15")
    pitcher = payload["pitchers"][0]
    # Never zero-fill a missing count: absent upstream stays explicitly None.
    assert pitcher["pitches"] is None
    assert pitcher["strikes"] is None


def test_write_refuses_tiny_refresh_against_existing_file(tmp_path):
    path = tmp_path / "milb_season_stats.json"
    existing = {
        "hitters": [{"mlbam_id": i} for i in range(800)],
        "pitchers": [{"mlbam_id": 1000 + i} for i in range(800)],
    }
    path.write_text(json.dumps(existing), encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to write tiny MiLB stats refresh"):
        refresh.write_milb_season_stats({"hitters": [], "pitchers": []}, path)

    assert json.loads(path.read_text(encoding="utf-8")) == existing


def test_write_allows_tiny_refresh_when_skip_flag_set(tmp_path, monkeypatch):
    path = tmp_path / "milb_season_stats.json"
    existing = {
        "hitters": [{"mlbam_id": i} for i in range(800)],
        "pitchers": [{"mlbam_id": 1000 + i} for i in range(800)],
    }
    path.write_text(json.dumps(existing), encoding="utf-8")

    monkeypatch.setenv("VALUCAST_SKIP_MILB_TINY_GUARD", "1")
    tiny = {"hitters": [{"mlbam_id": 42}], "pitchers": []}
    refresh.write_milb_season_stats(tiny, path)

    assert json.loads(path.read_text(encoding="utf-8")) == tiny
