"""HKB consensus builder: normalized_name + org + age gating (no role on this source).
The board carries mlb_team + age; HKB's CSV carries Team + Age. A same-name row whose
team/age disagree must route to unmatched instead of silently re-keying onto a twin.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_hkb_consensus_snapshot as hkb  # noqa: E402


def _cand(mlbam, *, org, age, role="hitter"):
    return {"mlbam_id": mlbam, "org": org, "age": age, "role": role}


_HEADER = '"Rank","Name","Value","Age","Positions","Team","Level"\n'


def _write(tmp_path, monkeypatch, body, index):
    csv_path = tmp_path / "hkb.csv"
    csv_path.write_text(_HEADER + body, encoding="utf-8")
    monkeypatch.setattr(hkb, "SOURCE_CSV", csv_path)
    monkeypatch.setattr(hkb, "SNAPSHOT_PATH", tmp_path / "out.json")
    monkeypatch.setattr(hkb, "_name_index", lambda: index)
    return hkb.build_hkb_snapshot()


def test_team_age_mismatch_routes_to_unmatched(tmp_path, monkeypatch):
    # HKB "Luis Hernandez" is a 17.6yo SF shortstop; the board id is a 23yo MIN
    # catcher. Team AND age disagree -> unmatched, NOT players_by_mlbam.
    snap = _write(
        tmp_path, monkeypatch,
        '46,"Luis Hernandez",824,17.6,"SS","SF","ROOKIE_BALL"\n',
        {"luis hernandez": [_cand("801346", org="MIN", age=23)]},
    )
    assert "801346" not in snap["players_by_mlbam"]
    assert [u["name"] for u in snap["unmatched"]] == ["Luis Hernandez"]


def test_happy_path_team_and_age_match(tmp_path, monkeypatch):
    snap = _write(
        tmp_path, monkeypatch,
        '1,"Jesus Made",4168,19.2,"SS","MIL","AA"\n',
        {"jesus made": [_cand("111", org="MIL", age=19)]},
    )
    assert snap["players_by_mlbam"]["111"]["hkb_rank"] == 1
    assert snap["unmatched_count"] == 0


def test_org_alias_sf_matches_board_sfg(tmp_path, monkeypatch):
    # Source spells the team "SF"; the board spells it "SFG". The org map bridges them.
    snap = _write(
        tmp_path, monkeypatch,
        '5,"Some Giant",900,20,"SS","SF","AA"\n',
        {"some giant": [_cand("222", org="SFG", age=20)]},
    )
    assert snap["players_by_mlbam"]["222"]["hkb_rank"] == 5
    assert snap["unmatched_count"] == 0
