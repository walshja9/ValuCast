"""Same-day call-up pulse = board prospects who are now on a fresh MLB roster."""
import json

from scripts.build_call_up_pulse import build_call_up_pulse


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _board(tmp_path):
    return _write(
        tmp_path / "board.json",
        {
            "generated_at": "2026-06-24T11:00:00+00:00",
            "board": [
                {"mlbam_id": 111, "role": "hitter", "name": "Promoted Guy", "rank": 12},
                {"mlbam_id": 222, "role": "pitcher", "name": "Still A Prospect", "rank": 30},
            ],
        },
    )


def _roster(tmp_path, active_ids):
    return _write(
        tmp_path / "roster.json",
        {
            "generated_at": "2026-06-24T20:00:00+00:00",
            "profiles": [
                {
                    "mlbam_id": mid,
                    "name": "X",
                    "team_abbreviation": "MIL",
                    "position": "CF",
                    "status_description": "Active",
                    "active_mlb_roster": True,
                }
                for mid in active_ids
            ],
        },
    )


def test_board_prospect_on_active_roster_is_flagged(tmp_path):
    payload = build_call_up_pulse(
        board_path=_board(tmp_path),
        roster_path=_roster(tmp_path, [111]),  # only #111 was called up
    )
    assert payload["summary"]["call_up_count"] == 1
    entry = payload["by_identity"]["111_hitter"]
    assert entry["name"] == "Promoted Guy"
    assert entry["mlb_team"] == "MIL"
    assert "222_pitcher" not in payload["by_identity"]
    # Display-only firewall.
    assert payload["source_policy"]["feeds_model_score"] is False


def test_no_call_ups_when_no_board_prospect_is_active(tmp_path):
    payload = build_call_up_pulse(
        board_path=_board(tmp_path),
        roster_path=_roster(tmp_path, [999]),  # an unrelated active player
    )
    assert payload["summary"]["call_up_count"] == 0
    assert payload["by_identity"] == {}


def test_missing_inputs_fail_soft(tmp_path):
    payload = build_call_up_pulse(
        board_path=tmp_path / "missing_board.json",
        roster_path=tmp_path / "missing_roster.json",
    )
    assert payload["status"] == "blocked"
    assert payload["by_identity"] == {}
    assert payload["source_policy"]["feeds_model_score"] is False
