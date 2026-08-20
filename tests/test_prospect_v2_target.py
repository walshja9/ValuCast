import pytest

from prospects.prospect_v2_target import (
    canonical_sha256,
    derive_four_year_outcome,
    derive_legacy_outcome,
)


def test_v2_target_is_any_season_fixed_horizon_with_star_precedence():
    hitter = [
        {"year": 2022, "pa": 460, "ops": 0.790},
        {"year": 2023, "pa": 451, "ops": 0.801},
        {"year": 2026, "pa": 700, "ops": 1.100},
    ]
    pitcher = [
        {"year": 2022, "ip": 121, "era": 3.74},
        {"year": 2026, "ip": 200, "era": 1.00},
    ]

    assert derive_four_year_outcome("hitter", 2021, hitter) == "star"
    assert derive_four_year_outcome("pitcher", 2021, pitcher) == "star"
    assert derive_four_year_outcome(
        "hitter", 2021, [{"year": 2022, "pa": 300, "ops": 0.700}]
    ) == "role"
    assert derive_four_year_outcome(
        "pitcher", 2021, [{"year": 2022, "ip": 50, "era": 9.00}]
    ) == "role"
    assert derive_four_year_outcome(
        "hitter", 2021, [{"year": 2022, "pa": 299, "ops": 1.000}]
    ) == "bust"
    assert derive_four_year_outcome(
        "pitcher", 2021, [{"year": 2022, "ip": 49.2, "era": 0.00}]
    ) == "bust"


def test_legacy_target_matches_documented_unbounded_peak_rules():
    assert derive_legacy_outcome(
        "hitter", [{"year": 2030, "pa": 150, "ops": 0.500}]
    ) == "role"
    assert derive_legacy_outcome(
        "pitcher", [{"year": 2030, "ip": 50, "era": 9.00}]
    ) == "role"


def test_target_validation_fails_closed():
    with pytest.raises(ValueError, match="unsupported role"):
        derive_four_year_outcome("catcher", 2021, [])
    with pytest.raises(ValueError, match="pa must be finite"):
        derive_four_year_outcome(
            "hitter", 2021, [{"year": 2022, "pa": float("nan"), "ops": 1.0}]
        )


def test_canonical_hash_is_key_order_independent():
    assert canonical_sha256({"a": 1, "b": 2}) == canonical_sha256({"b": 2, "a": 1})
