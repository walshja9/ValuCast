"""Tests for targeted MiLB player stat refreshes."""
import pytest

from scripts.refresh_milb_player_stats import _hitter_updates
from scripts.refresh_milb_player_stats import _latest_current_row
from scripts.refresh_milb_player_stats import _pitcher_updates
from scripts.refresh_milb_player_stats import extract_mlb_stats_data


def test_extracts_milb_stats_data_array_from_player_page_script():
    html = '''
    <script>
      window.foo = true;
      mlbStatsData: [{"type":"yearByYear","group":"hitting","gameType":"R",
        "season":"2026","playerId":"806198","plateAppearances":261}]
      , nextGame: {}
    </script>
    '''

    rows = extract_mlb_stats_data(html)

    assert rows == [
        {
            "type": "yearByYear",
            "group": "hitting",
            "gameType": "R",
            "season": "2026",
            "playerId": "806198",
            "plateAppearances": 261,
        }
    ]


def test_hitter_updates_recompute_display_stats_from_current_milb_row():
    row = {
        "type": "yearByYear",
        "group": "hitting",
        "gameType": "R",
        "season": "2026",
        "playerId": "806198",
        "gamesPlayed": 58,
        "runs": 34,
        "doubles": 6,
        "triples": 4,
        "homeRuns": 6,
        "strikeOuts": 37,
        "baseOnBalls": 34,
        "hits": 53,
        "avg": ".241",
        "atBats": 220,
        "obp": ".349",
        "slg": ".386",
        "ops": ".735",
        "stolenBases": 17,
        "plateAppearances": 261,
        "rbi": 32,
        "sacFlies": 1,
    }

    selected = _latest_current_row([row], 806198, "hitter", 2026)
    updates = _hitter_updates(selected, "2026-06-15")

    assert updates["plate_appearances"] == 261
    assert updates["at_bats"] == 220
    assert updates["avg"] == 0.241
    assert updates["obp"] == 0.349
    assert updates["slg"] == 0.386
    assert updates["ops"] == 0.735
    assert updates["iso"] == 0.145
    assert updates["k_pct"] == 14.2
    assert updates["bb_pct"] == 13.0
    assert updates["babip"] == 0.264
    assert updates["sample_fetched_date"] == "2026-06-15"


def test_pitcher_updates_recompute_display_stats_from_current_milb_row():
    row = {
        "type": "yearByYear",
        "group": "pitching",
        "gameType": "R",
        "season": "2026",
        "playerId": "806198",
        "inningsPitched": "45.1",
        "strikeOuts": 60,
        "baseOnBalls": 15,
        "hits": 40,
        "homeRuns": 5,
        "earnedRuns": 20,
        "runs": 22,
        "battersFaced": 190,
        "wins": 4,
        "losses": 2,
        "gamesPlayed": 12,
        "gamesStarted": 8,
    }

    selected = _latest_current_row([row], 806198, "pitcher", 2026)
    updates = _pitcher_updates(selected, "2026-06-15")

    assert updates["innings_pitched"] == pytest.approx(45.3333333333)
    assert updates["strikeouts"] == 60
    assert updates["walks"] == 15
    assert updates["hits"] == 40
    assert updates["home_runs"] == 5
    assert updates["earned_runs"] == 20
    assert updates["runs"] == 22
    assert updates["batters_faced"] == 190
    assert updates["wins"] == 4
    assert updates["losses"] == 2
    assert updates["games_played"] == 12
    assert updates["games_started"] == 8
    assert updates["era"] == 3.97
    assert updates["whip"] == 1.21
    assert updates["k_per_9"] == 11.91
    assert updates["bb_per_9"] == 2.98
    assert updates["k_bb_pct"] == 23.7
    assert updates["sample_fetched_date"] == "2026-06-15"
