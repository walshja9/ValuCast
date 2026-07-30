"""Display-only prospect-card additions: AOTC lead-time line + buy-thesis string.

Both are honesty-gated (omit-never-zero): absent/None/zero data must leave the
card byte-identical to today's rendering — no dashes, no placeholders.
"""
from __future__ import annotations

import pytest

import app as app_module
from web.dynasty_models import DynastyRankingRow


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
        "stat_line": {"pa": 220, "avg": 0.285, "obp": 0.370, "slg": 0.510, "ops": 0.880},
        "context": {"role": "hitter"},
        "source_ranks": {"ba": 60, "mlb": 66, "kb": 72},
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
        source_ranks=record["source_ranks"],
        stat_line=record["stat_line"],
        metadata=record,
    )


def _render_detail(row, **context):
    from flask import render_template

    with app_module.app.test_request_context("/player/x"):
        return render_template("partials/player_detail_dynasty.html", row=row, **context)


def _receipt(**overrides):
    receipt = {
        "valucast_rank": 3,
        "consensus_rank": 66,
        "divergence": 63,
        "board_count": 5,
        "days_ahead": None,
        "ahead_since": None,
        "ahead_since_is_archive_start": None,
    }
    receipt.update(overrides)
    return receipt


# ---------------------------------------------------------------------------
# Feature 1: AOTC lead-time line
# ---------------------------------------------------------------------------

def test_lead_time_line_renders_days_and_since_date():
    html = _render_detail(
        _prospect_row(),
        ahead_of_consensus=_receipt(days_ahead=17, ahead_since="2026-06-29"),
    )
    assert "Ahead of the field for 17 days (since 2026-06-29)" in html


def test_lead_time_line_singular_day():
    html = _render_detail(
        _prospect_row(),
        ahead_of_consensus=_receipt(days_ahead=1, ahead_since="2026-07-15"),
    )
    assert "Ahead of the field for 1 day (since 2026-07-15)" in html
    assert "1 days" not in html


def test_lead_time_line_archive_start_floor():
    """Archive-start streaks are a floor, not an origin: '+' and 'tracked since'
    (same convention as the backfields consensus strip)."""
    html = _render_detail(
        _prospect_row(),
        ahead_of_consensus=_receipt(
            days_ahead=27, ahead_since="2026-05-29", ahead_since_is_archive_start=True
        ),
    )
    assert "Ahead of the field for 27+ days (tracked since 2026-05-29)" in html


@pytest.mark.parametrize(
    "overrides",
    [
        {},  # days_ahead absent (None)
        {"days_ahead": 0, "ahead_since": "2026-06-29"},  # zero = omit, never "0 days"
        {"days_ahead": 17},  # no date on record: never fabricate one
    ],
)
def test_lead_time_line_omitted_when_data_missing_or_zero(overrides):
    baseline = _render_detail(_prospect_row(), ahead_of_consensus=_receipt())
    html = _render_detail(_prospect_row(), ahead_of_consensus=_receipt(**overrides))
    assert "Ahead of the field for" not in html
    assert html == baseline  # today's exact rendering, nothing added


# ---------------------------------------------------------------------------
# Feature 2: buy thesis string next to the Buy Board chip
# ---------------------------------------------------------------------------

def test_buy_reason_renders_next_to_buy_rank():
    html = _render_detail(
        _prospect_row(),
        recent_signal={"buy_rank": 12, "buy_reason": "Young runway"},
    )
    assert '<span class="stat-value">#12 · Young runway</span>' in html


@pytest.mark.parametrize("signal", [
    {"buy_rank": 12},
    {"buy_rank": 12, "buy_reason": None},
    {"buy_rank": 12, "buy_reason": ""},
])
def test_missing_buy_reason_leaves_chip_unchanged(signal):
    baseline = _render_detail(_prospect_row(), recent_signal={"buy_rank": 12})
    html = _render_detail(_prospect_row(), recent_signal=signal)
    assert '<span class="stat-value">#12</span>' in html
    assert html == baseline


def test_buy_terms_and_score_history_never_surface():
    """Internal composition stays internal — only the reason string is display-safe."""
    html = _render_detail(
        _prospect_row(),
        recent_signal={
            "buy_rank": 12,
            "buy_reason": "Young runway",
            "buy_terms": {
                "buy_window": 0.9,
                "conviction": 0.67,
                "model_strength": 0.7,
                "momentum": 0.4,
                "runway": 0.6,
            },
            "score_history": [["2026-07-14", 43.1]],
        },
    )
    # NB: bare "runway" can't be asserted absent — the honest reason string
    # ("Young runway") legitimately contains it. The numbers can.
    for term in ("buy_window", "conviction", "model_strength", "momentum",
                 "score_history", "0.9", "0.67", "0.4", "0.6", "43.1"):
        assert term not in html


# ---------------------------------------------------------------------------
# Real card through the test client, both features via patched context
# ---------------------------------------------------------------------------

def test_real_card_renders_both_features_via_test_client(monkeypatch):
    if not app_module.dd_store.is_available:
        pytest.skip("dd feed not available")
    prospect = next(
        (r for r in app_module.dd_store.get_all() if getattr(r, "is_prospect", False)),
        None,
    )
    if prospect is None:
        pytest.skip("no prospect rows in dd feed")

    monkeypatch.setattr(
        app_module,
        "_artifact_context_for_row",
        lambda _row: {
            "scouting_report": None,
            "recent_signal": {"buy_rank": 12, "buy_reason": "Young runway"},
            "recent_form": None,
            "call_up": None,
            "card_data_status": None,
            "role_profile": None,
            "ahead_of_consensus": _receipt(days_ahead=17, ahead_since="2026-06-29"),
        },
    )

    client = app_module.app.test_client()
    resp = client.get(
        f"/player/{prospect.id}?mode=prospects", headers={"HX-Request": "true"}
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Ahead of the field for 17 days (since 2026-06-29)" in html
    assert "#12 · Young runway" in html


# ---------------------------------------------------------------------------
# AAA-Statcast card: honest sample labels + visible as_of (F4 / P2-6,
# audit 2026-07-30). ev_n is absent on artifacts built before 2026-07-30, so
# the template must fail soft to the n_bip-only wording until a fresh rebuild.
# ---------------------------------------------------------------------------

def _contact_quality(**overrides):
    section = {
        "as_of": "2026-07-14",
        "n_pitches": 700,
        "n_bip": 120,
        "ev_n": None,  # legacy default: pre-fix artifacts lack ev_n
        "rows": [{"key": "avg_ev", "label": "Avg Exit Velo", "value": "90.4 mph"}],
    }
    section.update(overrides)
    return section


def test_aaa_sample_line_legacy_artifact_without_ev_n():
    html = _render_detail(_prospect_row(), aaa_contact_quality=_contact_quality())
    # n_bip counts ALL balls in play — never labeled "tracked".
    assert "120 balls in play" in html
    assert "tracked balls in play" not in html
    assert "with tracked EV" not in html


def test_aaa_sample_line_shows_ev_sample_when_present():
    html = _render_detail(
        _prospect_row(), aaa_contact_quality=_contact_quality(ev_n=110)
    )
    assert "120 balls in play" in html
    assert "110 with tracked EV" in html


def test_aaa_card_shows_artifact_as_of():
    html = _render_detail(_prospect_row(), aaa_contact_quality=_contact_quality())
    assert "through 2026-07-14" in html


def test_aaa_card_omits_as_of_when_absent():
    html = _render_detail(
        _prospect_row(), aaa_contact_quality=_contact_quality(as_of=None)
    )
    assert "through" not in html.split("AAA Statcast")[1].split("</p>")[0]
