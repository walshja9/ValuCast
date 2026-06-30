"""ProspectsLive consensus source: role mapping, hyphen-aware join, dedup, and
that 'pl' counts toward (and is capped by) the public consensus median."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_prospectslive_consensus_snapshot as pl  # noqa: E402
from prospects.rank_v1 import _merge_external_consensus  # noqa: E402
from prospects.ahead_of_consensus import (  # noqa: E402
    _public_source_consensus,
    _public_source_ranks,
)


def test_role_from_pos():
    assert pl._role_from_pos("P") == "pitcher"
    assert pl._role_from_pos("SP") == "pitcher"
    assert pl._role_from_pos("SS") == "hitter"
    assert pl._role_from_pos("OF,P") == "hitter"  # two-way listed bat-position-first
    assert pl._role_from_pos("") == "hitter"


def test_norm_matches_board_hyphen_and_dot_spacing():
    # the board normalizes hyphen/dot to a space; the builder must match, not strip
    assert pl._norm("Devin Fitz-Gerald") == "devin fitz gerald"
    assert pl._norm("K.C. Hunt") == "k c hunt"
    assert pl._norm("José De Paula") == "jose de paula"  # accents dropped


def test_merge_injects_pl_rank():
    row = {"context_only": {"source_ranks": {}}}
    _merge_external_consensus(
        row, 123, {}, {}, {"123": {"pl_rank": 136}},
        {"123": {"pipeline_rank": 18}}, {"123": {"hkb_rank": 50}},
    )
    sr = row["context_only"]["source_ranks"]
    assert sr["pl"] == 136 and sr["pipeline"] == 18 and sr["hkb"] == 50


def test_pl_counts_toward_consensus_and_is_capped():
    ranks = _public_source_ranks({"hkb": 184, "sts": 481, "pl": 136})
    assert ranks["pl"] == 136
    assert _public_source_consensus(ranks) == 184  # median(136, 184, 481)
    # a pl rank past the 600 cap does not vote
    assert "pl" not in _public_source_ranks({"hkb": 184, "pl": 601})


def test_best_rank_wins_on_duplicate_join(tmp_path, monkeypatch):
    csv_path = tmp_path / "pl.csv"
    csv_path.write_text(
        "Tier,Rk,Player,Pos\n1,50,Same Guy,SS\n1,30,Same Guy,SS\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pl, "PL_CSV", csv_path)
    monkeypatch.setattr(pl, "_board_name_index", lambda: {"same guy": {"hitter": "999"}})
    snap = pl.build_snapshot()
    assert snap["players_by_mlbam"]["999"]["pl_rank"] == 30  # best (lowest) rank wins
    assert snap["counts"]["matched_to_mlbam"] == 1
