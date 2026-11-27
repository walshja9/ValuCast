"""Aggregation-math tests for scripts/build_prospect_rank_history.py (offline)."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.build_prospect_rank_history as b


def _row(mlbam, rank, name=None):
    return {"mlbam_id": mlbam, "name": name or f"P{mlbam}", "rank_v1_rank": rank}


def _make(by_date):
    """Write an archive under a fresh temp dir and return its path."""
    return _make_at(Path(tempfile.mkdtemp()), by_date)


def _make_at(tmp_path, by_date):
    d = tmp_path / "archive"
    d.mkdir()
    for date, rows in by_date.items():
        (d / f"{date}.json").write_text(
            json.dumps({"date": date, "projections": rows}), encoding="utf-8"
        )
    return d


# --- absent-date omission --------------------------------------------------
def test_absent_date_is_omitted_never_fabricated():
    # Player 1 is ranked on day 1 and day 3 but simply not present on day 2.
    archive = _make(
        {
            "2026-06-15": [_row(1, 10)],
            "2026-06-16": [_row(2, 20)],           # player 1 absent this day
            "2026-06-17": [_row(1, 12), _row(2, 22)],
        }
    )
    payload = b.build_history(archive)
    series = payload["players"]["1"]["series"]
    assert series == [["2026-06-15", 10], ["2026-06-17", 12]]  # 06-16 omitted


# --- null-rank omission ----------------------------------------------------
def test_null_rank_is_omitted():
    archive = _make(
        {
            "2026-06-15": [_row(1, 10)],
            "2026-06-16": [_row(1, None)],  # null rank -> not recorded
            "2026-06-17": [_row(1, 11)],
        }
    )
    payload = b.build_history(archive)
    series = payload["players"]["1"]["series"]
    assert series == [["2026-06-15", 10], ["2026-06-17", 11]]


# --- top-N filter excludes never-ranked players ----------------------------
def test_top_n_filter_excludes_never_ranked_players():
    # Player 2 never cracks the top-N (rank always > TOP_N) -> excluded entirely.
    archive = _make(
        {
            "2026-06-15": [_row(1, 5), _row(2, b.TOP_N + 1)],
            "2026-06-16": [_row(1, 6), _row(2, b.TOP_N + 500)],
        }
    )
    payload = b.build_history(archive)
    assert "1" in payload["players"]
    assert "2" not in payload["players"]
    assert payload["player_count"] == 1


def test_top_n_boundary_is_inclusive():
    # Exactly TOP_N is included; TOP_N + 1 is not.
    archive = _make({"2026-06-15": [_row(1, b.TOP_N), _row(2, b.TOP_N + 1)]})
    payload = b.build_history(archive)
    assert "1" in payload["players"]
    assert "2" not in payload["players"]


def test_player_ranked_once_is_kept_with_all_ranked_points():
    # A player who cracks top-N on ONE day is tracked; a later out-of-band day for
    # that same player is dropped from the series (never fabricated as top-N).
    archive = _make(
        {
            "2026-06-15": [_row(1, 50)],
            "2026-06-16": [_row(1, b.TOP_N + 10)],  # dropped: out of band
        }
    )
    payload = b.build_history(archive)
    assert payload["players"]["1"]["series"] == [["2026-06-15", 50]]


# --- best_rank + best_rank_date earliest-tie semantics ---------------------
def test_best_rank_and_earliest_tie_date():
    # Best rank 3 achieved on two dates; best_rank_date is the EARLIEST.
    archive = _make(
        {
            "2026-06-15": [_row(1, 8)],
            "2026-06-16": [_row(1, 3)],   # first time at best
            "2026-06-17": [_row(1, 5)],
            "2026-06-18": [_row(1, 3)],   # ties best, but later
        }
    )
    payload = b.build_history(archive)
    p = payload["players"]["1"]
    assert p["best_rank"] == 3
    assert p["best_rank_date"] == "2026-06-16"  # earliest achiever, not 06-18
    assert p["latest_rank"] == 3
    assert p["latest_date"] == "2026-06-18"


def test_latest_reflects_last_archived_date():
    archive = _make(
        {
            "2026-06-15": [_row(1, 1)],
            "2026-06-16": [_row(1, 4)],
            "2026-06-17": [_row(1, 7)],
        }
    )
    p = b.build_history(archive)["players"]["1"]
    assert p["latest_rank"] == 7
    assert p["latest_date"] == "2026-06-17"
    assert p["best_rank"] == 1 and p["best_rank_date"] == "2026-06-15"


# --- duplicate mlbam in one file raises ------------------------------------
def test_duplicate_mlbam_among_top_n_rows_raises():
    archive = _make(
        {"2026-06-15": [_row(1, 10), _row(1, 12)]}  # same mlbam, both in-universe
    )
    with pytest.raises(ValueError, match="duplicate mlbam_id"):
        b.build_history(archive)


def test_duplicate_mlbam_outside_top_n_does_not_raise():
    # The real archive carries genuine same-mlbam depth-arm duplicates far outside the
    # top-N (e.g. split A/A+ rows, rank ~2400). Those never enter our universe and must
    # NOT crash the daily build.
    archive = _make(
        {
            "2026-06-15": [
                _row(1, 10),
                _row(9, b.TOP_N + 100),
                _row(9, b.TOP_N + 400),  # duplicate, but both out of band
            ]
        }
    )
    payload = b.build_history(archive)  # no raise
    assert "9" not in payload["players"]
    assert payload["players"]["1"]["series"] == [["2026-06-15", 10]]


# --- name / envelope / validation ------------------------------------------
def test_latest_nonempty_name_is_kept():
    archive = _make(
        {
            "2026-06-15": [_row(1, 10, name="Old Name")],
            "2026-06-16": [_row(1, 11, name="")],       # empty -> keep prior
            "2026-06-17": [_row(1, 12, name="New Name")],
        }
    )
    assert b.build_history(archive)["players"]["1"]["name"] == "New Name"


def test_envelope_and_validation_house_style():
    archive = _make(
        {
            "2026-06-15": [_row(1, 3)],
            "2026-06-16": [_row(1, 4)],
        }
    )
    payload = b.build_history(archive)
    assert payload["artifact"] == "valucast_prospect_rank_history"
    assert payload["archive_dates"] == ["2026-06-15", "2026-06-16"]
    assert payload["player_count"] == 1
    sp = payload["source_policy"]
    assert sp["display_only"] is True
    assert sp["feeds_model_score"] is False
    assert sp["feeds_public_rank"] is False
    assert sp["feeds_buy_score"] is False
    v = payload["validation"]
    assert v["blockers"] == []
    assert v["ready_for_rank_history"] is True
    assert v["archive_date_count"] == 2
    assert v["player_count"] == 1


def test_series_is_date_ascending_regardless_of_dir_iteration():
    # Files written out of order still produce an ascending series (dates are sorted).
    archive = _make(
        {
            "2026-06-17": [_row(1, 7)],
            "2026-06-15": [_row(1, 5)],
            "2026-06-16": [_row(1, 6)],
        }
    )
    series = b.build_history(archive)["players"]["1"]["series"]
    assert series == [["2026-06-15", 5], ["2026-06-16", 6], ["2026-06-17", 7]]


def test_write_artifact_roundtrips(tmp_path):
    archive = _make_at(tmp_path, {"2026-06-15": [_row(1, 3)], "2026-06-16": [_row(1, 4)]})
    out = tmp_path / "rank_history.json"
    payload = b.build_history(archive)
    b.write_artifact(payload, out)
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["players"]["1"]["best_rank"] == 3


def test_main_no_op_on_missing_archive(tmp_path, capsys):
    missing = tmp_path / "nope"
    out = tmp_path / "out.json"
    rc = b.main(["--archive-dir", str(missing), "--out", str(out)])
    assert rc == 0
    assert not out.exists()
    assert "archive dir absent" in capsys.readouterr().out
