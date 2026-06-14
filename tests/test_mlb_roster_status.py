"""Tests for the ValuCast MLB active-roster status contract."""

from mlb.roster_status import active_roster_lookup, build_mlb_roster_status


def test_mlb_roster_status_uses_active_roster_mlbam_identities():
    payload = build_mlb_roster_status(
        generated_at="2026-06-14T12:00:00Z",
        season=2026,
        teams=[
            {
                "id": 137,
                "name": "San Francisco Giants",
                "abbreviation": "SF",
            }
        ],
        rosters_by_team={
            "137": [
                {
                    "person": {"id": 805811, "fullName": "Bryce Eldridge"},
                    "position": {
                        "abbreviation": "DH",
                        "name": "Designated Hitter",
                    },
                    "status": {"code": "A", "description": "Active"},
                    "parentTeamId": 137,
                }
            ]
        },
    )

    profile = active_roster_lookup(payload)["805811"]

    assert payload["artifact"] == "valucast_mlb_roster_status"
    assert payload["source_policy"]["name_matching_used"] is False
    assert payload["source_policy"]["official_mlb_rosters_used"] is True
    assert payload["validation"]["ready_for_public_snapshot"] is True
    assert payload["validation"]["active_roster_profile_count"] == 1
    assert profile["name"] == "Bryce Eldridge"
    assert profile["team_abbreviation"] == "SF"
    assert profile["active_mlb_roster"] is True


def test_mlb_roster_status_rejects_duplicate_active_mlbam_profiles():
    row = {
        "person": {"id": 805811, "fullName": "Bryce Eldridge"},
        "position": {"abbreviation": "DH", "name": "Designated Hitter"},
        "status": {"code": "A", "description": "Active"},
    }
    payload = build_mlb_roster_status(
        generated_at="2026-06-14T12:00:00Z",
        season=2026,
        teams=[{"id": 137, "name": "San Francisco Giants", "abbreviation": "SF"}],
        rosters_by_team={"137": [row, row]},
    )

    assert payload["validation"]["ready_for_public_snapshot"] is False
    assert payload["validation"]["duplicate_identity_count"] == 1
