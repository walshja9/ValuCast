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


def _render_detail(row, ahead_of_consensus):
    from flask import render_template

    with app_module.app.test_request_context("/player/x"):
        return render_template(
            "partials/player_detail_dynasty.html",
            row=row,
            ahead_of_consensus=ahead_of_consensus,
        )


def test_source_evidence_rank_matches_receipt_not_feed_rank():
    """Plan 010 gap (c): when a player has an ahead_of_consensus receipt, the HTML
    source-evidence block must render the SAME ValuCast rank / consensus / divergence
    the share PNG stamps (the receipt), never the feed's prospect_rank. Otherwise the
    card (feed P#53) contradicts the PNG (VC #3) for one player."""
    row = _prospect_row()
    row.metadata["prospect_rank"] = 53  # feed rank — must NOT surface when a receipt exists
    row.metadata["source_ranks"] = {"ba": 60, "mlb": 66, "kb": 72}
    receipt = {
        "valucast_rank": 3,
        "consensus_rank": 66,
        "divergence": 63,
        "board_count": 5,
        "days_ahead": 17,
    }

    html = _render_detail(_prospect_row_with(row.metadata), receipt)

    # The single source: rank/consensus/spots-ahead all come from the receipt.
    assert 'class="source-summary-rank">P#3</span>' in html
    assert "63 spots ahead of the field" in html
    assert "~P#66" in html
    # The feed rank must not appear in the source-evidence block.
    assert 'class="source-summary-rank">P#53</span>' not in html


def test_source_evidence_falls_back_to_feed_rank_without_receipt():
    """No receipt = no second source to contradict: the feed prospect_rank and the
    feed-median consensus render exactly as before."""
    row = _prospect_row()
    row.metadata["prospect_rank"] = 53
    row.metadata["source_ranks"] = {"ba": 40, "mlb": 50, "kb": 55}

    html = _render_detail(_prospect_row_with(row.metadata), None)

    assert 'class="source-summary-rank">P#53</span>' in html
    assert "~P#50" in html  # median of 40/50/55


def _prospect_row_with(metadata):
    from web.dynasty_models import DynastyRankingRow

    return DynastyRankingRow(
        id=metadata["id"],
        name=metadata["name"],
        player_type=metadata["player_type"],
        positions=tuple(metadata["positions"]),
        team=metadata["mlb_team"],
        age=metadata["age"],
        dynasty_rank=metadata["dynasty_rank"],
        dynasty_value=metadata["dynasty_value"],
        status=metadata["status"],
        mlbam_id=metadata["mlbam_id"],
        prospect_rank=metadata.get("prospect_rank"),
        level=metadata["level"],
        source_ranks=metadata.get("source_ranks"),
        stat_line=metadata["stat_line"],
        metadata=metadata,
    )


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
