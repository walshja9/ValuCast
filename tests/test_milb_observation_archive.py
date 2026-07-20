import json

import pytest

from scripts.archive_milb_observations import build_snapshot, write_snapshot


def _contract():
    return {
        "current": {
            "fetched_date": "2026-07-20",
            "season": 2026,
            "hitters": [
                {
                    "mlbam_id": 10,
                    "role": "hitter",
                    "team": "Erie SeaWolves",
                    "level": "AA",
                    "source_kind": "current_season",
                    "age": 20,
                    "plate_appearances": 120,
                    "iso": 0.190,
                    "k_pct": 18.0,
                    "bb_pct": 11.0,
                    "ops": 0.820,
                    "avg": 0.270,
                    "obp": 0.360,
                    "slg": 0.460,
                    "babip": 0.310,
                }
            ],
            "pitchers": [
                {
                    "mlbam_id": 20,
                    "role": "pitcher",
                    "team": "Toledo Mud Hens",
                    "level": "AAA",
                    "source_kind": "current_season",
                    "age": 23,
                    "innings_pitched": 50.0,
                    "k_per_9": 10.5,
                    "bb_per_9": 2.7,
                    "k_bb_pct": 24.0,
                    "era": 3.10,
                    "whip": 1.08,
                    "games_started": 8,
                    "is_starter": True,
                }
            ],
        }
    }


def test_snapshot_contains_only_registered_factual_fields_and_a_seal():
    snapshot = build_snapshot(_contract())
    assert snapshot["observation_date"] == "2026-07-20"
    assert [row["mlbam_id"] for row in snapshot["rows"]] == [10, 20]
    assert snapshot["rows"][0]["sample_unit"] == "PA"
    assert snapshot["rows"][1]["sample_unit"] == "IP"
    assert "outcome" not in json.dumps(snapshot)
    assert len(snapshot["input_sha256"]) == 64
    assert len(snapshot["content_sha256"]) == 64


def test_same_date_same_content_is_noop_but_changed_content_fails(tmp_path):
    snapshot = build_snapshot(_contract())
    path, status = write_snapshot(snapshot, tmp_path)
    assert status == "created"
    assert write_snapshot(snapshot, tmp_path) == (path, "unchanged")
    changed_contract = _contract()
    changed_contract["current"]["hitters"][0]["iso"] = 0.999
    changed = build_snapshot(changed_contract)
    with pytest.raises(ValueError, match="sealed date"):
        write_snapshot(changed, tmp_path)


def test_unknown_organization_stays_null_not_invented():
    contract = _contract()
    contract["current"]["hitters"][0]["team"] = "Unknown Club"
    row = build_snapshot(contract)["rows"][0]
    assert row["organization"] is None
    assert row["organization_status"] == "unknown"
