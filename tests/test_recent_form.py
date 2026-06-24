import pytest

from prospects.recent_form import compute_momentum


def test_hitter_heating_up_classification():
    season = {
        "plate_appearances": 220,
        "k_pct": 24.0,
        "bb_pct": 8.0,
        "iso": 0.150,
        "ops": 0.720,
    }
    recent = {
        "plate_appearances": 55,
        "k_pct": 18.0,
        "bb_pct": 12.0,
        "iso": 0.230,
        "ops": 0.910,
    }

    result = compute_momentum(season, recent, "hitter")

    assert result["momentum_label"] == "Heating Up"
    assert result["momentum_score"] == pytest.approx(1.347)


def test_pitcher_cooling_off_classification():
    season = {
        "innings_pitched": 65.0,
        "k_bb_pct": 22.0,
        "k_per_9": 11.0,
        "bb_per_9": 3.0,
        "era": 3.20,
    }
    recent = {
        "innings_pitched": 12.0,
        "k_bb_pct": 12.0,
        "k_per_9": 8.0,
        "bb_per_9": 5.0,
        "era": 5.60,
    }

    result = compute_momentum(season, recent, "pitcher")

    assert result["momentum_label"] == "Cooling Off"
    assert result["momentum_score"] == pytest.approx(-1.92)


def test_hitter_steady_classification():
    season = {
        "plate_appearances": 180,
        "k_pct": 22.0,
        "bb_pct": 9.0,
        "iso": 0.170,
        "ops": 0.780,
    }
    recent = {
        "plate_appearances": 45,
        "k_pct": 21.5,
        "bb_pct": 9.4,
        "iso": 0.175,
        "ops": 0.795,
    }

    result = compute_momentum(season, recent, "hitter")

    assert result["momentum_label"] == "Steady"
    assert result["momentum_score"] == pytest.approx(0.105)


def test_min_sample_guard_returns_none():
    season = {
        "plate_appearances": 180,
        "k_pct": 22.0,
        "bb_pct": 9.0,
        "iso": 0.170,
        "ops": 0.780,
    }
    recent = {
        "plate_appearances": 39,
        "k_pct": 12.0,
        "bb_pct": 14.0,
        "iso": 0.280,
        "ops": 1.010,
    }

    result = compute_momentum(season, recent, "hitter")

    assert result == {"momentum_score": None, "momentum_label": None}


def test_missing_rate_fields_are_skipped_and_renormalized():
    season = {
        "innings_pitched": 50.0,
        "k_bb_pct": 15.0,
        "k_per_9": None,
        "bb_per_9": 3.0,
        "era": None,
    }
    recent = {
        "innings_pitched": 11.0,
        "k_bb_pct": 20.0,
        "k_per_9": 10.5,
        "bb_per_9": 2.0,
        "era": 2.90,
    }

    result = compute_momentum(season, recent, "pitcher")

    assert result["momentum_label"] == "Heating Up"
    assert result["momentum_score"] == pytest.approx(1.0)
