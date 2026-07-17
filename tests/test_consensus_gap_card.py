"""Prospect-card consensus divergence backed by the authored gap artifact
(data/models/valucast_consensus_gap.json — the same file /gaps renders) plus the
attribution panel's /models cross-link. Display-only card behavior."""
from __future__ import annotations

from types import SimpleNamespace

import app as app_module
from web.dynasty_models import DynastyRankingRow

GAP_PAYLOAD = {
    "artifact": "valucast_consensus_gap",
    "higher": [
        {
            "identity_key": "809707_hitter",
            "mlbam_id": "809707",
            "name": "Higher Prospect",
            "valucast_rank": 3,
            "consensus_rank": 66,
            "divergence": 63,
            "board_count": 5,
            "board_min": 30,
            "board_max": 157,
        }
    ],
    "higher_all": [
        {
            "identity_key": "809707_hitter",
            "mlbam_id": "809707",
            "name": "Higher Prospect",
            "valucast_rank": 3,
            "consensus_rank": 66,
            "divergence": 63,
            "board_count": 5,
            "board_min": 30,
            "board_max": 157,
        },
        {
            "identity_key": "700001_hitter",
            "mlbam_id": "700001",
            "name": "Deep Higher Prospect",
            "valucast_rank": 40,
            "consensus_rank": 71,
            "divergence": 31,
            "board_count": 4,
            "board_min": 55,
            "board_max": 90,
        },
    ],
    "lower": [],
    "lower_all": [
        {
            "identity_key": "815888_hitter",
            "mlbam_id": "815888",
            "name": "Lower Prospect",
            "valucast_rank": 44,
            "consensus_rank": 3,
            "divergence": -41,
            "board_count": 5,
            "board_min": 2,
            "board_max": 23,
        }
    ],
}


def _metadata(mlbam_id="999999"):
    return {
        "id": f"vc_prospect_{mlbam_id}_hitter",
        "player_type": "prospect",
        "name": "Gap Prospect",
        "positions": ["SS"],
        "mlb_team": "SEA",
        "age": 19,
        "dynasty_rank": 12,
        "dynasty_value": 64.2,
        "status": "minors",
        "mlbam_id": mlbam_id,
        "role": "hitter",
        "prospect_rank": 53,
        "level": "AA",
        "stat_line": {"pa": 220, "avg": 0.285, "obp": 0.370, "slg": 0.510},
        "context": {"role": "hitter"},
        "last_updated": "2026-06-25",
    }


def _row(metadata) -> DynastyRankingRow:
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


def _render_detail(row, ahead_of_consensus):
    from flask import render_template

    with app_module.app.test_request_context("/player/x"):
        return render_template(
            "partials/player_detail_dynasty.html",
            row=row,
            ahead_of_consensus=ahead_of_consensus,
        )


# --- _consensus_gap_for_key: the authored-artifact reader ---


def test_consensus_gap_for_key_reads_full_populations(monkeypatch):
    monkeypatch.setattr(app_module, "_load_artifact", lambda _path: GAP_PAYLOAD)

    higher = app_module._consensus_gap_for_key("700001_hitter")  # _all-only row
    lower = app_module._consensus_gap_for_key("815888_hitter")

    assert higher == {
        "valucast_rank": 40,
        "consensus_rank": 71,
        "divergence": 31,
        "board_count": 4,
    }
    assert lower == {
        "valucast_rank": 44,
        "consensus_rank": 3,
        "divergence": -41,
        "board_count": 5,
    }


def test_consensus_gap_for_key_absent_player_or_artifact_is_none(monkeypatch):
    monkeypatch.setattr(app_module, "_load_artifact", lambda _path: GAP_PAYLOAD)
    assert app_module._consensus_gap_for_key("111111_hitter") is None
    assert app_module._consensus_gap_for_key(None) is None

    monkeypatch.setattr(app_module, "_load_artifact", lambda _path: None)
    assert app_module._consensus_gap_for_key("809707_hitter") is None


def test_consensus_gap_for_key_malformed_row_never_fabricates(monkeypatch):
    payload = {
        "higher_all": [
            {
                "identity_key": "809707_hitter",
                "valucast_rank": 3,
                "consensus_rank": 66,
                "divergence": "63",  # non-int -> no override
                "board_count": 5,
            }
        ]
    }
    monkeypatch.setattr(app_module, "_load_artifact", lambda _path: payload)
    assert app_module._consensus_gap_for_key("809707_hitter") is None


# --- the merge: gap artifact backs the AOTC receipt (one set of numbers) ---


def _fake_loader(gap=None, aotc=None):
    def fake_load(path):
        s = str(path)
        if s.endswith("valucast_consensus_gap.json"):
            return gap
        if s.endswith("valucast_ahead_of_consensus.json"):
            return aotc
        return {}

    return fake_load


def test_gap_row_overrides_aotc_receipt_numbers(monkeypatch):
    aotc = {
        "ahead_of_consensus": [
            {
                "identity_key": "809707_hitter",
                "valucast_rank": 5,  # drifted copy — the authored artifact wins
                "consensus_rank": 60,
                "divergence": 55,
                "board_count": 4,
                "days_ahead": 17,
                "ahead_since": "2026-06-28",
            }
        ]
    }
    monkeypatch.setattr(
        app_module, "_load_artifact", _fake_loader(gap=GAP_PAYLOAD, aotc=aotc)
    )

    context = app_module._artifact_context_for_row(
        SimpleNamespace(mlbam_id="809707", role="hitter")
    )
    receipt = context["ahead_of_consensus"]

    # Gap fields win; the lead-time receipt survives from the AOTC artifact.
    assert receipt["valucast_rank"] == 3
    assert receipt["consensus_rank"] == 66
    assert receipt["divergence"] == 63
    assert receipt["board_count"] == 5
    assert receipt["days_ahead"] == 17
    assert receipt["ahead_since"] == "2026-06-28"


def test_gap_only_lower_side_player_gets_a_receipt(monkeypatch):
    monkeypatch.setattr(
        app_module, "_load_artifact", _fake_loader(gap=GAP_PAYLOAD, aotc=None)
    )

    context = app_module._artifact_context_for_row(
        SimpleNamespace(mlbam_id="815888", role="hitter")
    )

    assert context["ahead_of_consensus"] == {
        "valucast_rank": 44,
        "consensus_rank": 3,
        "divergence": -41,
        "board_count": 5,
    }


def test_absent_from_artifact_leaves_context_unchanged(monkeypatch):
    monkeypatch.setattr(
        app_module, "_load_artifact", _fake_loader(gap=GAP_PAYLOAD, aotc=None)
    )

    context = app_module._artifact_context_for_row(
        SimpleNamespace(mlbam_id="111111", role="hitter")
    )

    assert context["ahead_of_consensus"] is None


# --- rendering: one first-class divergence number, both directions ---


def test_card_renders_gap_backed_ahead_direction_once():
    metadata = _metadata("809707")
    metadata["source_ranks"] = {"ba": 60, "mlb": 66, "kb": 72}
    receipt = {
        "valucast_rank": 3,
        "consensus_rank": 66,
        "divergence": 63,
        "board_count": 5,
    }

    html = _render_detail(_row(metadata), receipt)

    assert 'class="source-summary-rank">P#3</span>' in html
    assert "63 spots ahead of the field" in html
    assert "~P#66" in html
    # ONE spots-ahead statement on the card — never two sources.
    assert html.count("spots ahead of the field") == 1
    assert "spots behind the field" not in html


def test_card_renders_behind_direction_as_plainly_as_ahead():
    metadata = _metadata("815888")
    metadata["source_ranks"] = {"ba": 2, "mlb": 3, "kb": 23}
    receipt = {
        "valucast_rank": 44,
        "consensus_rank": 3,
        "divergence": -41,
        "board_count": 5,
    }

    html = _render_detail(_row(metadata), receipt)

    assert 'class="source-summary-rank">P#44</span>' in html
    assert "41 spots behind the field" in html
    assert "~P#3" in html
    assert "spots ahead of the field" not in html
    # A behind-consensus player never earns the Ahead of the Curve chip.
    assert "Ahead of the Curve" not in html


def test_absent_from_artifact_render_matches_todays_feed_rendering():
    """No gap row and no receipt -> the feed rank + feed-median consensus render
    exactly as before (no fabricated divergence, no new copy)."""
    metadata = _metadata("999999")
    metadata["source_ranks"] = {"ba": 40, "mlb": 50, "kb": 55}

    html = _render_detail(_row(metadata), None)

    assert 'class="source-summary-rank">P#53</span>' in html
    assert "~P#50" in html  # median of 40/50/55 (ad-hoc feed math, unchanged)
    # Feed ad-hoc gap: 50 - 53 = -3 -> behind note still renders from feed math.
    assert "3 spots behind the field" in html


def test_gap_backing_adds_no_board_names_outside_existing_details():
    """The artifact carries no per-board ranks; the gap-backed rendering must not
    add a single new board-name occurrence anywhere on the card (names stay only
    where they already were — the collapsed external-board details)."""
    metadata = _metadata("809707")
    metadata["source_ranks"] = {"ba": 60, "mlb": 66, "kb": 72}
    receipt = {
        "valucast_rank": 3,
        "consensus_rank": 66,
        "divergence": 63,
        "board_count": 5,
    }

    with_gap = _render_detail(_row(metadata), receipt)
    without = _render_detail(_row(metadata), None)

    for name in ("BA", "MLB", "KB"):
        assert with_gap.count(f"<strong>{name}</strong>") == without.count(
            f"<strong>{name}</strong>"
        ) == 1
        assert with_gap.count(f"{name} #") == without.count(f"{name} #")
    # And the individual-board list stays inside the collapsed details element.
    assert with_gap.index('<details class="public-board-details">') < with_gap.index(
        "<strong>BA</strong>"
    )


# --- attribution panel /models cross-link ---


def test_attribution_panel_links_model_verdicts():
    metadata = _metadata("999999")
    metadata["components"] = {
        "uncertainty": {"band": "medium", "lower": 60.0, "upper": 70.0}
    }

    html = _render_detail(_row(metadata), None)

    assert "How ValuCast graded him" in html
    assert 'href="/models"' in html
    assert "Model Verdicts" in html


def test_models_link_absent_without_attribution_panel():
    html = _render_detail(_row(_metadata("999999")), None)

    assert "How ValuCast graded him" not in html
    assert 'href="/models"' not in html
