import json

from mlb.playing_time_role import build_playing_time_role_tracker
from mlb.playing_time_role import run_playing_time_role_tracker
from scripts.validate_playing_time_role_tracker import validate_playing_time_role_tracker


def _hitter():
    return {
        "name": "Everyday Bat",
        "pool": "hitter",
        "team": "BOS",
        "positions": ["SS"],
        "stats": {"PA": 585},
        "metadata": {"mlbam_id": "100"},
    }


def _pitcher():
    return {
        "name": "Starter Arm",
        "pool": "starter",
        "team": "SEA",
        "positions": ["SP"],
        "stats": {"IP": 165, "GS": 28},
        "metadata": {"mlbam_id": "200"},
    }


def test_playing_time_tracker_uses_mlbam_keyed_status_context():
    payload = build_playing_time_role_tracker(
        projections=[_hitter(), _pitcher()],
        roster_status={
            "artifact": "valucast_mlb_roster_status",
            "generated_at": "2026-06-16",
            "profiles": [
                {
                    "mlbam_id": 100,
                    "active_mlb_roster": True,
                    "source": "official_mlb_statsapi_active_roster",
                }
            ],
        },
        availability={
            "artifact": "valucast_mlb_availability",
            "generated_at": "2026-06-16",
            "profiles": [
                {
                    "mlbam_id": 200,
                    "status": "rehab",
                    "active_injury_risk": True,
                    "source": "official_mlb_statsapi_transactions",
                }
            ],
        },
        generated_at="2026-06-16T00:00:00+00:00",
    )

    assert payload["artifact"] == "valucast_playing_time_role_tracker"
    assert payload["source_policy"]["name_based_joins_used"] is False
    assert payload["validation"]["ready_for_role_context"] is True
    hitter = next(row for row in payload["profiles"] if row["mlbam_id"] == "100")
    pitcher = next(row for row in payload["profiles"] if row["mlbam_id"] == "200")
    assert hitter["projected_role"] == "everyday_regular"
    assert hitter["identity_key"] == "100_hitter"
    assert hitter["active_mlb_roster"] is True
    assert pitcher["projected_role"] == "rotation_workhorse"
    assert pitcher["active_injury_risk"] is True


def test_run_and_validate_role_tracker(tmp_path):
    projection_path = tmp_path / "hp.json"
    roster_path = tmp_path / "roster.json"
    availability_path = tmp_path / "availability.json"
    artifact_path = tmp_path / "role.json"
    projection_path.write_text(json.dumps([_hitter(), _pitcher()]), encoding="utf-8")
    roster_path.write_text(json.dumps({"profiles": []}), encoding="utf-8")
    availability_path.write_text(json.dumps({"profiles": []}), encoding="utf-8")

    result = run_playing_time_role_tracker(
        projection_path=projection_path,
        roster_status_path=roster_path,
        availability_path=availability_path,
        artifact_path=artifact_path,
    )
    _, problems = validate_playing_time_role_tracker(artifact_path)

    assert result["ready_for_role_context"] is True
    assert problems == []
