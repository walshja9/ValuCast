"""Tests for the ValuCast MLB track-record contract."""
import json

from mlb.track_record import (
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
