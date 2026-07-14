"""Tests for the two-sided gaps claim lifecycle ledger (plan 017)."""
from __future__ import annotations

from prospects.gaps_claim_ledger import (
    CONSENSUS_MOVE_FLOOR_SPOTS,
    EXPIRY_DAYS,
    MODEL_MOVE_FLOOR_SPOTS,
    build_gaps_claim_ledger,
)

# The public board launched 2026-06-16; all synthetic dates sit on/after it.
LAUNCH = "2026-06-16"
BOARDS_HIGH = {"hkb": 200, "pl": 210, "sts": 190}   # field median ~#200
BOARDS_LOW = {"hkb": 20, "pl": 25, "sts": 15}       # field median ~#20


def _rank_row(mlbam_id, name, rank, *, role="hitter", boards=None, in_mlb=False):
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        "role": role,
        "rank": rank,
        "mlb_team": "BOS",
        "active_mlb_roster": in_mlb,
        "context_only": {"source_ranks": boards or {}},
    }


def _snapshot(date, rows):
    return {"date": date, "board": rows}


def _call_up_cache(mlbam_id, date, type_code="CU"):
    return {
        "queries": {
            "q": {
                "transactions": [
                    {
                        "typeCode": type_code,
                        "person": {"id": mlbam_id},
                        "effectiveDate": date,
                    }
                ]
            }
        }
    }


def _claim(payload, identity_key, side):
    for c in payload["claims"]:
        if c["identity_key"] == identity_key and c["side"] == side:
            return c
    return None


def test_enrollment_opens_a_claim_on_each_side():
    # One qualifying higher row + one qualifying lower row -> two open claims,
    # correct side, claim_date = first qualifying snapshot.
    archives = [
        _snapshot("2026-06-20", [
            _rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH),   # VC 40 vs ~200 -> higher
            _rank_row(2, "Fade Guy", 240, boards=BOARDS_LOW),    # VC 240 vs ~20 -> lower
        ]),
        _snapshot("2026-06-21", [
            _rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH),
            _rank_row(2, "Fade Guy", 240, boards=BOARDS_LOW),
        ]),
    ]
    payload = build_gaps_claim_ledger(archive_payloads=archives, transactions_cache={})

    higher = _claim(payload, "1_hitter", "higher")
    lower = _claim(payload, "2_hitter", "lower")
    assert higher is not None and lower is not None
    assert higher["side"] == "higher" and lower["side"] == "lower"
    assert higher["claim_date"] == "2026-06-20"  # first qualifying snapshot, not the 2nd
    assert lower["claim_date"] == "2026-06-20"
    assert payload["summary"]["higher"]["total"] == 1
    assert payload["summary"]["lower"]["total"] == 1


def test_resolved_by_callup_higher_sets_lead_time():
    archives = [
        _snapshot("2026-06-20", [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),
        _snapshot("2026-06-30", [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),
    ]
    cache = _call_up_cache(1, "2026-06-25")  # called up 5 days after claim, gap still holds
    payload = build_gaps_claim_ledger(archive_payloads=archives, transactions_cache=cache)

    claim = _claim(payload, "1_hitter", "higher")
    assert claim["outcome"] == "resolved_by_callup"
    assert claim["resolved_date"] == "2026-06-25"
    assert claim["lead_time_days"] == 5


def test_resolved_by_callup_lower_is_a_fade_miss():
    # The symmetric accountability the mandate demands: a fade player who gets
    # called up resolves on the LOWER side (the field was right, we were wrong).
    archives = [
        _snapshot("2026-06-20", [_rank_row(2, "Fade Guy", 240, boards=BOARDS_LOW)]),
        _snapshot("2026-06-30", [_rank_row(2, "Fade Guy", 240, boards=BOARDS_LOW)]),
    ]
    cache = _call_up_cache(2, "2026-06-28")
    payload = build_gaps_claim_ledger(archive_payloads=archives, transactions_cache=cache)

    claim = _claim(payload, "2_hitter", "lower")
    assert claim["outcome"] == "resolved_by_callup"
    assert claim["side"] == "lower"
    assert claim["resolved_date"] == "2026-06-28"
    assert claim["lead_time_days"] == 8


def test_resolved_by_consensus_move_when_field_converges():
    # No call-up, but the later snapshot's field median moved TOWARD our rank by
    # more than the floor (higher side: consensus_now < consensus_then).
    then_boards = {"hkb": 200, "pl": 210, "sts": 190}   # median ~200
    now_boards = {"hkb": 60, "pl": 70, "sts": 50}        # median ~60 (moved up ~140 >> floor)
    archives = [
        _snapshot("2026-06-20", [_rank_row(1, "Ahead Guy", 40, boards=then_boards)]),
        _snapshot("2026-06-30", [_rank_row(1, "Ahead Guy", 40, boards=now_boards)]),
    ]
    payload = build_gaps_claim_ledger(archive_payloads=archives, transactions_cache={})

    claim = _claim(payload, "1_hitter", "higher")
    assert claim["outcome"] == "resolved_by_consensus_move"
    assert claim["consensus_move_spots"] <= -CONSENSUS_MOVE_FLOOR_SPOTS
    assert claim["resolved_date"] == "2026-06-30"


def test_retracted_by_model_move_when_we_back_off():
    # OUR rank moved to close the gap (higher side: our rank rose toward the field)
    # by more than the floor, before the field moved -> retracted_by_model_move.
    archives = [
        _snapshot("2026-06-20", [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),
        # our rank slid from 40 to 180 (we backed off ~140 spots); field unchanged.
        _snapshot("2026-06-30", [_rank_row(1, "Ahead Guy", 180, boards=BOARDS_HIGH)]),
    ]
    payload = build_gaps_claim_ledger(archive_payloads=archives, transactions_cache={})

    claim = _claim(payload, "1_hitter", "higher")
    assert claim["outcome"] == "retracted_by_model_move"
    assert claim["model_move_spots"] >= MODEL_MOVE_FLOOR_SPOTS
    assert claim["resolved_date"] == "2026-06-30"


def test_expired_unresolved_after_expiry_days():
    # EXPIRY_DAYS+ between claim_date and latest snapshot with no other resolution.
    late = "2026-06-20"
    from datetime import date, timedelta

    later = (date.fromisoformat(late) + timedelta(days=EXPIRY_DAYS + 5)).isoformat()
    archives = [
        _snapshot(late, [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),
        _snapshot(later, [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),  # gap unchanged
    ]
    payload = build_gaps_claim_ledger(archive_payloads=archives, transactions_cache={})

    claim = _claim(payload, "1_hitter", "higher")
    assert claim["outcome"] == "expired_unresolved"
    assert claim["age_days"] >= EXPIRY_DAYS


def test_append_only_merge_keeps_terminal_claims_verbatim():
    # Build once -> a terminal (call-up) claim. Build AGAIN with a later archive
    # where the player's board row would now classify differently -> the terminal
    # claim is UNCHANGED and no claim_date mutates. (The load-bearing invariant.)
    archives_1 = [
        _snapshot("2026-06-20", [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),
        _snapshot("2026-06-30", [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),
    ]
    cache = _call_up_cache(1, "2026-06-25")
    first = build_gaps_claim_ledger(archive_payloads=archives_1, transactions_cache=cache)
    terminal = _claim(first, "1_hitter", "higher")
    assert terminal["outcome"] == "resolved_by_callup"

    # A later build where a fresh scan would GENUINELY classify differently: the
    # call-up vanishes from the cache (so priority 1 can't fire) and our rank slid
    # enough that a rescan yields retracted_by_model_move. If the merge re-resolved
    # terminal claims, the outcome would flip — it must stay verbatim instead.
    archives_2 = archives_1 + [
        _snapshot("2026-07-10", [_rank_row(1, "Ahead Guy", 250, boards=BOARDS_HIGH)]),
    ]
    fresh_rescan = build_gaps_claim_ledger(
        archive_payloads=archives_2, transactions_cache={}, existing_log=[]
    )
    assert _claim(fresh_rescan, "1_hitter", "higher")["outcome"] == "retracted_by_model_move"

    second = build_gaps_claim_ledger(
        archive_payloads=archives_2, transactions_cache={}, existing_log=first
    )
    kept = _claim(second, "1_hitter", "higher")
    assert kept == terminal  # byte-for-byte the same dict, outcome + date + lead time
    assert kept["claim_date"] == "2026-06-20"


def test_launch_date_guard_excludes_pre_launch_callups():
    # A call-up dated BEFORE LAUNCH_DATE never resolves a claim as a call-up (the
    # field already reflected the outcome before the public board existed).
    archives = [
        _snapshot("2026-06-20", [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),
        _snapshot("2026-06-30", [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),
    ]
    cache = _call_up_cache(1, "2026-06-10")  # pre-launch
    payload = build_gaps_claim_ledger(archive_payloads=archives, transactions_cache=cache)

    claim = _claim(payload, "1_hitter", "higher")
    assert claim["outcome"] != "resolved_by_callup"
    assert "lead_time_days" not in claim


def test_pre_launch_snapshots_never_mint_claims():
    # Enrollment starts at LAUNCH_DATE: a qualifying row on a pre-launch snapshot
    # can't open a claim dated before the board existed.
    archives = [
        _snapshot("2026-06-13", [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),  # pre-launch
        _snapshot("2026-06-20", [_rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH)]),
    ]
    payload = build_gaps_claim_ledger(archive_payloads=archives, transactions_cache={})
    claim = _claim(payload, "1_hitter", "higher")
    assert claim["claim_date"] == "2026-06-20"  # clamped to first on-or-after launch
