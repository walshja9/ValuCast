"""Tests for permanent ValuCast call-up receipts."""
from __future__ import annotations

from pathlib import Path

import app as app_module
from app import app


def test_receipts_page_shows_hold_message_and_hides_share_card_when_held(monkeypatch):
    """7/1: the pre-launch fix shrank the board to 4 hits / 0 misses -- too thin to
    show credibly. Held from public view (nav + share-card) while the daily build
    keeps running in the background; see RECEIPTS_HOLD in app.py."""
    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", True)
    client = app.test_client()

    page = client.get("/receipts").data.decode("utf-8")
    assert "Building a real track record" in page
    assert 'href="/receipts"' not in page  # nav tab hidden
    assert "buys-actions" not in page  # export buttons hidden

    assert client.get("/receipts/share-card").status_code == 404
    assert client.get("/receipts/share-card.png").status_code == 404


def test_receipts_page_renders_normally_when_not_held(monkeypatch):
    monkeypatch.setattr(app_module, "RECEIPTS_HOLD", False)
    client = app.test_client()

    page = client.get("/receipts").data.decode("utf-8")
    assert "Building a real track record" not in page
    assert 'href="/receipts"' in page  # nav tab shown
    assert client.get("/receipts/share-card").status_code == 200


def test_call_up_receipts_wired_into_daily_public_build_and_publish_workflow():
    from scripts import run_daily_public_build
    from scripts import validate_public_data_freshness as freshness

    workflow = Path(".github/workflows/daily-public-data.yml").read_text(encoding="utf-8")
    build_steps = [" ".join(step) for step in run_daily_public_build.BUILD_STEPS]
    validate_steps = [" ".join(step) for step in run_daily_public_build.VALIDATE_STEPS]

    assert build_steps.index("scripts/build_valucast_call_up_receipts.py") > build_steps.index(
        "scripts/build_call_up_pulse.py"
    )
    assert "scripts/validate_valucast_call_up_receipts.py" in validate_steps
    assert hasattr(freshness, "VALUCAST_RECEIPTS")
    assert "data/models/valucast_call_up_receipts.json" in workflow
    assert "data/prediction_archive/valucast_call_up_receipts" in workflow


def test_detect_receipts_recomputes_consensus_and_merges_idempotently():
    from prospects.call_up_receipts import detect_receipts

    prev_board = {
        "date": "2026-06-24",
        "board": [
            _rank_row(101, "Early Call", 50, {"pipeline": 110, "hkb": 120, "sts": 100}),
            _rank_row(202, "Field Agrees", 50, {"pipeline": 60, "hkb": 70, "sts": 65}),
        ],
    }
    cur_board = {"date": "2026-06-25", "board": []}
    roster = {
        "101": {"active_mlb_roster": True},
        "202": {"active_mlb_roster": True},
    }

    first = detect_receipts(prev_board, cur_board, "2026-06-25", roster, [])
    second = detect_receipts(prev_board, cur_board, "2026-06-25", roster, first)

    assert [row["identity_key"] for row in first] == ["101_hitter"]
    assert first[0]["consensus_rank"] == 110
    assert first[0]["divergence"] == 60
    assert first[0]["call_up_date"] == "2026-06-25"
    assert second == first


def test_detect_receipts_flags_on_board_active_roster_flip():
    """7/4+ the board RETAINS called-up rookies on-board with active_mlb_roster=True
    instead of dropping them, so a call-up is no longer a disappearance. The flag
    flipping falsy->True while the player stays on-board must still mint a receipt,
    dated the archive where the flip is first observed."""
    from prospects.call_up_receipts import detect_receipts

    prev_board = {
        "date": "2026-07-03",
        "board": [_rank_row(101, "Flipped Up", 20, {"pipeline": 90, "hkb": 95, "sts": 100})],
    }
    cur_board = {
        "date": "2026-07-04",
        "board": [
            _rank_row(101, "Flipped Up", 20, {"pipeline": 90, "hkb": 95, "sts": 100},
                      active_mlb_roster=True),
        ],
    }
    roster = {"101": {"active_mlb_roster": True}}

    receipts = detect_receipts(prev_board, cur_board, "2026-07-04", roster, [])

    assert [r["identity_key"] for r in receipts] == ["101_hitter"]
    assert receipts[0]["consensus_rank"] == 95 and receipts[0]["divergence"] == 75
    assert receipts[0]["call_up_date"] == "2026-07-04"  # the archive where the flip shows


def test_flip_and_later_disappearance_do_not_double_mint():
    """A player who flips on-board active_mlb_roster=True, then later drops off the
    board entirely, must keep exactly one receipt (earliest call-up date), not two."""
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-07-03", "board": [
            _rank_row(101, "Flip Then Gone", 20, {"pipeline": 90, "hkb": 95, "sts": 100})]},
        {"date": "2026-07-04", "board": [  # flip observed here
            _rank_row(101, "Flip Then Gone", 20, {"pipeline": 90, "hkb": 95, "sts": 100},
                      active_mlb_roster=True)]},
        {"date": "2026-07-05", "board": []},  # now disappears entirely
    ]
    roster = {"profiles": [{"mlbam_id": 101, "active_mlb_roster": True}]}

    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log=[],
        seed_rows=[], generated_at="2026-07-05T00:00:00+00:00",
    )
    hits = [r for r in payload["receipts"] if r["identity_key"] == "101_hitter"]
    assert len(hits) == 1  # exactly one receipt, no double-count
    assert hits[0]["call_up_date"] == "2026-07-04"  # earliest event (the flip) wins


def test_guards_still_filter_flip_detected_players():
    """The full guard chain (MIN_BOARDS, hit-magnitude band, roster confirmation,
    EXCLUDED_IDENTITY_KEYS) applies to flip-detected rows exactly as to disappearances."""
    from prospects import call_up_receipts as cur

    prev = [
        _rank_row(101, "One Board Only", 20, {"pipeline": 90}),                 # MIN_BOARDS fail
        _rank_row(102, "Field Agrees", 50, {"pipeline": 55, "hkb": 52, "sts": 60}),  # divergence in noise band
        _rank_row(103, "Not On Roster", 20, {"pipeline": 90, "hkb": 95, "sts": 100}),  # roster confirm fail
        _rank_row(682634, "Denylisted", 20, {"pipeline": 90, "hkb": 95, "sts": 100}),  # EXCLUDED
        _rank_row(200, "Clean Hit", 20, {"pipeline": 90, "hkb": 95, "sts": 100}),      # passes
    ]
    on = lambda r: {**r, "active_mlb_roster": True}
    archives = [
        {"date": "2026-07-03", "board": prev},
        {"date": "2026-07-04", "board": [on(r) for r in prev]},  # all flip on-board
    ]
    roster = {"profiles": [
        {"mlbam_id": 101, "active_mlb_roster": True},
        {"mlbam_id": 102, "active_mlb_roster": True},
        # 103 deliberately absent from the roster lookup
        {"mlbam_id": 682634, "active_mlb_roster": True},
        {"mlbam_id": 200, "active_mlb_roster": True},
    ]}

    payload = cur.build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log=[],
        seed_rows=[], generated_at="2026-07-04T00:00:00+00:00",
    )
    keys = [r["identity_key"] for r in payload["receipts"]]
    assert keys == ["200_hitter"]  # only the clean, corroborated, on-roster hit survives
    assert "682634_hitter" not in keys  # denylist still applies to flips


def test_build_merges_seed_rows_and_auto_wins_on_identity_collision():
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-06-24", "board": [_rank_row(101, "Scored Guy", 20, {"pipeline": 90, "hkb": 95, "sts": 100})]},
        {"date": "2026-06-25", "board": []},
    ]
    roster = {"profiles": [{"mlbam_id": 101, "active_mlb_roster": True}]}
    seed = [
        {  # collides with the auto-detected 101 -> auto must win (keeps real divergence)
            "identity_key": "101_hitter", "mlbam_id": "101", "role": "hitter",
            "name": "Scored Guy", "valucast_rank": 20, "consensus_rank": None,
            "divergence": None, "field_label": "field outside top 100", "call_up_date": "2026-06-29",
        },
        {  # field-unranked guy the gate can't score
            "identity_key": "900_hitter", "mlbam_id": "900", "role": "hitter",
            "name": "Field Ignores Him", "valucast_rank": 41, "consensus_rank": None,
            "divergence": None, "field_label": "field outside top 100", "call_up_date": "2026-06-29",
        },
    ]

    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log=[],
        seed_rows=seed, generated_at="2026-06-29T00:00:00+00:00",
    )
    rows = payload["receipts"]
    keys = [row["identity_key"] for row in rows]

    assert payload["summary"]["seed_count"] == 1  # only 900 merged; 101 collision skipped
    assert keys == ["101_hitter", "900_hitter"]  # scored row leads the curated one
    auto = next(row for row in rows if row["identity_key"] == "101_hitter")
    assert auto["divergence"] == 75 and "seed" not in auto  # auto kept, real gap preserved
    curated = next(row for row in rows if row["identity_key"] == "900_hitter")
    assert curated["divergence"] is None and curated["seed"] is True


def test_detect_misses_flags_call_ups_where_valucast_was_behind():
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-06-24", "board": [
            _rank_row(301, "We Were High", 20, {"pipeline": 90, "hkb": 95, "sts": 100}),    # hit: div +75
            _rank_row(302, "Field Was High", 200, {"pipeline": 40, "hkb": 50, "sts": 60}),  # miss: div -150
        ]},
        {"date": "2026-06-25", "board": []},
    ]
    roster = {"profiles": [
        {"mlbam_id": 301, "active_mlb_roster": True},
        {"mlbam_id": 302, "active_mlb_roster": True},
    ]}

    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-06-29T00:00:00+00:00",
    )
    hits = {r["identity_key"]: r for r in payload["receipts"]}
    misses = {m["identity_key"]: m for m in payload["misses"]}

    assert "301_hitter" in hits and "301_hitter" not in misses
    assert "302_hitter" in misses and "302_hitter" not in hits
    miss = misses["302_hitter"]
    assert (miss["consensus_rank"], miss["valucast_rank"], miss["divergence"]) == (50, 200, -150)
    assert payload["summary"]["miss_count"] == 1
    assert not (set(hits) & set(misses))  # a player can't be both a hit and a miss


def test_excluded_identity_keys_never_make_the_board_even_when_auto_detected():
    from prospects import call_up_receipts as cur

    # 682634 would auto-detect as a +N hit (board -> roster), but it's on the denylist.
    archives = [
        {"date": "2026-06-29", "board": [_rank_row(682634, "Excluded Guy", 20, {"pipeline": 90, "hkb": 95, "sts": 100})]},
        {"date": "2026-06-30", "board": []},
    ]
    roster = {"profiles": [{"mlbam_id": 682634, "active_mlb_roster": True}]}

    assert "682634_hitter" in cur.EXCLUDED_IDENTITY_KEYS
    payload = cur.build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log=[],
        seed_rows=[], generated_at="2026-06-30T00:00:00+00:00",
    )
    keys = [row["identity_key"] for row in payload["receipts"]] + [m["identity_key"] for m in payload["misses"]]
    assert "682634_hitter" not in keys
    assert payload["summary"]["receipt_count"] == 0


def test_noah_schultz_excluded_rehab_activation_looked_like_a_fresh_call_up():
    from prospects import call_up_receipts as cur

    assert "702273_pitcher" in cur.EXCLUDED_IDENTITY_KEYS
    archives = [
        {"date": "2026-06-30", "board": [_rank_row(702273, "Noah Schultz", 952, {"pipeline": 26, "hkb": 20, "sts": 30})]},
        {"date": "2026-07-01", "board": []},
    ]
    roster = {"profiles": [{"mlbam_id": 702273, "active_mlb_roster": True}]}
    payload = cur.build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log=[],
        seed_rows=[], generated_at="2026-07-01T00:00:00+00:00",
    )
    keys = [row["identity_key"] for row in payload["receipts"]] + [m["identity_key"] for m in payload["misses"]]
    assert "702273_pitcher" not in keys


def test_actual_call_up_date_shadow_attaches_real_date_without_changing_anything_else():
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-06-24", "board": [_rank_row(101, "Scored Guy", 20, {"pipeline": 90, "hkb": 95, "sts": 100})]},
        {"date": "2026-06-25", "board": []},
    ]
    roster = {"profiles": [{"mlbam_id": 101, "active_mlb_roster": True}]}
    # A genuine call-up transaction (typeCode SE), post-launch, dated before the
    # archive-diff's inferred call_up_date -- the shadow should surface the earlier,
    # real date without excluding the row (it's still after LAUNCH_DATE).
    transactions_cache = {
        "queries": {
            "2026-01-01:2026-06-25:sportId=1": {
                "transactions": [
                    {
                        "typeCode": "SE",
                        "date": "2026-06-20",
                        "effectiveDate": "2026-06-20",
                        "person": {"id": 101, "fullName": "Scored Guy"},
                    },
                    {  # non-call-up transaction for the same player -- must be ignored
                        "typeCode": "NUM",
                        "date": "2026-06-22",
                        "person": {"id": 101, "fullName": "Scored Guy"},
                    },
                ]
            }
        }
    }

    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-06-25T00:00:00+00:00",
        transactions_cache=transactions_cache,
    )
    receipt = payload["receipts"][0]
    assert receipt["call_up_date"] == "2026-06-25"  # unchanged -- still the archive-diff date
    assert receipt["actual_call_up_date"] == "2026-06-20"  # shadow: the real date
    assert payload["summary"]["pre_launch_excluded_count"] == 0


def test_pre_launch_actual_call_up_date_gets_excluded():
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-06-24", "board": [_rank_row(101, "Actually Pre-Launch", 20, {"pipeline": 90, "hkb": 95, "sts": 100})]},
        {"date": "2026-06-25", "board": []},
    ]
    roster = {"profiles": [{"mlbam_id": 101, "active_mlb_roster": True}]}
    # Real call-up (typeCode SE) before ValuCast's 2026-06-16 launch -- the field/board
    # comparison isn't meaningful (same principle as the Alcántara/Schultz denylist
    # entries), so this must be dropped entirely, not just re-dated.
    transactions_cache = {
        "queries": {
            "2026-01-01:2026-06-25:sportId=1": {
                "transactions": [
                    {
                        "typeCode": "SE",
                        "date": "2026-05-01",
                        "effectiveDate": "2026-05-01",
                        "person": {"id": 101, "fullName": "Actually Pre-Launch"},
                    },
                ]
            }
        }
    }

    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-06-25T00:00:00+00:00",
        transactions_cache=transactions_cache,
    )
    assert payload["receipts"] == []
    assert payload["summary"]["pre_launch_excluded_count"] == 1
    assert payload["summary"]["pre_launch_excluded_names"] == ["Actually Pre-Launch"]


def test_actual_call_up_date_shadow_absent_without_a_transactions_cache():
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-06-24", "board": [_rank_row(101, "Scored Guy", 20, {"pipeline": 90, "hkb": 95, "sts": 100})]},
        {"date": "2026-06-25", "board": []},
    ]
    roster = {"profiles": [{"mlbam_id": 101, "active_mlb_roster": True}]}

    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-06-25T00:00:00+00:00",
    )
    assert "actual_call_up_date" not in payload["receipts"][0]


def _rank_row(
    mlbam_id: int,
    name: str,
    rank: int,
    source_ranks: dict,
    *,
    active_mlb_roster: bool | None = None,
) -> dict:
    row = {
        "mlbam_id": mlbam_id,
        "role": "hitter",
        "name": name,
        "mlb_team": "BOS",
        "positions": ["SS", "2B"],
        "level": "AAA",
        "rank": rank,
        "context_only": {"source_ranks": source_ranks},
    }
    if active_mlb_roster is not None:
        row["active_mlb_roster"] = active_mlb_roster
    return row
