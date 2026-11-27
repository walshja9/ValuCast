"""Pipeline consensus builder: the source carries name + rank ONLY (no team/age/role),
so it can join only when a normalized name resolves to exactly one board identity.
A shared name (>=2 board ids) or an accented collision must route to unmatched.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_pipeline_consensus_snapshot as pipe  # noqa: E402


def _cand(mlbam, *, org="MIN", age=21, role="hitter"):
    return {"mlbam_id": mlbam, "org": org, "age": age, "role": role}


def _run(tmp_path, monkeypatch, players, index):
    src = tmp_path / "pipeline_top100.json"
    src.write_text(json.dumps({"players": players}), encoding="utf-8")
    monkeypatch.setattr(pipe, "SOURCE_PATH", src)
    monkeypatch.setattr(pipe, "SNAPSHOT_PATH", tmp_path / "out.json")
    monkeypatch.setattr(pipe, "_name_index", lambda: index)
    return pipe.build_pipeline_consensus_snapshot()


def test_ambiguous_name_routes_to_unmatched(tmp_path, monkeypatch):
    # Two board identities share the name; a name-only source cannot pick one.
    snap = _run(
        tmp_path, monkeypatch,
        [{"rank": 10, "name": "Carlos Sanchez"}],
        {"carlos sanchez": [_cand("800176"), _cand("801522", org="MIA")]},
    )
    assert snap["players_by_mlbam"] == {}
    assert [u["name"] for u in snap["unmatched"]] == ["Carlos Sanchez"]


def test_accented_name_does_not_silently_collide(tmp_path, monkeypatch):
    # "Luis Hernandez" normalizes across the accent; if the board holds two identities
    # under that key it stays unmatched rather than routing to either.
    snap = _run(
        tmp_path, monkeypatch,
        [{"rank": 46, "name": "Luis Hernandez"}],
        {"luis hernandez": [_cand("801346"), _cand("999999", org="SFG", age=17)]},
    )
    assert snap["players_by_mlbam"] == {}
    assert [u["name"] for u in snap["unmatched"]] == ["Luis Hernandez"]


def test_unique_name_still_matches(tmp_path, monkeypatch):
    snap = _run(
        tmp_path, monkeypatch,
        [{"rank": 1, "name": "Jesus Made"}],
        {"jesus made": [_cand("111", org="MIL", age=19)]},
    )
    assert snap["players_by_mlbam"]["111"]["pipeline_rank"] == 1
    assert snap["unmatched"] == []
