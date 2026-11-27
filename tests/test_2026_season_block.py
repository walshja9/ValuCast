"""Regression guards for the prospect card's 2026 SEASON per-level stats block."""
import pytest

import app


def test_index_milb_season_stats_groups_by_mlbam():
    payload = {
        "hitters": [
            {"mlbam_id": "111", "level": "AA", "plate_appearances": 200, "avg": 0.300},
            {"mlbam_id": "111", "level": "AAA", "plate_appearances": 80, "avg": 0.250},
            {"mlbam_id": "", "level": "AA"},          # empty id skipped
            {"mlbam_id": None, "level": "AA"},        # None id skipped
            "not-a-dict",                              # non-dict skipped
        ],
        "pitchers": [
            {"mlbam_id": "222", "level": "A+", "innings_pitched": 30.0, "era": 3.0},
        ],
    }
    indexed = app._index_milb_season_stats(payload)
    assert set(indexed) == {"111", "222"}
    assert len(indexed["111"]) == 2  # AA + AAA grouped
    assert {r["level"] for r in indexed["111"]} == {"AA", "AAA"}
    assert len(indexed["222"]) == 1
    assert app._index_milb_season_stats(None) == {}
    assert app._index_milb_season_stats({}) == {}


def test_prospect_card_renders_for_multilevel_and_no_stats_prospects():
    if not app.dd_store.is_available:
        pytest.skip("dd_store not available")
    prospects = [r for r in app.dd_store.get_all() if getattr(r, "is_prospect", False)]
    index = app.MILB_SEASON_STATS_BY_MLBAM

    multilevel = next(
        (r for r in prospects if len(index.get(str(getattr(r, "mlbam_id", "")), [])) >= 2),
        None,
    )
    if multilevel is not None:  # data-dependent; skip the assertion if none today
        png = app._prospect_player_card_png(multilevel)
        assert isinstance(png, (bytes, bytearray)) and png[:8] == b"\x89PNG\r\n\x1a\n"

    no_stats = next(
        (r for r in prospects
         if getattr(r, "mlbam_id", None) and str(r.mlbam_id) not in index),
        None,
    )
    if no_stats is not None:  # the guarded path: block omitted, must still render
        png = app._prospect_player_card_png(no_stats)
        assert isinstance(png, (bytes, bytearray)) and png[:8] == b"\x89PNG\r\n\x1a\n"
