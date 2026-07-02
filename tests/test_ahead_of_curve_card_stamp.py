"""Ahead-of-the-Curve receipt context and prospect-card rendering."""
from __future__ import annotations

import app as app_module
from web.dynasty_models import DynastyRankingRow

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _prospect_row() -> DynastyRankingRow:
    record = {
        "id": "vc_prospect_999999_hitter",
        "player_type": "prospect",
        "name": "Receipt Prospect",
        "positions": ["SS"],
        "mlb_team": "SEA",
        "age": 19,
        "dynasty_rank": 12,
        "dynasty_value": 64.2,
        "status": "minors",
        "mlbam_id": "999999",
        "role": "hitter",
        "prospect_rank": 12,
        "level": "AA",
        "stat_line": {
            "pa": 220,
            "avg": 0.285,
            "obp": 0.370,
            "slg": 0.510,
            "ops": 0.880,
            "bb_pct": 12.0,
            "k_pct": 17.0,
            "iso": 0.225,
        },
        "context": {"role": "hitter"},
        "last_updated": "2026-06-25",
    }
    return DynastyRankingRow(
        id=record["id"],
        name=record["name"],
        player_type=record["player_type"],
        positions=tuple(record["positions"]),
        team=record["mlb_team"],
        age=record["age"],
        dynasty_rank=record["dynasty_rank"],
        dynasty_value=record["dynasty_value"],
        status=record["status"],
        mlbam_id=record["mlbam_id"],
        prospect_rank=record["prospect_rank"],
        level=record["level"],
        stat_line=record["stat_line"],
        metadata=record,
    )


def test_ahead_of_consensus_for_key_merges_showcase_receipt(monkeypatch):
    payload = {
        "divergence_by_identity": {
            "999999_hitter": {
                "valucast_rank": 20,
                "consensus_rank": 63,
                "board_count": 4,
                "divergence": 43,
            }
        },
        "ahead_of_consensus": [
            {
                "identity_key": "999999_hitter",
                "valucast_rank": 18,
                "consensus_rank": 61,
                "board_count": 5,
                "divergence": 43,
                "days_ahead": 27,
                "ahead_since": "2026-05-29",
                "boards": ["BA", "MLB"],
                "name": "Receipt Prospect",
            }
        ],
    }
    monkeypatch.setattr(app_module, "_load_artifact", lambda _path: payload)

    receipt = app_module._ahead_of_consensus_for_key("999999_hitter")

    assert receipt == {
        "valucast_rank": 18,
        "consensus_rank": 61,
        "divergence": 43,
        "board_count": 5,
        "days_ahead": 27,
        "ahead_since": "2026-05-29",
        "ahead_since_is_archive_start": None,
    }


def test_prospect_card_renders_with_synthetic_ahead_of_curve_receipt(monkeypatch):
    row = _prospect_row()
    row.metadata["context"]["ahead_of_consensus"] = {
        "valucast_rank": 18,
        "consensus_rank": 61,
        "divergence": 43,
        "board_count": 5,
        "days_ahead": 27,
        "ahead_since": "2026-05-29",
    }
    monkeypatch.setattr(app_module, "prospect_pool", {
        "ops": [0.700, 0.880],
        "bb_pct": [8.0, 12.0],
        "k_pct": [24.0, 17.0],
        "iso": [0.120, 0.225],
    })

    png = app_module._prospect_player_card_png(row)

    assert png[:8] == PNG_MAGIC
    assert len(png) > 1000
