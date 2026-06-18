"""Tests for the DD-independence ratchet (residual factual-fallback counts may only shrink)."""
import json

from scripts.validate_dd_independence_ratchet import validate_ratchet


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _rank(counts=None):
    validation = {"ranked_count": 10}
    if counts is not None:
        validation["dd_factual_fallback"] = counts
    return {"generated_at": "2026-06-17", "validation": validation}


def test_dormant_when_field_absent(tmp_path):
    rank = tmp_path / "rank.json"
    baseline = tmp_path / "baseline.json"
    _write(rank, _rank(counts=None))

    problems, info = validate_ratchet(rank, baseline)
    assert problems == []
    assert info["status"] == "dormant"
    assert not baseline.exists()


def test_seeds_baseline_on_first_emit(tmp_path):
    rank = tmp_path / "rank.json"
    baseline = tmp_path / "baseline.json"
    _write(rank, _rank({"mlb_stat_line_from_dd_feed": 12, "translated_dd_feed_fallback": 30}))

    problems, info = validate_ratchet(rank, baseline)
    assert problems == []
    assert info["status"] == "seeded"
    seeded = json.loads(baseline.read_text(encoding="utf-8"))
    assert seeded["max_mlb_stat_line_from_dd_feed"] == 12
    assert seeded["max_translated_dd_feed_fallback"] == 30


def test_passes_when_counts_at_or_below_ceiling(tmp_path):
    rank = tmp_path / "rank.json"
    baseline = tmp_path / "baseline.json"
    _write(rank, _rank({"mlb_stat_line_from_dd_feed": 5, "translated_dd_feed_fallback": 20}))
    _write(baseline, {"max_mlb_stat_line_from_dd_feed": 12, "max_translated_dd_feed_fallback": 30})

    problems, info = validate_ratchet(rank, baseline)
    assert problems == []
    assert info["status"] == "enforced"


def test_fails_when_a_count_exceeds_ceiling(tmp_path):
    rank = tmp_path / "rank.json"
    baseline = tmp_path / "baseline.json"
    _write(rank, _rank({"mlb_stat_line_from_dd_feed": 13, "translated_dd_feed_fallback": 30}))
    _write(baseline, {"max_mlb_stat_line_from_dd_feed": 12, "max_translated_dd_feed_fallback": 30})

    problems, info = validate_ratchet(rank, baseline)
    assert any("mlb_stat_line_from_dd_feed=13 exceeds baseline ceiling 12" in p for p in problems)
