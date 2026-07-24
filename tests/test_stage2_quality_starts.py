import copy
import json

from scripts.build_stage2_quality_starts import (
    build_from_files,
    build_quality_starts,
)


def _game(date, ip, er, started=1):
    return {
        "date": date,
        "stat": {
            "gamesStarted": started,
            "inningsPitched": ip,
            "earnedRuns": er,
        },
    }


def _input():
    return {
        "current": {"fetched_date": "2026-07-23"},
        "historical_mlb_seasons": {
            "101_pitcher": [
                {"year": 2024, "ip": 50.0},
                {"year": 2024, "ip": 100.0},
            ],
            "102_pitcher": [{"year": 2024, "ip": 30.0}],
            "103_pitcher": [{"year": 2024, "ip": 80.0, "qs": 2}],
            "104_pitcher": [{"year": 2026, "ip": 10.0}],
            "999_hitter": [{"year": 2024, "pa": 500}],
        },
    }


def _history():
    return {
        "rows": [
            {"id": 101, "season": 2024, "gs": 2},
            {"id": 102, "season": 2024, "gs": 0},
            {"id": 103, "season": 2024, "gs": 2},
        ]
    }


def _logs():
    return {
        ("101", 2024): [
            _game("2024-04-01", "6.0", 2),
            _game("2024-04-07", "5.2", 1),
        ],
        ("103", 2024): [
            _game("2024-05-01", "6.0", 2),
            _game("2024-05-07", "7.0", 3),
        ],
        ("104", 2026): [
            _game("2026-07-20", "6.0", 3),
            _game("2026-07-24", "7.0", 0),
        ],
    }


def test_builds_complete_deterministic_sidecar_without_mutating_inputs():
    source = _input()
    history = _history()
    before_source = copy.deepcopy(source)
    before_history = copy.deepcopy(history)
    calls = []

    def fetcher(mlbam_id, group, season):
        calls.append((mlbam_id, group, season))
        return _logs()[(mlbam_id, season)]

    report = build_quality_starts(
        source,
        history,
        input_path="data/prospects/prospect_model_inputs.json",
        input_sha256="abc123",
        fetcher=fetcher,
        delay=0,
    )

    assert report["status"] == "ready"
    assert report["blockers"] == []
    assert report["coverage"] == {
        "source_rows": 5,
        "unique_player_seasons": 4,
        "resolved_player_seasons": 4,
        "post_join_rows_with_qs": 5,
    }
    assert [
        (row["mlbam_id"], row["season"], row["games_started"],
         row["quality_starts"], row["provenance"])
        for row in report["rows"]
    ] == [
        (101, 2024, 2, 1, "derived_game_log"),
        (102, 2024, 0, 0, "no_starts"),
        (103, 2024, 2, 2, "existing_qs"),
        (104, 2026, 1, 1, "derived_game_log"),
    ]
    assert calls == [
        ("101", "pitching", 2024),
        ("103", "pitching", 2024),
        ("104", "pitching", 2026),
    ]
    assert report["validation"]["existing_values_checked"] == 1
    assert report["content_sha256"]
    assert source == before_source
    assert history == before_history

    second = build_quality_starts(
        source,
        history,
        input_path="data/prospects/prospect_model_inputs.json",
        input_sha256="abc123",
        fetcher=lambda mlbam_id, group, season: _logs()[(mlbam_id, season)],
        delay=0,
    )
    assert second == report


def test_blocks_duplicate_qs_conflicts():
    source = {
        "current": {"fetched_date": "2026-07-23"},
        "historical_mlb_seasons": {
            "201_pitcher": [
                {"year": 2024, "ip": 20, "qs": 1},
                {"year": 2024, "ip": 40, "qs": 2},
            ]
        },
    }
    report = build_quality_starts(
        source,
        {"rows": [{"id": 201, "season": 2024, "gs": 0}]},
        input_path="input.json",
        input_sha256="hash",
        fetcher=lambda *_: [],
        delay=0,
    )

    assert report["status"] == "blocked"
    assert report["rows"] == []
    assert report["validation"]["duplicate_value_conflicts"] == [
        {"mlbam_id": 201, "season": 2024, "values": [1, 2]}
    ]
    assert "duplicate_qs_conflict:201:2024" in report["blockers"]


def test_blocks_start_and_existing_qs_mismatches():
    source = {
        "current": {"fetched_date": "2026-07-23"},
        "historical_mlb_seasons": {
            "301_pitcher": [{"year": 2024, "ip": 80, "qs": 2}]
        },
    }
    report = build_quality_starts(
        source,
        {"rows": [{"id": 301, "season": 2024, "gs": 3}]},
        input_path="input.json",
        input_sha256="hash",
        fetcher=lambda *_: [
            _game("2024-04-01", "6.0", 2),
            _game("2024-04-07", "5.0", 1),
        ],
        delay=0,
    )

    assert report["status"] == "blocked"
    assert report["rows"] == []
    assert report["validation"]["games_started_mismatches"] == [
        {"mlbam_id": 301, "season": 2024, "expected": 3, "actual": 2}
    ]
    assert report["validation"]["existing_value_mismatches"] == [
        {"mlbam_id": 301, "season": 2024, "existing": 2, "derived": 1}
    ]


def test_current_season_unversioned_qs_is_superseded_and_disclosed():
    source = {
        "current": {"fetched_date": "2026-07-23"},
        "historical_mlb_seasons": {
            "302_pitcher": [{"year": 2026, "ip": 80, "qs": 1}]
        },
    }
    report = build_quality_starts(
        source,
        {"rows": []},
        input_path="input.json",
        input_sha256="hash",
        fetcher=lambda *_: [
            _game("2026-04-01", "6.0", 2),
            _game("2026-05-01", "6.0", 3),
            _game("2026-06-01", "7.0", 1),
        ],
        delay=0,
    )

    assert report["status"] == "ready"
    assert report["rows"] == [
        {
            "mlbam_id": 302,
            "season": 2026,
            "games_started": 3,
            "quality_starts": 3,
            "provenance": "derived_game_log",
        }
    ]
    assert report["validation"]["current_season_values_superseded"] == [
        {"mlbam_id": 302, "season": 2026, "existing": 1, "derived": 3}
    ]


def test_fetch_failure_blocks_instead_of_zero_filling():
    source = {
        "current": {"fetched_date": "2026-07-23"},
        "historical_mlb_seasons": {
            "401_pitcher": [{"year": 2024, "ip": 10}]
        },
    }

    def fail(*_):
        raise RuntimeError("upstream unavailable")

    report = build_quality_starts(
        source,
        {"rows": [{"id": 401, "season": 2024, "gs": 1}]},
        input_path="input.json",
        input_sha256="hash",
        fetcher=fail,
        delay=0,
    )

    assert report["status"] == "blocked"
    assert report["rows"] == []
    assert report["blockers"] == ["game_log_fetch_failed:401:2024"]


def test_checkpoint_is_hash_bound_and_file_build_is_atomic(tmp_path):
    input_path = tmp_path / "input.json"
    history_path = tmp_path / "history.json"
    output_path = tmp_path / "sidecar.json"
    checkpoint_path = tmp_path / "checkpoint.json"
    input_path.write_text(json.dumps(_input()), encoding="utf-8")
    history_path.write_text(json.dumps(_history()), encoding="utf-8")
    before_input = input_path.read_bytes()
    before_history = history_path.read_bytes()
    checkpoint_path.write_text(
        json.dumps({
            "input_sha256": "wrong-hash",
            "rows": {"101:2024": {"games_started": 99, "quality_starts": 99}},
        }),
        encoding="utf-8",
    )
    calls = []

    def fetcher(mlbam_id, group, season):
        calls.append((mlbam_id, season))
        return _logs()[(mlbam_id, season)]

    first = build_from_files(
        input_path,
        history_path,
        output_path,
        checkpoint_path=checkpoint_path,
        fetcher=fetcher,
        delay=0,
    )
    assert first["status"] == "ready"
    assert len(calls) == 3
    assert json.loads(output_path.read_text(encoding="utf-8")) == first
    assert input_path.read_bytes() == before_input
    assert history_path.read_bytes() == before_history
    assert not list(tmp_path.glob("*.tmp"))

    calls.clear()
    second = build_from_files(
        input_path,
        history_path,
        output_path,
        checkpoint_path=checkpoint_path,
        fetcher=lambda *_: calls.append("unexpected"),
        delay=0,
    )
    assert second == first
    assert calls == []
