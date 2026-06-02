import unittest
from scraper.combine import combine_outlook, _pool_family


class TestPoolFamily(unittest.TestCase):
    def test_hitter(self):
        self.assertEqual(_pool_family("hitter"), "hitter")

    def test_starter(self):
        self.assertEqual(_pool_family("starter"), "pitcher")

    def test_reliever(self):
        self.assertEqual(_pool_family("reliever"), "pitcher")

    def test_pitcher(self):
        self.assertEqual(_pool_family("pitcher"), "pitcher")


ROS_HITTER = {
    "id": "15640", "name": "Aaron Judge", "pool": "hitter",
    "positions": ["RF", "DH"], "team": "NYY",
    "stats": {"PA": 450, "AB": 380, "H": 110, "HR": 28, "R": 75,
              "RBI": 80, "SB": 4, "CS": 1, "BB": 60, "SO": 100,
              "HBP": 3, "SF": 4, "1B": 60, "2B": 18, "3B": 0, "G": 100,
              "AVG": 0.289, "OBP": 0.400, "SLG": 0.570, "OPS": 0.970,
              "TB": 217, "NSB": 3},
    "metadata": {"fangraphs_id": "15640", "mlbam_id": "592450"},
}

ACTUAL_HITTER = {
    "id": "mlbam_592450_H", "name": "Aaron Judge", "pool": "hitter",
    "positions": [], "team": "NYY",
    "stats": {"PA": 241, "AB": 198, "H": 50, "HR": 17, "R": 41,
              "RBI": 32, "SB": 5, "CS": 1, "BB": 39, "SO": 68,
              "HBP": 2, "SF": 0, "1B": 24, "2B": 9, "3B": 0, "G": 55,
              "AVG": 0.253, "OBP": 0.381, "SLG": 0.556, "OPS": 0.937,
              "TB": 110, "NSB": 4},
    "metadata": {"mlbam_id": "592450", "base_id": "mlbam_592450",
                 "source": "mlb_stats_api", "as_of": "2026-05-25"},
}

ROS_PITCHER = {
    "id": "22267", "name": "Tarik Skubal", "pool": "starter",
    "positions": ["SP"], "team": "DET",
    "stats": {"IP": 97.29, "ER": 30, "BB": 20, "H_ALLOWED": 78, "K": 116,
              "W": 7, "L": 4, "SV": 0, "HLD": 0, "GS": 15, "G": 15,
              "QS": 10, "SV_HLD": 0,
              "ERA": 2.78, "WHIP": 1.01, "K_BB": 5.8, "K_9": 10.74, "BB_9": 1.85},
    "metadata": {"fangraphs_id": "22267", "mlbam_id": "669373"},
}

ACTUAL_PITCHER = {
    "id": "mlbam_669373_P", "name": "Tarik Skubal", "pool": "starter",
    "positions": ["SP"], "team": "DET",
    "stats": {"IP": 43.3333, "ER": 13, "BB": 8, "H_ALLOWED": 30, "K": 45,
              "W": 4, "L": 1, "SV": 0, "HLD": 0, "GS": 7, "G": 7,
              "QS": 5, "SV_HLD": 0,
              "ERA": 2.70, "WHIP": 0.88, "K_BB": 5.63, "K_9": 9.35, "BB_9": 1.66},
    "metadata": {"mlbam_id": "669373", "base_id": "mlbam_669373",
                 "source": "mlb_stats_api", "as_of": "2026-05-25"},
}


class TestCombineOutlook(unittest.TestCase):
    def test_hitter_counting_stats_add(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        self.assertEqual(judge["stats"]["PA"], 241 + 450)
        self.assertEqual(judge["stats"]["HR"], 17 + 28)

    def test_hitter_rate_stats_recalculated(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        total_h = 50 + 110
        total_ab = 198 + 380
        expected_avg = total_h / total_ab
        self.assertAlmostEqual(judge["stats"]["AVG"], expected_avg, places=3)

    def test_preserves_ros_id(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        self.assertEqual(judge["id"], "15640")

    def test_has_base_id(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        self.assertEqual(judge["metadata"]["base_id"], "mlbam_592450")

    def test_pitcher_ip_adds(self):
        result = combine_outlook([ROS_PITCHER], [ACTUAL_PITCHER])
        skubal = next(p for p in result if p["name"] == "Tarik Skubal")
        self.assertAlmostEqual(skubal["stats"]["IP"], 43.3333 + 97.29, places=2)

    def test_pitcher_era_recalculated(self):
        result = combine_outlook([ROS_PITCHER], [ACTUAL_PITCHER])
        skubal = next(p for p in result if p["name"] == "Tarik Skubal")
        total_er = 13 + 30
        total_ip = 43.3333 + 97.29
        expected_era = 9 * total_er / total_ip
        self.assertAlmostEqual(skubal["stats"]["ERA"], expected_era, places=2)

    def test_ros_only_player_passes_through(self):
        ros_only = dict(ROS_HITTER)
        ros_only = {**ros_only, "id": "99999", "name": "ROS Only",
                    "metadata": {**ROS_HITTER["metadata"], "mlbam_id": "999999"}}
        result = combine_outlook([ROS_HITTER, ros_only], [ACTUAL_HITTER])
        names = [p["name"] for p in result]
        self.assertIn("ROS Only", names)

    def test_actuals_only_player_included(self):
        actuals_only = {**ACTUAL_HITTER, "id": "mlbam_111111_H", "name": "Call Up",
                        "metadata": {**ACTUAL_HITTER["metadata"], "mlbam_id": "111111",
                                     "base_id": "mlbam_111111"}}
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER, actuals_only])
        callup = next(p for p in result if p["name"] == "Call Up")
        self.assertEqual(callup["metadata"]["has_ros"], False)

    def test_actuals_only_keeps_namespaced_id(self):
        actuals_only = {**ACTUAL_HITTER, "id": "mlbam_111111_H", "name": "Call Up",
                        "metadata": {**ACTUAL_HITTER["metadata"], "mlbam_id": "111111",
                                     "base_id": "mlbam_111111"}}
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER, actuals_only])
        callup = next(p for p in result if p["name"] == "Call Up")
        self.assertEqual(callup["id"], "mlbam_111111_H")

    def test_matched_has_ros_true(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        self.assertEqual(judge["metadata"]["has_ros"], True)

    def test_matched_has_stats_actual(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        stats_actual = judge["metadata"]["stats_actual"]
        self.assertEqual(stats_actual["PA"], 241)
        self.assertEqual(stats_actual["HR"], 17)

    def test_matched_has_stats_ros(self):
        result = combine_outlook([ROS_HITTER], [ACTUAL_HITTER])
        judge = next(p for p in result if p["name"] == "Aaron Judge")
        stats_ros = judge["metadata"]["stats_ros"]
        self.assertEqual(stats_ros["PA"], 450)
        self.assertEqual(stats_ros["HR"], 28)

    def test_ros_only_has_no_stats_actual(self):
        ros_only = {**ROS_HITTER, "id": "99999", "name": "ROS Only",
                    "metadata": {**ROS_HITTER["metadata"], "mlbam_id": "999999"}}
        result = combine_outlook([ros_only], [])
        player = next(p for p in result if p["name"] == "ROS Only")
        self.assertNotIn("stats_actual", player["metadata"])

    def test_actuals_only_has_no_stats_ros(self):
        actuals_only = {**ACTUAL_HITTER, "id": "mlbam_111111_H", "name": "Call Up",
                        "metadata": {**ACTUAL_HITTER["metadata"], "mlbam_id": "111111",
                                     "base_id": "mlbam_111111"}}
        result = combine_outlook([], [actuals_only])
        player = next(p for p in result if p["name"] == "Call Up")
        self.assertNotIn("stats_ros", player["metadata"])

    def test_matched_player_carries_sources(self):
        ros = [{
            "id": "mlbam_5_H", "name": "Test Bat", "pool": "hitter",
            "positions": ["1B"], "team": "NYY",
            "stats": {"PA": 100, "AB": 90, "H": 30, "HR": 5, "1B": 20,
                      "2B": 4, "3B": 1, "R": 15, "RBI": 18, "SB": 2, "CS": 1,
                      "BB": 8, "SO": 20, "HBP": 1, "SF": 1, "G": 25},
            "metadata": {"mlbam_id": "5"},
            "sources": ["steamer"],
        }]
        actual = [{
            "id": "mlbam_5_H", "name": "Test Bat", "pool": "hitter",
            "stats": {"PA": 50, "AB": 45, "H": 15, "HR": 2, "1B": 10,
                      "2B": 2, "3B": 1, "R": 7, "RBI": 9, "SB": 1, "CS": 0,
                      "BB": 4, "SO": 10, "HBP": 0, "SF": 1, "G": 12},
            "metadata": {"mlbam_id": "5"},
        }]
        out = combine_outlook(ros, actual)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["sources"], ["steamer"])
