"""Hosted-only real-app suppression probe; candidate files stay read-only."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
import sys
from pathlib import Path
import traceback
from urllib.parse import quote, urlencode, urlsplit

TOKEN = "BUYZXQ"
RANK_TOKEN = 77777743
PNG = b"\x89PNG\r\n\x1a\n"


def _has_sentinel(value):
    lowered = str(value).casefold()
    return TOKEN.casefold() in lowered or f"b#{RANK_TOKEN}" in lowered


def _route_coverage(url_map, paths):
    actual = {rule.rule for rule in url_map.iter_rules() if rule.rule.endswith(".png")}
    adapter = url_map.bind("localhost")
    matched, errors = [], []
    for label, path in paths.items():
        try:
            rule, _ = adapter.match(urlsplit(path).path, method="GET", return_rule=True)
            matched.append({"surface": label, "rule": rule.rule})
        except Exception as error:
            errors.append({"surface": label, "exception_class": type(error).__name__})
    templates = [item["rule"] for item in matched]
    return {"exact": not errors and actual == set(templates) and len(actual) == len(templates) == len(paths),
            "actual_count": len(actual), "matched": matched, "errors": errors,
            "missing_rules": sorted(actual - set(templates)),
            "unexpected_rules": sorted(set(templates) - actual),
            "duplicate_rule_count": len(templates) - len(set(templates))}


def _active_png_ok(status, signature, draws, cache_present):
    return status == 200 and signature and draws > 0 and cache_present


def _denied_png_ok(label, status, signature, draws, new_cache_present, repeated):
    if label == "buys" and status == 503:
        return draws == 0 and not new_cache_present and repeated
    return status == 200 and signature and draws > 0 and new_cache_present and repeated


def _route_exception(result, root, scratch, label, error):
    # Raw trace stays in runner temp; exports contain source frames and types only.
    with (scratch / "full-app-private-trace.txt").open("a", encoding="utf-8") as stream:
        stream.write(label + "\n" + traceback.format_exc() + "\n")
    result["route_exceptions"].append({"surface_case": label, "exception_class": type(error).__name__,
        "source_frames": [{"path": str(Path(frame.filename).relative_to(root)), "line": frame.lineno,
                           "function": frame.name}
                          for frame in traceback.extract_tb(error.__traceback__)
                          if Path(frame.filename).is_relative_to(root)]})
    result["failures"].append("exception_" + label)


def self_check():
    from types import SimpleNamespace
    class FakeMap:
        def iter_rules(self):
            return [SimpleNamespace(rule="/a.png"), SimpleNamespace(rule="/b/<player_id>.png")]
        def bind(self, host):
            return self
        def match(self, path, **kwargs):
            if path == "/a.png":
                return SimpleNamespace(rule="/a.png"), {}
            if path.startswith("/b/"):
                return SimpleNamespace(rule="/b/<player_id>.png"), {"player_id": "synthetic"}
            raise LookupError("synthetic missing route")
    routes = FakeMap()
    assert _route_coverage(routes, {"a":"/a.png", "b":"/b/synthetic.png?x=1"})["exact"]
    assert not _route_coverage(routes, {"a":"/a.png", "dup":"/a.png"})["exact"]
    assert not _route_coverage(routes, {"a":"/a.png", "bad":"/missing.png"})["exact"]
    assert _active_png_ok(200, True, 1, True)
    assert not _active_png_ok(404, False, 0, False)
    assert not _active_png_ok(200, True, 0, True)
    assert not _active_png_ok(500, True, 1, True)
    assert _denied_png_ok("buys", 503, False, 0, False, True)
    assert not _denied_png_ok("team", 503, False, 0, False, True)
    assert _denied_png_ok("team", 200, True, 1, True, True)
    assert not _denied_png_ok("team", 200, True, 0, True, True)
    assert _has_sentinel("buyzxq") and _has_sentinel(f"B#{RANK_TOKEN}")
    assert not _has_sentinel("Independent scouting text")
    return {"self_check": "passed", "app_imported": "app" in sys.modules}


def run(root: Path, scratch: Path) -> dict:
    from PIL import Image, ImageDraw

    result = {"kind": "full_app_buy_suppression", "app_imported": False,
              "publication_authorized": False, "candidate_files_modified": False,
              "fixture_controls": ["synthetic_receipt_in_temp_file", "in_memory_raw_buy_sentinel",
                                   "in_memory_recent_signal_sentinel", "in_memory_scouting_signal_sentinel",
                                   "served_buy_gate_proxy", "active_snapshot_label_for_adversarial_test",
                                   "aotc_feature_hold_disabled_for_adversarial_test"],
              "html": [], "png": [], "route_exceptions": [], "failures": [], "qualified": False}
    try:
        module = importlib.import_module("app")
        result["app_imported"] = True
        if Path(module.__file__).resolve() != root / "app.py":
            raise ValueError("Application import is not from the staged checkout")
        module.app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=True)
        original_snapshot = module.dd_store
        original_rows = list(original_snapshot.get_all())
        identities = {module._row_identity_key(row): row for row in original_rows
                      if getattr(row, "is_prospect", False)}
        original_loader = module._load_artifact
        scouting_path = root / "data/models/valucast_scouting_reports.json"
        scouting_payload = deepcopy(original_loader(scouting_path) or {})
        scouting_index = module._indexed_artifact_rows(scouting_payload, "reports")
        raw_rows = module.valucast_buy_store.get_all()
        pair = next(((raw, identities[module._identity_key(raw.get("mlbam_id"), raw.get("role"))])
                     for raw in raw_rows
                     if module._identity_key(raw.get("mlbam_id"), raw.get("role")) in identities
                     and module._identity_key(raw.get("mlbam_id"), raw.get("role")) in scouting_index), None)
        if pair is None:
            result["failures"].append("no_actual_buy_player_scouting_match")
            return result
        raw, prospect = pair
        raw = deepcopy(raw)
        raw.update(name=TOKEN, reason=TOKEN, rank=1)
        module.valucast_buy_store._rows = [raw]
        module.valucast_buy_store._is_available = True
        module.valucast_buy_store._ready_for_live_consumers = True
        module.AHEAD_OF_THE_CURVE_HOLD = False
        # Deliberately exercise the approval boundary even when this old candidate
        # would normally serve stale; this does not qualify its freshness.
        module.dynasty_data_source = "valucast_public_snapshot"

        class SnapshotProxy:
            served_buys = True

            def __getattr__(self, key):
                return getattr(original_snapshot, key)

            @property
            def surface_readiness(self):
                return {**original_snapshot.surface_readiness,
                        "buys": self.served_buys, "prospects": False}

        proxy = SnapshotProxy()
        module.dd_store = proxy
        review_path = scratch / "synthetic_buy_review.json"
        def load(path):
            return original_loader(review_path if Path(path) == module.VALUCAST_BUYS_REVIEW_PATH else path)

        module._load_artifact = load
        receipt = {"schema_version": "1.0.0", "origin": "explicit_manual_input",
                   "scope": "valucast_owned_buys_promotion_v1",
                   "approved_at": datetime.now(timezone.utc).isoformat()}
        review = {"review_status": "candidate_ready", "approval_receipt": None,
                  "source_policy": {"manual_approval_recorded": True, "prior_approval_reused": True},
                  "generated_at": "synthetic-unchanged"}

        def state(approved, served=True):
            proxy.served_buys = served
            review["approval_receipt"] = deepcopy(receipt) if approved else None
            before = review_path.stat().st_mtime_ns if review_path.exists() else None
            for _ in range(100):
                review_path.write_text(json.dumps(review), encoding="utf-8")
                if before is None or review_path.stat().st_mtime_ns != before:
                    break
            else:
                raise RuntimeError("fixture_mtime_did_not_advance")

        # Seed the real artifact cache with an unsafe legacy signal while keeping
        # its underlying immutable candidate file and unrelated context intact.
        signal_path = root / "data/models/valucast_recent_signal_report.json"
        signal_payload = deepcopy(original_loader(signal_path) or {})
        signals = signal_payload.setdefault("signals", [])
        identity = module._row_identity_key(prospect)
        signal = next((row for row in signals if row.get("identity_key") == identity), None)
        if signal is None:
            signal = {"identity_key": identity}
            signals.append(signal)
        signal.update(buy_rank=RANK_TOKEN, buy_reason=TOKEN)
        scouting_row = scouting_index[identity]
        scouting_row["recent_signal"] = {**(scouting_row.get("recent_signal") or {}),
                                         "buy_rank": RANK_TOKEN, "buy_reason": TOKEN}
        module._ARTIFACT_CACHE[scouting_path] = (scouting_path.stat().st_mtime_ns, scouting_payload)
        module._ARTIFACT_CACHE[signal_path] = (signal_path.stat().st_mtime_ns, signal_payload)

        client = module.app.test_client()
        player_id = quote(str(prospect.id), safe="")
        projection_rows = list(module.store.get_all())
        projection = next((row for row in projection_rows if getattr(row, "pool", None) == "hitter"),
                          projection_rows[0])
        projection_id = quote(str(projection.id), safe="")
        org = str(raw.get("team") or "SEA")
        trade_ids = [str(row.id) for row in original_rows[:2]]
        if len(trade_ids) != 2:
            raise RuntimeError("candidate_has_insufficient_trade_rows")
        trade_query = urlencode({"give": trade_ids[0], "get": trade_ids[1]})
        html_paths = {
            "home_dynasty": "/?mode=dd_dynasty", "home_prospects": "/?mode=prospects",
            "backfields": "/backfields", "team": f"/backfields/team/{org}",
            "team_preview": f"/backfields/team/{org}/share-card", "buys": "/buys",
            "buy_preview": "/buys/share-card", "gallery": "/cards",
            "player": f"/player/{player_id}?mode=prospects",
            "scouting": "/scouting?" + urlencode({"q": prospect.name}),
            "prospect_preview": f"/prospects/player-card/{player_id}",
            "dynasty_preview": f"/dynasty/player-card/{player_id}",
            "redraft_preview": f"/redraft/player-card/{projection_id}",
        }
        png_paths = {
            "farms": "/farms/share-card.png", "team": f"/backfields/team/{org}/share-card.png",
            "positional_prospects": "/share/prospects/SS.png", "trade": "/trade/share-card.png?" + trade_query,
            "map": "/map/share-card.png", "movers": "/movers/share-card.png",
            "discipline": "/discipline-leaders/share-card.png", "receipts": "/receipts/share-card.png",
            "ledger": "/ledger/share-card.png", "scoreboard": "/scoreboard/share-card.png",
            "buys": "/buys/share-card.png", "prospects_board": "/prospects/share-card.png",
            "prospect_player": f"/prospects/player-card/{player_id}.png",
            "redraft_player": f"/redraft/player-card/{projection_id}.png",
            "dynasty_player": f"/dynasty/player-card/{player_id}.png",
            "dynasty_board": "/dynasty/share-card.png", "redraft_board": "/redraft/share-card.png",
        }
        coverage = _route_coverage(module.app.url_map, png_paths)
        result["png_route_coverage"] = coverage
        result["actual_png_route_count"] = coverage["actual_count"]
        if not coverage["exact"]:
            result["failures"].append("png_route_inventory_mismatch")
        held_routes = {}
        if module.SCOREBOARD_HOLD:
            held_routes["scoreboard"] = "SCOREBOARD_HOLD"
        if module.RECEIPTS_HOLD:
            held_routes["receipts"] = "RECEIPTS_HOLD"
        result["explicitly_held_png_surfaces"] = held_routes

        result["positive_buy_selector_active"] = False
        result["positive_buy_html_sentinel"] = False
        try:
            state(True)
            positive_response = client.get("/buys")
            result["positive_buy_selector_active"] = module._select_buy_source(module.valucast_buy_store)[1] == "valucast_buys"
            result["positive_buy_html_sentinel"] = _has_sentinel(positive_response.get_data(as_text=True))
            if positive_response.status_code != 200 or not result["positive_buy_selector_active"] or not result["positive_buy_html_sentinel"]:
                result["failures"].append("positive_buy_control_inert")
        except Exception as error:
            _route_exception(result, root, scratch, "positive_buy_control", error)

        html_positive_marker = {"home_dynasty", "home_prospects", "team", "buys", "player", "scouting"}
        for label, path in html_paths.items():
            headers = {"HX-Request": "true"} if label == "player" else {}
            for withdrawal in ("receipt", "served_gate"):
                case = "html_" + label + "_" + withdrawal
                try:
                    state(True)
                    positive = client.get(path, headers=headers)
                    positive_body = positive.get_data(as_text=True)
                    marker = _has_sentinel(positive_body)
                    positive_ok = positive.status_code == 200 and (label not in html_positive_marker or marker)
                    # Repeated approved request warms actual artifact/context caches.
                    warm = client.get(path, headers=headers)
                    state(withdrawal == "served_gate", served=withdrawal != "served_gate")
                    response = client.get(path, headers=headers)
                    body = response.get_data(as_text=True)
                    safe = not _has_sentinel(body)
                    expected = {200, 503} if label == "buy_preview" else {200}
                    ok = positive_ok and warm.status_code == 200 and safe and response.status_code in expected
                    result["html"].append({"surface": label, "withdrawal": withdrawal,
                        "approved_status": positive.status_code, "approved_marker_present": marker,
                        "approved_control_ok": positive_ok, "warm_status": warm.status_code,
                        "status": response.status_code, "sentinel_absent": safe, "passed": ok})
                    if not ok:
                        result["failures"].append(case)
                except Exception as error:
                    _route_exception(result, root, scratch, case, error)
                    result["html"].append({"surface": label, "withdrawal": withdrawal,
                                           "status": "exception", "passed": False})

        drawn = []
        saves = [0]
        original_text = ImageDraw.ImageDraw.text
        original_save = Image.Image.save

        def record_text(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return original_text(draw, xy, text, *args, **kwargs)

        def save(image, *args, **kwargs):
            saves[0] += 1
            return original_save(image, *args, **kwargs)

        ImageDraw.ImageDraw.text = record_text
        Image.Image.save = save
        try:
            for label, path in png_paths.items():
                for withdrawal in ("receipt", "served_gate"):
                    case = "png_" + label + "_" + withdrawal
                    try:
                        # Isolate before warming only; withdrawal must retain approved entries.
                        module._PNG_CACHE.clear()
                        state(True)
                        drawn.clear()
                        before_saves = saves[0]
                        allowed = client.get(path)
                        approved_draw = saves[0] - before_saves
                        positive_sentinel = any(_has_sentinel(value) for value in drawn)
                        old_keys = set(module._PNG_CACHE)
                        before_cached = saves[0]
                        cached = client.get(path)
                        warm = (cached.status_code == allowed.status_code and cached.data == allowed.data
                                and saves[0] == before_cached)
                        state(withdrawal == "served_gate", served=withdrawal != "served_gate")
                        drawn.clear()
                        before_denied = saves[0]
                        denied = client.get(path)
                        denied_draw = saves[0] - before_denied
                        safe = all(not _has_sentinel(value) for value in drawn)
                        signature = denied.data.startswith(PNG)
                        new_keys = set(module._PNG_CACHE) - old_keys
                        after_denied = saves[0]
                        again = client.get(path)
                        repeated = (again.status_code == denied.status_code and again.data == denied.data
                                    and saves[0] == after_denied)
                        old_retained = old_keys.issubset(module._PNG_CACHE)
                        active = _active_png_ok(allowed.status_code, allowed.data.startswith(PNG),
                                                approved_draw, bool(old_keys))
                        held_flag = held_routes.get(label)
                        if held_flag:
                            # Source-held routes expose no public PNG; do not claim renderer coverage.
                            ok = (allowed.status_code == cached.status_code == denied.status_code == again.status_code == 404
                                  and approved_draw == denied_draw == 0 and not old_keys and not new_keys
                                  and safe and not _has_sentinel(denied.get_data(as_text=True)))
                            generation_ok = None
                        else:
                            generation_ok = (warm and old_retained and _denied_png_ok(
                                label, denied.status_code, signature, denied_draw, bool(new_keys), repeated))
                            ok = active and safe and generation_ok
                        if label in {"buys", "team"}:
                            ok = ok and positive_sentinel and "no-store" in denied.headers.get("Cache-Control", "")
                        result["png"].append({"surface": label, "withdrawal": withdrawal,
                            "approved_status": allowed.status_code, "denied_status": denied.status_code,
                            "repeat_status": again.status_code, "active_png": active,
                            "explicit_source_hold": held_flag, "renderer_exercised": approved_draw > 0,
                            "positive_sentinel_drawn": positive_sentinel,
                            "png_signature_ok": signature if not held_flag else None,
                            "sentinel_absent": safe, "warm_cache": warm,
                            "cache_entry_present": bool(old_keys), "new_generation_rendered": denied_draw > 0,
                            "denied_repeat_hit": repeated if denied.status_code == 200 else None,
                            "denied_rejection_repeated": repeated if denied.status_code == 503 else None,
                            "old_entry_retained": old_retained, "generation_ok": generation_ok, "passed": bool(ok)})
                        if not ok:
                            result["failures"].append(case)
                    except Exception as error:
                        _route_exception(result, root, scratch, case, error)
                        result["png"].append({"surface": label, "withdrawal": withdrawal,
                                              "status": "exception", "passed": False})
        finally:
            ImageDraw.ImageDraw.text = original_text
            Image.Image.save = original_save
        state(False, served=False)
        result["final_buy_selector_unavailable"] = module._select_buy_source(module.valucast_buy_store)[1] == "unavailable"
        result["raw_recommendation_still_present"] = module.valucast_buy_store.get_all()[0]["reason"] == TOKEN
        result["prospects_preliminary_in_probe"] = module._prospect_publication_status() == "preliminary"
        result["qualified"] = (not result["failures"] and result["final_buy_selector_unavailable"]
                               and result["raw_recommendation_still_present"]
                               and result["prospects_preliminary_in_probe"]
                               and len(result["html"]) == 2 * len(html_paths)
                               and len(result["png"]) == 2 * len(png_paths))
    except Exception as error:
        (scratch / "full-app-private-trace.txt").write_text(traceback.format_exc(), encoding="utf-8")
        result["failures"].append("probe_exception")
        result["exception_class"] = type(error).__name__
        result["source_frames"] = [
            {"path": str(Path(frame.filename).relative_to(root)), "line": frame.lineno,
             "function": frame.name}
            for frame in traceback.extract_tb(error.__traceback__)
            if Path(frame.filename).is_relative_to(root)]
    return result


def main():
    import argparse
    from contextlib import redirect_stderr, redirect_stdout
    import os
    parser = argparse.ArgumentParser(description="Read-only staged Dynasty Buy consumer rehearsal")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--run", metavar="SCRATCH")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_check(), sort_keys=True))
        return 0
    root = Path.cwd().resolve()
    scratch = Path(args.run).resolve()
    result = {"kind": "staged_buy_suppression_rehearsal", "qualified": False,
              "merge_authorized": False, "publication_authorized": False}
    guard = None
    bound = None
    try:
        if Path(__file__).resolve() != root / "scripts/probe_dynasty_buy_suppression.py":
            raise ValueError("Probe must run from its exact staged checkout root")
        if scratch == root or scratch.is_relative_to(root):
            raise ValueError("Scratch must be outside the staged checkout")
        if "app" in sys.modules:
            raise ValueError("Rehearsal requires a fresh process before app import")
        runtime_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
        if not scratch.is_relative_to(runtime_temp):
            raise ValueError("Scratch must be under RUNNER_TEMP")
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(root / "scripts"))
        import dynasty_rehearsal_access as access
        if Path(access.__file__).resolve() != root / "scripts/dynasty_rehearsal_access.py":
            raise ValueError("Access helper is not from the staged checkout")
        scratch.mkdir(parents=True, exist_ok=True)
        private_output = scratch / "probe-private-output.txt"
        with private_output.open("w", encoding="utf-8") as private, redirect_stdout(private), redirect_stderr(private):
            bound = access.bind_candidate(root, root / "scripts/dynasty_rehearsal_access_contract.json")
            # Match the original controller's separate dependency initialization;
            # urllib3 performs a local IPv6 capability bind before the serving guard.
            import requests
            import urllib3
            result["dependency_initialization"] = {"requests": requests.__version__,
                "urllib3": urllib3.__version__, "before_serving_guard": True}
            writes = (scratch / "synthetic_buy_review.json", scratch / "full-app-private-trace.txt", private_output)
            guard = access.install_guard(bound, write_files=writes)
            sys.path.insert(0, str(root))
            try:
                result["consumers"] = run(root, scratch)
            finally:
                guard.active = False
                result["access"] = access.verify_after(bound, guard)
                sys.meta_path.remove(guard.code_finder)
            result["candidate_commit"] = bound["contract"]["candidate_data_commit"]
            result["candidate_tree"] = bound["contract"]["staged_tree"]
            result["qualified"] = bool(result["consumers"].get("qualified") is True
                                       and result["access"].get("access_qualified") is True)
    except Exception as error:
        if guard is not None:
            guard.active = False
        result["failure_class"] = type(error).__name__
        result["qualified"] = False
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
