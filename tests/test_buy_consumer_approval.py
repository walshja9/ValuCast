"""Synthetic route/context/render checks; never import the data-loading app."""
from __future__ import annotations

from datetime import date, datetime
import io
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import quote, urlencode

from flask import Flask, abort, make_response, render_template, render_template_string, request
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from PIL import Image, ImageDraw, ImageFont

from test_public_consumer_safety import ROOT, definitions


class BuyConsumerApproval(unittest.TestCase):
    def setUp(self):
        self.receipt = {
            "schema_version": "1.0.0", "origin": "explicit_manual_input",
            "scope": "valucast_owned_buys_promotion_v1",
            "approved_at": "2026-01-01T00:00:00Z",
        }
        self.review = {"review_status": "candidate_ready", "approval_receipt": None,
                       "source_policy": {"manual_approval_recorded": True,
                                         "prior_approval_reused": True}}
        self.raw = {"id": "synthetic-buy", "name": "Synthetic Buy Sentinel",
                    "team": "SEA", "rank": 1, "score": 91.2,
                    "reason": "Synthetic recommendation reason", "terms": {}, "value_history": []}
        self.signal = {"identity_key": "1_hitter", "buy_rank": 1,
                       "buy_reason": self.raw["reason"], "movement_label": "Up 2"}
        self.loaded = []

        def load(path):
            self.loaded.append(path.name)
            return {
                "valucast_prospect_buys_review.json": self.review,
                "valucast_prospect_buys.json": {"board": [self.raw]},
                "valucast_recent_signal_report.json": {"signals": [self.signal]},
                "valucast_scouting_reports.json": {"reports": [{
                    "name": "Independent scouting report", "team": "SEA",
                    "recent_signal": self.signal}]},
            }.get(path.name, {})

        app = Flask(__name__, template_folder=str(ROOT / "templates"))
        app.config["TESTING"] = True
        # Exercise the real home strip and full team template, without unrelated
        # board/base-template dependencies or loading any project artifact.
        app.jinja_loader = ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}",
                        "index.html": '{% include "partials/_today_strip.html" %}'}),
            FileSystemLoader(ROOT / "templates"),
        ])
        app.jinja_env.globals["url_for"] = lambda *args, **kwargs: "/synthetic"
        qualifier = definitions("prospects/buy_approval.py", {
            "APPROVAL_SCHEMA_VERSION", "APPROVAL_SCOPE", "qualified_approval_receipt",
        }, {"datetime": datetime})["qualified_approval_receipt"]
        self.store = SimpleNamespace(
            is_available=True, ready_for_live_consumers=True,
            generated_at="2026-01-01T00:00:00Z", validation={},
            get_all=lambda: [self.raw],
        )
        snapshot = SimpleNamespace(is_available=True, surface_readiness={"buys": True},
                                   generated_at="2026-01-01T00:00:00Z")
        player = SimpleNamespace(name="Independent prospect", team="SEA")
        displayed_row = {"name": player.name, "position": "SS", "level": "AA",
                         "eta": "2027", "value": "50", "org_rank": 1,
                         "move": {}, "url": "/synthetic"}
        ns = {
            "app": app, "__file__": str(ROOT / "app.py"), "Path": Path,
            "os": SimpleNamespace(environ={}), "date": date, "io": io, "math": math,
            "request": request, "render_template": render_template,
            "make_response": make_response, "abort": abort,
            "quote": quote, "urlencode": urlencode,
            "AHEAD_OF_THE_CURVE_HOLD": False, "SCOREBOARD_HOLD": True,
            "RECEIPTS_HOLD": True, "VALUCAST_BUYS_PATH": Path("valucast_prospect_buys.json"),
            "VALUCAST_BUYS_REVIEW_PATH": Path("valucast_prospect_buys_review.json"),
            "_load_artifact": load, "qualified_approval_receipt": qualifier,
            "dd_store": snapshot, "valucast_buy_store": self.store,
            "dynasty_data_source": "valucast_public_snapshot",
            "_UNAVAILABLE_DYNASTY_STORE": SimpleNamespace(is_available=False),
            "store": SimpleNamespace(as_of="2026-01-01"),
            "pitch_discipline_store": SimpleNamespace(as_of="2026-01-01"),
            "_load_movers_payload": lambda: {}, "_load_scorecard_payload": lambda: {},
            "_load_gaps_ledger": lambda: {}, "_movers_epoch_drought": lambda *args: (False, None),
            "DEFAULT_MOVER_WINDOW": 14, "_build_context": lambda _: {},
            "_build_dynasty_context": lambda _: {}, "_apply_prospect_board_context": lambda *args: None,
            "_team_board_prospect_rows": lambda: [player],
            "_team_board_org_for": lambda _: "SEA", "_team_board_org_name": lambda _: "Seattle",
            "_canonical_team_board_org": lambda value: value,
            "_team_board_movements": lambda: {}, "_debuted_prospect_ids": lambda: set(),
            "_call_up_pulse_keys": lambda: set(), "_team_board_row": lambda *args: displayed_row,
            "_team_board_callups": lambda *args: [], "_team_board_reports": lambda *args: [],
            "_team_board_system_summary": lambda *args: {},
            "_build_backfields_page_context": lambda: {"aotc_hold": False, "stats": {}},
            "_team_board_share_limit": lambda: 20, "_row_mlb_debut": lambda _: None,
            "_graphic_font": lambda *args, **kwargs: ImageFont.load_default(),
            "_graphic_fill_background": lambda *args: None,
            "_graphic_header": lambda *args, **kwargs: None,
            "_graphic_footer": lambda *args, **kwargs: None,
            "_graphic_glass_panel": lambda *args, **kwargs: None,
            "_graphic_fit_text": lambda draw, text, *args: str(text),
            "_graphic_text_width": lambda draw, text, font: draw.textlength(text, font=font),
            "_GRAPHIC_PALETTE": {k: (20, 20, 20) for k in (
                "bg", "text", "muted", "teal", "clay", "slate", "card", "border", "green")},
            "_editorial_date": lambda value: value or "", "_artifact_is_fresh": lambda _: True,
            "_public_url": lambda value: value, "_prospect_publication_status": lambda: "preliminary",
            "build_share_preview_html": lambda **kwargs: " ".join(str(x) for x in kwargs.values()),
            "buy_score": SimpleNamespace(BOARD_SIZE=40, MOMENTUM_WINDOW_DAYS=14,
                clamp_n=lambda _: 40, build_valucast_board=lambda rows, **kwargs: [dict(x) for x in rows]),
            "SPARK_WINDOW_CHOICES": (7, 14, 21, 30),
            "build_spark": lambda *args, **kwargs: None, "_buy_spark_label": lambda _: "",
            "_first_read_sentence": lambda _: None,
            "_buys_share_card_png": lambda rows, **kwargs: b"PNG-" + repr(rows).encode(),
            "_format_context_label": lambda value: value, "_scouting_display_report": lambda row: dict(row or {}),
            "_row_identity_key": lambda _: "1_hitter", "_ahead_of_consensus_for_key": lambda _: None,
            "_consensus_gap_for_key": lambda _: None, "_role_tracker_profile_for_row": lambda *args: None,
        }
        names = {"_select_buy_source", "_front_door_digest", "index", "_team_board_buys",
                 "_aotc_hold_context", "buys", "_parse_spark_window",
                 "_buys_hold_share_card_png",
                 "_team_board_rank_value", "_team_board_fmt_value", "_team_board_as_float", "_build_team_board_context",
                 "_indexed_artifact_rows", "_identity_key", "backfields_team",
                 "_team_board_share_card_png", "backfields_team_share_card_png",
                 "_build_buys_page_context", "_buy_source_copy", "buys_share_card_png",
                 "buys_share_card", "cards_gallery", "scouting_reports", "_artifact_context_for_row"}
        self.ns = definitions("app.py", names, ns)
        self.app = app
        self.client = app.test_client()

    def approve(self):
        self.review["approval_receipt"] = dict(self.receipt)

    def test_selector_rejects_missing_legacy_and_wrong_scope_receipts(self):
        for receipt in (None, True, {}, {**self.receipt, "scope": "wrong"},
                        {**self.receipt, "approved_at": "invalid"},
                        {**self.receipt, "extra": True}):
            with self.subTest(receipt=receipt):
                self.review["approval_receipt"] = receipt
                selected, source = self.ns["_select_buy_source"](self.store)
                self.assertEqual(source, "unavailable")
                self.assertFalse(selected.is_available)

    def test_qualified_receipt_preserves_existing_readiness_and_hold_gates(self):
        self.approve()
        self.assertEqual(self.ns["_select_buy_source"](self.store)[1], "valucast_buys")
        self.review["review_status"] = "blocked"
        self.assertEqual(self.ns["_select_buy_source"](self.store)[1], "unavailable")
        self.review["review_status"] = "candidate_ready"
        self.ns["AHEAD_OF_THE_CURVE_HOLD"] = True
        self.assertEqual(self.ns["_select_buy_source"](self.store)[1], "unavailable")

    def test_home_route_hides_raw_buy_with_no_receipt_and_keeps_positive_control(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.raw["name"].encode(), response.data)
        self.assertNotIn(b"Top buy", response.data)
        self.approve()
        self.assertIn(self.raw["name"].encode(), self.client.get("/").data)

    def test_team_route_hides_raw_buy_with_no_receipt_and_keeps_positive_control(self):
        response = self.client.get("/backfields/team/SEA")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.raw["name"].encode(), response.data)
        self.assertNotIn(self.raw["reason"].encode(), response.data)
        self.approve()
        self.assertIn(self.raw["name"].encode(), self.client.get("/backfields/team/SEA").data)

    def test_team_png_draws_no_unapproved_recommendation(self):
        drawn = []
        original = ImageDraw.ImageDraw.text
        def record(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, "text", record):
            response = self.client.get("/backfields/team/SEA/share-card.png")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertFalse(any(self.raw["name"] in text or self.raw["reason"] in text for text in drawn))
            self.approve()
            drawn.clear()
            response = self.client.get("/backfields/team/SEA/share-card.png")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(any(self.raw["name"] in text for text in drawn))

    def test_buy_png_is_unavailable_without_receipt(self):
        response = self.client.get("/buys/share-card.png")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(self.raw["name"].encode(), response.data)
        self.approve()
        self.raw["value_history"] = []
        self.assertEqual(self.client.get("/buys/share-card.png").status_code, 200)

    def test_buy_page_explains_hold_without_recommendations_or_refresh_promise(self):
        response = self.client.get("/buys")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertNotIn(self.raw["name"], text)
        self.assertNotIn("0 best prospect buys", text)
        self.assertIn("approval and validation", text)
        self.assertNotIn("will return when the data refreshes", text)

    def test_navigation_marks_denied_buys_held(self):
        source = (ROOT / "templates/base.html").read_text(encoding="utf-8")
        buy_link = next(line for line in source.splitlines() if 'href="/buys"' in line)
        with self.app.test_request_context():
            self.assertIn("is-held", render_template_string(buy_link))
            self.approve()
            self.assertNotIn("is-held", render_template_string(buy_link))

    def test_injected_raw_team_payload_cannot_bypass_missing_receipt(self):
        self.assertEqual(self.ns["_team_board_buys"]("SEA", payload={"board": [self.raw]}), [])

    def test_explicit_hold_copy_does_not_promise_a_release_date(self):
        self.ns["AHEAD_OF_THE_CURVE_HOLD"] = True
        html = self.client.get("/buys").get_data(as_text=True)
        self.assertNotIn("later this week", html.lower())
        self.assertIn("approval and validation", html)
        drawn = []
        original = ImageDraw.ImageDraw.text
        def record(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, "text", record):
            response = self.client.get("/buys/share-card.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertFalse(any("later this week" in text.lower() for text in drawn))
        self.assertFalse(any(self.raw["name"] in text for text in drawn))

    def test_gallery_and_preview_do_not_advertise_unapproved_buys(self):
        with self.app.test_request_context():
            with patch.dict(self.ns, render_template=lambda _, **ctx: ctx):
                gallery = self.ns["cards_gallery"]()
            self.assertFalse(any(x["board_url"] == "/buys" for x in gallery["entries"]))
        preview = self.client.get("/buys/share-card").get_data(as_text=True)
        self.assertNotIn("Top prospect buys by signal", preview)
        self.assertNotIn("returns later this week", preview.lower())

    def test_scouting_buy_rank_is_hidden_but_movement_is_preserved(self):
        with self.app.test_request_context():
            with patch.dict(self.ns, render_template=lambda _, **ctx: ctx):
                result = self.ns["scouting_reports"]()
        self.assertIsNone(result["reports"][0].get("buy_rank_label"))
        self.assertEqual(result["reports"][0]["movement_label"], "Up 2")

    def test_player_context_removes_only_buy_fields_without_mutating_cache(self):
        context = self.ns["_artifact_context_for_row"](object())
        self.assertNotIn("buy_rank", context["recent_signal"])
        self.assertNotIn("buy_reason", context["recent_signal"])
        self.assertEqual(context["recent_signal"]["movement_label"], "Up 2")
        self.assertEqual(self.signal["buy_rank"], 1)
        self.assertEqual(self.signal["buy_reason"], self.raw["reason"])


if __name__ == "__main__":
    unittest.main()
