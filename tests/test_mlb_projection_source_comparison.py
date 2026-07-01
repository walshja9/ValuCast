"""Tests for the advisory MLB projection-source comparison (Marcel/H+P vs Steamer/ROS)."""
from mlb.projection_source_comparison import (
    MIN_SAMPLE,
    build_comparison,
    build_counting_stat_comparison,
    build_freeze,
    build_what_would_change,
    prorate_counting_projection,
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


def _counting_hitter(mlbam, hr, rbi, runs, sb, pa=120.0):
    return {
        "metadata": {"mlbam_id": str(mlbam)},
        "pool": "hitter",
        "stats": {"HR": hr, "RBI": rbi, "R": runs, "SB": sb, "PA": pa},
    }


def _counting_pitcher(mlbam, er, bb, hits, k, w, sv, hld, ip=40.0):
    return {
        "metadata": {"mlbam_id": str(mlbam)},
        "pool": "starter",
        "stats": {
            "ER": er, "BB": bb, "H_ALLOWED": hits, "K": k,
            "W": w, "SV": sv, "HLD": hld, "IP": ip,
        },
    }


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


def test_prorate_counting_projection_uses_elapsed_over_remaining_days():
    assert prorate_counting_projection(20, 10, 20) == 10.0
    assert prorate_counting_projection(20, 0, 20) == 0.0
    assert prorate_counting_projection(20, 20, 0) == 20.0


def test_counting_stat_comparison_scores_forward_deltas_with_proration():
    as_of_actuals = [_counting_hitter(101, hr=10, rbi=30, runs=40, sb=5, pa=200)]
    current_actuals = [_counting_hitter(101, hr=12, rbi=35, runs=43, sb=6, pa=260)]
    # With season_end 2026-07-08, the 6/18 -> 6/28 window is half the remaining season.
    hp_rows = [_counting_hitter(101, hr=20, rbi=50, runs=30, sb=10)]
    steamer_rows = [_counting_hitter(101, hr=10, rbi=20, runs=14, sb=4)]

    result = build_counting_stat_comparison(
        valucast_hp_rows=hp_rows,
        steamer_ros_rows=steamer_rows,
        as_of_actual_rows=as_of_actuals,
        current_actual_rows=current_actuals,
        as_of="2026-06-18",
        through="2026-06-28",
        season_end="2026-07-08",
    )

    assert result["status"] == "scored"
    assert result["window"]["proration_factor"] == 0.5
    assert result["scoreable_players"] == 1
    assert result["actual_counting_deltas"]["101"]["counts"] == {
        "HR": 2.0, "RBI": 5.0, "R": 3.0, "SB": 1.0,
    }
    assert result["scores"]["marcel_mae"]["HR"] == 8.0
    assert result["scores"]["steamer_mae"]["HR"] == 3.0
    assert result["scores"]["per_stat_ratio"]["HR"] == 2.6667


def test_counting_stat_comparison_scores_pitching_counts():
    as_of_actuals = [_counting_pitcher(202, er=8, bb=5, hits=15, k=30, w=2, sv=0, hld=3, ip=20)]
    current_actuals = [_counting_pitcher(202, er=15, bb=12, hits=25, k=55, w=3, sv=1, hld=5, ip=45)]
    hp_rows = [_counting_pitcher(202, er=20, bb=20, hits=30, k=60, w=4, sv=2, hld=8)]
    steamer_rows = [_counting_pitcher(202, er=14, bb=12, hits=20, k=40, w=2, sv=2, hld=4)]

    result = build_counting_stat_comparison(
        valucast_hp_rows=hp_rows,
        steamer_ros_rows=steamer_rows,
        as_of_actual_rows=as_of_actuals,
        current_actual_rows=current_actuals,
        as_of="2026-06-18",
        through="2026-06-28",
        season_end="2026-07-08",
    )

    assert result["status"] == "scored"
    assert result["actual_counting_deltas"]["202"]["counts"]["K"] == 25.0
    assert result["scores"]["marcel_mae"]["K"] == 5.0
    assert result["scores"]["steamer_mae"]["K"] == 5.0
    assert result["scores"]["per_stat_ratio"]["K"] == 1.0


def test_resolve_source_env_default_off(monkeypatch):
    monkeypatch.delenv("VALUCAST_MLB_LIVE_PROJECTION_SOURCE", raising=False)
    assert _resolve_source(None) == "current"               # default off
    monkeypatch.setenv("VALUCAST_MLB_LIVE_PROJECTION_SOURCE", "valucast-hp")
    assert _resolve_source(None) == "valucast-hp"            # manual flip
    assert _resolve_source("current") == "current"          # explicit arg wins (shadow step)
    monkeypatch.setenv("VALUCAST_MLB_LIVE_PROJECTION_SOURCE", "garbage")
    assert _resolve_source(None) == "current"               # invalid env falls back safe
