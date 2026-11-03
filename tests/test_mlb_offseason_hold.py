"""Synthetic offseason availability checks; every fetch is injected."""

from datetime import date, timedelta
import json
from urllib.parse import parse_qs, urlparse

import pytest

from mlb.availability import (
    _archive_profiles,
    _fetch_game_logs,
    _fetch_schedule,
    availability_lookup,
    build_mlb_availability,
    run_mlb_availability,
)


def _day(day, state="Final"):
    return {
        "date": day,
        "games": [{"status": {"detailedState": state, "abstractGameState": "Final"}}],
    }


SCHEDULE = [
    _day("2026-07-31"),
    _day("2026-09-27"),
    _day("2026-09-28", "Postponed"),
    _day("2026-09-29", "Cancelled"),
]
PROJECTIONS = [{"metadata": {"mlbam_id": "101"}}]


def _tx(tx_id, day, description, player=101):
    return {
        "id": tx_id,
        "date": day,
        "effectiveDate": day,
        "person": {"id": player, "fullName": "Synthetic Player"},
        "description": description,
    }


def _placed(list_type="60-day", day="2026-08-01", tx_id=1):
    return _tx(tx_id, day, f"Club placed Player on the {list_type} injured list. Elbow surgery.")


def _activated(list_type="60-day", day="2026-11-02", tx_id=2):
    return _tx(tx_id, day, f"Club activated Player from the {list_type} injured list.")


def _build(transactions=None, as_of="2026-11-03", **kwargs):
    return build_mlb_availability(
        PROJECTIONS,
        generated_at=as_of,
        season=2026,
        transactions=transactions if transactions is not None else [_placed(), _activated()],
        schedule_fetcher=kwargs.pop("schedule_fetcher", lambda season: SCHEDULE if season == 2026 else []),
        game_log_fetcher=kwargs.pop("game_log_fetcher", lambda player, season, game_type: []),
        **kwargs,
    )


def _profile(payload):
    return availability_lookup(payload)["101"]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("Synthetic offseason tests must never access the network")
    monkeypatch.setattr("mlb.availability.urlopen", refuse)


def test_sixty_day_administrative_activation_preserves_season_end_profile():
    placement = _placed("15-day")
    transfer = _tx(2, "2026-08-20", "Club transferred Player to the 60-day injured list.")
    payload = _build([placement, transfer, _activated(tx_id=3)])
    profile = _profile(payload)
    assert profile["status"] == "injured"
    assert profile["active_injury_risk"] is True
    assert profile["list_type"] == "60-day injured list"
    assert profile["description"] == transfer["description"]
    assert profile["effective_date"] == "2026-08-20"
    assert profile["offseason_hold"] is True
    assert profile["held_since"] == "2026-11-02"
    summary = payload["validation"]["offseason_hold"]
    assert summary["active"] is True
    assert summary["season_end"] == "2026-09-27"
    assert summary["held_count"] == 1
    assert summary["stuck_count"] == 0
    assert payload["validation"]["risk_profile_count"] == 1


def test_reinstatement_uses_open_stint_not_activation_list_text():
    profile = _profile(_build([
        _placed(), _tx(2, "2026-11-02", "Club reinstated Player from the injured list."),
    ]))
    assert profile["status"] == "injured"
    assert profile["list_type"] == "60-day injured list"
    assert profile["offseason_hold"] is True


@pytest.mark.parametrize("list_type", ["7-day", "10-day", "15-day"])
def test_short_list_activation_is_accepted(list_type):
    profile = _profile(_build([_placed(list_type), _activated(list_type)]))
    assert profile["status"] == "available"
    assert not profile.get("offseason_hold")


def test_activation_before_season_end_is_not_held():
    profile = _profile(_build([_placed(), _activated(day="2026-09-20")]))
    assert profile["status"] == "available"
    assert not profile.get("offseason_hold")


def test_old_sixty_day_stint_does_not_hold_a_later_short_stint():
    profile = _profile(_build([
        _placed(), _activated(day="2026-08-10"),
        _placed("15-day", "2026-09-01", 3), _activated("15-day", tx_id=4),
    ]))
    assert profile["status"] == "available"
    assert not profile.get("offseason_hold")


def test_activation_closed_sixty_day_stint_even_if_later_rehab_has_no_placement():
    profile = _profile(_build([
        _placed(), _activated(day="2026-08-10"),
        _tx(3, "2026-09-20", "Club sent Player on a rehab assignment."),
        _activated(tx_id=4),
    ]))
    assert profile["status"] == "available"
    assert not profile.get("offseason_hold")


def test_rehab_on_top_of_sixty_day_stint_preserves_rehab_at_season_end():
    rehab = _tx(2, "2026-09-20", "Club sent Player on a rehab assignment.")
    profile = _profile(_build([_placed(), rehab, _activated(tx_id=3)]))
    assert profile["status"] == "rehab"
    assert profile["description"] == rehab["description"]
    assert profile["offseason_hold"] is True


@pytest.mark.parametrize("activated_again", [False, True])
def test_new_spring_placement_overrides_even_an_older_appearance(activated_again):
    transactions = [_placed(), _activated(), _placed("15-day", "2027-03-15", 3)]
    if activated_again:
        transactions.append(_activated("15-day", "2027-03-25", 4))
    profile = _profile(_build(
        transactions, as_of="2027-03-26",
        game_log_fetcher=lambda *args: [{"date": "2027-03-01"}],
    ))
    assert profile["status"] == ("available" if activated_again else "injured")
    assert profile["list_type"] == "15-day injured list"
    assert not profile.get("offseason_hold")
    assert not profile.get("hold_cleared")


@pytest.mark.parametrize("season,game_type,appearance", [
    (2026, "F", "2026-09-30"), (2026, "D", "2026-10-05"),
    (2026, "L", "2026-10-15"), (2026, "W", "2026-10-25"),
    (2027, "S", "2027-03-10"), (2027, "R", "2027-04-01"),
])
def test_appearance_clears_held_player(season, game_type, appearance):
    def game_logs(player, year, kind):
        assert player == "101"
        return [{"date": appearance}] if (year, kind) == (season, game_type) else []
    payload = _build(as_of="2027-04-02", game_log_fetcher=game_logs)
    profile = _profile(payload)
    assert profile["status"] == "available"
    assert profile["active_injury_risk"] is False
    assert not profile.get("offseason_hold")
    assert profile["hold_cleared"] == "game_appearance"
    assert profile["hold_cleared_date"] == appearance
    assert payload["validation"]["offseason_hold"]["cleared_by_appearance"] == 1
    assert _archive_profiles(payload) == []


def test_appearance_must_be_after_season_end_and_not_in_the_future():
    payload = _build(game_log_fetcher=lambda *args: [
        {"date": "2026-09-27"}, {"date": "2026-11-04"},
    ])
    assert _profile(payload)["offseason_hold"] is True


def test_release_requires_fourteen_distinct_played_dates():
    played = [_day((date(2027, 4, 1) + timedelta(days=i)).isoformat()) for i in range(13)]
    next_schedule = played + [played[0], _day("2027-04-14", "Cancelled"), _day("2027-04-15", "Postponed")]
    def schedule(year):
        return SCHEDULE if year == 2026 else next_schedule
    payload = _build(as_of="2027-04-16", schedule_fetcher=schedule)
    summary = payload["validation"]["offseason_hold"]
    assert summary["played_date_count"] == 13
    assert summary["release_state"] == "pending"
    assert _profile(payload)["offseason_hold"] is True
    # A future final must not release a historical as-of board.
    next_schedule.append(_day("2027-04-17", "Game Over"))
    assert _profile(_build(as_of="2027-04-16", schedule_fetcher=schedule))["offseason_hold"] is True
    payload = _build(as_of="2027-04-17", schedule_fetcher=schedule)
    assert _profile(payload)["status"] == "available"
    assert not _profile(payload).get("offseason_hold")
    assert payload["validation"]["offseason_hold"]["release_state"] == "released"
    assert payload["validation"]["offseason_hold"]["played_date_count"] == 14


@pytest.mark.parametrize("status", ["injured", "rehab"])
def test_released_while_hurt_stuck_player_clears_on_fourteen_played_dates(status):
    transactions = [_placed("15-day")]
    if status == "rehab":
        transactions.append(_tx(2, "2026-09-01", "Club sent Player on a rehab assignment."))
    transactions.append(_tx(3, "2026-10-01", "Club released Player."))
    before = _build(transactions)
    assert _profile(before)["status"] == status
    assert _profile(before)["offseason_hold"] is True
    assert before["validation"]["offseason_hold"]["stuck_count"] == 1
    played = [_day(f"2027-04-{day:02d}", "Completed Early") for day in range(1, 15)]
    after = _build(transactions, as_of="2027-04-14", schedule_fetcher=lambda year: SCHEDULE if year == 2026 else played)
    assert _profile(after)["status"] == "available"
    assert _profile(after)["active_injury_risk"] is False
    assert not _profile(after).get("offseason_hold")
    assert _archive_profiles(after) == []


def test_stuck_player_also_clears_on_appearance():
    payload = _build([_placed("15-day")], game_log_fetcher=lambda *args: [{"date": "2026-10-01"}])
    assert _profile(payload)["hold_cleared"] == "game_appearance"
    assert _profile(payload)["status"] == "available"


@pytest.mark.parametrize("description", [
    "Club traded Player.", "Club released Player.", "Player elected free agency.",
    "Player retired.", "Club designated Player for assignment.",
    "Club signed Player to a minor league contract.", "Club suspended Player.",
])
def test_unrelated_transactions_neither_set_nor_clear_holds(description):
    transaction = _tx(3, "2026-11-03", description)
    held = _profile(_build([_placed(), _activated(), transaction]))
    assert held["offseason_hold"] is True
    assert held["held_since"] == "2026-11-02"
    assert _build([transaction])["profiles"] == []


def _failed(*args):
    raise OSError("synthetic fetch failure")


def test_schedule_failure_without_season_end_retains_current_behavior():
    payload = _build(schedule_fetcher=_failed)
    assert _profile(payload)["status"] == "available"
    assert not payload["validation"]["offseason_hold"]["active"]
    assert payload["validation"]["offseason_hold_error"]


def test_schedule_without_played_games_disables_hold_with_error():
    payload = _build(schedule_fetcher=lambda year: [_day("2026-09-27", "Cancelled")])
    assert _profile(payload)["status"] == "available"
    assert payload["validation"]["offseason_hold"]["season_end"] is None
    assert payload["validation"]["offseason_hold_error"]


def test_next_season_schedule_failure_keeps_hold_when_season_end_is_known():
    def schedule(year):
        return SCHEDULE if year == 2026 else _failed()
    payload = _build(as_of="2027-04-20", schedule_fetcher=schedule)
    assert _profile(payload)["offseason_hold"] is True
    assert payload["validation"]["offseason_hold"]["active"] is True
    assert payload["validation"]["offseason_hold_error"]


@pytest.mark.parametrize("transactions", [None, [_placed("15-day")]])
def test_game_log_failure_keeps_players_hold(transactions):
    payload = _build(transactions, game_log_fetcher=_failed)
    assert _profile(payload)["offseason_hold"] is True
    assert _profile(payload)["status"] == "injured"
    assert payload["validation"]["offseason_hold_error"]


def test_game_log_failure_is_confined_to_one_player():
    def game_logs(player, year, game_type):
        if player == "101":
            raise OSError("synthetic player failure")
        return [{"date": "2026-10-01"}]
    transactions = [_placed(), _activated()]
    transactions += [dict(row, person={"id": 202}) for row in transactions]
    payload = build_mlb_availability(
        PROJECTIONS + [{"metadata": {"mlbam_id": "202"}}],
        transactions=transactions, generated_at="2026-11-03", season=2026,
        schedule_fetcher=lambda year: SCHEDULE, game_log_fetcher=game_logs,
    )
    lookup = availability_lookup(payload)
    assert lookup["101"]["offseason_hold"] is True
    assert lookup["202"]["status"] == "available"
    assert lookup["202"]["hold_cleared"] == "game_appearance"


@pytest.mark.parametrize("as_of", ["2026-08-02", "2026-09-28", "2026-09-29"])
def test_hold_is_off_on_or_before_last_scheduled_date(as_of):
    payload = _build([_placed(), _activated(day="2026-08-02")], as_of=as_of, game_log_fetcher=_failed)
    assert _profile(payload)["status"] == "available"
    assert not _profile(payload).get("offseason_hold")
    assert payload["validation"]["offseason_hold"]["active"] is False
    assert not payload["validation"].get("offseason_hold_error")


def test_hold_metadata_survives_risk_archive_selection():
    profile = _archive_profiles(_build())[0]
    assert profile["status"] == "injured"
    assert profile["offseason_hold"] is True
    assert profile["held_since"] == "2026-11-02"


def test_run_injects_fetchers_through_to_artifact(tmp_path):
    projection = tmp_path / "projection.json"
    projection.write_text(json.dumps(PROJECTIONS), encoding="utf-8")
    artifact = tmp_path / "availability.json"
    run_mlb_availability(
        projection_path=projection, metadata_path=tmp_path / "missing.json",
        artifact_path=artifact, cache_path=tmp_path / "cache.json", archive_dir=tmp_path / "archive",
        generated_at="2026-11-03", season=2026,
        fetcher=lambda start, end: [_placed(), _activated()],
        schedule_fetcher=lambda year: SCHEDULE, game_log_fetcher=lambda *args: [],
    )
    assert _profile(json.loads(artifact.read_text(encoding="utf-8")))["offseason_hold"] is True


def test_statsapi_fetchers_request_exact_schedule_and_both_game_log_groups(monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            if len(requests) == 1:
                return json.dumps({"dates": SCHEDULE}).encode()
            return json.dumps({"stats": [
                {"splits": [{"date": "2026-10-01"}]},
                {"splits": [{"date": "2026-10-02"}]},
            ]}).encode()

    def open_response(request, timeout):
        requests.append(urlparse(request.full_url))
        assert timeout == 45
        return Response()

    monkeypatch.setattr("mlb.availability.urlopen", open_response)
    assert _fetch_schedule(2026) == SCHEDULE
    assert parse_qs(requests[0].query) == {"sportId": ["1"], "gameType": ["R"], "season": ["2026"]}
    assert requests[0].path.endswith("/schedule")
    assert _fetch_game_logs("101", 2026, "W") == [{"date": "2026-10-01"}, {"date": "2026-10-02"}]
    assert parse_qs(requests[1].query) == {
        "stats": ["gameLog"], "group": ["hitting,pitching"], "season": ["2026"], "gameType": ["W"],
    }
    assert requests[1].path.endswith("/people/101/stats")
