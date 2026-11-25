from contextlib import nullcontext
import ast
from datetime import datetime, timezone
from http.client import IncompleteRead
import json
import os
from pathlib import Path
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


def test_official_debut_date_covers_zero_pa_and_zero_outs_but_not_roster_membership():
    now = datetime(2026, 11, 25, 22, tzinfo=timezone.utc)
    requests = []

    def fetch(path, **query):
        requests.append((path, query))
        return {"people": [
            {"id": 100, "mlbDebutDate": "2026-08-09", "pa": 0},
            {"id": 101, "mlbDebutDate": "2026-08-10", "ip": 0},
            {"id": 102, "active": True},
            {"id": 999, "mlbDebutDate": "2026-08-09"},
        ]}

    result = source.collect_appearance_display([100, "100", 101, 102, True, "0100"], fetch=fetch, clock=lambda: now)
    assert requests == [("/people", {"personIds": "100,101,102"})]
    assert result["source"] == display.APPEARANCE_SOURCE
    assert display.qualified_appearance_display(result, now=now) == {
        "100": {"mlb_debut_date": "2026-08-09", "observed_at": now.isoformat()},
        "101": {"mlb_debut_date": "2026-08-10", "observed_at": now.isoformat()},
    }


def test_appearance_source_batches_ids_and_rejects_ambiguous_or_future_dates():
    now = datetime(2026, 11, 25, 22, tzinfo=timezone.utc)
    batches = []

    def fetch(path, **query):
        ids = query["personIds"].split(",")
        batches.append(ids)
        people = [{"id": int(player), "mlbDebutDate": "2026-08-09"} for player in ids]
        if "100" in ids:
            people += [{"id": 100, "mlbDebutDate": "2026-08-10"}]
        if "101" in ids:
            people += [{"id": 101, "mlbDebutDate": None}]
        if "102" in ids:
            people = [{**row, "mlbDebutDate": "2026-11-26"} if row["id"] == 102 else row for row in people]
        if "103" in ids:
            people = [{**row, "mlbDebutDate": "20260809"} if row["id"] == 103 else row for row in people]
        return {"people": people}

    result = source.collect_appearance_display(range(100, 205), fetch=fetch, clock=lambda: now)
    assert len(batches) == 2 and max(map(len, batches)) <= 100
    assert {"100", "101", "102", "103"}.isdisjoint(result["by_mlbam"])
    assert len(result["by_mlbam"]) == 101


def test_historical_appearance_evidence_has_no_roster_expiry_and_fails_closed():
    now = datetime(2026, 11, 25, 22, tzinfo=timezone.utc)
    good = {"mlb_debut_date": "2026-08-09", "observed_at": "2026-08-09T20:00:00Z"}
    payload = {"source": display.APPEARANCE_SOURCE, "by_mlbam": {
        "100": good,
        None: good,
        "0100": good,
        "101": {**good, "mlb_debut_date": "2026-08-10"},
        "102": {**good, "observed_at": "2026-11-26T00:00:00Z"},
        "103": {**good, "observed_at": "2026-08-09T20:00:00"},
        "104": {**good, "observed_at": "0001-01-01T00:00:00Z"},
        "105": {**good, "mlb_debut_date": "20260809"},
    }}
    assert display.qualified_appearance_display(payload, now=now) == {"100": good}
    assert display.qualified_appearance_display({**payload, "source": display.OFFICIAL_SOURCE}, now=now) == {}
    for bad in (None, [], "bad", {"source": display.APPEARANCE_SOURCE, "by_mlbam": []}):
        assert display.qualified_appearance_display(bad, now=now) == {}


def pulse_functions():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "scripts/build_call_up_pulse.py").read_text(encoding="utf-8"))
    names = {"_load", "_identity_key", "build_call_up_pulse", "run_call_up_pulse", "_appearance_player_ids", "main"}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == names
    namespace = {
        "json": json, "os": os, "datetime": datetime, "timezone": timezone, "Path": Path,
        "BOARD_PATH": None, "ROSTER_PATH": None, "ARTIFACT_PATH": None, "SCORECARD_PATH": None,
        "ARTIFACT_NAME": "valucast_call_up_pulse", "SIGNAL_VERSION": "0.1.0",
        "active_roster_lookup": lambda _: {"100": {"team_abbreviation": "MIL"}},
        "APPEARANCE_SOURCE": display.APPEARANCE_SOURCE,
        "qualified_appearance_display": display.qualified_appearance_display,
        "roster_id": display.roster_id,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<synthetic pulse>", "exec"), namespace)
    return namespace


def test_pulse_appearance_seeds_include_historical_calls_and_survive_failed_refresh(tmp_path):
    pulse = pulse_functions()
    board, roster, scorecard, artifact = (tmp_path / name for name in ("board.json", "roster.json", "scorecard.json", "pulse.json"))
    board.write_text(json.dumps({"board": [{"mlbam_id": 100, "role": "hitter"}]}), encoding="utf-8")
    roster.write_text(json.dumps({"profiles": [{"mlbam_id": 101}]}), encoding="utf-8")
    scorecard.write_text(json.dumps({"calls": [
        {"identity_key": "102_pitcher"}, {"identity_key": "0103_hitter"},
        {"identity_key": "104_unverified"}, {"identity_key": "105_pitcher_extra"},
    ]}), encoding="utf-8")
    observed = "2026-08-09T20:00:00Z"
    prior = {"mlb_debut_date": "2026-08-09", "observed_at": observed}
    artifact.write_text(json.dumps({
        "by_identity": {"106_pitcher": {"mlbam_id": "106"}},
        "appearance_display_evidence": {"source": display.APPEARANCE_SOURCE, "by_mlbam": {"107": prior}},
    }), encoding="utf-8")
    requests = []

    def appearance_fetcher(ids):
        requests.append(set(ids))
        return {"source": display.APPEARANCE_SOURCE, "by_mlbam": {"100": prior}}

    args = dict(board_path=board, roster_path=roster, scorecard_path=scorecard, artifact_path=artifact)
    pulse["run_call_up_pulse"](**args, appearance_fetcher=appearance_fetcher)
    result = json.loads(artifact.read_text(encoding="utf-8"))
    assert requests == [{"100", "101", "102", "106", "107"}]
    assert result.pop("appearance_display_evidence")["by_mlbam"] == {"100": prior, "107": prior}
    legacy = pulse["build_call_up_pulse"](board_path=board, roster_path=roster, generated_at=result["generated_at"])
    assert result == legacy
    pulse["run_call_up_pulse"](**args, appearance_fetcher=lambda _: {})
    result = json.loads(artifact.read_text(encoding="utf-8"))
    assert result["appearance_display_evidence"]["by_mlbam"] == {"100": prior, "107": prior}


def test_main_wires_official_appearance_collection_into_pulse():
    pulse = pulse_functions()
    calls = []
    pulse.update(
        collect_roster_display=object(), collect_appearance_display=object(),
        run_call_up_pulse=lambda **kwargs: calls.append(kwargs) or {"status": "fixture", "call_up_count": 0, "artifact_path": "fixture"},
    )
    assert pulse["main"]() == 0
    assert calls == [{
        "display_fetcher": pulse["collect_roster_display"],
        "appearance_fetcher": pulse["collect_appearance_display"], "scorecard_path": pulse["SCORECARD_PATH"],
    }]
