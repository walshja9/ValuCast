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
