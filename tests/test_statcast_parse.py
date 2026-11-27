import unittest
from projections.data.statcast import parse_expected_stats, parse_quality


# Mimics Savant CSV: UTF-8 BOM (﻿) + quoted "last_name, first_name" field.
EXPECTED_CSV = (
    '﻿"last_name, first_name",player_id,year,pa,bip,ba,est_ba,'
    'est_ba_minus_ba_diff,slg,est_slg,est_slg_minus_slg_diff,woba,est_woba,'
    'est_woba_minus_woba_diff\n'
    '"Semien, Marcus",543760,2023,753,565,0.276,0.258,-0.018,0.478,0.434,'
    '-0.044,0.354,0.330,-0.024\n'
)

QUALITY_CSV = (
    '﻿"last_name, first_name",player_id,attempts,avg_hit_angle,'
    'anglesweetspotpercent,max_hit_speed,avg_hit_speed,ev50,fbld,gb,'
    'max_distance,avg_distance,avg_hr_distance,ev95plus,ev95percent,barrels,'
    'brl_percent,brl_pa\n'
    '"Semien, Marcus",543760,400,12.5,34.0,110.0,89.5,100,50,25,440,180,400,'
    '120,30.0,40,10.0,7.1\n'
)


class TestStatcastParse(unittest.TestCase):
    def test_parse_expected_keys_off_player_id(self):
        out = parse_expected_stats(EXPECTED_CSV)
        self.assertIn("543760", out)
        self.assertAlmostEqual(out["543760"]["xba"], 0.258)
        self.assertAlmostEqual(out["543760"]["xslg"], 0.434)
        self.assertAlmostEqual(out["543760"]["xwoba"], 0.330)

    def test_parse_quality_observe_only_fields(self):
        out = parse_quality(QUALITY_CSV)
        self.assertAlmostEqual(out["543760"]["barrel_pct"], 10.0)
        self.assertAlmostEqual(out["543760"]["avg_ev"], 89.5)
        self.assertAlmostEqual(out["543760"]["hardhit_pct"], 30.0)
        self.assertAlmostEqual(out["543760"]["launch_angle"], 12.5)
