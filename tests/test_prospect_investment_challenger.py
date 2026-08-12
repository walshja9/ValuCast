"""Contract tests for the fixed pitcher investment-feature challenger."""
from __future__ import annotations

import pytest


def test_investment_feature_names_drop_only_raw_pick_value():
    from prospects.investment_challenger import investment_feature_names

    incumbent = investment_feature_names("pitcher", "incumbent")
    candidate = investment_feature_names("pitcher", "drop_raw_pick_value")

    assert "pick_value" in incumbent
    assert "pick_value" not in candidate
    assert candidate == tuple(name for name in incumbent if name != "pick_value")
    assert investment_feature_names("hitter", "incumbent") == ()
    assert investment_feature_names("hitter", "drop_raw_pick_value") == ()


def test_investment_feature_vector_drops_only_pick_value_without_mutating_inputs():
    from prospects.investment_challenger import investment_feature_vector

    names = (
        "rule4_drafted",
        "draft_record_known",
        "pick_value",
        "inverse_draft_pick",
        "inverse_draft_round",
        "log_signing_bonus",
        "college_drafted",
        "prep_drafted",
    )
    values = [1.0, 1.0, 8_415_300.0, 0.1, 1.0, 15.9, 1.0, 0.0]
    original_names = tuple(names)
    original_values = list(values)

    incumbent = investment_feature_vector(names, values, "incumbent")
    candidate = investment_feature_vector(names, values, "drop_raw_pick_value")

    assert incumbent == values
    assert candidate == [value for name, value in zip(names, values) if name != "pick_value"]
    assert names == original_names
    assert values == original_values


@pytest.mark.parametrize("mode", ["", "drop_all_pedigree", None])
def test_investment_feature_contract_rejects_unknown_modes(mode):
    from prospects.investment_challenger import (
        investment_feature_names,
        investment_feature_vector,
    )

    with pytest.raises(ValueError, match="investment feature mode"):
        investment_feature_names("pitcher", mode)
    with pytest.raises(ValueError, match="investment feature mode"):
        investment_feature_vector(("pick_value",), [1.0], mode)


def test_investment_feature_vector_rejects_misaligned_names_and_values():
    from prospects.investment_challenger import investment_feature_vector

    with pytest.raises(ValueError, match="names and values"):
        investment_feature_vector(("pick_value",), [], "drop_raw_pick_value")
