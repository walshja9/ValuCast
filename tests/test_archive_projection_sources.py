"""Tests for the weekly per-source ROS projection archive (Phase 3)."""
import json
import os
import time
from pathlib import Path

import pytest

from scripts.archive_projection_sources import (
    CADENCE_DAYS,
    _due,
    _thin_rows,
    build_archive_payload,
    run_archive,
)


def _fg_hitter(pid, mlbam, pa=500):
    return {
        "playerids": pid,
        "PlayerName": f"Hitter {pid}",
        "xMLBAMID": mlbam,
        "minpos": "SS",
        "Team": "NYM",
        "PA": pa,
        "AB": pa * 0.9,
        "HR": 20,
        "AVG": 0.270,
        "OPS": 0.800,
    }


def _fg_pitcher(pid, mlbam, ip=150):
    return {
        "playerids": pid,
        "PlayerName": f"Pitcher {pid}",
        "xMLBAMID": mlbam,
        "Team": "NYM",
        "IP": ip,
        "GS": 25,
        "SO": 160,
        "ERA": 3.50,
        "WHIP": 1.20,
    }


def _hp_row(mlbam, pool="hitter", volume=400.0):
    volume_key = "PA" if pool == "hitter" else "IP"
    return {
        "id": f"fg{mlbam}",
        "name": f"Player {mlbam}",
        "pool": pool,
        "stats": {volume_key: volume, "HR" if pool == "hitter" else "SO": 15.0},
        "metadata": {"mlbam_id": str(mlbam)},
    }


def _write_fixture_repo(tmp_path, as_of="2026-07-14", stale_raw=False):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for name, rows in (
        ("steamer_hitters", [_fg_hitter(f"s{i}", 600000 + i) for i in range(4)]),
        ("steamer_pitchers", [_fg_pitcher(f"sp{i}", 610000 + i) for i in range(4)]),
        ("zips_hitters", [_fg_hitter(f"s{i}", 600000 + i) for i in range(2)]),
        ("zips_pitchers", [_fg_pitcher(f"sp{i}", 610000 + i) for i in range(2)]),
    ):
        path = raw_dir / f"{name}.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        if stale_raw:
            old = time.time() - 5 * 86400
            os.utime(path, (old, old))
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({"as_of": as_of, "season": 2026}), encoding="utf-8")
    hp_path = tmp_path / "projections.json"
    hp_rows = [_hp_row(700000 + i) for i in range(4)] + [
        _hp_row(710000 + i, pool="starter", volume=100.0) for i in range(4)
    ]
    hp_path.write_text(json.dumps(hp_rows), encoding="utf-8")
    return raw_dir, metadata_path, hp_path


def _today_utc():
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def test_thin_rows_drops_and_counts_unjoinable_and_zero_volume():
    rows = [
        _hp_row(1),
        {"name": "No Id", "pool": "hitter", "stats": {"PA": 500}, "metadata": {}},
        _hp_row(2, volume=0.0),
    ]
    result = _thin_rows(rows)
    assert [r["mlbam_id"] for r in result["rows"]] == ["1"]
    assert result["dropped_no_mlbam"] == 1
    assert result["dropped_zero_volume"] == 1
    # whitelist only, rounded floats
    assert set(result["rows"][0]["stats"]) <= {"PA", "AB", "H", "HR", "R", "RBI", "SB", "BB", "SO", "AVG", "OBP", "SLG", "OPS"}


def test_build_payload_refuses_truncated_required_source():
    with pytest.raises(RuntimeError, match="truncated vintage"):
        build_archive_payload(
            as_of="2026-07-14",
            season=2026,
            valucast_rows=[_hp_row(1)],
            steamer_rows=[_hp_row(2)],
            zips_rows=[],
            min_rows=3,
        )


def test_zips_may_be_small_but_is_disclosed():
    payload = build_archive_payload(
        as_of="2026-07-14",
        season=2026,
        valucast_rows=[_hp_row(i) for i in range(3)],
        steamer_rows=[_hp_row(10 + i) for i in range(3)],
        zips_rows=[],
        min_rows=3,
    )
    assert payload["sources"]["zips"]["row_count"] == 0


def test_due_respects_weekly_cadence(tmp_path):
    archive_dir = tmp_path / "arch"
    assert _due(archive_dir, "2026-07-14") is True
    archive_dir.mkdir()
    (archive_dir / "2026-07-10.json").write_text("{}", encoding="utf-8")
    assert _due(archive_dir, "2026-07-14") is False
    assert _due(archive_dir, "2026-07-17") is True
    assert CADENCE_DAYS == 7


def test_run_archive_writes_dated_snapshot_with_all_three_sources(tmp_path):
    as_of = _today_utc()
    raw_dir, metadata_path, hp_path = _write_fixture_repo(tmp_path, as_of=as_of)
    archive_dir = tmp_path / "arch"
    result = run_archive(
        archive_dir=archive_dir,
        raw_dir=raw_dir,
        metadata_path=metadata_path,
        hp_run_path=hp_path,
        min_rows=3,
    )
    assert result["changed"] is True
    payload = json.loads((archive_dir / f"{as_of}.json").read_text(encoding="utf-8"))
    assert set(payload["sources"]) == {"valucast_hp", "steamer", "zips"}
    assert payload["join_key"] == "mlbam_id"
    assert payload["sources"]["steamer"]["row_count"] == 8
    assert payload["sources"]["zips"]["row_count"] == 4
    # rerun inside the cadence window is a no-op skip
    again = run_archive(
        archive_dir=archive_dir,
        raw_dir=raw_dir,
        metadata_path=metadata_path,
        hp_run_path=hp_path,
        min_rows=3,
    )
    assert again.get("changed") is False or again.get("skipped") is True


def test_run_archive_refuses_stale_raw_pulls_as_fresh_vintage(tmp_path):
    as_of = _today_utc()
    raw_dir, metadata_path, hp_path = _write_fixture_repo(tmp_path, as_of=as_of, stale_raw=True)
    with pytest.raises(RuntimeError, match="stale pull under a fresh vintage"):
        run_archive(
            archive_dir=tmp_path / "arch",
            raw_dir=raw_dir,
            metadata_path=metadata_path,
            hp_run_path=hp_path,
            min_rows=3,
        )
