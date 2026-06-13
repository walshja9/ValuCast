"""Tests for current-projection identity backfill."""
import json

from scripts.backfill_projection_identities import (
    backfill_projection_identities,
    eligible_projection_mlbam_ids,
    missing_identity_ids,
    projection_mlbam_ids,
)


def test_projection_mlbam_ids_reads_metadata_and_top_level_ids(tmp_path):
    path = tmp_path / "current.json"
    path.write_text(
        json.dumps(
            [
                {"metadata": {"mlbam_id": 7}},
                {"metadata": {"mlbam_id": "5"}},
                {"mlbam_id": "9"},
                {"metadata": {}},
            ]
        ),
        encoding="utf-8",
    )

    assert projection_mlbam_ids(path) == ["5", "7", "9"]


def test_missing_identity_ids_requires_birth_date():
    assert missing_identity_ids(
        ["1", "2", "3"],
        {
            "1": {"birth_date": "2000-01-01"},
            "2": {"name": "No DOB"},
        },
    ) == ["2", "3"]


def test_backfill_merges_missing_identities_without_overwriting_existing(tmp_path):
    projection_path = tmp_path / "current.json"
    projection_path.write_text(
        json.dumps(
            [
                {
                    "id": "one",
                    "name": "One",
                    "pool": "hitter",
                    "positions": ["OF"],
                    "stats": {"PA": 600},
                    "metadata": {"mlbam_id": "1"},
                },
                {
                    "id": "two",
                    "name": "Two",
                    "pool": "starter",
                    "positions": ["SP"],
                    "stats": {"IP": 180},
                    "metadata": {"mlbam_id": "2"},
                },
                {
                    "id": "thin",
                    "name": "Thin",
                    "pool": "hitter",
                    "positions": ["OF"],
                    "stats": {"PA": 5},
                    "metadata": {"mlbam_id": "3"},
                },
            ]
        ),
        encoding="utf-8",
    )
    data_dir = tmp_path / "identity"
    data_dir.mkdir()
    (data_dir / "identity.json").write_text(
        json.dumps({"1": {"name": "Existing", "birth_date": "2001-01-01"}}),
        encoding="utf-8",
    )

    def fake_fetch(ids):
        assert ids == ["2"]
        return {"2": {"name": "Fetched", "birth_date": "2002-02-02"}}

    result = backfill_projection_identities(
        projection_path=projection_path,
        identity_data_dir=data_dir,
        fetcher=fake_fetch,
    )

    assert result["projected_id_count"] == 2
    assert result["missing_before"] == 1
    assert result["fetched_count"] == 1
    assert result["missing_after"] == 0
    stored = json.loads((data_dir / "identity.json").read_text(encoding="utf-8"))
    assert stored["1"]["name"] == "Existing"
    assert stored["2"]["name"] == "Fetched"
    assert "3" not in stored


def test_eligible_projection_mlbam_ids_uses_mlb_layer_playing_time_gate(tmp_path):
    path = tmp_path / "current.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "eligible",
                    "name": "Eligible",
                    "pool": "hitter",
                    "positions": ["OF"],
                    "stats": {"PA": 100},
                    "metadata": {"mlbam_id": "1"},
                },
                {
                    "id": "thin",
                    "name": "Thin",
                    "pool": "starter",
                    "positions": ["SP"],
                    "stats": {"IP": 39.9},
                    "metadata": {"mlbam_id": "2"},
                },
            ]
        ),
        encoding="utf-8",
    )

    assert eligible_projection_mlbam_ids(path) == ["1"]
