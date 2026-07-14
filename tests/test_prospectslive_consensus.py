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


_HEADER = "Rk,Player,Pos,Team,Level,Age,Min,Max,App,Var,High,Low,Greg,Kyle,PJ,Tom"


def _cand(mlbam, *, org, age, role):
    return {"mlbam_id": mlbam, "org": org, "age": age, "role": role}


def test_best_rank_wins_on_duplicate_join(tmp_path, monkeypatch):
    csv_path = tmp_path / "pl.csv"
    csv_path.write_text(
        _HEADER + "\n"
        "50,Same Guy,SS,BOS,AA,21,,,,,,,,,,\n"
        "30,Same Guy,SS,BOS,AA,21,,,,,,,,,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pl, "PL_CSV", csv_path)
    monkeypatch.setattr(
        pl, "_board_name_index",
        lambda: {"same guy": [_cand("999", org="BOS", age=21, role="hitter")]},
    )
    snap = pl.build_snapshot()
    assert snap["players_by_mlbam"]["999"]["pl_rank"] == 30  # best (lowest) rank wins
    assert snap["counts"]["matched_to_mlbam"] == 1


def test_team_age_mismatch_routes_to_unmatched(tmp_path, monkeypatch):
    # The 17.6yo SFG shortstop "Luis Hernandez" must NOT re-route onto the board's
    # 23yo MIN catcher of the same normalized name (mlbam 801346). Team AND age
    # disagree -> unmatched, never players_by_mlbam.
    csv_path = tmp_path / "pl.csv"
    csv_path.write_text(
        _HEADER + "\n35,Luis Hernandez,SS,SFG,CPX,17.6,,,,,,,,,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pl, "PL_CSV", csv_path)
    monkeypatch.setattr(
        pl, "_board_name_index",
        lambda: {"luis hernandez": [_cand("801346", org="MIN", age=23, role="hitter")]},
    )
    snap = pl.build_snapshot()
    assert "801346" not in snap["players_by_mlbam"]
    assert snap["counts"]["matched_to_mlbam"] == 0
    assert [u["name"] for u in snap["unmatched"]] == ["Luis Hernandez"]


def test_team_and_age_match_joins(tmp_path, monkeypatch):
    # The real identity (org + age agree, org via the SF->SFG normalization) matches.
    csv_path = tmp_path / "pl.csv"
    csv_path.write_text(
        _HEADER + "\n1,Real Guy,SS,SF,AA,21.4,,,,,,,,,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pl, "PL_CSV", csv_path)
    monkeypatch.setattr(
        pl, "_board_name_index",
        lambda: {"real guy": [_cand("555", org="SFG", age=21, role="hitter")]},
    )
    snap = pl.build_snapshot()
    assert snap["players_by_mlbam"]["555"]["pl_rank"] == 1
    assert snap["counts"]["matched_to_mlbam"] == 1


def test_per_ranker_columns_never_persisted(tmp_path, monkeypatch):
    csv_path = tmp_path / "pl.csv"
    csv_path.write_text(
        _HEADER + "\n1,Real Guy,SS,BOS,AA,21,1,1,4,0.0,Tie,Tie,1,1,1,1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pl, "PL_CSV", csv_path)
    monkeypatch.setattr(
        pl, "_board_name_index",
        lambda: {"real guy": [_cand("555", org="BOS", age=21, role="hitter")]},
    )
    snap = pl.build_snapshot()
    record = snap["players_by_mlbam"]["555"]
    assert set(record) == {"name", "role", "pl_rank", "mlbam_id"}
    for banned in ("Greg", "Kyle", "PJ", "Tom", "Min", "Max", "App", "Var", "High", "Low"):
        assert banned not in record


def test_source_as_of_is_csv_mtime(tmp_path, monkeypatch):
    csv_path = tmp_path / "pl.csv"
    csv_path.write_text(_HEADER + "\n1,Real Guy,SS,BOS,AA,21,,,,,,,,,,\n", encoding="utf-8")
    monkeypatch.setattr(pl, "PL_CSV", csv_path)
    monkeypatch.setattr(
        pl, "_board_name_index",
        lambda: {"real guy": [_cand("555", org="BOS", age=21, role="hitter")]},
    )
    snap = pl.build_snapshot()
    import datetime as _dt
    expected = _dt.datetime.fromtimestamp(
        csv_path.stat().st_mtime, _dt.timezone.utc
    ).date().isoformat()
    assert snap["source_as_of"] == expected
    assert "generated_at" in snap
