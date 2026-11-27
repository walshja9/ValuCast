"""Per-player Forward Ledger claim badge on the prospect card (display-only).

Honesty contract (same family as the /scoreboard anti-trophy-case checklist):
  - HOLD GATE: while SCOREBOARD_HOLD holds /scoreboard dark, the badge renders
    NOTHING anywhere — the card is byte-identical to today.
  - An open claim never reads as a win; resolved claims state the outcome plainly
    on both sides; retractions are shown, never hidden.
  - claim_date always renders (registration / no-backdating proof).
  - The join is strictly by mlbam id (twin-safe) — a near-name twin's claim must
    never render on the wrong card.
  - Omit-never-fabricate: no claim in the artifact -> byte-identical rendering.
"""
from __future__ import annotations

import pytest

import app as app_module
from web.dynasty_models import DynastyRankingRow


def _prospect_row(mlbam_id="999999", name="Ledger Prospect") -> DynastyRankingRow:
    record = {
        "id": f"vc_prospect_{mlbam_id}_hitter",
        "player_type": "prospect",
        "name": name,
        "positions": ["SS"],
        "mlb_team": "SEA",
        "age": 19,
        "dynasty_rank": 12,
        "dynasty_value": 64.2,
        "status": "minors",
        "mlbam_id": mlbam_id,
        "role": "hitter",
        "prospect_rank": 12,
        "level": "AA",
        "stat_line": {"pa": 220, "avg": 0.285},
        "context": {"role": "hitter"},
        "last_updated": "2026-07-10",
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


def _claim(**overrides):
    claim = {
        "claim_consensus_rank": 105,
        "claim_date": "2026-06-24",
        "claim_divergence": 52,
        "claim_valucast_rank": 53,
        "identity_key": "999999_hitter",
        "mlbam_id": "999999",
        "name": "Ledger Prospect",
        "outcome": "open",
        "role": "hitter",
        "side": "higher",
        "team": "SEA",
    }
    claim.update(overrides)
    return claim


def _serve_ledger(monkeypatch, claims, *, hold=False, provisional=None):
    """Point the badge at an in-memory ledger; hold + scoreboard artifact patched
    through the exact module seams the routes use."""
    monkeypatch.setattr(app_module, "SCOREBOARD_HOLD", hold)
    monkeypatch.setattr(app_module, "_load_gaps_ledger", lambda: {"claims": claims})
    sc = (
        {"anticipation_score": {"provisional": provisional}}
        if provisional is not None
        else None
    )
    monkeypatch.setattr(app_module, "_load_forward_scoreboard_payload", lambda: sc)


def _render_detail(row, **context):
    from flask import render_template

    with app_module.app.test_request_context("/player/x"):
        return render_template("partials/player_detail_dynasty.html", row=row, **context)


# ---------------------------------------------------------------------------
# Hold gate: badge ships dark with /scoreboard
# ---------------------------------------------------------------------------

def test_hold_on_badge_returns_none_even_with_claims(monkeypatch):
    _serve_ledger(monkeypatch, [_claim()], hold=True)
    assert app_module._forward_ledger_badge("999999") is None


def test_hold_on_card_renders_nothing_byte_identical(monkeypatch):
    _serve_ledger(monkeypatch, [_claim()], hold=True)
    baseline = _render_detail(_prospect_row())
    html = _render_detail(
        _prospect_row(),
        forward_ledger=app_module._forward_ledger_badge("999999"),
    )
    assert html == baseline
    assert "Forward Ledger" not in html


def test_hold_off_badge_lights_up(monkeypatch):
    _serve_ledger(monkeypatch, [_claim()], hold=False)
    badge = app_module._forward_ledger_badge("999999")
    assert badge is not None
    assert len(badge["claims"]) == 1


# ---------------------------------------------------------------------------
# Honesty: per-state copy
# ---------------------------------------------------------------------------

def test_open_claim_neutral_with_claim_date(monkeypatch):
    _serve_ledger(monkeypatch, [_claim()], provisional=False)
    html = _render_detail(
        _prospect_row(), forward_ledger=app_module._forward_ledger_badge("999999")
    )
    assert "higher claim — open · claimed 2026-06-24" in html
    assert 'href="/scoreboard"' in html
    # Never trophy-cased: an open claim must not read as a result.
    for banned in ("win", "leading", "ahead of the field"):
        assert banned not in html.lower()


def test_callup_resolution_with_lead_time(monkeypatch):
    _serve_ledger(
        monkeypatch,
        [_claim(outcome="resolved_by_callup", resolved_date="2026-06-26",
                lead_time_days=2)],
    )
    html = _render_detail(
        _prospect_row(), forward_ledger=app_module._forward_ledger_badge("999999")
    )
    assert (
        "higher claim — called up · 2 days early · claimed 2026-06-24 · resolved 2026-06-26"
        in html
    )


def test_field_move_resolution_states_outcome(monkeypatch):
    _serve_ledger(
        monkeypatch,
        [_claim(side="lower", outcome="resolved_by_consensus_move",
                resolved_date="2026-07-14")],
    )
    html = _render_detail(
        _prospect_row(), forward_ledger=app_module._forward_ledger_badge("999999")
    )
    assert (
        "lower claim — field moved toward us · claimed 2026-06-24 · resolved 2026-07-14"
        in html
    )


def test_retracted_claim_says_retracted_never_hidden(monkeypatch):
    _serve_ledger(
        monkeypatch,
        [_claim(outcome="retracted_by_model_move", resolved_date="2026-07-14")],
    )
    html = _render_detail(
        _prospect_row(), forward_ledger=app_module._forward_ledger_badge("999999")
    )
    assert (
        "higher claim — retracted (we backed off) · claimed 2026-06-24 · resolved 2026-07-14"
        in html
    )


def test_expired_claim_states_expiry(monkeypatch):
    _serve_ledger(
        monkeypatch,
        [_claim(outcome="expired_unresolved", resolved_date="2026-08-23")],
    )
    badge = app_module._forward_ledger_badge("999999")
    assert badge["claims"][0]["label"] == (
        "higher claim — expired unresolved · claimed 2026-06-24 · resolved 2026-08-23"
    )


def test_multiple_claims_all_render_newest_first_retraction_included(monkeypatch):
    """A later open claim never buries an earlier retraction — both render."""
    _serve_ledger(
        monkeypatch,
        [
            _claim(outcome="retracted_by_model_move", claim_date="2026-06-24",
                   resolved_date="2026-07-14"),
            _claim(outcome="open", claim_date="2026-07-10", side="lower"),
        ],
        provisional=False,
    )
    badge = app_module._forward_ledger_badge("999999")
    labels = [c["label"] for c in badge["claims"]]
    assert labels == [
        "lower claim — open · claimed 2026-07-10",
        "higher claim — retracted (we backed off) · claimed 2026-06-24 · resolved 2026-07-14",
    ]


def test_registration_proof_ranks_in_title(monkeypatch):
    _serve_ledger(monkeypatch, [_claim()], provisional=False)
    badge = app_module._forward_ledger_badge("999999")
    assert badge["claims"][0]["title"] == (
        "Registered 2026-06-24 — ValuCast #53 vs field consensus #105"
    )


def test_unknown_outcome_renders_nothing_not_guessed_copy(monkeypatch):
    _serve_ledger(monkeypatch, [_claim(outcome="some_future_state")])
    assert app_module._forward_ledger_badge("999999") is None


# ---------------------------------------------------------------------------
# Provisional note mirrors the /scoreboard idiom, artifact-derived only
# ---------------------------------------------------------------------------

def test_provisional_note_on_open_claim_when_scoreboard_provisional(monkeypatch):
    _serve_ledger(monkeypatch, [_claim()], provisional=True)
    badge = app_module._forward_ledger_badge("999999")
    assert badge["provisional_note"] == "expiry lane opens 2026-08-23"
    html = _render_detail(_prospect_row(), forward_ledger=badge)
    assert "expiry lane opens 2026-08-23" in html


@pytest.mark.parametrize(
    "claims, provisional",
    [
        ([_claim()], False),  # scoreboard says not provisional -> no note
        ([_claim()], None),   # scoreboard artifact missing -> never asserted app-side
        (  # no open claim -> the note has nothing to caveat
            [_claim(outcome="retracted_by_model_move", resolved_date="2026-07-14")],
            True,
        ),
    ],
)
def test_provisional_note_absent_otherwise(monkeypatch, claims, provisional):
    _serve_ledger(monkeypatch, claims, provisional=provisional)
    badge = app_module._forward_ledger_badge("999999")
    assert badge["provisional_note"] is None


# ---------------------------------------------------------------------------
# Omit-never-fabricate + twin-safe join
# ---------------------------------------------------------------------------

def test_no_claim_returns_none_and_card_byte_identical(monkeypatch):
    _serve_ledger(monkeypatch, [])
    badge = app_module._forward_ledger_badge("999999")
    assert badge is None
    baseline = _render_detail(_prospect_row())
    html = _render_detail(_prospect_row(), forward_ledger=badge)
    assert html == baseline


def test_near_name_twin_claim_never_misjoins(monkeypatch):
    """The worst possible failure: another player's claim on this card. The twin
    shares the display name but has a different mlbam id — nothing may render."""
    twin_claim = _claim(
        mlbam_id="999998", identity_key="999998_hitter", name="Ledger Prospect"
    )
    _serve_ledger(monkeypatch, [twin_claim])
    assert app_module._forward_ledger_badge("999999") is None
    html = _render_detail(
        _prospect_row(), forward_ledger=app_module._forward_ledger_badge("999999")
    )
    assert "Forward Ledger" not in html


def test_join_is_mlbam_only_int_str_tolerant(monkeypatch):
    """Same physical player, int-vs-str id representations still join."""
    _serve_ledger(monkeypatch, [_claim(mlbam_id=999999)])
    assert app_module._forward_ledger_badge("999999") is not None
    _serve_ledger(monkeypatch, [_claim(mlbam_id="999999")])
    assert app_module._forward_ledger_badge(999999) is not None


def test_missing_mlbam_never_joins(monkeypatch):
    _serve_ledger(monkeypatch, [_claim(mlbam_id="")])
    assert app_module._forward_ledger_badge("") is None
    assert app_module._forward_ledger_badge(None) is None


# ---------------------------------------------------------------------------
# Real card through the test client (context builder wiring)
# ---------------------------------------------------------------------------

def test_real_card_via_test_client_hold_off_and_on(monkeypatch):
    if not app_module.dd_store.is_available:
        pytest.skip("dd feed not available")
    prospect = next(
        (
            r
            for r in app_module.dd_store.get_all()
            if getattr(r, "is_prospect", False) and getattr(r, "mlbam_id", None)
        ),
        None,
    )
    if prospect is None:
        pytest.skip("no prospect rows with mlbam in dd feed")

    claims = [_claim(mlbam_id=str(prospect.mlbam_id))]
    client = app_module.app.test_client()

    _serve_ledger(monkeypatch, claims, hold=False, provisional=False)
    resp = client.get(
        f"/player/{prospect.id}?mode=prospects", headers={"HX-Request": "true"}
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "higher claim — open · claimed 2026-06-24" in html
    assert 'href="/scoreboard"' in html

    _serve_ledger(monkeypatch, claims, hold=True)
    resp = client.get(
        f"/player/{prospect.id}?mode=prospects", headers={"HX-Request": "true"}
    )
    assert resp.status_code == 200
    held = resp.get_data(as_text=True)
    assert "Forward Ledger" not in held
    assert "claimed 2026-06-24" not in held
