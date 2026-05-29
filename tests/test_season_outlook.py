import unittest

from league_values.models import PlayerProjection
from web.dynasty_models import DynastyRankingRow
from web.season_outlook import find_season_outlook


def _proj(pid, name, pool, positions=(), base_id=None, stats=None, actual=None, ros=None):
    meta = {}
    if base_id:
        meta["base_id"] = base_id
    if actual is not None:
        meta["stats_actual"] = actual
    if ros is not None:
        meta["stats_ros"] = ros
    return PlayerProjection(
        id=pid, name=name, pool=pool, positions=positions, stats=stats or {}, metadata=meta
    )


def _feed_row(name, positions, mlbam_id=None, player_type="mlb"):
    return DynastyRankingRow.from_feed({
        "id": "dd_" + name.lower().replace(" ", "_"),
        "player_type": player_type,
        "name": name,
        "positions": positions,
        "mlbam_id": mlbam_id,
        "dynasty_rank": 1,
        "dynasty_value": 50.0,
    })


class TestFindSeasonOutlook(unittest.TestCase):
    def test_single_hitter_match(self):
        row = _feed_row("Bob Bat", ["1B"])
        projs = [_proj("h1", "Bob Bat", "hitter", ("1B",), base_id="b_a",
                       stats={"HR": 30}, actual={"PA": 600}, ros={"HR": 10})]
        outlook = find_season_outlook(row, projs)
        self.assertIsNotNone(outlook)
        stats, actual, ros = outlook
        self.assertEqual(stats, {"HR": 30})
        self.assertEqual(actual, {"PA": 600})
        self.assertEqual(ros, {"HR": 10})

    def test_pitcher_feed_ignores_same_name_hitter(self):
        # The Will Smith case: a reliever feed row must NOT match the catcher.
        row = _feed_row("Will Smith", ["RP"])
        projs = [
            _proj("h", "Will Smith", "hitter", ("C",), base_id="b_cat", stats={"HR": 20}),
            _proj("p", "Will Smith", "starter", ("SP",), base_id="b_sp", stats={"K": 180}),
        ]
        stats, _, _ = find_season_outlook(row, projs)
        self.assertEqual(stats, {"K": 180})  # the pitcher, not the catcher

    def test_hitter_feed_ignores_same_name_pitcher(self):
        row = _feed_row("Will Smith", ["C"])
        projs = [
            _proj("h", "Will Smith", "hitter", ("C",), base_id="b_cat", stats={"HR": 20}),
            _proj("p", "Will Smith", "starter", ("SP",), base_id="b_sp", stats={"K": 180}),
        ]
        stats, _, _ = find_season_outlook(row, projs)
        self.assertEqual(stats, {"HR": 20})  # the catcher, not the pitcher

    def test_two_way_same_base_merges(self):
        # Ohtani: feed row has both hitter + pitcher positions; both projections
        # share a base_id, so collect/merge into one outlook.
        row = _feed_row("Shohei Ohtani", ["DH", "SP"])
        projs = [
            _proj("19755", "Shohei Ohtani", "hitter", ("DH",), base_id="mlbam_660271",
                  stats={"PA": 600, "HR": 50, "G": 150}),
            _proj("19755_P", "Shohei Ohtani", "starter", ("SP",), base_id="mlbam_660271",
                  stats={"IP": 150, "K": 200, "G": 30}),
        ]
        stats, _, _ = find_season_outlook(row, projs)
        # merged: hitting AND pitching keys present
        self.assertEqual(stats["HR"], 50)
        self.assertEqual(stats["IP"], 150)
        self.assertEqual(stats["K"], 200)
        # shared key resolves to the hitter side (hitter-first precedence)
        self.assertEqual(stats["G"], 150)

    def test_ambiguous_different_people_returns_none(self):
        # Two distinct hitters sharing a name (different base_id) -> no outlook,
        # because showing one's stats on the other's card is wrong.
        row = _feed_row("Jose Ramos", ["OF"])
        projs = [
            _proj("a", "Jose Ramos", "hitter", ("OF",), base_id="b_1", stats={"HR": 5}),
            _proj("b", "Jose Ramos", "hitter", ("OF",), base_id="b_2", stats={"HR": 25}),
        ]
        self.assertIsNone(find_season_outlook(row, projs))

    def test_no_match_returns_none(self):
        row = _feed_row("Nobody Here", ["1B"])
        projs = [_proj("h1", "Bob Bat", "hitter", ("1B",), stats={"HR": 30})]
        self.assertIsNone(find_season_outlook(row, projs))

    def test_mlbam_id_match_wins_over_name(self):
        # When the feed carries an mlbam_id, join by id even if the name differs.
        row = _feed_row("Stale Name", ["1B"], mlbam_id="660271")
        projs = [
            _proj("x", "Correct Player", "hitter", ("1B",),
                  stats={"HR": 42}),
        ]
        # attach mlbam_id to the projection metadata
        projs[0].metadata["mlbam_id"] = "660271"
        stats, _, _ = find_season_outlook(row, projs)
        self.assertEqual(stats, {"HR": 42})

    def test_normalizes_case_and_whitespace(self):
        row = _feed_row("  WILL  smith ", ["C"])
        projs = [_proj("h", "Will Smith", "hitter", ("C",), stats={"HR": 20})]
        stats, _, _ = find_season_outlook(row, projs)
        self.assertEqual(stats, {"HR": 20})


if __name__ == "__main__":
    unittest.main()
