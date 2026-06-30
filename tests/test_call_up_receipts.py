"""Tests for permanent ValuCast call-up receipts."""
from __future__ import annotations

from pathlib import Path


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


def _rank_row(mlbam_id: int, name: str, rank: int, source_ranks: dict) -> dict:
    return {
        "mlbam_id": mlbam_id,
        "role": "hitter",
        "name": name,
        "mlb_team": "BOS",
        "positions": ["SS", "2B"],
        "level": "AAA",
        "rank": rank,
        "context_only": {"source_ranks": source_ranks},
    }
