import json

from scripts import archive_valucast_actuals_snapshot as snapshots


def _freeze():
    return {
        "sources": {
            "valucast_hp": {
                "rate_lines": {
                    "101": {"role": "hitter"},
                    "202": {"role": "pitcher"},
                }
            },
            "steamer_ros": {
                "rate_lines": {
                    "202": {"role": "starter"},
                    "303": {"role": "hitter"},
                }
            },
        }
    }


def test_player_roles_from_freeze_uses_union_of_both_sources():
    assert snapshots.player_roles_from_freeze(_freeze()) == {
        "101": "hitter",
        "202": "pitcher",
        "303": "hitter",
    }


def test_archive_actuals_snapshot_writes_atomically_and_skips_unchanged(tmp_path):
    payload = [{"metadata": {"mlbam_id": "101", "as_of": "2026-06-18"}}]

    path, changed = snapshots.archive_actuals_snapshot(
        payload, "2026-06-18", archive_dir=tmp_path,
    )
    second_path, second_changed = snapshots.archive_actuals_snapshot(
        payload, "2026-06-18", archive_dir=tmp_path,
    )

    assert path == tmp_path / "2026-06-18.json"
    assert second_path == path
    assert changed is True
    assert second_changed is False
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert not path.with_suffix(".json.tmp").exists()


def test_backfill_actuals_snapshot_scopes_to_frozen_source_players(tmp_path, monkeypatch):
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps(_freeze()), encoding="utf-8")
    called = {}

    def fake_build(player_roles, season, as_of, delay):
        called.update(
            {"player_roles": player_roles, "season": season, "as_of": as_of, "delay": delay}
        )
        return [{"metadata": {"mlbam_id": "101", "as_of": as_of}}]

    monkeypatch.setattr(snapshots, "build_historical_actuals", fake_build)

    result = snapshots.backfill_actuals_snapshot(
        "2026-06-18", season=2026, freeze_path=freeze_path,
        archive_dir=tmp_path / "archive", delay=0.0,
    )

    assert called == {
        "player_roles": {"101": "hitter", "202": "pitcher", "303": "hitter"},
        "season": 2026,
        "as_of": "2026-06-18",
        "delay": 0.0,
    }
    assert result["archive_changed"] is True
    assert result["row_count"] == 1
    assert result["archive_path"].endswith("2026-06-18.json")
