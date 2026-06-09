import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app
from web.category_registry import canonicalize_cats


class TestCategoryOrdering(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_canonicalize_sorts_to_registry_order(self):
        out = canonicalize_cats(["AVG", "SB", "R", "RBI", "HR"])
        self.assertEqual(out, ["R", "HR", "RBI", "SB", "AVG"])

    def test_shuffled_preset_still_reads_standard(self):
        qs = "cats=AVG&cats=R&cats=HR&cats=RBI&cats=SB&pcats=WHIP&pcats=W&pcats=SV&pcats=K&pcats=ERA"
        r = self.client.get("/rankings?" + qs)
        self.assertIn(b"Standard 5x5", r.data)
        self.assertNotIn(b"Custom", r.data)

    def test_column_order_is_canonical_regardless_of_input(self):
        qs = "cats=AVG&cats=R&cats=HR&cats=RBI&cats=SB&pcats=W&pcats=SV&pcats=K&pcats=ERA&pcats=WHIP"
        r = self.client.get("/rankings?" + qs).data.decode("utf-8")
        self.assertLess(r.index('title="Runs"'), r.index('title="Batting Average"'))


if __name__ == "__main__":
    unittest.main()
