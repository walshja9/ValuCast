"""Tests for the MLB chart method ID: the build stamps it, the chart line restarts on a change."""

import json

import mlb.dynasty as dynasty
from mlb.dynasty import archive_layer, value_method_id
# The legacy-date tests go away together with MLB_LEGACY_METHOD_BREAK_DATE.
from scripts.build_public_dynasty_snapshot import (
    MLB_LEGACY_METHOD_BREAK_DATE,
    TWO_WAY_SECONDARY_VALUE_WEIGHT,
    _mlb_value_history_from_archives,
)


def _write(archive_dir, date_str, rows, method_id=None):
    payload = {"players": rows}
    if method_id is not None:
        payload["method_id"] = method_id
    (archive_dir / f"{date_str}.json").write_text(json.dumps(payload), encoding="utf-8")


def _row(value, mlbam_id=99, **extra):
    return {"mlbam_id": mlbam_id, "value": value, **extra}


def test_same_method_id_keeps_every_point(tmp_path):
    _write(tmp_path, "2026-12-01", [_row(80.0)], "m1")
    _write(tmp_path, "2026-12-02", [_row(81.5)], "m1")
    _write(tmp_path, "2026-12-03", [_row(83.0)], "m1")

    history = _mlb_value_history_from_archives(tmp_path, "m1")

    assert history["99"] == [("2026-12-01", 80.0), ("2026-12-02", 81.5), ("2026-12-03", 83.0)]


def test_unstamped_files_on_or_after_the_legacy_date_are_compatible(tmp_path):
    day_after = "2026-11-19"
    assert MLB_LEGACY_METHOD_BREAK_DATE < day_after
    _write(tmp_path, MLB_LEGACY_METHOD_BREAK_DATE, [_row(70.0)])
    _write(tmp_path, day_after, [_row(71.0)])

    history = _mlb_value_history_from_archives(tmp_path, "m1")

    assert history["99"] == [(MLB_LEGACY_METHOD_BREAK_DATE, 70.0), (day_after, 71.0)]


def test_method_id_change_keeps_only_points_after_the_change(tmp_path):
    _write(tmp_path, "2026-12-01", [_row(60.0), _row(40.0, mlbam_id=7)], "m1")
    _write(tmp_path, "2026-12-02", [_row(61.0), _row(41.0, mlbam_id=7)], "m1")
    _write(tmp_path, "2026-12-03", [_row(75.0)], "m2")
    _write(tmp_path, "2026-12-04", [_row(76.0)], "m2")

    history = _mlb_value_history_from_archives(tmp_path, "m2")

    assert history["99"] == [("2026-12-03", 75.0), ("2026-12-04", 76.0)]
    # A player who only appears before the change has no line left.
    assert "7" not in history


def test_a_later_change_wipes_earlier_compatible_points(tmp_path):
    # An unstamped file is compatible with anything, but it sits before a known change.
    _write(tmp_path, "2026-11-19", [_row(60.0)])
    _write(tmp_path, "2026-12-01", [_row(61.0)], "m1")
    _write(tmp_path, "2026-12-02", [_row(75.0)], "m2")

    assert _mlb_value_history_from_archives(tmp_path, "m2")["99"] == [("2026-12-02", 75.0)]


def test_switching_away_and_back_keeps_only_the_latest_run(tmp_path):
    _write(tmp_path, "2026-12-01", [_row(60.0)], "a")
    _write(tmp_path, "2026-12-02", [_row(61.0)], "a")
    _write(tmp_path, "2026-12-03", [_row(40.0)], "b")
    _write(tmp_path, "2026-12-04", [_row(62.0)], "a")

    assert _mlb_value_history_from_archives(tmp_path, "a")["99"] == [("2026-12-04", 62.0)]


def test_first_rebuild_after_deploy_starts_at_the_legacy_date(tmp_path):
    # Unstamped files on both sides of the 2027 flip, then the first stamped file.
    _write(tmp_path, "2026-11-16", [_row(74.0)])
    _write(tmp_path, "2026-11-17", [_row(74.5)])
    _write(tmp_path, "2026-11-18", [_row(71.5)])
    _write(tmp_path, "2026-11-19", [_row(71.6)])
    _write(tmp_path, "2026-11-20", [_row(71.4)], "m1")

    assert _mlb_value_history_from_archives(tmp_path, "m1")["99"] == [
        ("2026-11-18", 71.5),
        ("2026-11-19", 71.6),
        ("2026-11-20", 71.4),
    ]


def test_method_id_ignores_layer_version_and_value_source(monkeypatch):
    before = dynasty.value_method_id("preseason", "k")
    monkeypatch.setattr(dynasty, "LAYER_VERSION", "9.9.9")
    monkeypatch.setattr(dynasty, "VALUE_SOURCE", "another_label")

    assert dynasty.value_method_id("preseason", "k") == before


def test_two_way_label_change_does_not_break_the_line(tmp_path):
    # Ohtani case: two rows share an mlbam_id and the row labels change between dates
    # while the method ID stays the same. Every point stays, combined as stronger + 0.65 x other.
    _write(
        tmp_path,
        "2026-12-01",
        [
            _row(50.0, mlbam_id=660271, value_source="valucast_mlb_dynasty_horizon_v0_5"),
            _row(20.0, mlbam_id=660271, value_source="valucast_mlb_dynasty_horizon_v0_5"),
        ],
        "m1",
    )
    _write(
        tmp_path,
        "2026-12-02",
        [
            _row(52.0, mlbam_id=660271, value_source="valucast_mlb_two_way_hitter_v0_2"),
            _row(22.0, mlbam_id=660271, value_source="valucast_mlb_two_way_pitcher_v0_2"),
        ],
        "m1",
    )

    history = _mlb_value_history_from_archives(tmp_path, "m1")

    assert history["660271"] == [
        ("2026-12-01", round(50.0 + TWO_WAY_SECONDARY_VALUE_WEIGHT * 20.0, 2)),
        ("2026-12-02", round(52.0 + TWO_WAY_SECONDARY_VALUE_WEIGHT * 22.0, 2)),
    ]


def test_unstamped_file_before_the_legacy_date_is_the_old_method(tmp_path):
    _write(tmp_path, "2026-11-16", [_row(50.0)])
    _write(tmp_path, "2026-11-17", [_row(51.0)])
    _write(tmp_path, MLB_LEGACY_METHOD_BREAK_DATE, [_row(70.0)])

    cut = _mlb_value_history_from_archives(tmp_path, "m1")
    uncut = _mlb_value_history_from_archives(tmp_path, None)

    assert cut["99"] == [(MLB_LEGACY_METHOD_BREAK_DATE, 70.0)]
    assert uncut["99"] == [
        ("2026-11-16", 50.0),
        ("2026-11-17", 51.0),
        (MLB_LEGACY_METHOD_BREAK_DATE, 70.0),
    ]


def test_unknown_current_method_id_never_cuts_stamped_files(tmp_path):
    _write(tmp_path, "2026-12-01", [_row(60.0)], "m1")
    _write(tmp_path, "2026-12-02", [_row(61.0)], "m2")

    history = _mlb_value_history_from_archives(tmp_path, None)

    assert history["99"] == [("2026-12-01", 60.0), ("2026-12-02", 61.0)]


def test_value_method_id_differs_by_phase():
    assert value_method_id("preseason", "k") != value_method_id("in_season", "k")
    assert value_method_id("preseason", "k") != value_method_id("preseason", "other")
    assert value_method_id("preseason", "k").startswith("mlb-5x5-r")


def test_archive_layer_writes_method_id_and_tolerates_its_absence(tmp_path):
    payload = {
        "layer_version": "0.0.0",
        "method_id": value_method_id("preseason", "k"),
        "generated_at": "2026-12-01T12:00:00+00:00",
        "validation": {},
        "players": [_row(80.0)],
    }

    path, written = archive_layer(payload, "2026-12-01", archive_dir=tmp_path)
    assert written is True
    assert json.loads(path.read_text(encoding="utf-8"))["method_id"] == payload["method_id"]

    del payload["method_id"]
    path, written = archive_layer(payload, "2026-12-02", archive_dir=tmp_path)
    assert written is True
    assert json.loads(path.read_text(encoding="utf-8"))["method_id"] is None
