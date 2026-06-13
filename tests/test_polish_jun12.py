"""Launch-polish pass (2026-06-12): statcast raw values, prospect statcast,
two-way splits, dynasty category picker, glass ambient layer, value map, and
shareable card links. Integration tests run against the real committed stores
(same precedent as test_player_links)."""
import json
import tempfile
import unittest
from pathlib import Path

from werkzeug.datastructures import MultiDict

import app as app_module
from league_values.models import PlayerPool, PlayerProjection
from scripts.fetch_statcast_percentiles import _combine, _parse_raw
from web.season_outlook import build_outlook_match_index, split_outlook
from web.statcast_store import StatcastStore, format_raw


def _store_from(payload):
    fixture = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fixture)
    fixture.close()
    return StatcastStore(fixture.name), Path(fixture.name)


class TestFormatRaw(unittest.TestCase):
    def test_format_table(self):
        self.assertEqual(format_raw("xba", 0.412), ".412")
        self.assertEqual(format_raw("xwoba", 1.012), "1.012")
        self.assertEqual(format_raw("k_percent", 22.06), "22.1%")
        self.assertEqual(format_raw("exit_velocity", 93.5), "93.5 mph")
        self.assertEqual(format_raw("fb_spin", 2467.2), "2467 rpm")
        self.assertEqual(format_raw("sprint_speed", 27.5), "27.5 ft/s")
        self.assertEqual(format_raw("oaa", 5), "+5")
        self.assertEqual(format_raw("xera", 2.6), "2.60")
        self.assertIsNone(format_raw("xba", None))
        self.assertIsNone(format_raw("xba", "n/a"))


class TestStatcastArtifactShapes(unittest.TestCase):
    def test_v1_int_percentiles_render_without_raw(self):
        store, path = _store_from({
            "as_of": "2026-06-12",
            "batters": {"1": {"xwoba": 98, "k_percent": 41}},
            "pitchers": {},
        })
        try:
            groups = store.display_groups("1")
            metrics = [m for g in groups for m in g["metrics"]]
            self.assertTrue(metrics)
            for metric in metrics:
                self.assertIsNone(metric["raw"])
                self.assertIsNone(metric["display"])
                self.assertIsInstance(metric["pct"], int)
        finally:
            path.unlink()

    def test_v2_dict_percentiles_carry_raw_and_display(self):
        store, path = _store_from({
            "as_of": "2026-06-12",
            "batters": {"1": {
                "xwoba": {"pct": 98, "raw": 0.412},
                "k_percent": {"pct": 41},          # raw missing -> graceful
            }},
            "pitchers": {},
        })
        try:
            groups = store.display_groups("1")
            metrics = {m["label"]: m for g in groups for m in g["metrics"]}
            xwoba = next(m for label, m in metrics.items() if "xwOBA" in label)
            self.assertEqual(xwoba["pct"], 98)
            self.assertEqual(xwoba["raw"], 0.412)
            self.assertEqual(xwoba["display"], ".412")
            kpct = next(m for label, m in metrics.items() if "K" in label and "%" in label)
            self.assertEqual(kpct["pct"], 41)
            self.assertIsNone(kpct["raw"])
        finally:
            path.unlink()


class TestFetchScriptRawParsing(unittest.TestCase):
    CSV = (
        '"last_name, first_name","player_id","year","xwoba","fastball_avg_speed"\n'
        '"Ohtani, Shohei",660271,2026,".418","97.6"\n'
        '"Empty, Cells",123,2026,"",""\n'
    )

    def test_parse_raw_maps_aliases_and_drops_blanks(self):
        raws = _parse_raw(self.CSV)
        self.assertEqual(raws["660271"]["xwoba"], 0.418)
        # custom-leaderboard alias mapped back to the artifact key
        self.assertEqual(raws["660271"]["fb_velocity"], 97.6)
        self.assertNotIn("123", raws)

    def test_combine_never_invents_raws(self):
        combined = _combine(
            {"660271": {"xwoba": 98, "chase_percent": 60}},
            {"660271": {"xwoba": 0.418}},
        )
        self.assertEqual(combined["660271"]["xwoba"], {"pct": 98, "raw": 0.418})
        self.assertEqual(combined["660271"]["chase_percent"], {"pct": 60})


def _proj(pid, name, pool, stats, positions=("OF",), metadata=None):
    return PlayerProjection(
        id=pid, name=name, pool=pool, stats=stats,
        positions=positions, metadata=metadata or {},
    )


class TestSplitOutlook(unittest.TestCase):
    def test_two_way_split(self):
        hitter = _proj(
            "x-h", "Two Way", PlayerPool.HITTER, {"PA": 600, "HR": 30},
            positions=("DH",),
            metadata={"base_id": "x", "stats_actual": {"PA": 300},
                      "stats_ros": {"PA": 280}},
        )
        pitcher = _proj(
            "x-p", "Two Way", PlayerPool.PITCHER, {"IP": 120, "K": 140},
            positions=("SP",),
            metadata={"base_id": "x", "stats_actual": {"IP": 60},
                      "stats_ros": {"IP": 55}},
        )
        outlook, actual, ros = split_outlook([hitter, pitcher])
        self.assertEqual(outlook["hitting"]["PA"], 600)
        self.assertEqual(outlook["pitching"]["IP"], 120)
        self.assertEqual(actual["hitting"]["PA"], 300)
        self.assertEqual(actual["pitching"]["IP"], 60)
        self.assertEqual(ros["pitching"]["IP"], 55)

    def test_single_pool_has_no_pitching_side(self):
        hitter = _proj("h", "Hitter Only", PlayerPool.HITTER, {"PA": 600})
        outlook, _, _ = split_outlook([hitter])
        self.assertEqual(outlook["hitting"]["PA"], 600)
        self.assertIsNone(outlook["pitching"])


class _RealAppCase(unittest.TestCase):
    """Shared client over the real committed stores."""
    HX = {"HX-Request": "true"}

    @classmethod
    def setUpClass(cls):
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()
        cls.dd_rows = app_module.dd_store.get_all()


class TestTwoWayCards(_RealAppCase):
    def _ohtani(self):
        row = next((r for r in self.dd_rows if r.name == "Shohei Ohtani"), None)
        if row is None:
            self.skipTest("Ohtani not in feed")
        return row

    def test_dynasty_card_splits_hitting_and_pitching(self):
        row = self._ohtani()
        html = self.client.get(
            f"/player/{row.id}?mode=dd_dynasty", headers=self.HX,
        ).data.decode("utf-8")
        self.assertIn("two-way-stats", html)
        self.assertIn(">Hitting</h5>", html)
        self.assertIn(">Pitching</h5>", html)

    def test_redraft_card_splits_for_two_way(self):
        match_index = build_outlook_match_index(app_module.store.get_all())
        matches = match_index.find(self._ohtani())
        self.assertGreaterEqual(len(matches), 2, "expected both Ohtani pools")
        html = self.client.get(
            f"/player/{matches[0].id}", headers=self.HX,
        ).data.decode("utf-8")
        self.assertIn("two-way-stats", html)

    def test_single_pool_card_is_unchanged(self):
        html = self.client.get("/player/15640", headers=self.HX).data.decode("utf-8")
        self.assertNotIn("two-way-stats", html)


class TestProspectStatcast(_RealAppCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        match_index = build_outlook_match_index(app_module.store.get_all())
        cls.with_sc = cls.without_sc = None
        for row in cls.dd_rows:
            if not row.is_prospect:
                continue
            matches = match_index.find(row)
            mlbam = matches[0].metadata.get("mlbam_id") if matches else None
            groups = app_module.statcast.display_groups(mlbam) if mlbam else []
            if groups and cls.with_sc is None:
                cls.with_sc = row
            if not groups and cls.without_sc is None:
                cls.without_sc = row
            if cls.with_sc is not None and cls.without_sc is not None:
                break

    def test_called_up_prospect_card_shows_mlb_statcast(self):
        self.assertIsNotNone(self.with_sc, "no prospect with Savant data found")
        html = self.client.get(
            f"/player/{self.with_sc.id}?mode=prospects", headers=self.HX,
        ).data.decode("utf-8")
        self.assertIn("MLB Statcast", html)
        self.assertIn("vs MLB league percentiles", html)
        self.assertIn("pct-row", html)

    def test_prospect_without_savant_data_has_no_block(self):
        self.assertIsNotNone(self.without_sc)
        html = self.client.get(
            f"/player/{self.without_sc.id}?mode=prospects", headers=self.HX,
        ).data.decode("utf-8")
        self.assertNotIn("MLB Statcast", html)


class TestDynastyCategories(_RealAppCase):
    CUSTOM = "cats=R,HR,RBI,SB,OBP&pcats=W,SV,K,ERA,WHIP"

    def test_default_board_has_no_now_column(self):
        html = self.client.get("/?mode=dd_dynasty").data.decode("utf-8")
        self.assertNotIn("col-now-dollar", html)
        self.assertIn("prospect slots · 7x7 · Updated", html)
        self.assertIn("DD 7x7", html)

    def test_default_dynasty_categories_are_not_redraft_5x5(self):
        ctx = app_module._build_dynasty_context(MultiDict())
        self.assertEqual(
            set(ctx["cats"]),
            {"R", "HR", "RBI", "SB", "AVG", "OPS", "SO"},
        )
        self.assertEqual(
            set(ctx["pcats"]),
            {"ERA", "WHIP", "K", "SV", "HLD", "K_BB", "QS"},
        )
        self.assertFalse(ctx["custom_cats_active"])
        self.assertIn("7x7", ctx["config_summary"])
        self.assertNotIn("DD 7x7", ctx["config_summary"])

    def test_dd_7x7_remains_selectable_but_is_not_default(self):
        ctx = app_module._build_dynasty_context(MultiDict([
            ("cats", "R,HR,RBI,SB,AVG,OPS,SO"),
            ("pcats", "L,K,QS,SV_HLD,ERA,WHIP,K_BB"),
        ]))
        self.assertTrue(ctx["custom_cats_active"])
        self.assertIn("DD 7x7", ctx["config_summary"])

    def test_standard_5x5_is_recognized_regardless_of_canonical_order(self):
        ctx = app_module._build_dynasty_context(MultiDict([
            ("cats", "R,HR,RBI,SB,AVG"),
            ("pcats", "W,SV,K,ERA,WHIP"),
        ]))
        self.assertTrue(ctx["custom_cats_active"])
        self.assertIn("5x5", ctx["config_summary"])
        self.assertNotIn("Custom 5x5", ctx["config_summary"])

    def test_custom_cats_add_now_column_and_summary(self):
        html = self.client.get(
            f"/?mode=dd_dynasty&{self.CUSTOM}").data.decode("utf-8")
        self.assertIn("col-now-dollar", html)
        self.assertIn("Now $", html)
        self.assertIn("Custom 5x5 (OBP, W)", html)
        # prospects can't have a this-season value -> em-dash cell
        self.assertIn('<td class="col-now-dollar">—</td>', html)

    def test_six_by_six_preset_label(self):
        html = self.client.get(
            "/?mode=dd_dynasty&cats=R,HR,RBI,SB,AVG,OBP&pcats=W,QS,SV,K,ERA,WHIP"
        ).data.decode("utf-8")
        self.assertIn("6x6 (OBP, QS)", html)

    def test_now_values_cached_and_mapped(self):
        args = (("R", "HR", "RBI", "SB", "OBP"), ("W", "SV", "K", "ERA", "WHIP"))
        first = app_module._custom_dynasty_values(args[0], args[1], 12, 200)
        second = app_module._custom_dynasty_values(args[0], args[1], 12, 200)
        self.assertIs(first, second)
        self.assertTrue(first, "no feed rows mapped to engine results")
        ohtani = next((r for r in self.dd_rows if r.name == "Shohei Ohtani"), None)
        if ohtani is not None:
            self.assertIn(ohtani.id, first)

    def test_rank_by_now_reorders_board(self):
        args = MultiDict([
            ("cats", "R,HR,RBI,SB,OBP"), ("pcats", "W,SV,K,ERA,WHIP"),
            ("rank_by", "now"),
        ])
        ctx = app_module._build_dynasty_context(args)
        self.assertEqual(ctx["rank_by"], "now")
        rows = ctx["dd_rows"]
        now = ctx["now_dollars"]
        self.assertIn(rows[0].id, now)
        valued = [now[r.id] for r in rows if r.id in now]
        self.assertEqual(valued, sorted(valued, reverse=True))

    def test_rank_by_ignored_without_custom_cats(self):
        ctx = app_module._build_dynasty_context(MultiDict([("rank_by", "now")]))
        self.assertEqual(ctx["rank_by"], "dynasty")
        self.assertEqual(ctx["now_dollars"], {})

    def test_league_import_panel_renders_categories(self):
        r = self.client.get("/league-import?teams=12")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Scoring categories", r.data)

    def test_rankings_replace_url_round_trips_cats(self):
        r = self.client.get(
            f"/rankings?mode=dd_dynasty&{self.CUSTOM}&rank_by=now",
            headers=self.HX,
        )
        push = r.headers.get("HX-Replace-Url", "")
        self.assertIn("cats=", push)
        self.assertIn("rank_by=now", push)

    def test_dynasty_detail_uses_active_category_state(self):
        hitter = next(
            row for row in self.dd_rows
            if not row.is_prospect and not {"P", "SP", "RP"}.intersection(row.positions)
        )
        default_html = self.client.get(
            f"/player/{hitter.id}?mode=dd_dynasty", headers=self.HX,
        ).data.decode("utf-8")
        self.assertIn("7x7 categories", default_html)
        self.assertNotIn("DD 7x7 categories", default_html)

        custom_html = self.client.get(
            f"/player/{hitter.id}?mode=dd_dynasty&cats=OPS&pcats=QS",
            headers=self.HX,
        ).data.decode("utf-8")
        self.assertIn("Custom 1x1 (OPS, QS) categories", custom_html)
        self.assertIn(">OPS<", custom_html)
        self.assertNotIn(">Runs<", custom_html)

    def test_h2h_category_fit_matches_default_separate_saves_and_holds(self):
        html = self.client.get("/?mode=dd_dynasty").data.decode("utf-8")
        self.assertIn(
            "h2h: {R:1, HR:1, RBI:1, SB:1, AVG:1, OPS:1, SO:1, "
            "ERA:1, WHIP:1, K:1, QS:1, SV:1, HLD:1, 'K/BB':1}",
            html,
        )


class TestGlassAndMap(_RealAppCase):
    def test_ambient_layer_and_glass_tokens_in_stylesheet(self):
        css = (Path(app_module.__file__).parent / "static" / "style.css").read_text(
            encoding="utf-8")
        self.assertIn("body::before", css)
        self.assertIn("body::after", css)
        self.assertIn("radial-gradient", css)
        self.assertIn("blur(28px) saturate(185%)", css)
        self.assertIn("ambient-drift", css)

    def test_map_route_embeds_feed_players(self):
        r = self.client.get("/map")
        self.assertEqual(r.status_code, 200)
        html = r.data.decode("utf-8")
        self.assertIn('id="value-map"', html)
        start = html.index('id="map-data"')
        payload = html[html.index(">", start) + 1:html.index("</script>", start)]
        players = json.loads(payload)
        expected = [row for row in self.dd_rows
                    if row.age is not None and row.dynasty_value is not None]
        self.assertEqual(len(players), len(expected))
        groups = {p["group"] for p in players}
        self.assertIn("prospect", groups)
        self.assertIn("hitter", groups)

    def test_map_payload_drops_rows_missing_age_or_value(self):
        class _Row:
            def __init__(self, **kw):
                self.__dict__.update(kw)
        rows = [
            _Row(id="a", name="A", age=None, dynasty_value=50.0, positions=["OF"],
                 is_prospect=False, player_type="mlb", prospect_rank=None),
            _Row(id="b", name="B", age=24, dynasty_value=None, positions=["SP"],
                 is_prospect=False, player_type="mlb", prospect_rank=None),
            _Row(id="c", name="C", age=24, dynasty_value=70.0, positions=["SP"],
                 is_prospect=False, player_type="mlb", prospect_rank=None),
        ]
        payload = app_module._value_map_players(rows)
        self.assertEqual([p["id"] for p in payload], ["c"])
        self.assertEqual(payload[0]["group"], "sp")

    def test_map_links_on_dynasty_and_prospect_toolbars(self):
        for mode in ("dd_dynasty", "prospects"):
            html = self.client.get(f"/?mode={mode}").data.decode("utf-8")
            self.assertIn('class="map-link"', html)


class TestShareableCardLinks(_RealAppCase):
    def test_direct_hit_redirects_to_board(self):
        row = next(r for r in self.dd_rows if not r.is_prospect)
        r = self.client.get(f"/player/{row.id}?mode=dd_dynasty")
        self.assertEqual(r.status_code, 302)
        self.assertIn("mode=dd_dynasty", r.headers["Location"])
        self.assertIn("search=", r.headers["Location"])

    def test_redraft_direct_hit_redirects(self):
        r = self.client.get("/player/15640")
        self.assertEqual(r.status_code, 302)
        self.assertIn("mode=categories", r.headers["Location"])

    def test_htmx_hit_still_returns_partial(self):
        row = next(r for r in self.dd_rows if not r.is_prospect)
        r = self.client.get(f"/player/{row.id}?mode=dd_dynasty", headers=self.HX)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"player-detail", r.data)

    def test_unknown_id_direct_hit_is_404_not_redirect(self):
        r = self.client.get("/player/dd_nope?mode=dd_dynasty")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
