"""Synthetic source regressions; never import app or read committed player data."""
from __future__ import annotations

import ast
import builtins
from collections import OrderedDict
from datetime import datetime
import json
import math
from pathlib import Path
import re
import tempfile
import threading
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


def definitions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if (
        isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
        or isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
    )]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    exec(compile(module, str(ROOT / path), "exec"), namespace)
    return namespace


class ContenderLock:
    def __init__(self, boundary):
        self.lock = threading.Lock()
        self.boundary = boundary

    def __enter__(self):
        if threading.current_thread().name == "contender":
            self.boundary.set()
        self.lock.acquire()

    def __exit__(self, *args):
        self.lock.release()


class PausingDict(OrderedDict):
    def __init__(self, values, operation, key, entered, release):
        super().__init__(values)
        self.pause = (operation, key)
        self.entered, self.release = entered, release

    def paused(self, operation, key):
        if threading.current_thread().name == "reader" and self.pause == (operation, key):
            self.entered.set()
            if not self.release.wait(5):
                raise AssertionError("reader was not released")

    def get(self, key, default=None):
        value = super().get(key, default)
        self.paused("get", key)
        return value

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if hasattr(self, "pause"):
            self.paused("set", key)


class PublicConsumerSafety(unittest.TestCase):
    def interleave(self, first, second, entered, release, boundary):
        errors = []
        def run(callback, contender=False):
            try:
                callback()
            except Exception as exc:
                errors.append(exc)
            finally:
                if contender:
                    boundary.set()
        reader = threading.Thread(target=run, args=(first,), name="reader")
        contender = threading.Thread(target=run, args=(second, True), name="contender")
        reader.start()
        try:
            self.assertTrue(entered.wait(5), "reader did not reach the race")
            contender.start()
            self.assertTrue(boundary.wait(5), "contender did not reach the mutex or finish")
        finally:
            release.set()
            reader.join(5)
            if contender.ident is not None:
                contender.join(5)
        self.assertFalse(reader.is_alive() or contender.is_alive(), "thread did not finish")
        self.assertEqual(errors, [])

    def validator(self):
        names = {
            "SUPPORTED_SCHEMA_VERSIONS", "ARTIFACT_NAME", "REQUIRED_RECORD_FIELDS",
            "PROSPECT_REQUIRED_RECORD_FIELDS", "PROSPECT_REQUIRED_CONTEXT_FIELDS",
            "PROSPECT_VALUCAST_STAT_CONTEXT_FIELDS", "PROHIBITED_TRUE_FLAGS",
            "DD_DERIVED_SOURCE_TOKENS", "_is_dd_derived_source", "_missing_required",
            "_identity_key", "_is_finite_number", "required_field_problems",
            "validate_public_snapshot_payload",
        }
        return definitions("web/public_snapshot_store.py", names, {"math": math})["validate_public_snapshot_payload"]

    def payload(self):
        return {
            "schema_version": "1.1", "artifact": "valucast_public_dynasty_snapshot",
            "generated_at": "2026-01-01T00:00:00Z",
            "source_policy": {key: False for key in (
                "dd_values_used", "dd_ranks_used", "external_rankings_used_for_score", "market_values_used_for_score")},
            "players": [{"id": "synthetic", "name": "Synthetic", "mlbam_id": 1,
                         "role": "hitter", "player_type": "mlb", "positions": ["DH"],
                         "rank": 1, "value": 50.0, "value_scale": "synthetic",
                         "value_source": "valucast_synthetic", "confidence": "high",
                         "updated_at": "2026-01-01T00:00:00Z"}],
        }

    def test_rejects_nonfinite_and_boolean_values(self):
        validate = self.validator()
        for value in (math.nan, math.inf, -math.inf, True, 10 ** 400):
            with self.subTest(value_type=type(value).__name__):
                payload = self.payload()
                payload["players"][0]["value"] = value
                self.assertTrue(any(".value " in problem for problem in validate(payload)))

    def test_rejects_invalid_preset_values(self):
        validate = self.validator()
        for value in (math.nan, math.inf, True, "50", None):
            with self.subTest(value_type=type(value).__name__):
                payload = self.payload()
                payload["players"][0]["value_by_preset"] = {"5x5": value}
                self.assertTrue(any("value_by_preset" in problem for problem in validate(payload)))

    def test_finite_values_keep_the_existing_range_contract(self):
        validate = self.validator()
        for value in (-1000.0, 0, 150.0):
            payload = self.payload()
            payload["players"][0].update(value=value, value_by_preset={"5x5": value})
            self.assertEqual(validate(payload), [])

    def test_rank_rejects_booleans_without_a_new_range(self):
        validate = self.validator()
        for rank in (True, False):
            with self.subTest(rank=rank):
                payload = self.payload()
                payload["players"][0]["rank"] = rank
                self.assertTrue(any(".rank " in problem for problem in validate(payload)))
        for rank in (-1, 0, 1):
            payload = self.payload()
            payload["players"][0]["rank"] = rank
            self.assertEqual(validate(payload), [])

    def buy_namespace(self, readiness):
        snapshot = SimpleNamespace(
            is_available=True, generated_at="2026-01-01T00:00:00Z",
            ready_for_live_consumers=True,
        )
        if readiness is not None:
            snapshot.surface_readiness = readiness
        buy = SimpleNamespace(is_available=True, ready_for_live_consumers=True)
        receipt = {"schema_version": "1.0.0", "origin": "explicit_manual_input",
                   "scope": "valucast_owned_buys_promotion_v1", "approved_at": "2026-01-01T00:00:00Z"}
        qualifier = definitions("prospects/buy_approval.py", {
            "APPROVAL_SCHEMA_VERSION", "APPROVAL_SCOPE", "qualified_approval_receipt",
        }, {"datetime": datetime})["qualified_approval_receipt"]
        return definitions("app.py", {"_select_buy_source", "health_ready"}, {
            "app": SimpleNamespace(route=lambda *args, **kwargs: lambda function: function),
            "os": SimpleNamespace(environ={}), "AHEAD_OF_THE_CURVE_HOLD": False,
            "_UNAVAILABLE_DYNASTY_STORE": SimpleNamespace(is_available=False),
            "dynasty_data_source": "valucast_public_snapshot",
            "dd_store": snapshot, "public_snapshot_store": (
                snapshot if readiness is not None
                else SimpleNamespace(**vars(snapshot), surface_readiness={})
            ),
            "valucast_buy_store": buy,
            "VALUCAST_BUYS_REVIEW_PATH": Path("synthetic-review.json"),
            "_load_artifact": lambda _: {"review_status": "candidate_ready", "approval_receipt": receipt},
            "qualified_approval_receipt": qualifier,
            "CATALOG": SimpleNamespace(store_for=lambda _: SimpleNamespace(player_count=1)),
            "jsonify": lambda body: body, "_artifact_is_fresh": lambda _: True,
        })

    def test_buy_source_requires_authoritative_surface_approval(self):
        for readiness in ({"buys": False}, {}, None):
            with self.subTest(readiness=readiness):
                namespace = self.buy_namespace(readiness)
                selected, source = namespace["_select_buy_source"](namespace["valucast_buy_store"])
                self.assertEqual(source, "unavailable")
                self.assertFalse(selected.is_available)

    def test_buy_source_keeps_the_approved_positive_case(self):
        namespace = self.buy_namespace({"buys": True})
        selected, source = namespace["_select_buy_source"](namespace["valucast_buy_store"])
        self.assertEqual(source, "valucast_buys")
        self.assertIs(selected, namespace["valucast_buy_store"])

    def test_blocked_buys_are_reported_without_failing_core_health(self):
        for readiness in ({"buys": False}, {}, None):
            with self.subTest(readiness=readiness):
                namespace = self.buy_namespace(readiness)
                body, status = namespace["health_ready"]()
                self.assertEqual(status, 200)
                self.assertTrue(body["ready"])
                self.assertFalse(body["valucast_buys"]["live"])

    def test_daily_buy_approval_requires_only_the_manual_input(self):
        workflow = (ROOT / ".github/workflows/daily-public-data.yml").read_text(encoding="utf-8")
        expressions = [line.split(":", 1)[1].strip() for line in workflow.splitlines()
                       if line.strip().startswith("VALUCAST_BUYS_REVIEW_APPROVED:")]
        self.assertEqual(len(expressions), 1)
        self.assertRegex(expressions[0], r"^\$\{\{\s*inputs\.approve_valucast_buys\s*&&\s*'1'\s*\|\|\s*'0'\s*\}\}$")

    def test_request_weights_drop_negatives_without_changing_point_coefficients(self):
        class Args(dict):
            def getlist(self, key):
                return [] if key not in self else [self[key]]
        class ConfigCaptured(Exception):
            pass
        captured = {}
        def capture_config(**kwargs):
            captured.update(kwargs)
            raise ConfigCaptured
        def controlled_import(name, *args, **kwargs):
            if name == "web.category_registry":
                return SimpleNamespace(canonicalize_cats=lambda values: values)
            return builtins.__import__(name, *args, **kwargs)
        namespace = definitions("app.py", {"_build_context"}, {
            "__builtins__": dict(vars(builtins), __import__=controlled_import),
            "math": math, "parse_list": lambda values: values,
            "DEFAULT_CATS": ["HR"], "DEFAULT_PCATS": ["K"],
            "_effective_source": lambda value: value, "_active_store": lambda _: object(),
            "_POINT_STAT_IDS": {"HR"}, "build_config": capture_config,
        })
        with self.assertRaises(ConfigCaptured):
            namespace["_build_context"](Args(w_HR="-1", w_R="0", w_SB="2", pt_HR="-2"))
        self.assertEqual(captured["weights"], {"R": 0.0, "SB": 2.0})
        self.assertEqual(captured["pt_params"], {"HR": -2.0})

    def test_cache_hit_cannot_be_evicted_before_lru_update(self):
        self.cache_race("get")

    def test_cache_insert_cannot_be_evicted_before_lru_update(self):
        self.cache_race("set")

    def cache_race(self, operation):
        namespace = definitions("web/board_time_machine_store.py", {"BoardTimeMachineStore"}, {
            "Path": Path, "OrderedDict": OrderedDict, "json": json, "threading": threading,
            "ARCHIVE_DIR": Path("."), "_ROW_LIMIT": 300, "_CACHE_MAX": 8,
            "_DATE_RE": re.compile(r"\d{4}-\d{2}-\d{2}"), "_comparability": lambda _: "clean",
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dates = [f"2026-01-{day:02d}" for day in range(1, 19)]
            for day in dates:
                (root / f"{day}.json").write_text(json.dumps({"board": []}), encoding="utf-8")
            store = namespace["BoardTimeMachineStore"](root)
            for day in dates[:8]:
                store.board_for(day)
            entered, release, boundary = threading.Event(), threading.Event(), threading.Event()
            target = dates[0] if operation == "get" else dates[8]
            store._board_cache = PausingDict(store._board_cache, operation, target, entered, release)
            store._cache_lock = ContenderLock(boundary)
            other_dates = dates[9:] if operation == "set" else dates[8:9]
            results = {}
            self.interleave(lambda: results.update(reader=store.board_for(target)),
                            lambda: results.update(contender=[store.board_for(day) for day in other_dates]),
                            entered, release, boundary)
            self.assertEqual(results["reader"]["date"], target)
            self.assertEqual([view["date"] for view in results["contender"]], other_dates)
            self.assertLessEqual(len(store._board_cache), 8)

    def test_concurrent_imports_cannot_exceed_the_per_ip_limit(self):
        namespace = definitions("app.py", {"_import_rate_limited"}, {
            "time": SimpleNamespace(monotonic=lambda: 100.0),
            "_IMPORT_RATE_WINDOW": 60.0, "_IMPORT_RATE_MAX": 5,
        })
        entered, release, boundary = threading.Event(), threading.Event(), threading.Event()
        namespace["_IMPORT_HITS"] = PausingDict({"synthetic": [99.0] * 4}, "get", "synthetic", entered, release)
        namespace["_IMPORT_HITS_LOCK"] = ContenderLock(boundary)
        limited = []
        check = lambda: limited.append(namespace["_import_rate_limited"]("synthetic"))
        self.interleave(check, check, entered, release, boundary)
        self.assertEqual(sorted(limited), [False, True])


if __name__ == "__main__":
    unittest.main()
