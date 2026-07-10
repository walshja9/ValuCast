"""Tests for the daily post-drafts digest (scripts/build_post_drafts.py).

Synthetic artifact fixtures exercise every scanner and guardrail without touching
the real committed artifacts.
"""
from __future__ import annotations

import pytest

from scripts import build_post_drafts as bpd


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------
def _scored_receipt(key, name, vc, cons, div, days_early=0):
    return {
        "identity_key": key,
        "name": name,
        "team": "ATL",
        "valucast_rank": vc,
        "consensus_rank": cons,
        "divergence": div,
        "flagged_days_early": days_early,
    }


def _unranked_receipt(key, name, vc, field_label, days_early=0):
    return {
        "identity_key": key,
        "name": name,
        "team": "COL",
        "valucast_rank": vc,
        "field_unranked": True,
        "field_label": field_label,
        "consensus_rank": None,
        "divergence": None,
        "flagged_days_early": days_early,
    }


def _miss(key, name, vc, cons, div):
    return {
        "identity_key": key,
        "name": name,
        "team": "CHW",
        "valucast_rank": vc,
        "consensus_rank": cons,
        "divergence": div,
    }


def _mover(mover_id, name, score_delta, window=14, level="AA"):
    mlbam = mover_id.split("_")[2] if "_" in mover_id else mover_id
    return {
        "id": mover_id,
        "player_id": f"vc_prospect_{mlbam}_hitter",
        "name": name,
        "team": "MIN",
        "level": level,
        "pos": "SS",
        "role": "hitter",
        "score_delta": score_delta,
        "rank_delta": int(score_delta * 10),
        "window_days": window,
        "why": "AA 258 PA, .850 OPS, .157 ISO, 17.1% K%, 12.0% BB%",
        "current_rank": 50,
    }


# ---------------------------------------------------------------------------
# Scanner a: NEW RECEIPT.
# ---------------------------------------------------------------------------
def test_new_scored_receipt_detected_with_numbers_from_row():
    today = {"receipts": [_scored_receipt("111_hitter", "Newy McNew", 8, 63, 55, 24)]}
    prior = {"receipts": []}

    drafts = bpd.scan_new_receipts(today, prior)

    assert len(drafts) == 1
    body = drafts[0].body
    assert "Newy McNew" in body
    assert "#8" in body  # valucast_rank
    assert "~#63" in body  # consensus_rank straight from row
    assert "+55" in body  # divergence straight from row
    assert "24d before the call" in body  # flagged_days_early
    assert bpd.ARRIVAL_CAVEAT in body  # arrival caveat always appended
    assert "valucast.app/receipts" in body


def test_new_field_unranked_receipt_uses_aggregate_label_not_a_number():
    today = {
        "receipts": [
            _unranked_receipt("222_pitcher", "Gabe Unranked", 9, "1 board, ~#512", 3)
        ]
    }
    prior = {"receipts": []}

    drafts = bpd.scan_new_receipts(today, prior)

    assert len(drafts) == 1
    body = drafts[0].body
    assert "1 board, ~#512" in body  # ToS-safe aggregate label from the row
    assert "no number on him" in body
    assert bpd.ARRIVAL_CAVEAT in body


def test_receipt_already_in_prior_mirror_is_suppressed():
    row = _scored_receipt("333_hitter", "Old News", 8, 63, 55)
    today = {"receipts": [row]}
    prior = {"receipts": [row]}

    assert bpd.scan_new_receipts(today, prior) == []


# ---------------------------------------------------------------------------
# Scanner b: NEW MISS.
# ---------------------------------------------------------------------------
def test_new_miss_produces_accountability_draft():
    today = {"receipts": [], "misses": [_miss("444_pitcher", "Missed Him", 952, 26, -926)]}
    prior = {"receipts": [], "misses": []}

    drafts = bpd.scan_new_misses(today, prior)

    assert len(drafts) == 1
    body = drafts[0].body
    assert "The field beat us on Missed Him" in body
    assert "~#26" in body  # consensus_rank from row
    assert "#952" in body  # valucast_rank from row
    assert "We log these too" in body
    assert "valucast.app/receipts" in body


def test_miss_already_in_prior_is_suppressed():
    row = _miss("555_pitcher", "Known Miss", 900, 30, -870)
    today = {"receipts": [], "misses": [row]}
    prior = {"receipts": [], "misses": [row]}

    assert bpd.scan_new_misses(today, prior) == []


# ---------------------------------------------------------------------------
# Scanner c: LEDGER CLOSE.
# ---------------------------------------------------------------------------
def test_ledger_close_fires_when_gate_open_and_count_increases():
    scorecard = {
        "gate": {"publishable": True},
        "funnel": {"closed_caught_up": 9},
        "calls": [
            {
                "identity_key": "691775_hitter",
                "name": "Ryan Clifford",
                "status": "closed_caught_up",
                "consensus_now": 112,
            }
        ],
    }
    prior = {"gate": {"publishable": True}, "funnel": {"closed_caught_up": 8}, "calls": []}

    drafts = bpd.scan_ledger_close(scorecard, prior)

    assert len(drafts) == 1
    body = drafts[0].body
    assert "Ryan Clifford" in body
    assert "~#112" in body
    assert "valucast.app/ledger" in body


def test_ledger_close_silent_when_gate_closed():
    scorecard = {
        "gate": {"publishable": False},
        "funnel": {"closed_caught_up": 9},
        "calls": [],
    }
    prior = {"funnel": {"closed_caught_up": 8}}

    assert bpd.scan_ledger_close(scorecard, prior) == []


def test_ledger_close_silent_without_prior_snapshot():
    scorecard = {
        "gate": {"publishable": True},
        "funnel": {"closed_caught_up": 9},
        "calls": [],
    }
    # No prior scorecard snapshot -> cannot establish an increase -> silent.
    assert bpd.scan_ledger_close(scorecard, None) == []


def test_ledger_close_aggregate_when_multiple_close_uncredited():
    scorecard = {
        "gate": {"publishable": True},
        "funnel": {"closed_caught_up": 10},
        "calls": [],  # no per-player attribution available
    }
    prior = {"funnel": {"closed_caught_up": 8}}

    drafts = bpd.scan_ledger_close(scorecard, prior)

    assert len(drafts) == 1
    body = drafts[0].body
    assert "closed 2 more calls" in body
    assert "valucast.app/ledger" in body


# ---------------------------------------------------------------------------
# Scanner d: BIG MOVER (freshness).
# ---------------------------------------------------------------------------
def test_fresh_big_mover_detected():
    fresh = _mover("vc_mover_694230_hitter", "Fresh Riser", 8.0)
    today = {"rising": [fresh], "cooling": []}
    prior = {"rising": [], "cooling": []}

    drafts = bpd.scan_big_mover(today, prior)

    assert len(drafts) == 1
    body = drafts[0].body
    assert "Fresh Riser" in body
    assert "up 8" in body
    assert "AA 258 PA, .850 OPS" in body  # exact stat line from row.why
    assert "valucast.app/movers" in body
    # Player-card link uses the vc_prospect_* player_id form, not vc_mover_*.
    assert "vc_prospect_694230_hitter" in drafts[0].extra_url


def test_repeat_mover_suppressed():
    row = _mover("vc_mover_694230_hitter", "Repeat Mover", 8.0)
    today = {"rising": [row], "cooling": []}
    prior = {"rising": [row], "cooling": []}  # same id in yesterday's top list

    assert bpd.scan_big_mover(today, prior) == []


def test_small_mover_below_threshold_suppressed():
    small = _mover("vc_mover_694230_hitter", "Tiny Move", 4.0)  # |delta| < 5
    today = {"rising": [small], "cooling": []}
    prior = {"rising": [], "cooling": []}

    assert bpd.scan_big_mover(today, prior) == []


def test_bigger_fresh_move_wins_between_riser_and_faller():
    riser = _mover("vc_mover_1_hitter", "Small Riser", 6.0)
    faller = _mover("vc_mover_2_hitter", "Big Faller", -9.0)
    today = {"rising": [riser], "cooling": [faller]}
    prior = {"rising": [], "cooling": []}

    drafts = bpd.scan_big_mover(today, prior)

    assert len(drafts) == 1
    assert "Big Faller" in drafts[0].body
    assert "down 9" in drafts[0].body


# ---------------------------------------------------------------------------
# Priority + cap.
# ---------------------------------------------------------------------------
def test_priority_order_and_cap_at_three():
    receipts_today = {
        "receipts": [_scored_receipt("r1_hitter", "Receipt One", 8, 63, 55)],
        "misses": [_miss("m1_pitcher", "Miss One", 900, 30, -870)],
    }
    receipts_prior = {"receipts": [], "misses": []}
    scorecard = {
        "gate": {"publishable": True},
        "funnel": {"closed_caught_up": 9},
        "calls": [
            {
                "identity_key": "c1_hitter",
                "name": "Closer One",
                "status": "closed_caught_up",
                "consensus_now": 100,
            }
        ],
    }
    scorecard_prior = {"funnel": {"closed_caught_up": 8}, "calls": []}
    movers_today = {"rising": [_mover("vc_mover_9_hitter", "Mover One", 8.0)], "cooling": []}
    movers_prior = {"rising": [], "cooling": []}

    drafts = bpd.collect_drafts(
        receipts_today,
        receipts_prior,
        scorecard,
        scorecard_prior,
        movers_today,
        movers_prior,
    )

    # 4 events fire (a, b, c, d) but cap is 3, in priority order a > b > c > d.
    assert len(drafts) == 3
    assert [d.priority for d in drafts] == [1, 2, 3]
    assert drafts[0].source == "RECEIPTS"  # a
    assert "beat us" in drafts[1].body  # b (miss)
    assert drafts[2].source == "LEDGER"  # c
    # Mover (priority 4) was dropped by the cap.


# ---------------------------------------------------------------------------
# Quiet day.
# ---------------------------------------------------------------------------
def test_quiet_day_single_line():
    digest = bpd.build_digest([])
    assert bpd.QUIET_LINE in digest
    assert "Quiet day" in digest


# ---------------------------------------------------------------------------
# Guardrails.
# ---------------------------------------------------------------------------
def test_forbidden_string_guard_raises_on_board_name():
    bad = bpd.Draft(
        priority=1,
        source="RECEIPTS",
        why="test",
        graphic_url="x",
        body="ValuCast had him #8 vs FanGraphs #63.",  # brand name leaked
    )
    with pytest.raises(bpd.ForbiddenStringError):
        bpd.build_digest([bad])


def test_forbidden_string_guard_raises_on_source_key():
    bad = bpd.Draft(
        priority=1,
        source="RECEIPTS",
        why="test",
        graphic_url="x",
        body="Ranked #8 on hkb but we had him higher.",  # source key leaked
    )
    with pytest.raises(bpd.ForbiddenStringError):
        bpd.build_digest([bad])


def test_forbidden_guard_does_not_false_positive_on_ordinary_words():
    # 'pl' in 'players', 'sts' in 'consists', 'fg' nowhere -- none should trip.
    clean = "This board consists of players ValuCast still likes."
    assert bpd._forbidden_strings(clean) == []


def test_non_ascii_draft_raises():
    bad = bpd.Draft(
        priority=1,
        source="MOVERS",
        why="test",
        graphic_url="x",
        body="He is up 8 — clear em-dash leak.",  # em-dash is not ASCII
    )
    with pytest.raises(bpd.ForbiddenStringError):
        bpd.build_digest([bad])


# ---------------------------------------------------------------------------
# Telegram split + missing secrets.
# ---------------------------------------------------------------------------
def test_split_for_telegram_under_limit_is_one_chunk():
    assert bpd._split_for_telegram("short text", limit=100) == ["short text"]


def test_split_for_telegram_splits_long_text():
    para = "x" * 1000
    text = "\n\n".join([para] * 6)  # ~6000 chars
    chunks = bpd._split_for_telegram(text, limit=4096)
    assert len(chunks) >= 2
    assert all(len(c) <= 4096 for c in chunks)
    # No content lost.
    assert "".join(c.replace("\n", "") for c in chunks) == text.replace("\n", "")


def test_main_send_without_secrets_exits_zero(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    rc = bpd.main(["build_post_drafts.py", "--send"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Telegram not configured" in out


def test_main_print_mode_exits_zero(capsys):
    rc = bpd.main(["build_post_drafts.py"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ValuCast post-drafts" in out
