"""Synthetic PNG-cache regressions; AST-load helpers without importing app."""
from __future__ import annotations

import ast
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest

from flask import Flask, g, make_response, request


ROOT = Path(__file__).resolve().parents[1]
BUY_PNG_PATHS = ("/buys/share-card.png", "/backfields/team/sea/share-card.png")
ORDINARY_PNG_PATH = "/board/share-card.png"


def cache_fixture():
    """Use the actual cache and selector bodies with isolated synthetic stores."""
    app = Flask(__name__, static_folder=None)
    app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=True)
    snapshot = SimpleNamespace(
        generated_at="2026-11-26T12:00:00Z",
        surface_readiness={"prospects": True, "buys": True},
    )
    candidate = SimpleNamespace(
        generated_at="2026-11-26T12:00:00Z",
        is_available=True,
        ready_for_live_consumers=True,
    )
    namespace = {
        "app": app, "g": g, "request": request, "make_response": make_response,
        "dd_store": snapshot, "store": SimpleNamespace(as_of="2026-11-26"),
        "valucast_buy_store": candidate, "AHEAD_OF_THE_CURVE_HOLD": False,
        "dynasty_data_source": "valucast_public_snapshot",
        "_UNAVAILABLE_DYNASTY_STORE": SimpleNamespace(is_available=False),
        "os": SimpleNamespace(environ={"VALUCAST_USE_VALUCAST_BUYS": "1"}),
        "_PNG_CACHE": OrderedDict(), "_PNG_CACHE_LOCK": threading.Lock(), "_PNG_CACHE_MAX": 32,
        # These tests do not submit category/point-rule query parameters.
        "_PNG_CACHE_PREFIXED_KEYS": frozenset(),
        "datetime": datetime,
    }
    names = {
        "_png_cache_generation", "_png_cache_key", "_serve_cached_png", "_maybe_cache_png",
        "_select_buy_source", "_prospect_publication_status", "_PNG_CACHE_PARAMS",
    }
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if (
        isinstance(node, ast.FunctionDef) and node.name in names
        or isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
    )]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    exec(compile(module, str(ROOT / "app.py"), "exec"), namespace)
    approval_names = {"APPROVAL_SCHEMA_VERSION", "APPROVAL_SCOPE", "qualified_approval_receipt"}
    approval_tree = ast.parse((ROOT / "prospects" / "buy_approval.py").read_text(encoding="utf-8"))
    approval_nodes = [node for node in approval_tree.body if (
        isinstance(node, ast.FunctionDef) and node.name in approval_names
        or isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in approval_names for target in node.targets)
    )]
    approval_module = ast.fix_missing_locations(ast.Module(body=[future, *approval_nodes], type_ignores=[]))
    exec(compile(approval_module, str(ROOT / "prospects" / "buy_approval.py"), "exec"), namespace)
    review = {
        "generated_at": "2026-11-26T12:00:00Z", "review_status": "candidate_ready",
        "approval_receipt": {
            "schema_version": namespace["APPROVAL_SCHEMA_VERSION"],
            "origin": "explicit_manual_input", "scope": namespace["APPROVAL_SCOPE"],
            "approved_at": "2026-11-26T12:00:00Z",
        },
    }
    review_path = object()
    def load_synthetic_review(path):
        if path is not review_path:
            raise AssertionError("Unexpected artifact request in synthetic PNG test")
        return review
    namespace["VALUCAST_BUYS_REVIEW_PATH"] = review_path
    namespace["_load_artifact"] = load_synthetic_review
    app.after_request(namespace["_maybe_cache_png"])
    controls = SimpleNamespace(public_header=None, flip_during_render=False)
    calls = {path: 0 for path in (*BUY_PNG_PATHS, ORDINARY_PNG_PATH)}

    def render_card():
        calls[request.path] += 1
        source = namespace["_select_buy_source"](candidate)[1]
        if request.path in BUY_PNG_PATHS and source != "valucast_buys":
            return make_response("synthetic blocked Buy card", 503)
        response = make_response(b"synthetic approved PNG")
        response.mimetype = "image/png"
        if controls.public_header is not None:
            response.headers["Cache-Control"] = controls.public_header
        if controls.flip_during_render:
            candidate.ready_for_live_consumers = False
            controls.flip_during_render = False
        return response

    for index, path in enumerate((*BUY_PNG_PATHS, ORDINARY_PNG_PATH)):
        app.add_url_rule(path, "synthetic_card_" + str(index), render_card)
    return SimpleNamespace(
        app=app, namespace=namespace, snapshot=snapshot, candidate=candidate, review=review,
        controls=controls, calls=calls, client=app.test_client(),
    )


def block(fixture, mechanism):
    if mechanism == "candidate_approval":
        fixture.candidate.ready_for_live_consumers = False
    elif mechanism == "receipt_withdrawal":
        fixture.review.pop("approval_receipt")
    else:
        fixture.snapshot.surface_readiness["buys"] = False


class BuyPngCache(unittest.TestCase):
    def test_generation_tracks_effective_approval_without_date_changes(self):
        for mechanism in ("candidate_approval", "served_buys_gate", "receipt_withdrawal"):
            with self.subTest(mechanism=mechanism):
                fixture = cache_fixture()
                namespace = fixture.namespace
                before = namespace["_png_cache_generation"]()
                dates = (fixture.snapshot.generated_at, fixture.candidate.generated_at, namespace["store"].as_of,
                         fixture.review["generated_at"])
                block(fixture, mechanism)
                self.assertEqual(namespace["_select_buy_source"](fixture.candidate)[1], "unavailable")
                self.assertEqual(dates, (fixture.snapshot.generated_at, fixture.candidate.generated_at, namespace["store"].as_of,
                                         fixture.review["generated_at"]))
                self.assertNotEqual(before, namespace["_png_cache_generation"]())

    def test_cached_card_cannot_bypass_same_date_approval_block_before_route(self):
        for path in BUY_PNG_PATHS:
            for mechanism in ("candidate_approval", "served_buys_gate", "receipt_withdrawal"):
                with self.subTest(path=path, mechanism=mechanism):
                    fixture = cache_fixture()
                    self.assertFalse(fixture.app.config["TESTING"])
                    approved = fixture.client.get(path)
                    self.assertEqual(approved.status_code, 200)
                    self.assertTrue(fixture.namespace["_PNG_CACHE"])
                    block(fixture, mechanism)
                    blocked = fixture.client.get(path)
                    self.assertEqual(blocked.status_code, 503)
                    self.assertNotEqual(blocked.data, approved.data)
                    self.assertEqual(fixture.calls[path], 2, "blocked request must reach the route gate")

    def test_sensitive_fresh_png_overrides_incoming_public_max_age(self):
        for path in BUY_PNG_PATHS:
            with self.subTest(path=path):
                fixture = cache_fixture()
                fixture.controls.public_header = "public, max-age=7200"
                response = fixture.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_sensitive_cached_hit_overrides_legacy_public_headers(self):
        for path in BUY_PNG_PATHS:
            with self.subTest(path=path):
                fixture = cache_fixture()
                with fixture.app.test_request_context(path):
                    key = fixture.namespace["_png_cache_key"]()
                fixture.namespace["_PNG_CACHE"][key] = (
                    b"synthetic older approved PNG",
                    {"Content-Type": "image/png", "Cache-Control": "public, max-age=7200"},
                )
                response = fixture.client.get(path)
                self.assertEqual(response.data, b"synthetic older approved PNG")
                self.assertEqual(fixture.calls[path], 0, "fixture must exercise the cache-hit response")
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_mid_render_approval_flip_cannot_cache_approved_body_as_blocked(self):
        for path in BUY_PNG_PATHS:
            with self.subTest(path=path):
                fixture = cache_fixture()
                fixture.controls.flip_during_render = True
                first = fixture.client.get(path)
                self.assertEqual(first.status_code, 200)
                self.assertFalse(fixture.candidate.ready_for_live_consumers)
                with fixture.app.test_request_context(path):
                    blocked_key = fixture.namespace["_png_cache_key"]()
                self.assertNotIn(blocked_key, fixture.namespace["_PNG_CACHE"])
                blocked = fixture.client.get(path)
                self.assertEqual(blocked.status_code, 503)
                self.assertEqual(fixture.calls[path], 2)

    def test_response_without_before_request_key_is_not_inserted(self):
        fixture = cache_fixture()
        with fixture.app.test_request_context(BUY_PNG_PATHS[0]):
            response = make_response(b"synthetic response without request-key capture")
            response.mimetype = "image/png"
            fixture.namespace["_maybe_cache_png"](response)
        self.assertFalse(fixture.namespace["_PNG_CACHE"])

    def test_approved_sensitive_png_still_uses_memory_cache(self):
        for path in BUY_PNG_PATHS:
            with self.subTest(path=path):
                fixture = cache_fixture()
                first = fixture.client.get(path)
                second = fixture.client.get(path)
                self.assertEqual(first.data, second.data)
                self.assertEqual(fixture.calls[path], 1)

    def test_other_png_retains_default_public_policy_and_memory_cache(self):
        fixture = cache_fixture()
        first = fixture.client.get(ORDINARY_PNG_PATH)
        second = fixture.client.get(ORDINARY_PNG_PATH)
        self.assertEqual(first.headers["Cache-Control"], "public, max-age=600")
        self.assertEqual(second.headers["Cache-Control"], first.headers["Cache-Control"])
        self.assertEqual(first.data, second.data)
        self.assertEqual(fixture.calls[ORDINARY_PNG_PATH], 1)


if __name__ == "__main__":
    unittest.main()
