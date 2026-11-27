import tempfile
import unittest
from pathlib import Path

from projections.data import batted_balls as bb


class TestChunkedPull(unittest.TestCase):
    def test_date_chunks_5day_windows(self):
        chunks = bb.date_chunks("2023-04-01", "2023-04-12", days=5)
        # [01-05], [06-10], [11-12]
        self.assertEqual(chunks[0], ("2023-04-01", "2023-04-05"))
        self.assertEqual(chunks[1], ("2023-04-06", "2023-04-10"))
        self.assertEqual(chunks[-1], ("2023-04-11", "2023-04-12"))

    def test_pull_window_is_resumable(self):
        calls = []

        def fake_fetch(start, end):
            calls.append((start, end))
            return [{"ev": 95.0, "la": 10.0, "events": "single", "batter": "1"}]

        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "bb_cache"
            n1 = bb.pull_window("2023-04-01", "2023-04-10", cache, days=5, fetch=fake_fetch)
            self.assertEqual(n1, 2)            # 2 chunks fetched
            self.assertEqual(len(calls), 2)
            # Re-run: chunks already cached -> no new fetches, same count.
            n2 = bb.pull_window("2023-04-01", "2023-04-10", cache, days=5, fetch=fake_fetch)
            self.assertEqual(n2, 2)
            self.assertEqual(len(calls), 2)    # unchanged: resumable, idempotent
