"""Cross-role calibration: pitcher-tier anchor applied; hitters untouched."""
import json
import pathlib

from mlb.dynasty import CROSS_ROLE_CALIBRATION_VERSION, PITCHER_PRODUCTION_ANCHOR

ARTIFACT = pathlib.Path("data/models/valucast_mlb_dynasty_layer.json")


def _players():
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))["players"]


def test_pitcher_anchor_applied_and_recorded():
    pitchers = [p for p in _players() if p["role"] == "pitcher"]
    assert pitchers
    for p in pitchers[:60]:
        cal = p["components"]["cross_role_calibration"]
        assert cal["version"] == CROSS_ROLE_CALIBRATION_VERSION
        assert cal["anchor"] == PITCHER_PRODUCTION_ANCHOR
        # production_score == pre_anchor * anchor (within rounding)
        expected = round(cal["pre_anchor_production_score"] * cal["anchor"], 2)
        assert abs(p["components"]["production_score"] - expected) <= 0.05


def test_hitter_values_are_never_anchored():
    hitters = [p for p in _players() if p["role"] == "hitter"]
    assert hitters
    for h in hitters[:60]:
        cal = h["components"]["cross_role_calibration"]
        assert cal["anchor"] == 1.0
        # anchor 1.0 means production score is its own pre-anchor value
        assert h["components"]["production_score"] == cal["pre_anchor_production_score"]
