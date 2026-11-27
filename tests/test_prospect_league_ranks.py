import importlib
import importlib.util
import json

import pytest


def _module():
    spec = importlib.util.find_spec("web.prospect_league_ranks")
    assert spec is not None
    return importlib.import_module("web.prospect_league_ranks")


def _covered_hitter_ids():
    payload = json.loads(_module()._ADAPTER_PATH.read_text(encoding="utf-8"))
    covered = []
    for preset in ("ops_7x7", "roto_5x5"):
        players = payload["presets"][preset]["roles"]["hitter"]["players"]
        covered.append({
            str(player["mlbam_id"]) for player in players
            if player.get("mlbam_id") is not None
            and isinstance(player.get("adapter_rank"), int)
            and player["adapter_rank"] >= 1
        })
    ids = covered[0] & covered[1]
    assert ids, "committed adapters must cover hitters in both surfaced formats"
    return ids


def test_loader_returns_format_ranks_for_covered_prospect():
    # ops_7x7 (split SV/HLD) ships in the committed adapters artifact as of 7/1;
    # dd_7x7 stays in the artifact but is deliberately no longer surfaced.
    # The artifact regenerates daily — assert structure, not ranks that drift.
    ranks = _module().format_ranks_for(sorted(_covered_hitter_ids())[0], "hitter")

    assert [r["label"] for r in ranks] == ["7x7 OPS", "5x5"]
    for r in ranks:
        assert isinstance(r["rank"], int) and r["rank"] >= 1
        assert r["total"] >= 1000
        assert r["total_label"] == f"{r['total']:,}"


def test_loader_returns_empty_list_for_unknown_player():
    assert _module().format_ranks_for("999999999", "hitter") == []


def test_loader_skips_entries_lacking_adapter_rank(tmp_path, monkeypatch):
    # Pin the coverage-refusal case independently of daily roster membership.
    path = tmp_path / "adapters.json"
    path.write_text(json.dumps({"presets": {
        "ops_7x7": {"roles": {"pitcher": {"players": [
            {"mlbam_id": "671936", "adapter_rank": 7},
        ]}}},
        "roto_5x5": {"roles": {"pitcher": {"players": [
            {"mlbam_id": "671936", "adapter_rank": None},
        ]}}},
    }}), encoding="utf-8")
    monkeypatch.setattr(_module(), "_ADAPTER_PATH", path)
    ranks = _module().format_ranks_for("671936", "pitcher")

    assert [r["label"] for r in ranks] == ["7x7 OPS"]
    assert isinstance(ranks[0]["rank"], int) and ranks[0]["rank"] >= 1


def test_player_detail_renders_format_ranks_for_covered_prospects():
    valucast_app = importlib.import_module("app")
    if not valucast_app.dd_store.is_available:
        pytest.skip("DD store not available")

    covered_ids = _covered_hitter_ids()
    covered = next((
        row for row in valucast_app.dd_store.get_all()
        if row.is_prospect and row.role == "hitter"
        and str(row.mlbam_id) in covered_ids
    ), None)
    assert covered is not None, "available snapshot must join covered prospect hitters"

    valucast_app.app.config["TESTING"] = True
    client = valucast_app.app.test_client()

    response = client.get(
        f"/player/{covered.id}?mode=prospects",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "format-ranks" in response.get_data(as_text=True)
