from contextlib import nullcontext
from datetime import datetime, timezone
from http.client import IncompleteRead
from unittest.mock import Mock, patch

from mlb import roster_display as source
from web import roster_event_display as display


def evidence(observations):
    return {
        "source": display.OFFICIAL_SOURCE,
        "effective_date": "2026-08-09",
        "season_start": "2026-03-25",
        "season_end": "2026-09-27",
        "by_mlbam": {
            player_id: {
                "on_40_man": True,
                "active_roster": True,
                "observed_at": observed,
            }
            for player_id, observed in observations.items()
        },
    }


def test_truncated_http_body_leaves_optional_evidence_empty():
    response = Mock()
    response.read.side_effect = IncompleteRead(b'{"roster":', 20)
    with patch.object(source, "urlopen", return_value=nullcontext(response)):
        assert source._fetch("/teams/158/roster", rosterType="active") == {}


def test_out_of_range_observation_does_not_hide_valid_neighbor():
    observed = "2026-08-09T20:00:00+00:00"
    payload = evidence({"100": "0001-01-01T00:00:00+00:00", "101": observed})

    assert display.qualified_roster_display(
        payload, now=datetime(2026, 8, 9, 22, tzinfo=timezone.utc),
    ) == {"101": payload["by_mlbam"]["101"]}


def test_z_observation_is_normalized_before_python310_parser():
    class Python310Datetime(datetime):
        @classmethod
        def fromisoformat(cls, value):
            if value.endswith("Z"):
                raise ValueError("Python 3.10 does not accept a trailing Z")
            return super().fromisoformat(value)

    payload = evidence({"101": "2026-08-09T20:00:00Z"})
    with patch.object(display, "datetime", Python310Datetime):
        assert display.qualified_roster_display(
            payload, now=datetime(2026, 8, 9, 22, tzinfo=timezone.utc),
        ) == {"101": payload["by_mlbam"]["101"]}


def test_40man_response_does_not_certify_60day_il_membership():
    now = datetime(2026, 8, 9, 22, tzinfo=timezone.utc)

    def fetch(path, **query):
        if path == "/seasons/2026":
            return {"seasons": [{
                "seasonId": "2026",
                "regularSeasonStartDate": "2026-03-25",
                "regularSeasonEndDate": "2026-09-27",
            }]}
        if path == "/teams":
            return {"teams": [{"id": i, "sport": {"id": 1}} for i in range(1, 31)]}
        team_id = int(path.split("/")[2])
        ids = range(team_id * 1000, team_id * 1000 + 40)
        if query["rosterType"] == "active":
            ids = range(team_id * 1000, team_id * 1000 + 26)
        roster = [{"person": {"id": player_id}, "status": {"code": "A"}} for player_id in ids]
        if query["rosterType"] == "40Man":
            roster.append({"person": {"id": team_id * 1000 + 99}, "status": {"code": "D60"}})
            if team_id == 2:
                roster.append({"person": {"id": 1000}, "status": {"code": "D60"}})
        return {"teamId": team_id, "rosterType": query["rosterType"], "roster": roster}

    result = source.collect_roster_display(fetch=fetch, clock=lambda: now)
    facts = display.qualified_roster_display(result, now=now)
    assert {"1099", "1000"}.isdisjoint(facts)
    assert facts["1001"]["on_40_man"] is True
    assert facts["1001"]["active_roster"] is True
    assert facts["1039"]["on_40_man"] is True
    assert facts["1039"]["active_roster"] is False


def test_roster_parser_rejects_missing_or_malformed_status_codes():
    for roster_type in ("active", "40Man"):
        for status in (None, "", " ", " A ", [], {}, 1):
            payload = {
                "teamId": 158,
                "rosterType": roster_type,
                "roster": [{"person": {"id": 1001}, "status": {"code": status}}],
            }
            assert source._roster_ids(payload, roster_type, "158") is None
