import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from scraper.mlb_actuals import (
    build_historical_actuals,
    derive_qs_from_games,
    fetch_actuals,
    fetch_game_logs,
    normalize_hitter,
    normalize_ip,
    normalize_pitcher,
    regular_season_games_final,
)


class TestNormalizeIP(unittest.TestCase):
    def test_whole_innings(self):
        self.assertAlmostEqual(normalize_ip(6.0), 6.0, places=4)

    def test_one_out(self):
        self.assertAlmostEqual(normalize_ip(4.1), 4.3333, places=3)

    def test_two_outs(self):
        self.assertAlmostEqual(normalize_ip(4.2), 4.6667, places=3)

    def test_zero(self):
        self.assertAlmostEqual(normalize_ip(0.0), 0.0, places=4)

    def test_string_input(self):
        self.assertAlmostEqual(normalize_ip(float("13.1")), 13.3333, places=3)


SAMPLE_MLB_HITTER = {
    "player": {"id": 592450, "fullName": "Aaron Judge"},
    "stat": {
        "plateAppearances": 241, "atBats": 198, "hits": 50,
        "homeRuns": 17, "runs": 41, "rbi": 32,
        "stolenBases": 5, "caughtStealing": 1,
        "baseOnBalls": 39, "strikeOuts": 68,
        "hitByPitch": 2, "sacFlies": 0,
        "doubles": 9, "triples": 0,
        "gamesPlayed": 55, "intentionalWalks": 3,
    },
    "team": {"abbreviation": "NYY"},
}


class TestNormalizeHitter(unittest.TestCase):
    def test_basic_fields(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        self.assertEqual(result["name"], "Aaron Judge")
        self.assertEqual(result["pool"], "hitter")
        self.assertEqual(result["metadata"]["mlbam_id"], "592450")
        self.assertEqual(result["stats"]["PA"], 241)
        self.assertEqual(result["stats"]["HR"], 17)

    def test_singles_derived(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        self.assertEqual(result["stats"]["1B"], 24)  # 50 - 9 - 0 - 17

    def test_tb_derived(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        self.assertEqual(result["stats"]["TB"], 110)  # 24 + 18 + 0 + 68

    def test_nsb_derived(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        self.assertEqual(result["stats"]["NSB"], 4)

    def test_has_base_id(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        self.assertEqual(result["metadata"]["base_id"], "mlbam_592450")

    def test_namespaced_id(self):
        result = normalize_hitter(SAMPLE_MLB_HITTER, "2026-05-25")
        self.assertEqual(result["id"], "mlbam_592450_H")


SAMPLE_MLB_PITCHER = {
    "player": {"id": 669373, "fullName": "Tarik Skubal"},
    "stat": {
        "inningsPitched": "43.1", "earnedRuns": 13,
        "baseOnBalls": 8, "hits": 30, "strikeOuts": 45,
        "wins": 4, "losses": 1, "saves": 0, "holds": 0,
        "gamesStarted": 7, "gamesPitched": 7,
    },
    "team": {"abbreviation": "DET"},
}


class TestNormalizePitcher(unittest.TestCase):
    def test_basic_fields(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertEqual(result["name"], "Tarik Skubal")
        self.assertEqual(result["pool"], "starter")
        self.assertEqual(result["metadata"]["mlbam_id"], "669373")

    def test_ip_normalized(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertAlmostEqual(result["stats"]["IP"], 43.3333, places=3)

    def test_h_allowed_not_h(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertIn("H_ALLOWED", result["stats"])
        self.assertNotIn("H", result["stats"])
        self.assertEqual(result["stats"]["H_ALLOWED"], 30)

    def test_k_not_strikeouts(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertIn("K", result["stats"])
        self.assertEqual(result["stats"]["K"], 45)

    def test_qs_included(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertEqual(result["stats"]["QS"], 5)

    def test_sv_hld_derived(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertEqual(result["stats"]["SV_HLD"], 0)

    def test_namespaced_id(self):
        result = normalize_pitcher(SAMPLE_MLB_PITCHER, qs=5, as_of="2026-05-25")
        self.assertEqual(result["id"], "mlbam_669373_P")

    def test_reliever_pool_detection(self):
        rp_data = {"player": {"id": 999, "fullName": "RP Guy"},
                   "stat": {"inningsPitched": "30.0", "earnedRuns": 5,
                            "baseOnBalls": 10, "hits": 20, "strikeOuts": 35,
                            "wins": 2, "losses": 1, "saves": 20, "holds": 5,
                            "gamesStarted": 0, "gamesPitched": 40},
                   "team": {"abbreviation": "BOS"}}
        result = normalize_pitcher(rp_data, qs=0, as_of="2026-05-25")
        self.assertEqual(result["pool"], "reliever")


class TestDeriveQS(unittest.TestCase):
    def test_qs_count(self):
        games = [
            {"stat": {"gamesStarted": 1, "inningsPitched": "6.0", "earnedRuns": 2}},
            {"stat": {"gamesStarted": 1, "inningsPitched": "5.2", "earnedRuns": 1}},
            {"stat": {"gamesStarted": 1, "inningsPitched": "7.0", "earnedRuns": 4}},
            {"stat": {"gamesStarted": 0, "inningsPitched": "1.0", "earnedRuns": 0}},
        ]
        # Game 1: 6.0 IP, 2 ER → QS
        # Game 2: 5.2 = 5⅔ IP < 6.0 → not QS
        # Game 3: 7.0 IP, 4 ER > 3 → not QS
        # Game 4: relief → skip
        self.assertEqual(derive_qs_from_games(games), 1)

    def test_empty_games(self):
        self.assertEqual(derive_qs_from_games([]), 0)


class TestRegularSeasonResponseGuards(unittest.TestCase):
    @patch("scraper.mlb_actuals._fetch_json")
    def test_rejects_wrong_schedule_shapes(self, fetch):
        payloads = (
            None, [], {}, {"dates": None}, {"dates": {}},
            {"dates": [None]}, {"dates": [{"games": None}]},
            {"dates": [{"games": {}}]}, {"dates": [{"games": [None]}]},
            {"dates": [{"games": [{}]}]},
            {"dates": [{"games": [{"status": None}]}]},
            {"dates": [{"games": [{"status": []}]}]},
            {"dates": [{"games": [{"status": {}}]}]},
            {"dates": [{"games": [{"status": {"abstractGameState": None}}]}]},
            {"dates": [{"games": [{"status": {"abstractGameState": 0}}]}]},
            {"dates": [{"games": [{"status": {"abstractGameState": ""}}]}]},
            {"dates": [{"games": [{"status": {"abstractGameState": "  "}}]}]},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                fetch.return_value = payload
                with self.assertRaisesRegex(ValueError, "MLB schedule"):
                    regular_season_games_final("2026-05-03", "2026-05-10")

    @patch("scraper.mlb_actuals._fetch_json")
    def test_empty_schedule_and_days_without_games_are_valid(self, fetch):
        for payload in ({"dates": []}, {"dates": [{}]}, {"dates": [{"games": []}]}):
            with self.subTest(payload=payload):
                fetch.return_value = payload
                self.assertEqual(regular_season_games_final("2026-05-03", "2026-05-10"), 0)


class TestActualsResponseGuards(unittest.TestCase):
    @patch("scraper.mlb_actuals._fetch_json")
    def test_rejects_wrong_actuals_shapes_in_either_group(self, fetch):
        payloads = (
            None, [], {}, {"stats": None}, {"stats": {}}, {"stats": []},
            {"stats": [None]}, {"stats": [[]]}, {"stats": [{}]},
            {"stats": [{"splits": None}]}, {"stats": [{"splits": {}}]},
        )
        for group in ("hitting", "pitching"):
            for payload in payloads:
                with self.subTest(group=group, payload=payload):
                    fetch.side_effect = lambda url: (
                        payload if f"group={group}" in url else {"stats": [{"splits": []}]}
                    )
                    with self.assertRaisesRegex(ValueError, f"MLB {group} actuals"):
                        fetch_actuals(2026)

    @patch("scraper.mlb_actuals._fetch_json", return_value={"stats": [{"splits": []}]})
    def test_empty_splits_are_valid(self, _fetch):
        self.assertEqual(fetch_actuals(2026), {"hitters": [], "pitchers": []})

    @patch("scraper.mlb_actuals._fetch_json")
    def test_rejects_wrong_total_splits_in_either_location(self, fetch):
        for group in ("hitting", "pitching"):
            for total in (1, None, False, "0"):
                for location in ("group", "payload"):
                    payload = {"stats": [{"splits": []}]}
                    (payload["stats"][0] if location == "group" else payload)["totalSplits"] = total
                    with self.subTest(group=group, total=total, location=location):
                        fetch.side_effect = lambda url: (
                            payload if f"group={group}" in url else {"stats": [{"splits": []}]}
                        )
                        with self.assertRaisesRegex(ValueError, f"MLB {group} actuals.*totalSplits"):
                            fetch_actuals(2026)

    @patch("scraper.mlb_actuals._fetch_json")
    def test_rejects_contradictory_total_splits_declarations(self, fetch):
        for group in ("hitting", "pitching"):
            with self.subTest(group=group):
                payload = {"stats": [{"splits": [], "totalSplits": 0}], "totalSplits": 1}
                fetch.side_effect = lambda url: (
                    payload if f"group={group}" in url else {"stats": [{"splits": []}]}
                )
                with self.assertRaisesRegex(ValueError, f"MLB {group} actuals.*totalSplits"):
                    fetch_actuals(2026)

    @patch("scraper.mlb_actuals._fetch_json")
    def test_limit_sized_response_needs_a_matching_total_in_both_groups(self, fetch):
        for group in ("hitting", "pitching"):
            with self.subTest(group=group):
                def fake_fetch(url):
                    limit = int(parse_qs(urlsplit(url).query)["limit"][0])
                    return {"stats": [{"splits": [{}] * limit if f"group={group}" in url else []}]}

                fetch.side_effect = fake_fetch
                with self.assertRaisesRegex(ValueError, f"MLB {group} actuals.*limit"):
                    fetch_actuals(2026)

    @patch("scraper.mlb_actuals._fetch_json")
    def test_matching_totals_accept_limit_sized_responses(self, fetch):
        for location in ("group", "payload"):
            with self.subTest(location=location):
                def fake_fetch(url):
                    limit = int(parse_qs(urlsplit(url).query)["limit"][0])
                    payload = {"stats": [{"splits": [{}] * limit}]}
                    (payload["stats"][0] if location == "group" else payload)["totalSplits"] = limit
                    return payload

                fetch.side_effect = fake_fetch
                result = fetch_actuals(2026)
                self.assertTrue(result["hitters"])
                self.assertEqual(len(result["hitters"]), len(result["pitchers"]))


class TestGameLogResponseGuards(unittest.TestCase):
    def test_rejects_wrong_game_log_shapes(self):
        for payload in (
            None, [], {}, {"stats": None}, {"stats": {}}, {"stats": ""},
            {"stats": [None]}, {"stats": [[]]}, {"stats": [{}]},
            {"stats": [{"splits": None}]}, {"stats": [{"splits": {}}]},
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "MLB.*game logs"):
                    fetch_game_logs("999", "hitting", season=2026, fetcher=lambda _url: payload)

    def test_empty_stats_and_splits_are_valid(self):
        for payload in ({"stats": []}, {"stats": [{"splits": []}]}):
            with self.subTest(payload=payload):
                self.assertEqual(
                    fetch_game_logs("999", "hitting", season=2026, fetcher=lambda _url: payload), []
                )


class TestHistoricalActuals(unittest.TestCase):
    def test_fetch_game_logs_treats_empty_stats_as_no_games(self):
        rows = fetch_game_logs(
            "999",
            "hitting",
            season=2026,
            fetcher=lambda _url: {"stats": []},
        )

        self.assertEqual(rows, [])

    def test_sums_hitter_game_logs_through_as_of_date(self):
        def fake_fetch(url):
            self.assertIn("group=hitting", url)
            return {"stats": [{"splits": [
                {
                    "date": "2026-06-17",
                    "player": {"id": 101, "fullName": "Test Hitter"},
                    "team": {"abbreviation": "BOS"},
                    "stat": {
                        "hits": 2, "homeRuns": 1, "runs": 1, "rbi": 3,
                        "doubles": 1, "triples": 0, "strikeOuts": 1,
                        "baseOnBalls": 1, "hitByPitch": 0, "sacFlies": 0,
                        "atBats": 4, "plateAppearances": 5,
                        "stolenBases": 1, "caughtStealing": 0,
                        "gamesPlayed": 1,
                    },
                },
                {
                    "date": "2026-06-18",
                    "player": {"id": 101, "fullName": "Test Hitter"},
                    "team": {"abbreviation": "BOS"},
                    "stat": {
                        "hits": 1, "homeRuns": 0, "runs": 1, "rbi": 1,
                        "doubles": 0, "triples": 0, "strikeOuts": 2,
                        "baseOnBalls": 0, "hitByPitch": 0, "sacFlies": 0,
                        "atBats": 4, "plateAppearances": 4,
                        "stolenBases": 0, "caughtStealing": 1,
                        "gamesPlayed": 1,
                    },
                },
                {
                    "date": "2026-06-19",
                    "player": {"id": 101, "fullName": "Test Hitter"},
                    "team": {"abbreviation": "BOS"},
                    "stat": {
                        "hits": 4, "homeRuns": 4, "runs": 4, "rbi": 8,
                        "doubles": 0, "triples": 0, "strikeOuts": 0,
                        "baseOnBalls": 0, "hitByPitch": 0, "sacFlies": 0,
                        "atBats": 4, "plateAppearances": 4,
                        "stolenBases": 4, "caughtStealing": 0,
                        "gamesPlayed": 1,
                    },
                },
            ]}]}

        rows = build_historical_actuals(
            {"101": "hitter"}, season=2026, as_of="2026-06-18",
            delay=0.0, fetcher=fake_fetch,
        )

        self.assertEqual(len(rows), 1)
        stats = rows[0]["stats"]
        self.assertEqual(stats["H"], 3)
        self.assertEqual(stats["HR"], 1)
        self.assertEqual(stats["R"], 2)
        self.assertEqual(stats["RBI"], 4)
        self.assertEqual(stats["SB"], 1)
        self.assertEqual(stats["CS"], 1)
        self.assertEqual(stats["PA"], 9)
        self.assertEqual(stats["G"], 2)
        self.assertEqual(stats["TB"], 7)
        self.assertEqual(stats["AVG"], 0.375)

    def test_sums_pitcher_ip_as_outs_and_excludes_future_games(self):
        def fake_fetch(url):
            self.assertIn("group=pitching", url)
            return {"stats": [{"splits": [
                {
                    "date": "2026-06-12",
                    "player": {"id": 202, "fullName": "Test Pitcher"},
                    "team": {"abbreviation": "LAD"},
                    "stat": {
                        "inningsPitched": "6.2", "earnedRuns": 2,
                        "baseOnBalls": 1, "hits": 5, "strikeOuts": 8,
                        "wins": 1, "losses": 0, "saves": 0, "holds": 0,
                        "gamesStarted": 1, "gamesPitched": 1,
                    },
                },
                {
                    "date": "2026-06-18",
                    "player": {"id": 202, "fullName": "Test Pitcher"},
                    "team": {"abbreviation": "LAD"},
                    "stat": {
                        "inningsPitched": "5.1", "earnedRuns": 1,
                        "baseOnBalls": 2, "hits": 5, "strikeOuts": 5,
                        "wins": 0, "losses": 1, "saves": 0, "holds": 0,
                        "gamesStarted": 1, "gamesPitched": 1,
                    },
                },
                {
                    "date": "2026-06-19",
                    "player": {"id": 202, "fullName": "Test Pitcher"},
                    "team": {"abbreviation": "LAD"},
                    "stat": {
                        "inningsPitched": "1.0", "earnedRuns": 10,
                        "baseOnBalls": 10, "hits": 10, "strikeOuts": 0,
                        "wins": 0, "losses": 0, "saves": 1, "holds": 0,
                        "gamesStarted": 0, "gamesPitched": 1,
                    },
                },
            ]}]}

        rows = build_historical_actuals(
            {"202": "pitcher"}, season=2026, as_of="2026-06-18",
            delay=0.0, fetcher=fake_fetch,
        )

        self.assertEqual(len(rows), 1)
        stats = rows[0]["stats"]
        self.assertEqual(stats["IP"], 12.0)
        self.assertEqual(stats["ER"], 3)
        self.assertEqual(stats["BB"], 3)
        self.assertEqual(stats["H_ALLOWED"], 10)
        self.assertEqual(stats["K"], 13)
        self.assertEqual(stats["W"], 1)
        self.assertEqual(stats["SV"], 0)
        self.assertEqual(stats["GS"], 2)
        self.assertEqual(stats["G"], 2)
        self.assertEqual(stats["QS"], 1)


if __name__ == "__main__":
    unittest.main()
