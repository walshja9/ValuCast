import re
import sys
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app
from werkzeug.datastructures import ImmutableMultiDict


def _rows(html):
    """Parse (rank, name) from each player-row in the rankings table."""
    out = []
    for row in re.findall(r'<tr class="player-row.*?</tr>', html, re.S):
        rk = re.search(r'col-rank">\s*(.*?)\s*</td>', row, re.S)
        nm = re.search(r'<strong>([^<]+)</strong>', row)
        if rk and nm:
            out.append((rk.group(1).strip(), nm.group(1)))
    return out


class TestCorrectnessFollowup(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    # --- Finding 1: overall rank is filter-independent ---
    def test_overall_rank_stable_under_search(self):
        full = _rows(self.client.get("/rankings").data.decode("utf-8"))
        self.assertGreater(len(full), 12)
        rank12, name12 = full[11]
        q = urllib.parse.quote(name12)
        searched = _rows(self.client.get(f"/rankings?search={q}").data.decode("utf-8"))
        match = [r for r in searched if r[1] == name12]
        self.assertTrue(match, f"{name12} not found under search")
        self.assertEqual(match[0][0], rank12, "overall # changed under search")

    def test_overall_rank_stable_under_pool_filter(self):
        full = {n: r for r, n in _rows(self.client.get("/rankings").data.decode("utf-8"))}
        hitters = _rows(self.client.get("/rankings?pool=hitter").data.decode("utf-8"))
        # A hitter's # in the filtered view equals its overall # on the full board.
        checked = 0
        for rank, name in hitters[:10]:
            if name in full:
                self.assertEqual(rank, full[name], f"{name} # changed under pool filter")
                checked += 1
        self.assertGreater(checked, 0)

    # --- Finding 2: prospect tiers from prospect-only universe ---
    def test_prospect_tiers_have_spread(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed unavailable")
        html = self.client.get("/rankings?mode=prospects").data.decode("utf-8")
        tiers = set(re.findall(r'tier-badge[^>]*>T(\d+)', html))
        self.assertGreaterEqual(len(tiers), 4, f"prospect tiers collapsed: {sorted(tiers)}")

    # --- Finding 3: subthreshold search shows projection but no value/rank ---
    def test_subthreshold_search_is_below_floor(self):
        from app import store, _build_context
        full = _build_context(ImmutableMultiDict([]))
        canon = full["canonical_ids"]
        sub = next((p for p in store.get_all() if p.id not in canon), None)
        if sub is None:
            self.skipTest("no sub-threshold player available")
        ctx = _build_context(ImmutableMultiDict([("search", sub.name)]))
        ids = {r.player.id for r in ctx["results"]}
        self.assertIn(sub.id, ids, "sub-threshold player not surfaced by search")
        self.assertNotIn(sub.id, ctx["canonical_ids"])
        # The rendered row must blank Value for a below-floor player.
        html = self.client.get(
            f"/rankings?search={urllib.parse.quote(sub.name)}"
        ).data.decode("utf-8")
        row = re.search(r'<tr class="player-row.*?</tr>', html, re.S).group(0)
        val = re.search(r'col-value[^>]*>(.*?)</td>', row, re.S).group(1).strip()
        self.assertIn(val, ("", "&mdash;", "—"), f"below-floor Value not blank: {val!r}")

    # --- Finding 4: display toggle only in Categories/Roto ---
    def test_display_toggle_scope(self):
        self.assertIn(b'name="display"', self.client.get("/").data)
        self.assertIn(b'name="display"', self.client.get("/?mode=roto").data)
        self.assertNotIn(b'name="display"', self.client.get("/?mode=points").data)
        from app import dd_store
        if dd_store.is_available:
            self.assertNotIn(b'name="display"', self.client.get("/?mode=dd_dynasty").data)

    # --- Finding 5: value-view wording + export headers ---
    def test_value_view_tooltip_not_zscore(self):
        html = self.client.get("/rankings?display=values").data.decode("utf-8")
        self.assertNotIn("z-score", html.lower())

    def test_value_export_headers_have_value_suffix(self):
        v = self.client.get("/export?display=values").data.decode("utf-8")
        self.assertIn("Home Runs value", v)
        p = self.client.get("/export").data.decode("utf-8")
        self.assertNotIn("Home Runs value", p)
        self.assertIn("Home Runs", p)


if __name__ == "__main__":
    unittest.main()
