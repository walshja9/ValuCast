"""Tests for the advisory MLB projection-source comparison (Marcel/H+P vs Steamer/ROS)."""
from mlb.projection_source_comparison import (
    MIN_SAMPLE,
    build_comparison,
    build_freeze,
    build_what_would_change,
    validate_comparison,
    _actual_lines,
    _scoreable,
)
from scripts.build_mlb_dynasty_layer import _resolve_source


def _hitter(mlbam, avg, obp, slg, ops, pa=120.0):
    return {
        "metadata": {"mlbam_id": str(mlbam)},
        "pool": "hitter",
        "stats": {"AVG": avg, "OBP": obp, "SLG": slg, "OPS": ops, "PA": pa},
    }


def _cohort(n, avg, obp, slg, ops, pa=120.0):
    return [_hitter(1000 + i, avg, obp, slg, ops, pa) for i in range(n)]


def test_build_freeze_captures_rate_lines_and_coverage():
    freeze = build_freeze(
        [_hitter(1, 0.300, 0.380, 0.500, 0.880)],
        [_hitter(1, 0.290, 0.370, 0.480, 0.850)],
        "2026-05-01T00:00:00+00:00",
    )
    assert freeze["date"] == "2026-05-01"
    hp = freeze["sources"]["valucast_hp"]
    assert hp["coverage"] == {"player_count": 1, "hitter_count": 1, "pitcher_count": 0}
    assert hp["rate_lines"]["1"]["rates"]["OPS"] == 0.880


def test_marcel_wins_with_enough_horizon_and_sample():
    # Marcel's frozen rates == actuals (MAE 0); Steamer is off → Marcel must win.
    actuals = _cohort(MIN_SAMPLE + 10, 0.300, 0.380, 0.500, 0.880)
    marcel = _cohort(MIN_SAMPLE + 10, 0.300, 0.380, 0.500, 0.880)
    steamer = _cohort(MIN_SAMPLE + 10, 0.250, 0.320, 0.420, 0.740)
    freeze = build_freeze(marcel, steamer, "2026-05-01T00:00:00+00:00")

    payload = build_comparison(
        frozen=freeze,
        actual_lines=_actual_lines(actuals),
        live_layer=None,
        shadow_layer=None,
        generated_at="2026-06-17T00:00:00+00:00",  # 47 days forward
        now="2026-06-17T00:00:00+00:00",
    )

    assert payload["comparison_basis"]["horizon_sufficient"] is True
    assert payload["comparison_basis"]["scoreable_players"] == MIN_SAMPLE + 10
    assert payload["gate"]["status"] == "active"
    assert payload["marcel_beats_steamer"] is True
    assert payload["scores"]["marcel_mean_ratio_vs_steamer"] == 0.0
    assert validate_comparison(payload) == []


def test_insufficient_when_horizon_too_short():
    actuals = _cohort(MIN_SAMPLE + 10, 0.300, 0.380, 0.500, 0.880)
    marcel = _cohort(MIN_SAMPLE + 10, 0.300, 0.380, 0.500, 0.880)
    steamer = _cohort(MIN_SAMPLE + 10, 0.250, 0.320, 0.420, 0.740)
    freeze = build_freeze(marcel, steamer, "2026-06-15T00:00:00+00:00")  # only 2 days old

    payload = build_comparison(
        frozen=freeze,
        actual_lines=_actual_lines(actuals),
        live_layer=None,
        shadow_layer=None,
        generated_at="2026-06-17T00:00:00+00:00",
        now="2026-06-17T00:00:00+00:00",
    )

    assert payload["comparison_basis"]["horizon_sufficient"] is False
    assert payload["gate"]["status"] == "insufficient_sample"
    assert payload["marcel_beats_steamer"] is False
    assert "horizon" in payload["gate"]["reason"]


def test_insufficient_when_sample_too_small():
    actuals = _cohort(5, 0.300, 0.380, 0.500, 0.880)
    marcel = _cohort(5, 0.300, 0.380, 0.500, 0.880)
    steamer = _cohort(5, 0.250, 0.320, 0.420, 0.740)
    freeze = build_freeze(marcel, steamer, "2026-05-01T00:00:00+00:00")

    payload = build_comparison(
        frozen=freeze,
        actual_lines=_actual_lines(actuals),
        live_layer=None,
        shadow_layer=None,
        generated_at="2026-06-17T00:00:00+00:00",
        now="2026-06-17T00:00:00+00:00",
    )

    assert payload["gate"]["status"] == "insufficient_sample"
    assert payload["marcel_beats_steamer"] is False


def test_thin_actual_volume_is_not_scoreable():
    # 100 players present in all three, but actual PA below the 50 floor → 0 scoreable.
    actuals = _cohort(100, 0.300, 0.380, 0.500, 0.880, pa=10.0)
    marcel = _cohort(100, 0.300, 0.380, 0.500, 0.880)
    steamer = _cohort(100, 0.250, 0.320, 0.420, 0.740)
    freeze = build_freeze(marcel, steamer, "2026-05-01T00:00:00+00:00")
    assert _scoreable(freeze, _actual_lines(actuals)) == []


def test_validator_rejects_win_without_evidence():
    actuals = _cohort(MIN_SAMPLE + 10, 0.300, 0.380, 0.500, 0.880)
    marcel = _cohort(MIN_SAMPLE + 10, 0.300, 0.380, 0.500, 0.880)
    steamer = _cohort(MIN_SAMPLE + 10, 0.250, 0.320, 0.420, 0.740)
    freeze = build_freeze(marcel, steamer, "2026-05-01T00:00:00+00:00")
    payload = build_comparison(
        frozen=freeze, actual_lines=_actual_lines(actuals), live_layer=None,
        shadow_layer=None, generated_at="2026-06-17T00:00:00+00:00", now="2026-06-17T00:00:00+00:00",
    )
    # Tamper: claim a win while marking the horizon insufficient → validator must catch it.
    payload["comparison_basis"]["horizon_sufficient"] = False
    assert "claimed a win before the forward horizon is sufficient" in validate_comparison(payload)

    payload["comparison_basis"]["horizon_sufficient"] = True
    payload["live_source_flip"]["automatic"] = True
    assert any("automatic must be False" in p for p in validate_comparison(payload))


def test_what_would_change_ranks_by_value_delta():
    live = {"players": [
        {"mlbam_id": "1", "role": "hitter", "name": "A", "value": 50.0},
        {"mlbam_id": "2", "role": "hitter", "name": "B", "value": 40.0},
    ]}
    shadow = {"players": [
        {"mlbam_id": "1", "role": "hitter", "name": "A", "value": 52.0},   # +2
        {"mlbam_id": "2", "role": "hitter", "name": "B", "value": 60.0},   # +20
    ]}
    changes = build_what_would_change(live, shadow, top_n=5)
    assert changes[0]["name"] == "B"
    assert changes[0]["value_delta"] == 20.0


def test_resolve_source_env_default_off(monkeypatch):
    monkeypatch.delenv("VALUCAST_MLB_LIVE_PROJECTION_SOURCE", raising=False)
    assert _resolve_source(None) == "current"               # default off
    monkeypatch.setenv("VALUCAST_MLB_LIVE_PROJECTION_SOURCE", "valucast-hp")
    assert _resolve_source(None) == "valucast-hp"            # manual flip
    assert _resolve_source("current") == "current"          # explicit arg wins (shadow step)
    monkeypatch.setenv("VALUCAST_MLB_LIVE_PROJECTION_SOURCE", "garbage")
    assert _resolve_source(None) == "current"               # invalid env falls back safe
