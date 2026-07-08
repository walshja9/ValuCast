"""Tests for the two-sided consensus-gap board."""
from __future__ import annotations

import json
from pathlib import Path

from prospects.consensus_gap import build_consensus_gap_board

ROOT = Path(__file__).parent.parent


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


BOARDS_HIGH = {"hkb": 200, "pl": 210, "sts": 190}   # field ~#200
BOARDS_LOW = {"hkb": 20, "pl": 25, "sts": 15}       # field ~#20


def test_two_sided_split_uses_the_same_consensus_math():
    payload = build_consensus_gap_board({"board": [
        _rank_row(1, "Ahead Guy", 40, boards=BOARDS_HIGH),   # VC 40 vs ~200 -> higher
        _rank_row(2, "Fade Guy", 240, boards=BOARDS_LOW),    # VC 240 vs ~20 -> lower
        _rank_row(3, "Agree Guy", 21, boards=BOARDS_LOW),    # gap 1 -> neither
    ]})

    assert [row["name"] for row in payload["higher"]] == ["Ahead Guy"]
    assert payload["higher"][0]["divergence"] == 160
    assert [row["name"] for row in payload["lower"]] == ["Fade Guy"]
    assert payload["lower"][0]["divergence"] == -220
    # boards breakdown travels with every row — the receipt
    assert payload["higher"][0]["boards"] == {"hkb": 200, "pl": 210, "sts": 190}


def test_guards_thin_boards_callups_and_the_symmetric_depth_rule():
    payload = build_consensus_gap_board({"board": [
        # only 2 boards -> below the 3-board corroboration bar, both sides
        _rank_row(1, "Thin Ahead", 40, boards={"hkb": 200, "pl": 210}),
        # call-up exclusion: boards delist call-ups; that's eligibility, not disagreement
        _rank_row(2, "Called Up", 40, boards=BOARDS_HIGH, in_mlb=True),
        # symmetric depth rule, fade direction: VC #900 vs field #20 is a
        # sample-size statement, not a call
        _rank_row(3, "Tail Noise", 900, boards=BOARDS_LOW),
        _rank_row(4, "Real Fade", 250, boards=BOARDS_LOW),
        # symmetric depth rule, ahead direction (7/8 review): field ~#380 is
        # past the top-300 conversation, so this can't be an ahead call either
        _rank_row(5, "Deep Field", 60, boards={"hkb": 380, "pl": 390, "sts": 350}),
    ]})

    assert payload["higher"] == []
    assert [row["name"] for row in payload["lower"]] == ["Real Fade"]
    # no silent caps: qualified counts are disclosed even when rows are trimmed
    assert payload["summary"]["fade_qualified"] == 1
    assert payload["summary"]["evaluated"] == 5
    # fades must be explicitly marked as NOT ledger-scored
    assert payload["scoring"]["fade_scored_by_ledger"] is False
    assert payload["scoring"]["ahead_scored_by_ledger"] is True
    assert payload["source_policy"]["display_only"] is True


def test_live_roster_belt_excludes_same_day_callups():
    # Mirrors the AOTC belt: the committed rank artifact can predate the
    # active_mlb_roster stamp, so a live roster snapshot must also exclude.
    board = {"board": [_rank_row(7, "Fresh Callup", 40, boards=BOARDS_HIGH)]}

    without_belt = build_consensus_gap_board(board)
    assert [row["name"] for row in without_belt["higher"]] == ["Fresh Callup"]

    roster_status = {"profiles": [{"mlbam_id": "7", "active_mlb_roster": True}]}
    with_belt = build_consensus_gap_board(board, roster_status=roster_status)
    assert with_belt["higher"] == []


def test_gaps_page_drift_locks_to_the_committed_artifact():
    artifact = json.loads(
        (ROOT / "data" / "models" / "valucast_consensus_gap.json").read_text(encoding="utf-8")
    )
    import app as app_module
    client = app_module.app.test_client()
    html = client.get("/gaps").data.decode("utf-8")

    assert "WHERE WE DISAGREE" in html
    for row in artifact["higher"][:3] + artifact["lower"][:3]:
        assert row["name"] in html
        assert f"~#{row['consensus_rank']}" in html
    # the honesty spine: fades are published, not ledger-scored
    assert "not ledger-scored yet" in html
    assert "sample-size statement" in html
    # consensus provenance: same math as the AOTC surfaces
    assert "build_consensus_gap_board.py" in html


def test_gaps_wired_into_nav_llms_and_daily_build():
    from scripts import run_daily_public_build

    steps = [" ".join(step) for step in run_daily_public_build.BUILD_STEPS]
    assert steps.index("scripts/build_consensus_gap_board.py") > steps.index(
        "scripts/build_ahead_of_consensus.py"
    )
    workflow = (ROOT / ".github" / "workflows" / "daily-public-data.yml").read_text(encoding="utf-8")
    assert "data/models/valucast_consensus_gap.json" in workflow
    nav = (ROOT / "templates" / "partials" / "_board_nav.html").read_text(encoding="utf-8")
    assert '/gaps' in nav
    llms = (ROOT / "static" / "llms.txt").read_text(encoding="utf-8")
    assert "valucast.app/gaps" in llms
