"""Guards the committed DD dynasty feed against the duplicate-id corruption that
took Dynasty + Prospects offline (DDFeedStore fails closed on duplicate ids).

If this fails, the feed producer published an invalid snapshot — do NOT weaken
the loader; fix the feed.
"""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "src"))
FEED = REPO / "data" / "dd" / "dd_dynasty_feed.json"


class TestCommittedDDFeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.feed = json.loads(FEED.read_text(encoding="utf-8"))
        cls.players = cls.feed["players"]

    def test_loader_marks_feed_available(self):
        from web.dd_feed_store import DDFeedStore
        store = DDFeedStore(str(FEED))
        self.assertTrue(store.is_available, "DDFeedStore rejected the committed feed")

    def test_ids_are_unique(self):
        dupes = [i for i, c in Counter(p["id"] for p in self.players).items() if c > 1]
        self.assertEqual(dupes, [], f"duplicate ids in committed feed: {dupes}")

    def test_declared_counts_match_records(self):
        mlb = sum(1 for p in self.players if p["player_type"] == "mlb")
        pro = sum(1 for p in self.players if p["player_type"] == "prospect")
        self.assertEqual(self.feed["player_count"], mlb)
        self.assertEqual(self.feed["prospect_count"], pro)
        self.assertEqual(len(self.players), mlb + pro)

    def test_dynasty_ranks_are_contiguous(self):
        ranks = sorted(p["dynasty_rank"] for p in self.players)
        self.assertEqual(ranks, list(range(1, len(self.players) + 1)))


if __name__ == "__main__":
    unittest.main()
