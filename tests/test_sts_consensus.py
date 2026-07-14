"""STS consensus builder: role (from hitter/pitcher CSV) + org + age gating.
The real 23yo MIN catcher must still match; a same-name/different-team row must not.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_sts_consensus_snapshot as sts  # noqa: E402


def _cand(mlbam, *, org, age, role):
    return {"mlbam_id": mlbam, "org": org, "age": age, "role": role}


_HEADER = "#,Name,Age,Level,Team,Pos,Avg Rank,Coverage\n"


def _write(tmp_path, monkeypatch, hitters, pitchers, index):
    hit = tmp_path / "hit.csv"
    pit = tmp_path / "pit.csv"
    hit.write_text(_HEADER + hitters, encoding="utf-8")
    pit.write_text(_HEADER + pitchers, encoding="utf-8")
    monkeypatch.setattr(sts, "HIT_CSV", hit)
    monkeypatch.setattr(sts, "PIT_CSV", pit)
    monkeypatch.setattr(sts, "_board_name_index", lambda: index)
    return sts.build_snapshot()


def test_real_min23_catcher_still_matches(tmp_path, monkeypatch):
    # The genuine STS row (MIN, 23, catcher -> hitter role) must resolve to 801346.
    snap = _write(
        tmp_path, monkeypatch,
        '"1319","Luis Hernandez","23","AAA","MIN","C","1289.6","5"\n',
        "",
        {"luis hernandez": [_cand("801346", org="MIN", age=23, role="hitter")]},
    )
    assert snap["players_by_mlbam"]["801346"]["name"] == "Luis Hernandez"
    assert snap["counts"]["unmatched"] == 0


def test_same_name_different_team_routes_to_unmatched(tmp_path, monkeypatch):
    # An STS row for a same-name player on a different org must not re-key onto 801346.
    snap = _write(
        tmp_path, monkeypatch,
        '"1319","Luis Hernandez","23","AAA","BOS","C","1289.6","5"\n',
        "",
        {"luis hernandez": [_cand("801346", org="MIN", age=23, role="hitter")]},
    )
    assert "801346" not in snap["players_by_mlbam"]
    assert [u["name"] for u in snap["unmatched"]] == ["Luis Hernandez"]


def test_org_alias_and_role_gate(tmp_path, monkeypatch):
    # Pitcher CSV -> pitcher role; source "KCR" maps to the board's "KC".
    snap = _write(
        tmp_path, monkeypatch,
        "",
        '"1","Some Arm","21","AA","KCR","","1.0","6"\n',
        {"some arm": [_cand("333", org="KC", age=21, role="pitcher")]},
    )
    assert snap["players_by_mlbam"]["333"]["role"] == "pitcher"
    assert snap["counts"]["unmatched"] == 0
