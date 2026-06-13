"""Tests for the projection contract shared by prospect and MLB models."""
import pytest

from projections.league_adapter import (
    PROJECTION_CONTRACT_VERSION,
    engine_projection_row,
    projection_contract,
    projection_row,
    rank_projection_rows,
)


def test_shared_projection_contract_is_source_neutral_and_rankable():
    rows = [
        projection_row(
            player_id=1,
            role="hitter",
            projected_volume=600,
            categories={"HR": 30, "AVG": 0.280},
        ),
        projection_row(
            player_id=2,
            role="hitter",
            projected_volume=300,
            categories={"HR": 10, "AVG": 0.250},
        ),
    ]
    contract = projection_contract(
        rows,
        source_kind="prospect",
        source_model="Test model",
        source_model_version="1",
    )
    ranked = rank_projection_rows(rows, "hitter", {"HR": 1, "AVG": 1})

    assert contract["version"] == PROJECTION_CONTRACT_VERSION
    assert contract["source_kind"] == "prospect"
    assert ranked["status"] == "research_ranked"
    assert ranked["players"][0]["player_id"] == "1"


def test_shared_projection_contract_fails_closed_on_bad_or_partial_rows():
    with pytest.raises(ValueError, match="Projected volume"):
        projection_row(
            player_id=1,
            role="hitter",
            projected_volume=-1,
            categories={"HR": 1},
        )

    rows = [
        projection_row(
            player_id=1,
            role="pitcher",
            projected_volume=100,
            categories={"K": 100, "ERA": 3.50},
        ),
        projection_row(
            player_id=2,
            role="pitcher",
            projected_volume=100,
            categories={"K": 90},
        ),
    ]
    ranked = rank_projection_rows(rows, "pitcher", {"K": 1, "ERA": -1})
    assert ranked["status"] == "insufficient_category_coverage"
    assert ranked["missing_categories"] == ["ERA"]
    assert all("adapter_rank" not in player for player in ranked["players"])

    with pytest.raises(ValueError, match="Duplicate projection row"):
        rank_projection_rows([rows[0], rows[0]], "pitcher", {"K": 1})


def test_existing_mlb_projection_exports_can_enter_the_same_contract():
    row = engine_projection_row(
        {
            "id": "mlbam_5_H",
            "name": "MLB Hitter",
            "pool": "hitter",
            "stats": {"PA": 600, "HR": 30, "AVG": 0.280},
            "metadata": {
                "mlbam_id": "5",
                "source": "marcel",
                "model": "valucast_marcel",
                "model_version": 1,
            },
        }
    )
    assert row["player_id"] == "5"
    assert row["projected_volume"] == 600
    assert row["categories"] == {"AVG": 0.28, "HR": 30.0}
    assert row["source_model"] == "valucast_marcel"
