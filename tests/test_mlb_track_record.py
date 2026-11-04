"""Tests for the ValuCast MLB track-record contract."""
import json

import pytest

import scraper.season as season_config
from mlb.track_record import (
    _history_payloads,
    _season_rows,
    build_mlb_track_record,
    run_mlb_track_record,
)


def _bucket(group, type_name, splits):
    return {
        "type": {"displayName": type_name},
        "group": {"displayName": group},
        "splits": splits,
    }


def _hitting_split(season, pa, ab, hits, doubles, triples, hr, walks, sb=0, cs=0):
    return {
        "season": str(season),
        "stat": {
            "gamesPlayed": int(pa / 4),
            "plateAppearances": pa,
            "atBats": ab,
            "hits": hits,
            "doubles": doubles,
            "triples": triples,
            "homeRuns": hr,
            "baseOnBalls": walks,
            "strikeOuts": int(pa * 0.2),
            "hitByPitch": 4,
            "sacFlies": 3,
            "runs": int(pa * 0.15),
            "rbi": int(pa * 0.16),
            "stolenBases": sb,
            "caughtStealing": cs,
        },
    }


def _pitching_split(season, ip, er, hits, walks, strikeouts, starts=24):
    return {
        "season": str(season),
        "stat": {
            "gamesPitched": starts,
            "gamesStarted": starts,
            "inningsPitched": ip,
            "earnedRuns": er,
            "hits": hits,
            "baseOnBalls": walks,
            "strikeOuts": strikeouts,
            "wins": 11,
            "losses": 7,
            "saves": 0,
            "holds": 0,
        },
    }


def _raw_history(hitting=None, pitching=None):
    stats = []
    if hitting is not None:
        stats.append(_bucket("hitting", "yearByYear", hitting))
        stats.append(_bucket("hitting", "career", [{"stat": {}}]))
    if pitching is not None:
        stats.append(_bucket("pitching", "yearByYear", pitching))
        stats.append(_bucket("pitching", "career", [{"stat": {}}]))
    return {"stats": stats}


def _hitter_projection(mlbam_id="1", actual=None):
    return {
        "id": f"{mlbam_id}",
        "name": "Track Record Bat",
        "pool": "hitter",
        "positions": ["OF"],
        "team": "BOS",
        "stats": {"PA": 650},
        "metadata": {
            "mlbam_id": str(mlbam_id),
            "stats_actual": actual
            or {
                "G": 70,
                "PA": 300,
                "AB": 250,
                "H": 75,
                "HR": 18,
                "R": 48,
                "RBI": 52,
                "SB": 5,
                "CS": 1,
                "BB": 42,
                "SO": 68,
                "HBP": 2,
                "SF": 2,
                "1B": 42,
                "2B": 14,
                "3B": 1,
            },
        },
    }


def _pitcher_projection(mlbam_id="2", actual=None):
    return {
        "id": f"{mlbam_id}_P",
        "name": "Track Record Arm",
        "pool": "starter",
        "positions": ["SP"],
        "team": "MIL",
        "stats": {"IP": 160},
        "metadata": {
            "mlbam_id": str(mlbam_id),
            "stats_actual": actual
            or {
                "G": 14,
                "GS": 14,
                "IP": 82.0,
                "ER": 24,
                "BB": 22,
                "H_ALLOWED": 66,
                "K": 92,
                "W": 7,
                "L": 3,
                "SV": 0,
                "HLD": 0,
            },
        },
    }


def test_track_record_builds_hitter_prior_current_and_floor():
    raw = _raw_history(
        hitting=[
            _hitting_split(2024, 620, 540, 150, 30, 2, 30, 70, sb=10, cs=2),
            _hitting_split(2025, 610, 530, 154, 34, 1, 32, 72, sb=12, cs=3),
        ],
    )
    payload = build_mlb_track_record(
        [_hitter_projection("10")],
        generated_at="2026-06-13T12:00:00+00:00",
        cache={"players": {"10": {"raw": raw}}},
        refresh_missing=False,
    )

    profile = payload["profiles"][0]

    assert payload["contract_version"] == "0.1.1"
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["validation"]["ready_for_mlb_dynasty_layer"] is True
    assert profile["mlbam_id"] == 10
    assert profile["role"] == "hitter"
    assert profile["volume"]["prior_mlb"] == 1230
    assert profile["volume"]["current_season"] == 300
    assert profile["volume"]["career"] == 1530
    assert profile["experience_band"] == "partial_track_record"
    assert profile["track_record_certainty"] > 55
    assert 55 < profile["track_record_floor_score"] < 63


def test_track_record_builds_two_way_profiles_by_role():
    raw = _raw_history(
        hitting=[_hitting_split(2025, 500, 430, 120, 25, 3, 25, 60, sb=20, cs=5)],
        pitching=[_pitching_split(2025, "140.2", 48, 110, 40, 170)],
    )
    payload = build_mlb_track_record(
        [_hitter_projection("20"), _pitcher_projection("20")],
        generated_at="2026-06-13T12:00:00+00:00",
        cache={"players": {"20": {"raw": raw}}},
        refresh_missing=False,
    )

    profiles = {(row["mlbam_id"], row["role"]): row for row in payload["profiles"]}

    assert set(profiles) == {(20, "hitter"), (20, "pitcher")}
    assert profiles[(20, "pitcher")]["volume"]["prior_mlb"] == 140.667
    assert profiles[(20, "pitcher")]["track_record_certainty"] > 20
    assert profiles[(20, "hitter")]["current_season"]["PA"] == 300


def test_track_record_targets_mlb_dynasty_eligible_projection_rows_only():
    raw = _raw_history(hitting=[_hitting_split(2025, 650, 560, 165, 35, 1, 38, 80)])
    placeholder = _hitter_projection("31")
    placeholder["stats"] = {"PA": 1.0}
    cache = {"players": {"30": {"raw": raw}, "31": {"raw": raw}}}

    payload = build_mlb_track_record(
        [_hitter_projection("30"), placeholder],
        generated_at="2026-06-13T12:00:00+00:00",
        cache=cache,
        refresh_missing=False,
    )

    assert payload["validation"]["tracked_identity_count"] == 1
    assert payload["validation"]["profile_count"] == 1
    assert payload["profiles"][0]["mlbam_id"] == 30
    assert payload["contract"]["universe"] == "MLB dynasty-eligible projection rows only"
    assert payload["cache"]["pruned_player_count"] == 1
    assert set(cache["players"]) == {"30"}


def test_run_mlb_track_record_writes_artifact_cache_and_archive(tmp_path):
    projection_path = tmp_path / "current.json"
    projection_path.write_text(json.dumps([_hitter_projection("30")]), encoding="utf-8")
    (tmp_path / "metadata.json").write_text(
        json.dumps({"as_of": "2026-06-13T12:00:00+00:00"}),
        encoding="utf-8",
    )
    cache_path = tmp_path / "cache.json"
    artifact_path = tmp_path / "track.json"
    archive_dir = tmp_path / "archive"
    raw = _raw_history(hitting=[_hitting_split(2025, 650, 560, 165, 35, 1, 38, 80)])

    calls = []

    def fetcher(mlbam_id):
        calls.append(mlbam_id)
        return raw

    result = run_mlb_track_record(
        projection_path=projection_path,
        artifact_path=artifact_path,
        cache_path=cache_path,
        archive_dir=archive_dir,
        fetcher=fetcher,
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert calls == ["30"]
    assert result["profile_count"] == 1
    assert result["ready_for_mlb_dynasty_layer"] is True
    assert payload["profiles"][0]["mlbam_id"] == 30
    assert cache["players"]["30"]["raw"] == raw
    assert (archive_dir / "2026-06-13.json").exists()


def test_run_mlb_track_record_can_limit_and_resume_fetches(tmp_path):
    projection_path = tmp_path / "current.json"
    projection_path.write_text(
        json.dumps([_hitter_projection("40"), _hitter_projection("41")]),
        encoding="utf-8",
    )
    (tmp_path / "metadata.json").write_text(
        json.dumps({"as_of": "2026-06-13T12:00:00+00:00"}),
        encoding="utf-8",
    )
    cache_path = tmp_path / "cache.json"
    artifact_path = tmp_path / "track.json"
    archive_dir = tmp_path / "archive"
    raw = _raw_history(hitting=[_hitting_split(2025, 650, 560, 165, 35, 1, 38, 80)])

    def fetcher(mlbam_id):
        return raw

    first = run_mlb_track_record(
        projection_path=projection_path,
        artifact_path=artifact_path,
        cache_path=cache_path,
        archive_dir=archive_dir,
        fetcher=fetcher,
        fetch_limit=1,
    )
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert first["fetched_count"] == 1
    assert len(cache["players"]) == 1
    assert first["ready_for_mlb_dynasty_layer"] is False

    second = run_mlb_track_record(
        projection_path=projection_path,
        artifact_path=artifact_path,
        cache_path=cache_path,
        archive_dir=archive_dir,
        fetcher=fetcher,
        fetch_limit=1,
    )
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert second["fetched_count"] == 1
    assert len(cache["players"]) == 2
    assert second["profile_count"] == 2


def test_run_mlb_track_record_fetches_missing_histories_in_bulk(tmp_path):
    projection_path = tmp_path / "current.json"
    projection_path.write_text(
        json.dumps([_hitter_projection("50"), _hitter_projection("51")]),
        encoding="utf-8",
    )
    (tmp_path / "metadata.json").write_text(
        json.dumps({"as_of": "2026-06-13T12:00:00+00:00"}),
        encoding="utf-8",
    )
    cache_path = tmp_path / "cache.json"
    artifact_path = tmp_path / "track.json"
    archive_dir = tmp_path / "archive"
    raw = _raw_history(hitting=[_hitting_split(2025, 650, 560, 165, 35, 1, 38, 80)])
    calls = []

    def bulk_fetcher(mlbam_ids):
        ids = list(mlbam_ids)
        calls.append(ids)
        return {mlbam_id: raw for mlbam_id in ids}

    result = run_mlb_track_record(
        projection_path=projection_path,
        artifact_path=artifact_path,
        cache_path=cache_path,
        archive_dir=archive_dir,
        bulk_fetcher=bulk_fetcher,
    )
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert calls == [["50", "51"]]
    assert result["fetched_count"] == 2
    assert len(cache["players"]) == 2
    assert result["profile_count"] == 2
    assert result["ready_for_mlb_dynasty_layer"] is True


def test_track_record_backfills_mlb_debut_date():
    raw = _raw_history(hitting=[_hitting_split(2025, 650, 560, 165, 35, 1, 38, 80)])
    captured = {}

    def debut_fetcher(mlbam_ids):
        captured["ids"] = list(mlbam_ids)
        return {"40": "2025-04-01T00:00:00Z"}

    payload = build_mlb_track_record(
        [_hitter_projection("40")],
        generated_at="2026-06-13T12:00:00+00:00",
        cache={"players": {"40": {"raw": raw, "fetched_at": "2026-06-13T12:00:00Z"}}},
        refresh_missing=True,
        debut_fetcher=debut_fetcher,
    )

    assert captured["ids"] == ["40"]
    assert payload["profiles"][0]["mlb_debut_date"] == "2025-04-01"


@pytest.mark.parametrize("role,volume", [("hitter", "PA"), ("pitcher", "IP")])
def test_traded_seasons_use_combined_split_or_sum_team_splits(role, volume):
    def split(year, amount, team=None):
        row = (
            _hitting_split(year, amount, amount, 10, 2, 0, 1, 5)
            if role == "hitter"
            else _pitching_split(year, str(amount), 5, 10, 2, 10)
        )
        if team is not None:
            row["team"] = {"id": team}
        return row

    rows = [
        split(2023, 50),
        split(2024, 100, 1), split(2024, 200, 2), split(2024, 300),
        split(2025, 100, 1), split(2025, 200, 2),
    ]
    raw = _raw_history(**{"hitting" if role == "hitter" else "pitching": rows})
    totals = {}
    for year, stats in _season_rows(raw, role):
        totals[year] = totals.get(year, 0) + stats[volume]
    assert totals == {2023: 50, 2024: 300, 2025: 300}


@pytest.mark.parametrize("timestamp", [None, "invalid", "2026-10-31T23:59:59Z"])
def test_history_cache_refreshes_stale_or_unknown_fetch_dates(timestamp):
    old = {"stats": []}
    new = _raw_history(hitting=[_hitting_split(2026, 600, 500, 150, 30, 1, 20, 60)])
    cache = {"players": {"1": {"raw": old, "fetched_at": timestamp}}}
    calls = []

    def fetcher(mlbam_id):
        calls.append(mlbam_id)
        return new

    payloads, missing, fetched = _history_payloads(
        ["1"], cache, season=2027, fetcher=fetcher, fetched_at="2026-11-03T12:00:00Z",
    )
    assert calls == ["1"]
    assert (payloads, missing, fetched) == ({"1": new}, [], 1)
    assert cache["players"]["1"]["fetched_at"] == "2026-11-03T12:00:00Z"


@pytest.mark.parametrize("timestamp", ["2026-11-01T00:00:00Z", "2026-11-02T12:00:00"])
def test_history_cache_reuses_entries_at_or_after_cutoff(timestamp):
    old = {"stats": []}
    cache = {"players": {"1": {"raw": old, "fetched_at": timestamp}}}

    def fetcher(mlbam_id):
        pytest.fail("fresh cache must not be fetched")

    assert _history_payloads(["1"], cache, season=2027, fetcher=fetcher) == ({"1": old}, [], 0)


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_history_refresh_failure_keeps_cached_payload(bulk, failure):
    old = {"stats": []}
    cached = {"raw": old, "fetched_at": "2026-10-01T00:00:00Z"}
    cache = {"players": {"1": cached.copy()}}

    def fetcher(ids):
        if failure:
            raise OSError("synthetic fetch failure")
        return {}

    kwargs = {"bulk_fetcher" if bulk else "fetcher": fetcher}
    result = _history_payloads(["1"], cache, season=2027, **kwargs)
    assert result == ({"1": old}, [], 0)
    assert cache["players"]["1"] == cached


@pytest.mark.parametrize("kwargs", [{"refresh_missing": False}, {"fetch_limit": 0}])
def test_stale_cache_remains_available_without_refresh(kwargs):
    old = {"stats": []}
    cache = {"players": {"1": {"raw": old}}}

    def fetcher(mlbam_id):
        pytest.fail("disabled refresh must not fetch")

    assert _history_payloads(["1"], cache, season=2027, fetcher=fetcher, **kwargs) == ({"1": old}, [], 0)


@pytest.mark.parametrize("explicit_season", [None, 2028])
def test_preseason_counts_last_season_as_prior_without_duplicate_actuals(monkeypatch, explicit_season):
    monkeypatch.setattr(season_config, "TARGET_SEASON", 2027)
    monkeypatch.setattr(season_config, "CONTEXT_SEASON", 2026)
    rookie = _raw_history(hitting=[_hitting_split(2026, 300, 250, 75, 14, 1, 18, 42)])
    veteran = _raw_history(hitting=[
        _hitting_split(2025, 600, 500, 150, 30, 1, 20, 60),
        _hitting_split(2026, 300, 250, 75, 14, 1, 18, 42),
    ])
    payload = build_mlb_track_record(
        [_hitter_projection("1"), _hitter_projection("2")],
        generated_at="2026-11-03T12:00:00Z", season=explicit_season,
        cache={"players": {"1": {"raw": rookie}, "2": {"raw": veteran}}},
        refresh_missing=False,
    )
    assert payload["season"] == (explicit_season or 2027)
    assert [row["volume"] for row in payload["profiles"]] == [
        {"career": 300, "prior_mlb": 300, "current_season": 0, "recent_3yr_prior": 300},
        {"career": 900, "prior_mlb": 900, "current_season": 0, "recent_3yr_prior": 900},
    ]
