import unittest
from projections.models.marcel_pitcher import (
    compute_pitcher_league_rates, compute_role_factors, project_pitcher_rates,
    project_sp_usage, project_rp_usage, project_pitcher, build_pitcher_projections,
)
from projections.models.pitcher_params import PitcherMarcelParams


def _p(bf, k, gs, g):
    return {"BF": bf, "K": k, "BB": 0, "H_ALLOWED": 0, "HR": 0, "ER": 0, "HBP": 0,
            "GS": gs, "G": g}


class TestPitcherLeagueRates(unittest.TestCase):
    def test_league_rate_per_bf(self):
        snap = [_p(800, 200, 30, 30), _p(200, 60, 0, 60)]
        rates = compute_pitcher_league_rates([snap], weights=(5.0,), bf_floor=100)
        # K/BF = (200+60)/(800+200) = 260/1000 = 0.26
        self.assertAlmostEqual(rates["K"], 0.26)

    def test_role_factor_rp_over_sp(self):
        # SP-context K/BF = 200/800 = 0.25 ; RP-context K/BF = 60/200 = 0.30
        # f[K] = RP/SP = 0.30/0.25 = 1.2
        snap = [_p(800, 200, 30, 30), _p(200, 60, 0, 60)]
        f = compute_role_factors([snap], bf_floor=100)
        self.assertAlmostEqual(f["K"], 1.2, places=4)

    def test_role_factor_zero_rate_neutralizes(self):
        # SP has HR, RP has zero HR -> naive f[HR]=0 -> f^(negative) blows up. Must be 1.0.
        import math
        snap = [{"BF": 800, "K": 200, "HR": 20, "BB": 0, "H_ALLOWED": 0, "ER": 0, "HBP": 0,
                 "GS": 30, "G": 30},
                {"BF": 200, "K": 60, "HR": 0, "BB": 0, "H_ALLOWED": 0, "ER": 0, "HBP": 0,
                 "GS": 0, "G": 60}]
        f = compute_role_factors([snap], bf_floor=100)
        self.assertEqual(f["HR"], 1.0)
        self.assertTrue(math.isfinite(f["HR"] ** (0.0 - 1.0)))   # f^(neg) finite


class TestPitcherRateProjection(unittest.TestCase):
    def test_no_role_change_no_shift(self):
        # Career SP (h_sp=1) projected as SP (p_sp=1): exponent 0 -> no role-shift.
        prior = [{"BF": 800, "K": 200, "BB": 50, "H_ALLOWED": 160, "HR": 22,
                  "ER": 70, "HBP": 6, "GS": 30, "G": 30}]
        league = {c: prior[0][c] / 800 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        f = {c: 1.5 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}  # would matter if shifted
        rates = project_pitcher_rates(prior, league, f, h_sp=1.0, p_sp=1.0,
                                      params=PitcherMarcelParams())
        self.assertAlmostEqual(rates["K"], 0.25, places=6)   # 200/800, no shift

    def test_rp_to_sp_removes_reliever_boost(self):
        # Career RP (h_sp=0) projected as SP (p_sp=1): K rate divided by f (>1).
        prior = [{"BF": 300, "K": 105, "BB": 20, "H_ALLOWED": 50, "HR": 8,
                  "ER": 25, "HBP": 3, "GS": 0, "G": 60}]
        league = {c: prior[0][c] / 300 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        f = {"K": 1.2, "BB": 1.0, "H_ALLOWED": 1.0, "HR": 1.0, "ER": 1.0, "HBP": 1.0}
        rates = project_pitcher_rates(prior, league, f, h_sp=0.0, p_sp=1.0,
                                      params=PitcherMarcelParams())
        # pooled K/BF = 105/300 = 0.35 ; shift f^(0-1)=1/1.2 -> 0.35/1.2
        self.assertAlmostEqual(rates["K"], 0.35 / 1.2, places=5)

    def test_missed_t1_present_t2_offset_preserved(self):
        # index0=T-1 (None, missed), index1=T-2 present. Must not crash; uses T-2.
        season = {"BF": 300, "K": 105, "BB": 20, "H_ALLOWED": 50, "HR": 8,
                  "ER": 25, "HBP": 3, "GS": 0, "G": 60}
        league = {c: 0.0 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        f = {c: 1.0 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        rates = project_pitcher_rates([None, season], league, f, h_sp=0.0, p_sp=0.0,
                                      params=PitcherMarcelParams(n_reg=0.0))
        # n_reg=0 isolates the rate: 105/300 = 0.35, present season used despite None at T-1.
        self.assertAlmostEqual(rates["K"], 0.35, places=6)


class TestPitcherUsage(unittest.TestCase):
    def test_sp_usage_volume_and_qs(self):
        prior = [{"GS": 30, "G": 30, "BF": 750, "IP": 180.0, "QS": 18} for _ in range(3)]
        u = project_sp_usage(prior, (5.0, 4.0, 3.0))
        self.assertAlmostEqual(u["GS"], 30.0, places=4)
        self.assertAlmostEqual(u["BF"], 750.0, places=2)     # GS * BF/start
        self.assertAlmostEqual(u["IP"], 180.0, places=2)
        self.assertAlmostEqual(u["QS"], 18.0, places=2)

    def test_rp_usage_volume_sv_hld(self):
        prior = [{"G": 60, "GS": 0, "BF": 240, "IP": 60.0, "SV": 30, "HLD": 5} for _ in range(3)]
        u = project_rp_usage(prior, (5.0, 4.0, 3.0))
        self.assertAlmostEqual(u["G"], 60.0, places=4)
        self.assertAlmostEqual(u["BF"], 240.0, places=2)
        self.assertAlmostEqual(u["SV"], 30.0, places=2)
        self.assertAlmostEqual(u["HLD"], 5.0, places=2)


class TestProjectPitcher(unittest.TestCase):
    def test_pure_sp_reconstruction(self):
        prior = [{"mlbam_id": "600", "BF": 750, "IP": 180.0, "ER": 70, "H_ALLOWED": 150,
                  "BB": 45, "HBP": 5, "K": 200, "HR": 22, "GS": 30, "G": 30,
                  "SV": 0, "HLD": 0, "QS": 18, "W": 14} for _ in range(3)]
        league = {c: 0.0 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        f = {c: 1.0 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        out = project_pitcher(prior, league, f, params=PitcherMarcelParams())
        self.assertEqual(out["pool"], "starter")          # p_sp=1 -> starter
        self.assertFalse(out["metadata"]["mixed_role"])
        s = out["stats"]
        self.assertGreater(s["IP"], 150)
        self.assertAlmostEqual(s["ERA"], round(9 * s["ER"] / s["IP"], 3), places=3)
        self.assertAlmostEqual(s["WHIP"], round((s["BB"] + s["H_ALLOWED"]) / s["IP"], 3), places=3)
        self.assertGreaterEqual(s["BF"], 3 * s["IP"] - 1)  # BF >= 3*IP guard (tolerance)
        self.assertGreater(s["QS"], 0)

    def test_mixed_role_flagged_and_blended(self):
        prior = [{"mlbam_id": "601", "BF": 400, "IP": 90.0, "ER": 35, "H_ALLOWED": 80,
                  "BB": 25, "HBP": 3, "K": 100, "HR": 11, "GS": 15, "G": 30,
                  "SV": 2, "HLD": 8, "QS": 8, "W": 6} for _ in range(3)]
        league = {c: 0.0 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        f = {c: 1.0 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        out = project_pitcher(prior, league, f, params=PitcherMarcelParams())
        self.assertTrue(out["metadata"]["mixed_role"])
        self.assertGreater(out["stats"]["IP"], 0)
        self.assertAlmostEqual(out["metadata"]["p_sp"], 0.5, places=2)


class TestBuildPitcherProjections(unittest.TestCase):
    def test_build_from_backbone(self):
        import tempfile
        from pathlib import Path
        from projections.data.pitching_historical import store_pitching_season
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in (2021, 2022, 2023):
                store_pitching_season(yr, [
                    {"mlbam_id": "600", "season": yr, "BF": 750, "IP": 180.0, "ER": 70,
                     "H_ALLOWED": 150, "BB": 45, "HBP": 5, "K": 200, "HR": 22,
                     "W": 14, "L": 8, "SV": 0, "HLD": 0, "GS": 30, "G": 30, "GF": 0, "QS": 18},
                ], data_dir)
            rows = build_pitcher_projections(2024, data_dir, PitcherMarcelParams())
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], "mlbam_600_P")
            self.assertEqual(rows[0]["metadata"]["as_of_season"], 2024)
            self.assertIn("ERA", rows[0]["stats"])

    def test_missed_t1_present_t2_still_projects(self):
        import tempfile
        from pathlib import Path
        from projections.data.pitching_historical import store_pitching_season
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            row = {"mlbam_id": "700", "BF": 750, "IP": 180.0, "ER": 70, "H_ALLOWED": 150,
                   "BB": 45, "HBP": 5, "K": 200, "HR": 22, "W": 14, "L": 8, "SV": 0,
                   "HLD": 0, "GS": 30, "G": 30, "GF": 0, "QS": 18}
            # Present in 2022 (T-2) and 2021 (T-3); MISSING 2023 (T-1).
            store_pitching_season(2022, [dict(row, season=2022)], data_dir)
            store_pitching_season(2021, [dict(row, season=2021)], data_dir)
            rows = build_pitcher_projections(2024, data_dir, PitcherMarcelParams())
            self.assertIn("700", {r["metadata"]["mlbam_id"] for r in rows})  # projected, no crash

    def test_mixed_arm_positions_both(self):
        import tempfile
        from pathlib import Path
        from projections.data.pitching_historical import store_pitching_season
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in (2021, 2022, 2023):
                store_pitching_season(yr, [{"mlbam_id": "701", "season": yr, "BF": 400,
                    "IP": 90.0, "ER": 35, "H_ALLOWED": 80, "BB": 25, "HBP": 3, "K": 100,
                    "HR": 11, "W": 6, "L": 6, "SV": 2, "HLD": 8, "GS": 15, "G": 30,
                    "GF": 5, "QS": 8}], data_dir)
            rows = build_pitcher_projections(2024, data_dir, PitcherMarcelParams())
            r = next(x for x in rows if x["metadata"]["mlbam_id"] == "701")
            self.assertTrue(r["metadata"]["mixed_role"])
            self.assertEqual(set(r["positions"]), {"SP", "RP"})
