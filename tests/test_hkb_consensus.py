"""HKB consensus builder: normalized_name + org + age gating (no role on this source).
The board carries mlb_team + age; HKB's CSV carries Team + Age. A same-name row whose
team/age disagree must route to unmatched instead of silently re-keying onto a twin.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_hkb_consensus_snapshot as hkb  # noqa: E402
import fetch_hkb_source as fetcher  # noqa: E402
import run_daily_public_build  # noqa: E402


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


def test_daily_fetch_failure_preserves_last_good_pair(tmp_path, monkeypatch):
    source = tmp_path / "hkb_source.csv"
    snapshot = tmp_path / "hkb_consensus_snapshot.json"
    source.write_bytes(b"old source")
    snapshot.write_bytes(b"old snapshot")
    monkeypatch.setattr(fetcher, "OUT", source)
    monkeypatch.setattr(hkb, "SNAPSHOT_PATH", snapshot)
    monkeypatch.setattr(fetcher, "fetch_source", lambda _path: 1)
    monkeypatch.setattr(
        hkb,
        "build_hkb_snapshot",
        lambda: pytest.fail("builder must not run after a failed fetch"),
    )

    assert fetcher.refresh() == 0
    assert source.read_bytes() == b"old source"
    assert snapshot.read_bytes() == b"old snapshot"


def test_daily_refresh_promotes_source_and_snapshot_together(tmp_path, monkeypatch):
    source = tmp_path / "hkb_source.csv"
    snapshot = tmp_path / "hkb_consensus_snapshot.json"
    source.write_bytes(b"old source")
    snapshot.write_bytes(b"old snapshot")
    monkeypatch.setattr(fetcher, "OUT", source)
    monkeypatch.setattr(hkb, "SNAPSHOT_PATH", snapshot)

    def fake_fetch(path):
        path.write_bytes(b"new source")
        return 0

    def fake_build():
        hkb.SNAPSHOT_PATH.write_bytes(b"new snapshot")
        return {}

    monkeypatch.setattr(fetcher, "fetch_source", fake_fetch)
    monkeypatch.setattr(hkb, "build_hkb_snapshot", fake_build)

    assert fetcher.refresh() == 0
    assert source.read_bytes() == b"new source"
    assert snapshot.read_bytes() == b"new snapshot"


def test_daily_builder_failure_is_fatal_and_preserves_last_good_pair(tmp_path, monkeypatch):
    source = tmp_path / "hkb_source.csv"
    snapshot = tmp_path / "hkb_consensus_snapshot.json"
    source.write_bytes(b"old source")
    snapshot.write_bytes(b"old snapshot")
    monkeypatch.setattr(fetcher, "OUT", source)
    monkeypatch.setattr(hkb, "SNAPSHOT_PATH", snapshot)

    def fake_fetch(path):
        path.write_bytes(b"new source")
        return 0

    monkeypatch.setattr(fetcher, "fetch_source", fake_fetch)
    monkeypatch.setattr(hkb, "build_hkb_snapshot", lambda: (_ for _ in ()).throw(RuntimeError("bad join")))

    with pytest.raises(RuntimeError, match="bad join"):
        fetcher.refresh()
    assert source.read_bytes() == b"old source"
    assert snapshot.read_bytes() == b"old snapshot"


def test_hkb_refresh_is_wired_before_rank_and_staged_for_publish():
    steps = [" ".join(step) for step in run_daily_public_build.BUILD_STEPS]
    refresh = "scripts/fetch_hkb_source.py"
    assert steps.index("scripts/build_prospect_universe.py") < steps.index(refresh)
    assert steps.index(refresh) < steps.index("scripts/build_prospect_rank_v1.py")

    workflow = (ROOT / ".github/workflows/daily-public-data.yml").read_text(encoding="utf-8")
    assert "data/hkb/hkb_source.csv" in workflow
    assert "data/hkb/hkb_consensus_snapshot.json" in workflow
