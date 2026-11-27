"""Tests for the MiLB pitch/strike-count backfill (Wave A, strike-% program).

Invariants under test: additive-only (untouched bytes stay identical after the
added fields are stripped), no zero-filling of API-missing rows, checkpoint/resume
skips completed files, and each file's exact on-disk format is preserved.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import backfill_milb_pitch_counts as backfill


def _universe_bytes() -> bytes:
    # Mirrors the real universe file: single-line default json.dumps, no trailing NL.
    payload = {
        "candidate_count": 3,
        "rows": [
            {"mlbam_id": 111, "cohort_year": 2016, "sport_id": 14, "role": "pitcher",
             "level": "A", "innings_pitched": 50.0},
            {"mlbam_id": 222, "cohort_year": 2016, "sport_id": 14, "role": "pitcher",
             "level": "A", "innings_pitched": 40.0},
            {"mlbam_id": 333, "cohort_year": 2016, "sport_id": 14, "role": "hitter",
             "level": "A", "plate_appearances": 200},
        ],
    }
    return json.dumps(payload).encode("utf-8")


def _per_season_bytes(season: int) -> bytes:
    # Mirrors the real per-season files: indent=2, sort_keys, trailing NL, CRLF.
    payload = {
        "season": season,
        "fetched_date": f"{season}-06-28",
        "source": "mlb_statsapi_season_stats",
        "sport_levels": {"14": "A"},
        "hitters": [],
        "pitchers": [
            {"mlbam_id": 111, "sport_id": 14, "role": "pitcher", "level": "A",
             "innings_pitched": 50.0},
            {"mlbam_id": 999, "sport_id": 14, "role": "pitcher", "level": "A",
             "innings_pitched": 10.0},
        ],
    }
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return body.replace("\n", "\r\n").encode("utf-8")


def _fake_splits(season: int, sport_id: int) -> list[dict]:
    # 111 served with counts; 222 served but MISSING counts (must not be filled);
    # 999 not served at all (stays without fields).
    if (season, sport_id) == (2016, 14):
        return [
            {"player": {"id": 111}, "stat": {"numberOfPitches": 800, "strikes": 520}},
            {"player": {"id": 222}, "stat": {"battersFaced": 100}},  # no counts
        ]
    return []


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    universe = raw_dir / "valucast_universal_prospect_dataset.json"
    universe.write_bytes(_universe_bytes())
    per_season = raw_dir / "milb_season_stats_2016.json"
    per_season.write_bytes(_per_season_bytes(2016))
    ckpt = tmp_path / "ckpt.json"

    monkeypatch.setattr(backfill, "RAW_DIR", raw_dir)
    monkeypatch.setattr(backfill, "UNIVERSE_PATH", universe)
    monkeypatch.setattr(backfill, "_fetch_pitching_splits", _fake_splits)
    return {"universe": universe, "per_season": per_season, "ckpt": ckpt}


def test_backfill_adds_counts_only_to_served_rows(wired):
    backfill.run_backfill(checkpoint_path=wired["ckpt"], delay=0)

    uni = json.loads(wired["universe"].read_bytes())
    by_id = {r["mlbam_id"]: r for r in uni["rows"]}
    assert by_id[111]["pitches"] == 800
    assert by_id[111]["strikes"] == 520
    # 222 was served WITHOUT counts -> fields absent, never zero-filled.
    assert "pitches" not in by_id[222]
    assert "strikes" not in by_id[222]
    # hitter row untouched.
    assert "pitches" not in by_id[333]

    per = json.loads(wired["per_season"].read_bytes())
    ppitch = {r["mlbam_id"]: r for r in per["pitchers"]}
    assert ppitch[111]["pitches"] == 800 and ppitch[111]["strikes"] == 520
    # 999 not served at all -> fields absent.
    assert "pitches" not in ppitch[999]


def test_additive_only_strip_is_byte_identical(wired):
    before_uni = wired["universe"].read_bytes()
    before_per = wired["per_season"].read_bytes()

    backfill.run_backfill(checkpoint_path=wired["ckpt"], delay=0)

    # Strip the added keys and re-serialize with each file's exact format; must
    # reproduce the pre-backfill bytes exactly.
    uni = json.loads(wired["universe"].read_bytes())
    for row in uni["rows"]:
        row.pop("pitches", None)
        row.pop("strikes", None)
    assert backfill._serialize(uni, backfill._detect_format(before_uni)) == before_uni

    per = json.loads(wired["per_season"].read_bytes())
    for row in per["pitchers"]:
        row.pop("pitches", None)
        row.pop("strikes", None)
    assert backfill._serialize(per, backfill._detect_format(before_per)) == before_per


def test_format_preserved_crlf_and_single_line(wired):
    backfill.run_backfill(checkpoint_path=wired["ckpt"], delay=0)
    uni = wired["universe"].read_bytes()
    per = wired["per_season"].read_bytes()
    # Universe: single line, no newline at all.
    assert b"\n" not in uni
    # Per-season: CRLF, trailing newline, indented.
    assert b"\r\n" in per
    assert per.endswith(b"\r\n")


def test_checkpoint_resume_skips_completed_file(wired, monkeypatch):
    backfill.run_backfill(checkpoint_path=wired["ckpt"], delay=0)
    completed = json.loads(wired["ckpt"].read_text(encoding="utf-8"))["completed_files"]
    assert str(wired["universe"]) in completed
    assert str(wired["per_season"]) in completed

    # On resume the API must not be called again; a poisoned fetch proves the skip.
    def _poison(season, sport_id):  # pragma: no cover - must never run
        raise AssertionError("fetch called for an already-completed file")

    monkeypatch.setattr(backfill, "_fetch_pitching_splits", _poison)
    result = backfill.run_backfill(checkpoint_path=wired["ckpt"], delay=0)
    assert result["results"] == []


def test_partial_run_resumes_after_first_file(wired, monkeypatch):
    # Simulate an interruption: universe done, per-season not yet in checkpoint.
    backfill._save_checkpoint(wired["ckpt"], {str(wired["universe"])})
    result = backfill.run_backfill(checkpoint_path=wired["ckpt"], delay=0)
    processed = [Path(r["path"]).name for r in result["results"]]
    assert processed == ["milb_season_stats_2016.json"]
    per = json.loads(wired["per_season"].read_bytes())
    ppitch = {r["mlbam_id"]: r for r in per["pitchers"]}
    assert ppitch[111]["pitches"] == 800


def test_coverage_counts_match(wired):
    result = backfill.run_backfill(checkpoint_path=wired["ckpt"], delay=0)
    uni_result = next(r for r in result["results"] if "universal" in r["path"])
    # 2 pitcher rows total in 2016; only 111 got counts.
    assert uni_result["coverage"][2016] == {"with_counts": 1, "total": 2}
