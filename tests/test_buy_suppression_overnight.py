"""Isolated Buy suppression checks using real routes/templates/cache/Pillow bodies.

Never import app or read its data. Shared branding/font helpers, Buy row shaping,
and full player-detail context assembly stay synthetic; suppression functions,
the player/scouting templates, and Buy/team PNG renderers are production source.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from html import escape
import threading
from unittest import TestCase
from unittest.mock import patch

from flask import g
from PIL import ImageDraw

import test_buy_consumer_approval as consumer_fixture
from test_public_consumer_safety import definitions


class BuySuppressionOvernight(TestCase):
    def setUp(self):
        # Composition avoids rerunning the inherited fixture's existing tests.
        self.fixture = consumer_fixture.BuyConsumerApproval()
        self.fixture.setUp()
        self.ns = self.fixture.ns
        self.app = self.fixture.app
        self.client = self.fixture.client
        self.raw = self.fixture.raw
        self.review = self.fixture.review
        self.raw.update(pos="SS", level="AA", age=20, headshot_url="/synthetic.png")
        self.raw["terms"] = dict.fromkeys(
            ("model_strength", "momentum", "buy_window", "runway", "conviction"), 0.5)
        self.app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=True)
        self.app.jinja_env.globals["hp_season_context"] = {"season_note": "Synthetic season"}
        # Contrasting synthetic colors keep added/removed text observable in PNG bytes.
        self.ns["_GRAPHIC_PALETTE"].update(
            text=(240, 240, 240), muted=(150, 150, 150), card_2=(25, 25, 25),
            blue=(80, 100, 120), teal=(50, 200, 150), clay=(200, 80, 60))
        self.ns.update(g=g, _PNG_CACHE=OrderedDict(), _PNG_CACHE_LOCK=threading.Lock(),
                       _PNG_CACHE_MAX=32, _PNG_CACHE_PREFIXED_KEYS=frozenset())
        definitions("app.py", {
            "_png_cache_generation", "_png_cache_key", "_serve_cached_png", "_maybe_cache_png",
            "_PNG_CACHE_PARAMS", "_buys_share_card_png", "_draw_buys_spark",
            "_graphic_wrap_text", "player_detail", "backfields_team_share_card",
        }, self.ns)
        self.app.after_request(self.ns["_maybe_cache_png"])
        self.ns["build_share_preview_html"] = definitions(
            "web/share_pages.py", {"build_share_preview_html"}, {"escape": escape}
        )["build_share_preview_html"]
        row = defaultdict(lambda: None, id="independent-player", name="Independent prospect",
                          is_prospect=True, dynasty_value=50.0, positions=("SS",),
                          confidence={}, level="AA", source_ranks={})

        def player_context(player_id, args):
            context = dict(row=row, profile_bars=[], identity=None, spark=None,
                           vc_rank_trend={}, shape_comps=None, dyn_result=None,
                           statcast_groups=[], prospect_preliminary=False)
            context.update(self.ns["_artifact_context_for_row"](row))
            return context

        self.ns["_build_dynasty_player_detail_context"] = player_context

    def approve(self):
        self.fixture.approve()  # Synthetic in-memory receipt only.

    def deny(self):
        self.review["approval_receipt"] = None

    def capture_text(self):
        drawn = []
        original = ImageDraw.ImageDraw.text

        def record(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return original(draw, xy, text, *args, **kwargs)

        return drawn, patch.object(ImageDraw.ImageDraw, "text", record)

    def assert_no_recommendation(self, text):
        lowered = text.lower()
        self.assertNotIn(self.raw["name"].lower(), lowered)
        self.assertNotIn(self.raw["reason"].lower(), lowered)

    def test_actual_scouting_html_hides_buy_badge_and_preserves_independent_report(self):
        denied = self.client.get("/scouting")
        self.assertEqual(denied.status_code, 200)
        html = denied.get_data(as_text=True)
        self.assertNotIn("B#1", html)
        self.assert_no_recommendation(html)
        self.assertIn("Independent scouting report", html)
        self.assertIn("Up 2", html)
        self.approve()
        self.assertIn("B#1", self.client.get("/scouting").get_data(as_text=True))
        self.deny()
        self.assertNotIn("B#1", self.client.get("/scouting").get_data(as_text=True))
        self.assertEqual(self.fixture.signal["buy_rank"], 1)

    def test_actual_player_html_hides_buy_reason_with_context_assembly_stubbed(self):
        path = "/player/independent-player?mode=prospects"
        headers = {"HX-Request": "true"}
        denied = self.client.get(path, headers=headers)
        self.assertEqual(denied.status_code, 200)
        self.assertNotIn("Buy Board", denied.get_data(as_text=True))
        self.assert_no_recommendation(denied.get_data(as_text=True))
        self.assertIn("Independent prospect", denied.get_data(as_text=True))
        self.approve()
        allowed = self.client.get(path, headers=headers).get_data(as_text=True)
        self.assertIn("Buy Board", allowed)
        self.assertIn(self.raw["reason"], allowed)
        self.deny()
        denied_again = self.client.get(path, headers=headers).get_data(as_text=True)
        self.assertNotIn("Buy Board", denied_again)
        self.assert_no_recommendation(denied_again)
        self.assertEqual(self.fixture.signal["buy_reason"], self.raw["reason"])

    def test_actual_buy_png_warm_cache_denies_all_unqualified_receipts(self):
        path = "/buys/share-card.png"
        self.approve()
        drawn, capture = self.capture_text()
        with capture:
            allowed = self.client.get(path)
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertTrue(any(self.raw["name"] in text for text in drawn))
            self.assertTrue(any(self.raw["reason"].upper() in text for text in drawn))
            drawn.clear()
            self.assertEqual(self.client.get(path).data, allowed.data)
            self.assertEqual(drawn, [], "second request must hit the actual memory cache")
            self.assertTrue(self.ns["_PNG_CACHE"])
            dates = (self.fixture.store.generated_at, self.ns["dd_store"].generated_at)
            for receipt in (None, True, {}, {**self.fixture.receipt, "scope": "wrong"}):
                with self.subTest(receipt=receipt):
                    self.review["approval_receipt"] = receipt
                    denied = self.client.get(path)
                    self.assertEqual(denied.status_code, 503)
                    self.assertNotEqual(denied.data, allowed.data)
                    self.assertEqual(denied.headers["Cache-Control"], "no-store")
                    self.assertEqual(drawn, [])
            self.assertEqual(dates, (self.fixture.store.generated_at, self.ns["dd_store"].generated_at))

    def test_actual_team_png_warm_cache_removes_buy_text_after_receipt_withdrawal(self):
        path = "/backfields/team/SEA/share-card.png"
        self.approve()
        drawn, capture = self.capture_text()
        with capture:
            allowed = self.client.get(path)
            self.assertEqual(allowed.status_code, 200)
            self.assertTrue(any(self.raw["name"] in text for text in drawn))
            drawn.clear()
            self.assertEqual(self.client.get(path).data, allowed.data)
            self.assertEqual(drawn, [])
            self.deny()
            denied = self.client.get(path)
            self.assertEqual(denied.status_code, 200)
            self.assertEqual(denied.data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertTrue(denied.data != allowed.data, "denied team PNG must differ from approved cache bytes")
            self.assert_no_recommendation(" ".join(drawn))
            self.assertTrue(any("Independent prospect" in text for text in drawn))
            self.assertEqual(denied.headers["Cache-Control"], "no-store")
            drawn.clear()
            self.assertEqual(self.client.get(path).data, denied.data)
            self.assertEqual(drawn, [], "blocked team rendering may also be safely cached")

    def test_html_and_real_previews_remain_suppressed_with_warm_png_caches(self):
        self.approve()
        for path in ("/buys/share-card.png", "/backfields/team/SEA/share-card.png"):
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(len(self.ns["_PNG_CACHE"]), 2)
        self.assertIn(self.raw["name"], self.client.get("/buys").get_data(as_text=True))
        allowed_preview = self.client.get("/buys/share-card").get_data(as_text=True)
        self.assertIn("<!doctype html>", allowed_preview)
        self.assertIn("Top prospect buys by signal", allowed_preview)
        self.deny()
        for path in ("/", "/backfields/team/SEA", "/buys", "/buys/share-card",
                     "/backfields/team/SEA/share-card"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assert_no_recommendation(response.get_data(as_text=True))
        denied_preview = self.client.get("/buys/share-card").get_data(as_text=True)
        self.assertIn("<!doctype html>", denied_preview)
        self.assertIn("approval and validation", denied_preview)
        self.assertNotIn("Top prospect buys by signal", denied_preview)
        self.assertEqual(len(self.ns["_PNG_CACHE"]), 2, "old approved PNG entries remain warm")

    def test_actual_buy_route_does_not_cache_render_under_revoked_generation(self):
        self.approve()
        renderer = self.ns["_buys_share_card_png"]

        def revoke_after_draw(*args, **kwargs):
            png = renderer(*args, **kwargs)
            self.deny()
            return png

        self.ns["_buys_share_card_png"] = revoke_after_draw
        response = self.client.get("/buys/share-card.png")
        self.assertEqual(response.status_code, 200)  # Approved when route/render began.
        self.assertFalse(self.ns["_PNG_CACHE"], "must not insert approved bytes under a blocked key")
        self.assertEqual(self.client.get("/buys/share-card.png").status_code, 503)
