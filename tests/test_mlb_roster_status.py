"""Tests for the ValuCast MLB active-roster status contract."""

import json

import pytest

from mlb.roster_status import (
    active_roster_lookup,
    build_mlb_roster_status,
    run_mlb_roster_status,
)


def _roster_row(mlbam_id, name):
    return {
        "person": {"id": mlbam_id, "fullName": name},
        "position": {"abbreviation": "DH", "name": "Designated Hitter"},
        "status": {"code": "A", "description": "Active"},
    }


def _run_paths(tmp_path):
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({"as_of": "2026-06-14"}), encoding="utf-8")
    return {
        "metadata_path": metadata_path,
        "artifact_path": tmp_path / "roster_status.json",
        "cache_path": tmp_path / "roster_cache.json",
        "archive_dir": tmp_path / "archive",
    }


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


def test_empty_refetch_keeps_prior_cached_rows(tmp_path):
    paths = _run_paths(tmp_path)
    # Warm cache: team 137 previously had a real active roster.
    prior_rows = [_roster_row(805811, "Bryce Eldridge")]
    paths["cache_path"].write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "queries": {
                    "team:137:rosterType=active": {
                        "fetched_at": "2026-06-13T12:00:00Z",
                        "rows": prior_rows,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    payload = run_mlb_roster_status(
        paths["metadata_path"],
        paths["artifact_path"],
        paths["cache_path"],
        paths["archive_dir"],
        generated_at="2026-06-14T12:00:00Z",
        season=2026,
        teams_fetcher=lambda _season: [
            {"id": 137, "name": "San Francisco Giants", "abbreviation": "SF"}
        ],
        roster_fetcher=lambda _team_id: [],  # statsapi 200-with-empty-roster
        refresh=True,
    )

    # Prior rows survive in the published payload...
    assert payload["active_roster_profile_count"] == 1
    profiles = active_roster_lookup(
        json.loads(paths["artifact_path"].read_text(encoding="utf-8"))
    )
    assert profiles["805811"]["name"] == "Bryce Eldridge"

    # ...and in the saved cache (never overwritten with an empty rows list).
    saved = json.loads(paths["cache_path"].read_text(encoding="utf-8"))
    saved_rows = saved["queries"]["team:137:rosterType=active"]["rows"]
    assert len(saved_rows) == 1
    assert saved_rows[0]["person"]["id"] == 805811


def test_mass_empty_refetch_raises(tmp_path):
    paths = _run_paths(tmp_path)
    teams = [
        {"id": 100 + i, "name": f"Team {i}", "abbreviation": f"T{i}"}
        for i in range(6)
    ]
    # Warm cache so each team has prior rows to "keep" (which the raise guards).
    queries = {
        f"team:{team['id']}:rosterType=active": {
            "fetched_at": "2026-06-13T12:00:00Z",
            "rows": [_roster_row(9000 + i, f"Prior {i}")],
        }
        for i, team in enumerate(teams)
    }
    paths["cache_path"].write_text(
        json.dumps({"schema_version": "1.0", "queries": queries}), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="statsapi outage"):
        run_mlb_roster_status(
            paths["metadata_path"],
            paths["artifact_path"],
            paths["cache_path"],
            paths["archive_dir"],
            generated_at="2026-06-14T12:00:00Z",
            season=2026,
            teams_fetcher=lambda _season: teams,
            roster_fetcher=lambda _team_id: [],
            refresh=True,
        )
