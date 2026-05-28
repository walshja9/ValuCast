import json
import os
import tempfile
import unittest

from web.dd_feed_store import DDFeedStore


VALID_FEED = {
    "schema_version": "1.0",
    "generated_at": "2026-05-27T08:00:00",
    "generated_by": "diamond_dynasties",
    "source": "diamond_dynasties",
    "league_preset": "DD_7x7",
    "scale": "0_150_dynasty_value",
    "value_semantics": "higher_is_better",
    "player_count": 3,
    "prospect_count": 1,
    "players": [
        {"id": "dd_mlb_100", "player_type": "mlb", "name": "Star Hitter",
         "mlbam_id": None, "positions": ["OF"], "mlb_team": "NYY",
         "age": 28, "dynasty_rank": 1, "dynasty_value": 95.0, "status": "mlb"},
        {"id": "dd_mlb_200", "player_type": "mlb", "name": "Good Pitcher",
         "mlbam_id": None, "positions": ["SP"], "mlb_team": "LAD",
         "age": 26, "dynasty_rank": 2, "dynasty_value": 80.0, "status": "mlb"},
        {"id": "dd_prospect_300", "player_type": "prospect", "name": "Top Prospect",
         "mlbam_id": None, "positions": ["SS"], "mlb_team": "TEX",
         "age": 19, "dynasty_rank": 3, "dynasty_value": 72.0, "status": "minors",
         "level": "AA", "eta": 2028, "prospect_rank": 1,
         "source_ranks": {"pipeline": 1, "cfr": 2, "hkb": 3},
         "breakout_label": "rising", "breakout_rank_change": 5,
         "stat_line": {"pa": 200, "hr": 10, "ops": 0.900}},
    ],
}


def _write_feed(d, feed):
    path = os.path.join(d, "dd_dynasty_feed.json")
    with open(path, "w") as f:
        json.dump(feed, f)
    return path


class TestDDFeedStoreLoad(unittest.TestCase):
    def test_loads_valid_feed(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            self.assertTrue(store.is_available)
            self.assertEqual(len(store.get_all()), 3)

    def test_missing_file_not_available(self):
        store = DDFeedStore("/nonexistent/path/feed.json")
        self.assertFalse(store.is_available)

    def test_get_by_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            row = store.get_by_id("dd_prospect_300")
            self.assertIsNotNone(row)
            self.assertEqual(row.name, "Top Prospect")

    def test_get_by_id_missing(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            self.assertIsNone(store.get_by_id("nonexistent"))

    def test_generated_at(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            self.assertEqual(store.generated_at, "2026-05-27T08:00:00")

    def test_sorted_by_dynasty_rank(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            rows = store.get_all()
            ranks = [r.dynasty_rank for r in rows]
            self.assertEqual(ranks, sorted(ranks))


class TestDDFeedStoreValidation(unittest.TestCase):
    def test_rejects_wrong_schema_version(self):
        with tempfile.TemporaryDirectory() as d:
            bad = {**VALID_FEED, "schema_version": "2.0"}
            path = _write_feed(d, bad)
            store = DDFeedStore(path)
            self.assertFalse(store.is_available)

    def test_rejects_empty_players(self):
        with tempfile.TemporaryDirectory() as d:
            bad = {**VALID_FEED, "players": []}
            path = _write_feed(d, bad)
            store = DDFeedStore(path)
            self.assertFalse(store.is_available)

    def test_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as d:
            dup_players = [VALID_FEED["players"][0], VALID_FEED["players"][0]]
            bad = {**VALID_FEED, "players": dup_players}
            path = _write_feed(d, bad)
            store = DDFeedStore(path)
            self.assertFalse(store.is_available)

    def test_skips_records_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as d:
            players = list(VALID_FEED["players"]) + [
                {"id": "bad1", "player_type": "mlb"},
            ]
            feed = {**VALID_FEED, "players": players, "player_count": 4}
            path = _write_feed(d, feed)
            store = DDFeedStore(path)
            self.assertTrue(store.is_available)
            self.assertEqual(len(store.get_all()), 3)

    def test_rejects_high_invalid_rate(self):
        with tempfile.TemporaryDirectory() as d:
            bad_players = [{"id": f"bad{i}"} for i in range(20)] + [VALID_FEED["players"][0]]
            feed = {**VALID_FEED, "players": bad_players, "player_count": 21}
            path = _write_feed(d, feed)
            store = DDFeedStore(path)
            self.assertFalse(store.is_available)


class TestDDFeedStoreFilter(unittest.TestCase):
    def test_filter_by_player_type(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            prospects = store.filter(player_type="prospect")
            self.assertEqual(len(prospects), 1)
            self.assertEqual(prospects[0].name, "Top Prospect")

    def test_filter_by_position(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            sps = store.filter(position="SP")
            self.assertEqual(len(sps), 1)
            self.assertEqual(sps[0].name, "Good Pitcher")

    def test_filter_by_search(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            results = store.filter(search="star")
            self.assertEqual(len(results), 1)

    def test_filter_mlb_pool(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            mlb = store.filter(pool="mlb")
            self.assertEqual(len(mlb), 2)

    def test_filter_prospect_pool(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            pros = store.filter(pool="prospect")
            self.assertEqual(len(pros), 1)

    def test_filter_pitcher_pool(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_feed(d, VALID_FEED)
            store = DDFeedStore(path)
            pitchers = store.filter(pool="pitcher")
            self.assertEqual(len(pitchers), 1)
            self.assertEqual(pitchers[0].name, "Good Pitcher")
