"""Private hosted probes; stdout contains only bounded JSON evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from scripts.rehearsal_errors import HarnessError, exception_evidence, process_evidence

STAMP = {"in_house_season": 2026, "target_season": 2027,
         "season_note": "In-house line: 2026 season; not a 2027 comparison."}
ROUTES = ("/health/ready", "/", "/?mode=dd_dynasty", "/export", "/methodology", "/role-watch")
EXPECTED_STATUSES = {route: 200 for route in ROUTES}
EXPECTED_STATUSES["/role-watch"] = "same as committed-state result"


def stamp_evidence(payload):
    actual = {key: payload.get(key) for key in STAMP}
    return {"stamps": actual, "ok": actual == STAMP}


def provenance_evidence(html, metadata):
    footer = re.search(r'<div\b[^>]*id=[\"\']footer-provenance[\"\'][^>]*>(.*?)</div>',
                       html, re.S | re.I)
    phrase = bool(footer and "Steamer 2027 full-season projections" in footer.group(1))
    return {"footer_steamer_2027": phrase,
            "target_season": metadata.get("target_season"),
            "projection_phase": metadata.get("projection_phase"),
            "ros_source": metadata.get("ros_source"),
            "ok": phrase and metadata.get("target_season") == 2027
            and metadata.get("projection_phase") == "preseason_full_season"
            and metadata.get("ros_source") == "fangraphs_steamer_full_season"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def archive_stamp_state(current_bytes, committed_bytes):
    if current_bytes is None or current_bytes == committed_bytes:
        return {"stamp_check": "not_evaluated",
                "reason": "unchanged committed artifact or cadence/raw-vintage skip"}
    return {"stamp_check": "evaluated"}


def startup(state, committed_routes=None):
    try:
        import app as application
    except Exception as exc:
        return {"state": state, "ok": False, **exception_evidence(exc),
                "expected_statuses": EXPECTED_STATUSES, "routes": {
                    route: {"status": None, **exception_evidence(exc)} for route in ROUTES}}
    client = application.app.test_client()
    statuses = {}
    html = ""
    for route in ROUTES:
        try:
            response = client.get(route)
            statuses[route] = {"status": response.status_code}
            if route == "/":
                html = response.get_data(as_text=True)
        except Exception as exc:
            statuses[route] = {"status": None, **exception_evidence(exc)}
    reference = statuses if state == "committed" else (committed_routes or {})
    role_status = reference.get("/role-watch", {}).get("status")
    for route, item in statuses.items():
        item["expected_status"] = role_status if route == "/role-watch" else EXPECTED_STATUSES[route]
    result = {"state": state, "routes": statuses, "expected_statuses": EXPECTED_STATUSES,
              "notes": ["pre-existing: /role-watch 404 on committed data"] if role_status == 404 else [],
              "ok": all(item["status"] is not None and item["status"] == item["expected_status"]
                        for item in statuses.values())}
    for item in statuses.values():
        if "error_type" in item:
            result.update({key: value for key, value in item.items()
                           if key in ("error_type", "final_frame", "error_message")})
            break
    if state == "refreshed":
        result["provenance"] = provenance_evidence(html, load("data/projections/metadata.json"))
        result["ok"] = result["ok"] and result["provenance"]["ok"]
    else:
        result["committed_target_season"] = load("data/projections/metadata.json").get("target_season")
        result["ok"] = result["ok"] and result["committed_target_season"] == 2026
    return result


def isolation():
    result = {"artifacts": {}, "ok": True}
    for name in ("valucast_playing_time_role_tracker", "valucast_mlb_projection_source_comparison"):
        try:
            evidence = stamp_evidence(load(f"data/models/{name}.json"))
        except Exception as exc:
            evidence = {"ok": False, **exception_evidence(exc)}
            result.update(exception_evidence(exc))
        result["artifacts"][name] = evidence
        result["ok"] &= evidence["ok"]
    try:
        manifest = load("projections/runs/valucast_hp_2026_v2/run_manifest.json")
        result["run_as_of_season"] = manifest.get("as_of_season")
        result["ok"] &= result["run_as_of_season"] == 2026
    except Exception as exc:
        result["manifest_error_type"] = type(exc).__name__
        result["manifest_error"] = exception_evidence(exc)
        result.update(exception_evidence(exc))
        result["ok"] = False
    as_of = str(load("data/projections/metadata.json")["as_of"])
    path = Path("data/prediction_archive/projection_source_ros") / f"{as_of}.json"
    committed = Path(os.environ["REHEARSAL_COMMITTED_ROOT"]) / path
    state = archive_stamp_state(path.read_bytes() if path.exists() else None,
                               committed.read_bytes() if committed.exists() else None)
    result["source_archive"] = {"dated_artifact_present": path.exists(), **state}
    if state["stamp_check"] == "evaluated":
        payload = load(path)
        evidence = stamp_evidence(payload)
        evidence["hp_projection_season"] = payload.get("sources", {}).get("valucast_hp", {}).get("projection_season")
        evidence["ok"] &= evidence["hp_projection_season"] == 2026
        result["source_archive"].update(evidence)
        result["ok"] &= evidence["ok"]
    return result


def deny_write(*args, **kwargs):
    raise HarnessError("Fault probe reached a write")


def fault():
    from scraper import refresh
    metadata = os.environ["REHEARSAL_COMMITTED_METADATA"]
    result = {"target_mismatch": False, "writes_attempted": 0, "actuals_reached": 0, "ok": False}
    def guard(*args, **kwargs):
        result["writes_attempted"] += 1
        deny_write()
    def actuals_guard(*args, **kwargs):
        result["actuals_reached"] += 1
        raise HarnessError("Fault probe reached actuals")
    with patch.object(refresh, "fetch_all", return_value={"steamer_hitters": [], "steamer_pitchers": []}), \
         patch.object(refresh, "regular_season_games_final", return_value=0), \
         patch.object(refresh, "_write_json", side_effect=guard), \
         patch.object(refresh, "save_raw", side_effect=guard), \
         patch.object(refresh, "build_actuals", side_effect=actuals_guard):
        try:
            refresh.refresh(metadata_path=metadata, delay=0)
        except RuntimeError as exc:
            result["target_mismatch"] = str(exc) == "Prior ROS target_season must match TARGET_SEASON"
            if not result["target_mismatch"]:
                result.update(exception_evidence(exc))
        except Exception as exc:
            result.update(exception_evidence(exc))
    result["ok"] = result["target_mismatch"] and result["writes_attempted"] == 0 and result["actuals_reached"] == 0
    return result


def season_fields(rows):
    keys = sorted({key for row in rows for key in row
                   if re.search(r"season|year", key, re.I)})
    return {key: dict(sorted(Counter(str(row[key]) for row in rows if key in row).items()))
            for key in keys}


def refresh_counts():
    from scraper import season
    from scraper.fangraphs import fetch_all
    system = "steamer" if season.is_preseason() else "steamerr"
    rows = fetch_all(delay=0, system=system)
    return {"system": system, "row_counts": {key: len(value) for key, value in rows.items()}, "ok": True}


def feed():
    from scraper.fangraphs import fetch_projections
    pools = {pool: fetch_projections("steamer", pool) for pool in ("bat", "pit")}
    result = {"pools": {pool: {"rows": len(rows), "season_fields": season_fields(rows)}
                        for pool, rows in pools.items()}}
    env = os.environ.copy()
    env.pop("GITHUB_OUTPUT", None)
    run = subprocess.run([sys.executable, "scripts/check_steamer_season.py"],
                         capture_output=True, text=True, env=env)
    verdict = re.search(r"^verdict=(live|not_live|unknown)$", run.stdout, re.M)
    result["checker"] = {"exit_code": run.returncode,
                         "script": "scripts/check_steamer_season.py",
                         "verdict": verdict.group(1) if verdict else None,
                         "counts": [int(value) for value in re.findall(r" rows: (\d+)$", run.stdout, re.M)]}
    if run.returncode:
        result["checker"].update(process_evidence(run.stdout + "\n" + run.stderr))
    result["ok"] = run.returncode == 0 and verdict is not None and all(pools.values())
    return result


def self_test():
    assert stamp_evidence(STAMP)["ok"]
    assert not stamp_evidence({**STAMP, "target_season": 2026})["ok"]
    meta = {"target_season": 2027, "projection_phase": "preseason_full_season",
            "ros_source": "fangraphs_steamer_full_season"}
    html = '<div id="footer-provenance">Steamer 2027 full-season projections</div>'
    assert provenance_evidence(html, meta)["ok"]
    assert not provenance_evidence("Steamer 2027 full-season projections", meta)["ok"]
    assert not provenance_evidence(html, {**meta, "target_season": 2026})["ok"]
    assert archive_stamp_state(None, None)["stamp_check"] == "not_evaluated"
    assert archive_stamp_state(b"old", b"old")["stamp_check"] == "not_evaluated"
    assert archive_stamp_state(b"new", b"old")["stamp_check"] == "evaluated"
    assert archive_stamp_state(b"new", None)["stamp_check"] == "evaluated"
    def fake_isolation_load(path):
        if str(path).endswith("valucast_mlb_projection_source_comparison.json"):
            raise RuntimeError("private isolation rows")
        if str(path).endswith("run_manifest.json"):
            return {"as_of_season": 2026}
        return {**STAMP, "as_of": "synthetic"}
    with patch(__name__ + ".load", side_effect=fake_isolation_load), \
         patch.object(Path, "exists", return_value=False), \
         patch.dict(os.environ, {"REHEARSAL_COMMITTED_ROOT": "synthetic-committed"}):
        failed_isolation = isolation()
    assert not failed_isolation["ok"] and failed_isolation["error_type"] == "RuntimeError"
    assert failed_isolation["final_frame"].endswith(":" + str(fake_isolation_load.__code__.co_firstlineno + 2))
    assert "private isolation rows" not in json.dumps(failed_isolation)
    assert failed_isolation["source_archive"]["stamp_check"] == "not_evaluated"
    assert globals()["refresh-counts".replace("-", "_")] is refresh_counts
    with patch.dict(sys.modules, {"app": None}):
        failed = startup("committed")
    assert not failed["ok"] and set(failed["routes"]) == set(ROUTES)
    assert all(item["status"] is None and item["error_type"] == "ModuleNotFoundError"
               for item in failed["routes"].values())
    fake_app = ModuleType("app")
    route_codes = {route: 200 for route in ROUTES}
    route_codes["/role-watch"] = 404
    fake_app.app = SimpleNamespace(test_client=lambda: SimpleNamespace(
        get=lambda route: SimpleNamespace(status_code=route_codes[route],
                                          get_data=lambda **kwargs: html)))
    with patch.dict(sys.modules, {"app": fake_app}), patch(__name__ + ".load", return_value={"target_season": 2026}):
        committed = startup("committed")
        assert committed["ok"]
        assert committed["notes"] == ["pre-existing: /role-watch 404 on committed data"]
        assert committed["expected_statuses"]["/role-watch"] == "same as committed-state result"
        with patch(__name__ + ".load", return_value=meta):
            refreshed = startup("refreshed", committed["routes"])
            assert refreshed["ok"] and refreshed["routes"]["/role-watch"]["expected_status"] == 404
            assert not startup("refreshed")["ok"]
            route_codes["/role-watch"] = 500
            assert not startup("refreshed", committed["routes"])["ok"]
            route_codes["/role-watch"] = 404
            healthy_baseline = {route: {"status": 200} for route in ROUTES}
            assert not startup("refreshed", healthy_baseline)["ok"]
        route_codes["/methodology"] = 404
        assert not startup("committed")["ok"]
        def failed_route(route):
            raise RuntimeError("private feed body")
        fake_app.app = SimpleNamespace(test_client=lambda: SimpleNamespace(get=failed_route))
        failed = startup("committed")
        assert not failed["ok"] and failed["error_type"] == "RuntimeError"
        assert failed["final_frame"].endswith(":" + str(failed_route.__code__.co_firstlineno + 1))
        assert "private feed body" not in json.dumps(failed)
    fake_scraper = ModuleType("scraper")
    fake_season = ModuleType("scraper.season")
    fake_fangraphs = ModuleType("scraper.fangraphs")
    fake_scraper.season = fake_season
    observed = []
    def fake_fetch_all(**kwargs):
        observed.append(kwargs)
        return {"steamer_hitters": [{}, {}], "steamer_pitchers": [{}]}
    fake_fangraphs.fetch_all = fake_fetch_all
    with patch.dict(sys.modules, {"scraper": fake_scraper, "scraper.season": fake_season,
                                  "scraper.fangraphs": fake_fangraphs}):
        for preseason, system in ((True, "steamer"), (False, "steamerr")):
            fake_season.is_preseason = lambda: preseason
            evidence = refresh_counts()
            assert evidence == {"system": system, "row_counts": {
                "steamer_hitters": 2, "steamer_pitchers": 1}, "ok": True}
            assert observed[-1] == {"delay": 0, "system": system}
    assert season_fields([{"Season": 2027}, {"Season": 2027}, {"Year": 2026}]) == {
        "Season": {"2027": 2}, "Year": {"2026": 1}}
    try:
        deny_write()
    except HarnessError:
        pass
    else:
        raise AssertionError("write guard failed")
    return {"self_test": "passed", "ok": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("startup", "isolation", "feed", "fault", "refresh-counts"))
    parser.add_argument("state", nargs="?", choices=("committed", "refreshed"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test and (os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("REHEARSAL_PROXY")):
        parser.error("Real probes require the hosted rehearsal and replay proxy")
    if not args.self_test and (not args.command or (args.command == "startup" and not args.state)):
        parser.error("startup requires a state; otherwise select isolation, feed, or fault")
    sys.path.insert(0, str(Path.cwd()))
    sys.path.insert(0, str(Path.cwd() / "src"))
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            if args.self_test:
                result = self_test()
            elif args.command == "startup":
                reference = Path(os.environ["REHEARSAL_COMMITTED_STARTUP"])
                if args.state == "refreshed" and not reference.is_file():
                    raise HarnessError("Committed startup reference missing")
                committed_routes = load(reference).get("routes", {}) if args.state == "refreshed" else None
                result = startup(args.state, committed_routes)
                if args.state == "committed":
                    reference.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
            else:
                result = globals()[args.command.replace("-", "_")]()
            if not result["ok"] and "error_type" not in result:
                failures = {
                    "startup": "Startup route status or projection provenance check failed",
                    "isolation": "In-house season isolation check failed",
                    "feed": "Full-season feed check failed",
                    "fault": "Empty-feed fault isolation check failed",
                    "refresh-counts": "Requested feed row check failed",
                }
                try:
                    raise HarnessError(failures[args.command])
                except HarnessError as exc:
                    result.update(exception_evidence(exc))
        except Exception as exc:
            result = {"ok": False, **exception_evidence(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
