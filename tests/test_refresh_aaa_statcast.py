"""Offline tests for scripts/refresh_aaa_statcast.py (no network)."""
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.refresh_aaa_statcast as r


# A tiny synthetic CSV mixing an AAA park (BUF) with two FSL Single-A parks (DUN, JUP).
_HEADER = ["game_pk", "home_team", "game_date", "pitcher", "batter", "pitch_type",
           "release_speed", "pfx_x", "pfx_z", "release_spin_rate", "release_extension",
           "spin_axis", "arm_angle", "plate_x", "plate_z", "sz_top", "sz_bot",
           "description", "type", "events", "bb_type", "launch_speed", "launch_angle",
           "bat_speed", "swing_length"]


def _row(**kw):
    base = {h: "" for h in _HEADER}
    base.update(kw)
    return base


def _csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_HEADER)
    w.writeheader()
    for row in rows:
        w.writerow(row)
    return buf.getvalue()


# --- AAA filtering vs FSL --------------------------------------------------
def test_fetch_day_rows_filters_fsl(monkeypatch):
    rows = [
        _row(game_pk="100", home_team="BUF", pitcher="1", batter="2"),   # AAA
        _row(game_pk="200", home_team="DUN", pitcher="3", batter="4"),   # FSL A
        _row(game_pk="300", home_team="JUP", pitcher="5", batter="6"),   # FSL A
        _row(game_pk="101", home_team="BUF", pitcher="7", batter="8"),   # AAA
    ]
    monkeypatch.setattr(r, "_read_with_retry", lambda url, attempts=3: _csv(rows))
    aaa = {"BUF", "CLT", "GWN"}   # DUN/JUP deliberately absent
    kept = r.fetch_day_rows("2026-07-10", aaa)
    assert len(kept) == 2
    assert {row["home_team"] for row in kept} == {"BUF"}


def test_day_chunk_request_is_single_date(monkeypatch):
    captured = {}

    def fake_read(url, attempts=3):
        captured["url"] = url
        return _csv([])

    monkeypatch.setattr(r, "_read_with_retry", fake_read)
    r.fetch_day_rows("2026-07-10", {"BUF"})
    url = captured["url"]
    # One game-date per request: gt == lt == the same day (the 25k-row-cap rule).
    assert "game_date_gt=2026-07-10" in url
    assert "game_date_lt=2026-07-10" in url
    assert "player_type=pitcher" in url


# --- compact slice ---------------------------------------------------------
def test_compact_pitch_types_and_drops():
    row = _row(pitcher="803349", batter="699024", pitch_type="FF",
               release_speed="95.2", pfx_z="1.41", bb_type="ground_ball",
               launch_speed="", bat_speed="72.0", swing_length="6.9")
    c = r._compact_pitch(row)
    assert c["pitcher"] == "803349"          # id kept as str
    assert c["release_speed"] == 95.2        # numeric coerced
    assert c["launch_speed"] is None         # blank -> None
    assert c["bb_type"] == "ground_ball"
    # MLB-only fields are never carried in the compact slice.
    assert "bat_speed" not in c
    assert "swing_length" not in c


def test_rows_to_games_groups_by_game_pk():
    rows = [
        _row(game_pk="100", home_team="BUF", game_date="2026-07-10", pitcher="1"),
        _row(game_pk="100", home_team="BUF", game_date="2026-07-10", pitcher="1"),
        _row(game_pk="101", home_team="CLT", game_date="2026-07-10", pitcher="2"),
    ]
    games = r.rows_to_games(rows)
    assert set(games) == {"100", "101"}
    assert len(games["100"]["pitches"]) == 2
    assert games["101"]["home_team"] == "CLT"


# --- cache immutability -----------------------------------------------------
def test_cached_game_pk_not_refetched(monkeypatch):
    # Cache already has game 100. A fetch returning games 100 (changed) + 101 must
    # NOT overwrite 100 and must add 101.
    cache = {"games": {"100": {"home_team": "BUF", "game_date": "2026-07-10",
                               "season": 2026, "pitches": [{"pitcher": "orig"}]}}}
    day_rows = [
        _row(game_pk="100", home_team="BUF", game_date="2026-07-10", pitcher="CHANGED"),
        _row(game_pk="101", home_team="CLT", game_date="2026-07-10", pitcher="new"),
    ]
    monkeypatch.setattr(r, "fetch_day_rows", lambda day, abbrevs: day_rows)
    monkeypatch.setattr(r, "flush_cache", lambda *a, **k: None)
    stats = r.gather_days(["2026-07-10"], 2026, cache, {"BUF", "CLT"})
    assert stats["new_games"] == 1
    assert stats["skipped_games"] == 1
    # Original slice preserved (immutable finished game).
    assert cache["games"]["100"]["pitches"] == [{"pitcher": "orig"}]
    assert "101" in cache["games"]


# --- date planning ----------------------------------------------------------
def test_incremental_dates_after_cache_max():
    cache = {"games": {
        "1": {"game_date": "2026-07-09"},
        "2": {"game_date": "2026-07-11"},
    }}
    days = r.incremental_dates(cache, 2026, through=date(2026, 7, 13))
    assert days == ["2026-07-12", "2026-07-13"]   # strictly after the max (07-11)


def test_incremental_dates_empty_cache_is_empty():
    # Cold cache -> no dates (caller no-ops rather than backfilling in the daily job).
    assert r.incremental_dates({"games": {}}, 2026, through=date(2026, 7, 13)) == []


def test_cache_max_date():
    cache = {"games": {"1": {"game_date": "2026-05-01"}, "2": {"game_date": "2026-07-04"}}}
    assert r.cache_max_date(cache) == "2026-07-04"
    assert r.cache_max_date({"games": {}}) is None


def test_season_dates_bounds():
    days = r.season_dates(2026, through=date(2026, 3, 22))
    assert days[0] == "2026-03-20"        # season-start anchor
    assert days[-1] == "2026-03-22"


# --- load_cache fail-soft ---------------------------------------------------
def test_load_cache_missing(tmp_path):
    assert r.load_cache(tmp_path / "nope.json") == {"games": {}}


def test_load_cache_malformed(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json", encoding="utf-8")
    assert r.load_cache(p) == {"games": {}}


def test_load_cache_wrong_shape(tmp_path):
    p = tmp_path / "list.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert r.load_cache(p) == {"games": {}}


def test_fetch_aaa_abbreviations_parses(monkeypatch):
    payload = {"teams": [
        {"abbreviation": "BUF"}, {"abbreviation": "CLT"}, {"abbreviation": ""},
        {"abbreviation": None},
    ]}
    monkeypatch.setattr(r, "_read_with_retry", lambda url, attempts=3: json.dumps(payload))
    abbrevs = r.fetch_aaa_abbreviations(2026)
    assert abbrevs == {"BUF", "CLT"}
