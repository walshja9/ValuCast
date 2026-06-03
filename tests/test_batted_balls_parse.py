import unittest
from projections.data.batted_balls import parse_batted_balls


CSV = (
    "game_date,launch_speed,launch_angle,events,type,batter,bb_type\n"
    "2023-04-02,98.5,12,single,X,605141,line_drive\n"     # tracked BIP, hit
    "2023-04-02,81.0,-40,field_out,X,605141,ground_ball\n"  # tracked BIP, out
    "2023-04-02,,,strikeout,S,605141,\n"                    # not in play (type!=X) -> dropped
    "2023-04-02,,,field_out,X,592450,\n"                    # in play but MISSING EV -> kept
)


class TestBattedBallParse(unittest.TestCase):
    def test_keeps_only_balls_in_play(self):
        balls = parse_batted_balls(CSV)
        # 3 type=X rows kept; the strikeout (type=S) dropped.
        self.assertEqual(len(balls), 3)

    def test_fields_and_missing_ev(self):
        balls = parse_batted_balls(CSV)
        b0 = balls[0]
        self.assertEqual(b0["batter"], "605141")
        self.assertAlmostEqual(b0["ev"], 98.5)
        self.assertAlmostEqual(b0["la"], 12.0)
        self.assertEqual(b0["events"], "single")
        self.assertEqual(b0["game_year"], "2023")   # season tag for per-year grouping
        # Missing-EV in-play ball: ev/la None, retained (imputed later, not dropped).
        missing = [b for b in balls if b["ev"] is None]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["events"], "field_out")
