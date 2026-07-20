import copy

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
    assert set(snapshot) == {
        "artifact",
        "schema_version",
        "observation_date",
        "season",
        "source",
        "input_sha256",
        "rows",
        "content_sha256",
    }
    assert snapshot["observation_date"] == "2026-07-20"
    assert [row["mlbam_id"] for row in snapshot["rows"]] == [10, 20]
    hitter, pitcher = snapshot["rows"]
    hitter_fields = {
        "mlbam_id",
        "role",
        "organization",
        "organization_status",
        "minor_team",
        "level",
        "source_kind",
        "observation_date",
        "season",
        "age",
        "sample",
        "sample_unit",
        "rates",
    }
    assert set(hitter) == hitter_fields
    assert set(pitcher) == hitter_fields | {"role_facts"}
    assert set(hitter["rates"]) == {
        "iso",
        "k_pct",
        "bb_pct",
        "ops",
        "avg",
        "obp",
        "slg",
        "babip",
    }
    assert set(pitcher["rates"]) == {
        "k_per_9",
        "bb_per_9",
        "k_bb_pct",
        "era",
        "whip",
    }
    assert set(pitcher["role_facts"]) == {"games_started", "is_starter"}
    assert hitter["sample_unit"] == "PA"
    assert pitcher["sample_unit"] == "IP"
    forbidden_fragments = {
        "promotion",
        "transaction",
        "injur",
        "rank",
        "value",
        "outcome",
        "market",
        "availability",
        "external",
        "signal",
    }
    keys = set(snapshot) | set(hitter) | set(hitter["rates"]) | set(pitcher)
    keys |= set(pitcher["rates"]) | set(pitcher["role_facts"])
    assert not {
        key for key in keys if any(fragment in key for fragment in forbidden_fragments)
    }
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


def test_excluded_source_fields_do_not_change_snapshot_or_seals():
    baseline = build_snapshot(_contract())
    contract = _contract()
    contract["current"]["hitters"][0].update(
        {
            "availability_status": "injured",
            "availability_reason": "transaction",
            "pick_value": 9_999_999,
        }
    )

    changed = build_snapshot(contract)

    assert changed["input_sha256"] == baseline["input_sha256"]
    assert changed["content_sha256"] == baseline["content_sha256"]
    assert changed == baseline


def test_duplicate_id_multi_level_rows_are_order_independent():
    forward = _contract()
    second_level = copy.deepcopy(forward["current"]["hitters"][0])
    second_level.update(
        {
            "team": "West Michigan Whitecaps",
            "level": "A+",
            "plate_appearances": 80,
            "iso": 0.150,
        }
    )
    forward["current"]["hitters"].append(second_level)
    reversed_sources = copy.deepcopy(forward)
    reversed_sources["current"]["hitters"].reverse()

    forward_snapshot = build_snapshot(forward)
    reversed_snapshot = build_snapshot(reversed_sources)

    assert forward_snapshot["input_sha256"] == reversed_snapshot["input_sha256"]
    assert forward_snapshot["content_sha256"] == reversed_snapshot["content_sha256"]
    assert forward_snapshot == reversed_snapshot
