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


def test_receipts_png_travels_arrival_not_outcome_caveat():
    """7/9 claims-register gap (b): the share-card PNG is the og:image + Download
    target, detached from the page. The arrival-not-outcome caveat that lives on
    receipts.html must travel WITH the image. Render must succeed (non-empty PNG)
    and the caveat literal must exist in the builder so it stays in sync with the
    page disclaimer."""
    import inspect

    receipts = [
        {
            "name": "Test Prospect",
            "team": "TB",
            "pos": "SS",
            "level": "AAA",
            "call_up_date": "2026-07-01",
            "valucast_rank": 3,
            "consensus_rank": 69,
            "divergence": 66,
        }
    ]
    png = app_module._receipts_share_card_png(receipts, [], generated_at="2026-07-09")
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "must render valid PNG bytes"
    assert len(png) > 0

    src = inspect.getsource(app_module._receipts_share_card_png)
    assert "arrival" in src, "arrival-not-outcome caveat must live in the PNG builder"
    assert "outcome calls live on the ledger" in src


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


def test_selection_with_same_day_option_is_not_a_call_up_date():
    """A contract selection paired with a SAME-DAY option back to the minors is 40-man
    roster paperwork (Rule-5 protection), not a promotion -- it must not count as the
    player's call-up date. Proven case: Cooper Pratt, 2026-04-03 SE + same-day OPT."""
    from prospects.call_up_receipts import _actual_call_up_dates

    cache = {
        "queries": {
            "q": {
                "transactions": [
                    {"typeCode": "SE", "date": "2026-04-03", "effectiveDate": "2026-04-03",
                     "person": {"id": 806198, "fullName": "Cooper Pratt"},
                     "description": "selected the contract of SS Cooper Pratt"},
                    {"typeCode": "OPT", "date": "2026-04-03", "effectiveDate": "2026-04-03",
                     "person": {"id": 806198, "fullName": "Cooper Pratt"},
                     "description": "optioned SS Cooper Pratt to Nashville Sounds"},
                    {"typeCode": "CU", "date": "2026-06-16", "effectiveDate": "2026-06-16",
                     "person": {"id": 806198, "fullName": "Cooper Pratt"},
                     "description": "recalled SS Cooper Pratt from Nashville Sounds"},
                ]
            }
        }
    }
    # The 4/03 SE+OPT paperwork is skipped; the real call-up is the 6/16 recall.
    assert _actual_call_up_dates(cache) == {"806198": "2026-06-16"}


def test_selection_without_same_day_option_still_counts():
    """A genuine selection-to-active-roster with no same-day option counts as the call-up
    date -- Noah Schultz's 2026-04-14 SE is the documented example."""
    from prospects.call_up_receipts import _actual_call_up_dates

    cache = {
        "queries": {
            "q": {
                "transactions": [
                    {"typeCode": "SE", "date": "2026-04-14", "effectiveDate": "2026-04-14",
                     "person": {"id": 702273, "fullName": "Noah Schultz"},
                     "description": "selected the contract of LHP Noah Schultz"},
                    {"typeCode": "OPT", "date": "2026-05-01", "effectiveDate": "2026-05-01",
                     "person": {"id": 702273, "fullName": "Noah Schultz"},
                     "description": "optioned LHP Noah Schultz (different day)"},
                ]
            }
        }
    }
    assert _actual_call_up_dates(cache) == {"702273": "2026-04-14"}


def test_pratt_shaped_flow_passes_launch_guard_end_to_end():
    """Pratt-shaped: a pre-launch SE+same-day OPT (40-man paperwork) plus a post-launch
    recall. Corrected, the real call-up dates AFTER launch, so the row survives the
    LAUNCH_DATE guard instead of being wrongly dropped as pre-launch."""
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-06-16", "board": [_rank_row(806198, "Cooper Pratt", 25, {"pipeline": 90, "hkb": 95, "sts": 100})]},
        {"date": "2026-06-17", "board": []},  # disappears into the roster on/after launch
    ]
    roster = {"profiles": [{"mlbam_id": 806198, "active_mlb_roster": True}]}
    transactions_cache = {
        "queries": {
            "q": {
                "transactions": [
                    {"typeCode": "SE", "date": "2026-04-03", "effectiveDate": "2026-04-03",
                     "person": {"id": 806198, "fullName": "Cooper Pratt"}},
                    {"typeCode": "OPT", "date": "2026-04-03", "effectiveDate": "2026-04-03",
                     "person": {"id": 806198, "fullName": "Cooper Pratt"}},
                    {"typeCode": "CU", "date": "2026-06-16", "effectiveDate": "2026-06-16",
                     "person": {"id": 806198, "fullName": "Cooper Pratt"}},
                ]
            }
        }
    }

    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-06-17T00:00:00+00:00",
        transactions_cache=transactions_cache,
    )
    keys = [r["identity_key"] for r in payload["receipts"]]
    assert "806198_hitter" in keys  # survives -- real call-up (6/16) is not pre-launch
    receipt = next(r for r in payload["receipts"] if r["identity_key"] == "806198_hitter")
    assert receipt["actual_call_up_date"] == "2026-06-16"
    assert payload["summary"]["pre_launch_excluded_count"] == 0


def test_flagged_days_early_counts_continuous_in_band_run():
    """The helper counts only the SINGLE continuous run of in-band archive days walking
    back from the anchor, and a distant in-band day across an out-of-band gap does NOT
    bridge it (monotone/continuous, not a lifetime tally)."""
    from prospects.call_up_receipts import _flagged_days_early

    key = "101_hitter"
    # claimed_rank=20 -> band ceil(20*1.25)=25. anchor 2026-07-10.
    # Three in-band days immediately before, then an out-of-band day, then an earlier
    # in-band day that must NOT be bridged.
    archive_by_date_key = {
        "2026-07-09": {key: {"rank": 22}},   # in-band (day 1 of run)
        "2026-07-08": {key: {"rank": 24}},   # in-band (day 2)
        "2026-07-07": {key: {"rank": 25}},   # in-band (day 3, ==band)
        "2026-07-06": {key: {"rank": 40}},   # OUT of band -> run stops here
        "2026-07-05": {key: {"rank": 10}},   # in-band but past the gap -> not counted
    }
    assert _flagged_days_early(key, 20, "2026-07-10", archive_by_date_key) == 3


def test_flagged_days_early_omitted_when_unprovable():
    """Never returns 0: no anchor, no earlier archive, or a zero-length run (out-of-band
    on the first day before the anchor) all yield None (omit, don't fake a 0)."""
    from prospects.call_up_receipts import _flagged_days_early

    key = "101_hitter"
    full_index = {"2026-07-09": {key: {"rank": 22}}}

    # (a) no anchor date -> None
    assert _flagged_days_early(key, 20, None, full_index) is None
    # (a2) no claimed rank -> None (band can't be computed)
    assert _flagged_days_early(key, None, "2026-07-10", full_index) is None
    # (b) anchor with no committed archive date strictly before it -> None
    assert _flagged_days_early(key, 20, "2026-07-09", {"2026-07-09": {key: {"rank": 22}}}) is None
    # (c) out-of-band on the first day before the anchor (zero-length run) -> None, not 0
    out_of_band = {"2026-07-09": {key: {"rank": 99}}}
    assert _flagged_days_early(key, 20, "2026-07-10", out_of_band) is None


def test_build_attaches_flagged_days_early_to_auto_rows():
    """End-to-end: an auto receipt with in-band archive history before its call-up gains
    flagged_days_early == the run length, while a row without supporting history does NOT
    carry the key. call_up_date, divergence, and sort order are unchanged (additive-only)."""
    from prospects.call_up_receipts import build_call_up_receipts

    # Player 101 is in-band (rank <= ceil(15*1.25)=19) for the two days before disappearing
    # into the roster on 2026-06-27. Player 202 has no earlier archive coverage at all.
    archives = [
        {"date": "2026-06-24", "board": [
            _rank_row(101, "Held Guy", 15, {"pipeline": 90, "hkb": 95, "sts": 100}),
        ]},
        {"date": "2026-06-25", "board": [
            _rank_row(101, "Held Guy", 16, {"pipeline": 90, "hkb": 95, "sts": 100}),
        ]},
        {"date": "2026-06-26", "board": [
            _rank_row(101, "Held Guy", 15, {"pipeline": 90, "hkb": 95, "sts": 100}),
            _rank_row(202, "First Sight", 12, {"pipeline": 88, "hkb": 92, "sts": 96}),
        ]},
        {"date": "2026-06-27", "board": []},  # both disappear into the roster
    ]
    roster = {"profiles": [
        {"mlbam_id": 101, "active_mlb_roster": True},
        {"mlbam_id": 202, "active_mlb_roster": True},
    ]}

    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-06-27T00:00:00+00:00",
    )
    by_key = {r["identity_key"]: r for r in payload["receipts"]}
    held = by_key["101_hitter"]
    first_sight = by_key["202_hitter"]

    # Anchor is call_up_date 2026-06-27; in-band on 06-26 and 06-25 (ranks 15,16 <= 19),
    # then 06-24 rank 15 <= 19 too -> a 3-day continuous run.
    assert held["flagged_days_early"] == 3
    # First Sight only appears on 06-26, which is the day before its 06-27 call-up... but
    # 06-26 IS strictly < anchor, rank 12 <= ceil(12*1.25)=15 -> 1 day. Verify it's present
    # and correct rather than absent (it has exactly one supporting day).
    assert first_sight.get("flagged_days_early") == 1

    # Additive-only guarantee: the shadow field never rewrites core semantics.
    assert held["call_up_date"] == "2026-06-27"
    assert "divergence" in held and isinstance(held["divergence"], int)
    # Sort order unchanged: _sort_receipts orders by divergence desc; assert it's still sorted.
    divs = [r["divergence"] for r in payload["receipts"]]
    assert divs == sorted(divs, reverse=True)


def test_build_truncates_run_at_out_of_band_day_end_to_end():
    """End-to-end continuity: the run stops at the first out-of-band day. Player 303's
    day-before-call-up rank is in-band but the day before THAT is out of band, so the run
    truncates. The zero-length omit path is covered directly by the helper unit test
    (a disappearance-detected auto row always has its own last on-board day in band, so
    its minimum end-to-end run is 1 -- the omit case needs no-earlier-archive/lagged real
    dates, exercised in the unit test)."""
    from prospects.call_up_receipts import build_call_up_receipts

    # Player 303 (claimed rank 10 -> band ceil(10*1.25)=13): in-band on 06-24 (rank 10) but
    # OUT of band on 06-23 (rank 40) -> the run truncates to exactly 1 in-band day.
    archives = [
        {"date": "2026-06-22", "board": [
            _rank_row(303, "Truncated Run", 9, {"pipeline": 90, "hkb": 95, "sts": 100}),
        ]},
        {"date": "2026-06-23", "board": [
            _rank_row(303, "Truncated Run", 40, {"pipeline": 90, "hkb": 95, "sts": 100}),
        ]},
        {"date": "2026-06-24", "board": [
            _rank_row(303, "Truncated Run", 10, {"pipeline": 90, "hkb": 95, "sts": 100}),
        ]},
        {"date": "2026-06-25", "board": []},  # disappears -> call_up_date 2026-06-25
    ]
    roster = {"profiles": [{"mlbam_id": 303, "active_mlb_roster": True}]}
    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-06-25T00:00:00+00:00",
    )
    receipt = payload["receipts"][0]
    # anchor 2026-06-25: 06-24 rank 10 <= 13 (1 day), 06-23 rank 40 > 13 breaks it. The
    # in-band 06-22 day (rank 9) is across the gap and must NOT be bridged.
    assert receipt.get("flagged_days_early") == 1


def test_receipts_page_renders_flagged_days_early_when_present(monkeypatch):
    """The template emits 'flagged Nd early' when a receipt row carries the field and
    omits it (no 'flagged' text) when the row does not."""
    import app as app_mod

    monkeypatch.setattr(app_mod, "RECEIPTS_HOLD", False)

    with_lead = {
        "identity_key": "1_hitter", "mlbam_id": "1", "role": "hitter",
        "name": "Lead Guy", "team": "BOS", "pos": "SS", "level": "AAA",
        "valucast_rank": 5, "consensus_rank": 60, "divergence": 55,
        "call_up_date": "2026-07-01", "flagged_days_early": 12,
    }
    without_lead = {
        "identity_key": "2_hitter", "mlbam_id": "2", "role": "hitter",
        "name": "No Lead Guy", "team": "NYY", "pos": "CF", "level": "AA",
        "valucast_rank": 7, "consensus_rank": 70, "divergence": 63,
        "call_up_date": "2026-07-02",
    }

    def fake_context():
        # Mirror the real _build_receipts_page_context return shape (receipts_hold comes
        # from the app context processor, so it isn't returned here).
        return {
            "receipts": [with_lead, without_lead],
            "receipt_count": 2,
            "misses": [],
            "miss_count": 0,
            "no_claim_call_up_count": 0,
            "receipts_available": True,
            "receipts_generated_at": "2026-07-09",
            "as_of": "2026-07-09",
        }

    monkeypatch.setattr(app_mod, "_build_receipts_page_context", fake_context)
    page = app_mod.app.test_client().get("/receipts").data.decode("utf-8")
    assert "flagged 12d early" in page  # present row rendered
    assert page.count("flagged") == 1  # the no-lead row did NOT render a flagged suffix


def _cu(mlbam_id: int, date: str) -> dict:
    """A genuine call-up transaction (typeCode SE) for the at-promotion standard tests."""
    return {
        "typeCode": "SE", "date": date, "effectiveDate": date,
        "person": {"id": mlbam_id, "fullName": str(mlbam_id)},
    }


def _cache(*transactions: dict) -> dict:
    return {"queries": {"q": {"transactions": list(transactions)}}}


def test_lagged_flip_rescored_from_at_promotion_archive_even_then_no_row():
    """Keys-shaped: a retention-flip event (7/04) postdates the real call-up (6/27). The
    board row on the flip day is a post-graduation collapse (rank 522 vs field 162 = a
    false -360 "miss"). Scored from the AT-PROMOTION archive (6/27, where the field had
    him even), the honest outcome is NO ROW -- so no miss is minted, and he lands in the
    neither bucket. Pre-fix this booked a false miss; that OLD behavior was the defect."""
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        # 6/27 = the real call-up archive: field even with us, no qualifying gap.
        {"date": "2026-06-27", "board": [
            _rank_row(101, "Sean-shaped", 160, {"pipeline": 162, "hkb": 165, "sts": 161})]},
        # 7/04: post-graduation collapse -- our rank craters to 522, manufacturing a
        # false miss if scored from THIS row. active_mlb_roster flips True here.
        {"date": "2026-07-03", "board": [
            _rank_row(101, "Sean-shaped", 522, {"pipeline": 162, "hkb": 246, "sts": 71})]},
        {"date": "2026-07-04", "board": [
            _rank_row(101, "Sean-shaped", 522, {"pipeline": 162, "hkb": 246, "sts": 71},
                      active_mlb_roster=True)]},
    ]
    roster = {"profiles": [{"mlbam_id": 101, "active_mlb_roster": True}]}
    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-07-04T00:00:00+00:00",
        transactions_cache=_cache(_cu(101, "2026-06-27")),
    )
    assert payload["misses"] == []  # the false -360 miss is gone
    assert payload["receipts"] == []
    assert payload["summary"]["no_claim_call_up_count"] == 1  # honest neither outcome


def test_no_consensus_at_promotion_produces_no_row():
    """Cabrera-shaped: at the real call-up the player had ZERO qualifying public boards
    (no computable consensus), so no honest row exists. A later contaminated event where
    boards reappear must NOT manufacture one -- it re-sources to the at-promotion archive
    and finds no consensus -> neither bucket."""
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        # 6/21 real call-up: no public boards rate him -> no consensus.
        {"date": "2026-06-21", "board": [_rank_row(101, "Jose-shaped", 377, {})]},
        {"date": "2026-07-03", "board": [
            _rank_row(101, "Jose-shaped", 962, {"hkb": 262, "sts": 107})]},
        {"date": "2026-07-04", "board": [
            _rank_row(101, "Jose-shaped", 962, {"hkb": 262, "sts": 107},
                      active_mlb_roster=True)]},
    ]
    roster = {"profiles": [{"mlbam_id": 101, "active_mlb_roster": True}]}
    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-07-04T00:00:00+00:00",
        transactions_cache=_cache(_cu(101, "2026-06-21")),
    )
    assert payload["misses"] == [] and payload["receipts"] == []
    assert payload["summary"]["no_claim_call_up_count"] == 1


def test_genuine_call_up_transaction_satisfies_roster_guard_when_off_todays_snapshot():
    """Murphy-shaped: real MLB debut, but optioned back down before today's roster
    snapshot was taken, so he's ABSENT from roster_lookup. A genuine call-up transaction
    is direct evidence he reached MLB -- the roster guard must accept it and mint the
    clean at-promotion hit. Pre-fix the today's-snapshot-only guard wrongly dropped him."""
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-07-06", "board": [
            _rank_row(101, "Owen-shaped", 26, {"pipeline": 90, "hkb": 146, "sts": 267})]},
        {"date": "2026-07-07", "board": [
            _rank_row(101, "Owen-shaped", 16, {"pipeline": 90, "hkb": 146, "sts": 267},
                      active_mlb_roster=True)]},
    ]
    roster = {"profiles": []}  # deliberately NOT on today's snapshot
    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-07-07T00:00:00+00:00",
        transactions_cache=_cache(_cu(101, "2026-07-06")),
    )
    keys = [r["identity_key"] for r in payload["receipts"]]
    assert keys == ["101_hitter"]  # minted despite absent from today's roster
    receipt = payload["receipts"][0]
    assert receipt["divergence"] == 120  # scored at promotion (vc 26 vs consensus 146)
    assert receipt["actual_call_up_date"] == "2026-07-06"


def test_il_style_phantom_disappearance_without_call_up_transaction_still_rejected():
    """The roster guard's original job is preserved: a disappearance with NO call-up
    transaction (an IL move / option / trade that delisted him, not a promotion) and no
    active-roster confirmation must still be rejected -- neither a row nor a neither-bucket
    entry (there's no evidence he reached MLB)."""
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-06-24", "board": [
            _rank_row(101, "Phantom", 20, {"pipeline": 90, "hkb": 95, "sts": 100})]},
        {"date": "2026-06-25", "board": []},  # disappears, but no call-up transaction
    ]
    roster = {"profiles": []}  # not on the roster either
    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-06-25T00:00:00+00:00",
        transactions_cache=_cache(),  # no transactions at all
    )
    assert payload["receipts"] == [] and payload["misses"] == []
    assert payload["summary"]["no_claim_call_up_count"] == 0  # not a confirmed call-up


def test_neither_bucket_counter_counts_genuine_no_claim_call_ups():
    """The neither-bucket counter tallies genuine post-launch call-ups that produced no
    row, and only those: a clean hit is a claim (not neither), a phantom disappearance is
    not a confirmed call-up (not counted), and a dead-even at-promotion call-up IS a
    genuine no-claim (counted)."""
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-06-24", "board": [
            _rank_row(101, "Clean Hit", 20, {"pipeline": 90, "hkb": 95, "sts": 100}),   # hit
            _rank_row(102, "Dead Even", 60, {"pipeline": 61, "hkb": 62, "sts": 60}),    # neither
            _rank_row(103, "Phantom", 20, {"pipeline": 90, "hkb": 95, "sts": 100}),     # no CU txn
        ]},
        {"date": "2026-06-25", "board": []},
    ]
    roster = {"profiles": [
        {"mlbam_id": 101, "active_mlb_roster": True},
        {"mlbam_id": 102, "active_mlb_roster": True},
    ]}
    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload=roster, existing_log={},
        seed_rows=[], generated_at="2026-06-25T00:00:00+00:00",
        transactions_cache=_cache(_cu(101, "2026-06-24"), _cu(102, "2026-06-24")),
    )
    assert [r["identity_key"] for r in payload["receipts"]] == ["101_hitter"]  # the hit
    assert payload["summary"]["no_claim_call_up_count"] == 1  # only the dead-even 102


def test_seed_field_label_derived_from_archive_not_typed_contradiction():
    """A seed the boards actually rank (Gabriel Hughes: 1 board, STS ~#512) must not
    render "field outside top 100" -- the label is derived from the same ranked-board
    archive the builder loads. 0 boards -> "no public board inside 600"; 1 board ->
    "1 board, ~#r"; >=2 boards -> "N boards, consensus ~#c". Label-only: divergence
    stays None (still a seed, never auto-scored)."""
    from prospects.call_up_receipts import build_call_up_receipts

    archives = [
        {"date": "2026-06-30", "board": [
            # 1 in-cap board (#512); the second (630) is over the 600 cap -> excluded.
            _rank_row(700, "One Board Deep", 9, {"sts": 512, "hkb": 630}),
            _rank_row(701, "Three Board", 55, {"sts": 90, "hkb": 162, "pl": 443}),
        ]},
        {"date": "2026-07-01", "board": []},  # keep archive quiet; seeds drive the labels
    ]
    seed = [
        {  # 1-board case (Hughes shape): typed label contradicts the archive
            "identity_key": "700_hitter", "mlbam_id": "700", "role": "hitter",
            "name": "One Board Deep", "valucast_rank": 9, "consensus_rank": None,
            "divergence": None, "field_label": "field outside top 100",
            "call_up_date": "2026-07-01",
        },
        {  # >=2 board case: a consensus actually exists, so report it
            "identity_key": "701_hitter", "mlbam_id": "701", "role": "hitter",
            "name": "Three Board", "valucast_rank": 55, "consensus_rank": None,
            "divergence": None, "field_label": "field outside top 100",
            "call_up_date": "2026-07-01",
        },
        {  # field-unranked case: no board in the archive at all
            "identity_key": "702_hitter", "mlbam_id": "702", "role": "hitter",
            "name": "Field Ignores Him", "valucast_rank": 41, "consensus_rank": None,
            "divergence": None, "field_label": "field outside top 100",
            "call_up_date": "2026-07-01",
        },
    ]
    payload = build_call_up_receipts(
        archive_payloads=archives, roster_payload={"profiles": []}, existing_log=[],
        seed_rows=seed, generated_at="2026-07-01T00:00:00+00:00",
    )
    by_key = {r["identity_key"]: r for r in payload["receipts"]}
    assert by_key["700_hitter"]["field_label"] == "1 board, ~#512"
    assert by_key["700_hitter"]["divergence"] is None  # still a seed, not auto-scored
    assert by_key["701_hitter"]["field_label"] == "3 boards, consensus ~#162"
    # No archive row for 702 -> nothing to derive from, typed label stands.
    assert by_key["702_hitter"]["field_label"] == "field outside top 100"


def test_validator_fails_seed_field_label_contradicted_by_a_board(tmp_path, monkeypatch):
    """The build-time validator is the honesty backstop: a typed "outside top N" label
    can't survive if a public board in the archive ranks the identity at <= N."""
    import json
    import scripts.validate_valucast_call_up_receipts as validator

    # An identity the archive ranks at #90 on STS but seeded "outside top 100".
    archive_index = {
        "2026-07-01": {
            "703_hitter": _rank_row(703, "Ranked But Typed Out", 20, {"sts": 90, "hkb": 162}),
        }
    }
    receipts = [{
        "identity_key": "703_hitter", "mlbam_id": "703", "role": "hitter",
        "name": "Ranked But Typed Out", "team": "BOS", "pos": "SS", "level": "AAA",
        "valucast_rank": 20, "consensus_rank": None, "divergence": None,
        "field_label": "field outside top 100", "call_up_date": "2026-07-01",
        "logged_at": "2026-07-01T00:00:00+00:00", "seed": True,
    }]
    problems = validator._field_label_contradictions(receipts, archive_index)
    assert any("outside top 100" in p and "sts" in p and "#90" in p for p in problems)

    # Full validate_file must FAIL when the artifact carries that contradicted label.
    # Point the validator's archive read at the synthetic index above.
    monkeypatch.setattr(validator, "_archive_payloads", lambda *a, **k: [])
    monkeypatch.setattr(validator, "_archive_by_date_key", lambda *a, **k: archive_index)
    payload = {
        "artifact": validator.ARTIFACT_NAME, "signal_version": validator.SIGNAL_VERSION,
        "generated_at": "2026-07-01T00:00:00+00:00", "status": "candidate_ready",
        "summary": {"receipt_count": 1, "miss_count": 0, "archive_dates_scanned": []},
        "source_policy": {flag: False for flag in (
            "name_matching_used", "feeds_model_score", "feeds_public_rank",
            "feeds_buy_score", "dd_values_used", "dd_ranks_used",
            "external_rankings_used", "market_values_used",
        )},
        "receipts": receipts, "misses": [],
    }
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    _payload, problems = validator.validate_file(artifact)
    assert any("outside top 100" in p for p in problems)


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
