"""Synthetic offseason availability checks; every fetch is injected."""

from datetime import date, timedelta
import json
import subprocess
import time
from urllib.parse import parse_qs, urlparse

import pytest
import mlb.availability as availability

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
    return _tx(tx_id, day, f"Club placed RHP Player on the {list_type} injured list. Elbow surgery.")


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
    transfer = _tx(2, "2026-08-20", "Club transferred RHP Player to the 60-day injured list.")
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
    assert summary["stale_count"] == 0
    assert summary["lookup_failure_count"] == 0
    assert summary["lookups_by_season"] == {"2026": {"attempted": 1, "failed": 0}}
    assert set(summary) == {
        "active", "season_end", "held_count", "stale_count", "cleared_by_appearance",
        "lookup_failure_count", "played_date_count", "release_state", "lookups_by_season",
    }
    assert profile["hold_note"] == (
        "End-of-season injury status held. MLB's offseason roster activation on 2026-11-02 "
        "is not treated as a return. This clears when the player appears in a game."
    )
    assert payload["contract_version"] == "0.2.0"
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
        assert kind == ("R,F,D,L,W" if year == 2026 else "S,R")
        return [{"date": appearance}] if year == season and game_type in kind.split(",") else []
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
def test_released_while_hurt_stale_player_clears_on_fourteen_played_dates(status):
    transactions = [_placed("15-day")]
    if status == "rehab":
        transactions.append(_tx(2, "2026-09-01", "Club sent Player on a rehab assignment."))
    transactions.append(_tx(3, "2026-10-01", "Club released Player."))
    before = _build(transactions)
    assert _profile(before)["status"] == status
    assert _profile(before)["stale_status"] is True
    assert not _profile(before).get("offseason_hold")
    assert before["validation"]["offseason_hold"]["stale_count"] == 1
    assert before["validation"]["offseason_hold"]["held_count"] == 0
    played = [_day(f"2027-04-{day:02d}", "Completed Early") for day in range(1, 15)]
    after = _build(transactions, as_of="2027-04-14", schedule_fetcher=lambda year: SCHEDULE if year == 2026 else played)
    assert _profile(after)["status"] == "available"
    assert _profile(after)["active_injury_risk"] is False
    assert not _profile(after).get("offseason_hold")
    assert _archive_profiles(after) == []
    assert after["validation"]["offseason_hold"]["stale_count"] == 0


def test_stale_player_also_clears_on_appearance():
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


def test_context_schedule_failure_raises():
    with pytest.raises(availability.OffseasonHoldLookupError, match="schedule 2026"):
        _build(schedule_fetcher=_failed)


def test_past_end_schedule_without_played_games_raises():
    with pytest.raises(availability.OffseasonHoldLookupError):
        _build(schedule_fetcher=lambda year: [_day("2026-09-27", "Cancelled")])


def test_next_season_schedule_failure_raises():
    def schedule(year):
        return SCHEDULE if year == 2026 else _failed()
    with pytest.raises(availability.OffseasonHoldLookupError, match="schedule 2027"):
        _build(as_of="2027-04-20", schedule_fetcher=schedule)


@pytest.mark.parametrize("transactions", [None, [_placed("15-day")]])
def test_game_log_failure_keeps_players_hold(transactions):
    payload = _build(transactions, game_log_fetcher=_failed)
    assert _profile(payload)["offseason_hold" if transactions is None else "stale_status"] is True
    assert _profile(payload)["status"] == "injured"
    assert payload["validation"]["offseason_hold_error"] == ["game_log 101: synthetic fetch failure"]
    assert payload["validation"]["offseason_hold"]["lookup_failure_count"] == 1


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
    assert payload["validation"]["offseason_hold"]["lookups_by_season"] == {}
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
        assert timeout == 15
        return Response()

    monkeypatch.setattr("mlb.availability.urlopen", open_response)
    assert _fetch_schedule(2026) == SCHEDULE
    assert parse_qs(requests[0].query) == {"sportId": ["1"], "gameType": ["R"], "season": ["2026"]}
    assert requests[0].path.endswith("/schedule")
    assert _fetch_game_logs("101", 2026, "R,F,D,L,W") == [{"date": "2026-10-01"}, {"date": "2026-10-02"}]
    assert parse_qs(requests[1].query) == {
        "stats": ["gameLog"], "group": ["hitting,pitching"], "season": ["2026"], "gameType": ["R,F,D,L,W"],
    }
    assert requests[1].path.endswith("/people/101/stats")
    _fetch_game_logs("101", 2027, "S,R")
    assert parse_qs(requests[2].query) == {
        "stats": ["gameLog"], "group": ["hitting,pitching"], "season": ["2027"], "gameType": ["S,R"],
    }


@pytest.mark.parametrize("position,held", [
    ("RHP", True), ("LHP", True), ("1B", False), ("DH", False),
    ("", False), ("XRHP", False), ("LHPX", False),
])
def test_only_whole_pitcher_tokens_in_open_stint_are_held(position, held):
    placement = _tx(1, "2026-08-01", f"Club placed {position} Player on the 60-day injured list.")
    activation = _tx(2, "2026-11-02", "Club activated RHP Player from the 60-day injured list.")
    payload = _build([placement, activation])
    profile = _profile(payload)
    assert bool(profile.get("offseason_hold")) is held
    assert profile["status"] == ("injured" if held else "available")
    assert payload["validation"]["offseason_hold"]["held_count"] == int(held)


@pytest.mark.parametrize("appearance,cleared", [
    ("2026-06-05", True), ("2026-06-01", False), ("2026-05-31", False),
])
def test_stale_rehab_appearance_window_starts_after_own_effective_date(appearance, cleared):
    payload = _build([
        _placed("15-day", "2026-05-01"),
        _tx(2, "2026-06-01", "Club sent Player on a rehab assignment."),
    ], game_log_fetcher=lambda *args: [{"date": appearance}])
    profile = _profile(payload)
    assert profile["status"] == ("available" if cleared else "rehab")
    assert bool(profile.get("stale_status")) is not cleared
    assert not profile.get("offseason_hold")
    assert not profile.get("held_since")
    assert payload["validation"]["offseason_hold"]["stale_count"] == int(not cleared)
    if cleared:
        assert profile["hold_cleared_date"] == "2026-06-05"


def test_stale_hitter_clears_by_regular_season_appearance():
    placement = _tx(1, "2026-06-01", "Club placed 1B Player on the 10-day injured list.")
    payload = _build([placement], game_log_fetcher=lambda *args: [{"date": "2026-06-05"}])
    assert _profile(payload)["status"] == "available"
    assert _profile(payload)["hold_cleared_date"] == "2026-06-05"


def test_stale_hitter_without_games_keeps_separate_flag_and_archive_field():
    payload = _build([_tx(1, "2026-06-01", "Club placed DH Player on the 60-day injured list.")])
    profile = _profile(payload)
    assert profile["status"] == "injured"
    assert profile["stale_status"] is True
    assert not profile.get("offseason_hold")
    assert not profile.get("held_since")
    assert _archive_profiles(payload)[0]["stale_status"] is True


@pytest.mark.parametrize("position", ["RHP", "LHP", "1B", "DH", ""])
@pytest.mark.parametrize("list_type", ["7-day", "10-day", "15-day", "60-day"])
def test_stale_status_applies_to_all_positions_and_lists(position, list_type):
    payload = _build([_tx(1, "2026-06-01", f"Club placed {position} Player on the {list_type} injured list.")])
    assert _profile(payload)["stale_status"] is True
    assert not _profile(payload).get("offseason_hold")
    assert payload["validation"]["offseason_hold"]["stale_count"] == 1


@pytest.mark.parametrize("transactions", [None, [_placed("15-day")]])
def test_appearance_on_as_of_date_clears(transactions):
    payload = _build(transactions, game_log_fetcher=lambda *args: [{"date": "2026-11-03"}])
    assert _profile(payload)["status"] == "available"
    assert _profile(payload)["hold_cleared_date"] == "2026-11-03"


def test_game_logs_use_one_union_lookup_per_year_and_earliest_qualifying_date():
    calls = []

    def logs(player, season, game_types):
        calls.append((player, season, game_types))
        return [{"date": "2026-10-10"}, {"date": "2026-09-27"}, {"date": "2026-10-01"}]

    payload = _build(as_of="2027-03-01", game_log_fetcher=logs)
    assert _profile(payload)["hold_cleared_date"] == "2026-10-01"
    assert calls == [("101", 2026, "R,F,D,L,W")]


def test_game_logs_next_year_union_only_when_as_of_year_is_later():
    calls = []

    def logs(*args):
        calls.append(args)
        return []

    _build(game_log_fetcher=logs)
    assert calls == [("101", 2026, "R,F,D,L,W")]
    calls.clear()
    _build(as_of="2027-03-01", game_log_fetcher=logs)
    assert calls == [("101", 2026, "R,F,D,L,W"), ("101", 2027, "S,R")]


def test_empty_context_schedule_raises():
    with pytest.raises(availability.OffseasonHoldLookupError):
        _build(schedule_fetcher=lambda year: [])


def test_empty_next_season_schedule_keeps_hold_pending():
    payload = _build(as_of="2027-06-01")
    summary = payload["validation"]["offseason_hold"]
    assert _profile(payload)["offseason_hold"] is True
    assert summary["release_state"] == "pending"
    assert summary["played_date_count"] == 0
    assert not payload["validation"].get("offseason_hold_error")


def _many_players(count, game_log_fetcher, as_of="2026-11-03", schedule_fetcher=None):
    transactions = []
    for player in range(101, 101 + count):
        transactions.extend(dict(row, person={"id": player}) for row in [_placed(), _activated()])
    return build_mlb_availability(
        [{"metadata": {"mlbam_id": str(player)}} for player in range(101, 101 + count)],
        transactions=transactions, generated_at=as_of, season=2026,
        schedule_fetcher=schedule_fetcher or (lambda year: SCHEDULE if year == 2026 else []),
        game_log_fetcher=game_log_fetcher,
    )


@pytest.mark.parametrize("counts,expected", [
    ({2026: (1, 1)}, None),
    ({2026: (2, 2)}, None),
    ({2026: (3, 3)}, "season 2026, 3 of 3"),
    ({2026: (3, 2)}, None),
    ({2026: (4, 3)}, None),
    ({2026: (5, 4)}, None),
    ({2026: (6, 5)}, "season 2026, 5 of 6"),
    ({2026: (49, 4)}, None),
    ({2026: (50, 5)}, "season 2026, 5 of 50"),
    ({2026: (51, 5)}, None),
    ({2026: (155, 15)}, None),
    ({2026: (155, 16)}, "season 2026, 16 of 155"),
    ({2026: (155, 0)}, None),
    ({2026: (0, 0)}, None),
    ({}, None),
    ({2026: (155, 0), 2027: (138, 138)}, "season 2027, 138 of 138"),
    ({2026: (155, 0), 2027: (138, 15)}, "season 2027, 15 of 138"),
    ({2026: (155, 0), 2027: (138, 13)}, None),
    ({2026: (3, 0), 2027: (3, 3)}, "season 2027, 3 of 3"),
    ({2026: (155, 4), 2027: (138, 4)}, None),
    ({2026: (20, 2), 2027: (20, 3)}, "all seasons, 5 of 40"),
    ({2026: (30, 3), 2027: (30, 2)}, None),
    ({2026: (2, 0), 2027: (2, 2)}, None),
    ({2027: (50, 5), 2026: (50, 5)}, "season 2026, 5 of 50"),
])
def test_offseason_hold_failure_message(counts, expected):
    lookups = {
        str(year): {"attempted": attempted, "failed": failed}
        for year, (attempted, failed) in counts.items()
    }
    message = availability._offseason_hold_failure_message(lookups)
    assert message == (f"Offseason hold game-log failures: {expected}" if expected else None)


def test_alternating_game_log_failures_raise_after_all_players():
    calls = []

    def logs(*args):
        calls.append(args)
        return _failed() if len(calls) % 2 else []

    with pytest.raises(availability.OffseasonHoldLookupError, match="season 2026, 10 of 20"):
        _many_players(20, logs)
    assert len(calls) == 20


def test_next_season_game_log_outage_raises_despite_current_season_successes():
    calls = []

    def logs(player, year, game_types):
        calls.append((player, year, game_types))
        return _failed() if year == 2027 else []

    with pytest.raises(availability.OffseasonHoldLookupError, match="season 2027, 20 of 20"):
        _many_players(20, logs, as_of="2027-03-01", schedule_fetcher=lambda year: (
            SCHEDULE if year == 2026 else [_day("2027-03-01")]
        ))
    assert len(calls) == 40


def test_spaced_failures_below_share_stop_publish_and_counts_reset_between_builds():
    def logs(player, *args):
        return _failed() if int(player) in range(101, 191, 10) else []

    payload = _many_players(100, logs)
    summary = payload["validation"]["offseason_hold"]
    assert len(payload["validation"]["offseason_hold_error"]) == 9
    assert summary["lookup_failure_count"] == 9
    assert summary["held_count"] == 100
    assert summary["lookups_by_season"] == {"2026": {"attempted": 100, "failed": 9}}

    clean = _many_players(100, lambda *args: [])
    assert not clean["validation"].get("offseason_hold_error")
    assert clean["validation"]["offseason_hold"]["lookup_failure_count"] == 0
    assert clean["validation"]["offseason_hold"]["held_count"] == 100
    assert clean["validation"]["offseason_hold"]["lookups_by_season"] == {
        "2026": {"attempted": 100, "failed": 0},
    }
    assert summary["lookups_by_season"] == {"2026": {"attempted": 100, "failed": 9}}


def test_exactly_five_consecutive_game_log_failures_raise():
    assert availability.HOLD_MAX_CONSECUTIVE_FAILURES == 5
    calls = []

    def logs(*args):
        calls.append(args)
        return _failed()

    with pytest.raises(availability.OffseasonHoldLookupError):
        _many_players(6, logs)
    assert len(calls) == 5


def test_four_failures_then_zero_games_then_four_failures_do_not_raise():
    def logs(player, *args):
        return _failed() if int(player) < 110 and player != "105" else []

    payload = _many_players(100, logs)
    assert len(payload["validation"]["offseason_hold_error"]) == 8
    assert payload["validation"]["offseason_hold"]["lookup_failure_count"] == 8
    assert payload["validation"]["offseason_hold"]["held_count"] == 100
    assert all(row["offseason_hold"] for row in payload["profiles"])


def test_success_with_games_resets_consecutive_failure_count():
    def logs(player, *args):
        if player == "105":
            return [{"date": "2026-10-01"}]
        return _failed() if int(player) < 110 else []

    payload = _many_players(100, logs)
    assert payload["validation"]["offseason_hold"]["lookup_failure_count"] == 8
    assert payload["validation"]["offseason_hold"]["cleared_by_appearance"] == 1
    assert payload["validation"]["offseason_hold"]["held_count"] == 99


def test_second_year_failure_counts_once_and_next_player_success_resets():
    calls = []

    def logs(player, year, game_types):
        calls.append((player, year, game_types))
        if int(player) > 110 or player == "106" or (player == "105" and year == 2026):
            return []
        return _failed()

    payload = _many_players(100, logs, as_of="2027-03-01")
    summary = payload["validation"]["offseason_hold"]
    assert summary["lookup_failure_count"] == 9
    assert summary["held_count"] == 100
    assert len(calls) == 192
    assert summary["lookups_by_season"] == {
        "2026": {"attempted": 100, "failed": 8}, "2027": {"attempted": 92, "failed": 1},
    }
    assert ("105", 2026, "R,F,D,L,W") in calls
    assert ("105", 2027, "S,R") in calls
    assert len([error for error in payload["validation"]["offseason_hold_error"] if "105:" in error]) == 1


def test_calls_skipped_after_failure_do_not_count():
    calls = []

    def logs(*args):
        calls.append(args)
        return _failed()

    payload = _many_players(2, logs, as_of="2027-03-01")
    assert len(calls) == 2
    assert all(call[1] == 2026 for call in calls)
    assert payload["validation"]["offseason_hold"]["lookup_failure_count"] == 2
    assert payload["validation"]["offseason_hold"]["lookups_by_season"] == {
        "2026": {"attempted": 2, "failed": 2},
    }


def test_consecutive_failure_count_is_reset_between_builds():
    def logs(player, *args):
        return _failed() if int(player) < 105 or int(player) > 196 else []

    for _ in range(2):
        payload = _many_players(100, logs)
        assert payload["validation"]["offseason_hold"]["lookup_failure_count"] == 8
        assert payload["validation"]["offseason_hold"]["held_count"] == 100


def test_schedule_calls_do_not_count_as_game_log_successes():
    schedule_calls, log_calls = [], []

    def schedule(year):
        schedule_calls.append(year)
        return SCHEDULE if year == 2026 else []

    def logs(*args):
        log_calls.append(args)
        return _failed()

    with pytest.raises(availability.OffseasonHoldLookupError):
        _many_players(5, logs, as_of="2027-03-01", schedule_fetcher=schedule)
    assert schedule_calls == [2026, 2027]
    assert len(log_calls) == 5


def test_budget_expires_before_schedule_lookup(monkeypatch):
    assert availability.HOLD_LOOKUP_BUDGET_SECONDS == 300
    times = iter([0, 301])
    monkeypatch.setattr(availability.time, "monotonic", lambda: next(times))
    calls = []
    with pytest.raises(availability.OffseasonHoldLookupError):
        _build(schedule_fetcher=lambda year: calls.append(year) or SCHEDULE)
    assert calls == []


def test_budget_expires_before_game_log_and_is_not_player_failure(monkeypatch):
    times = iter([0, 0, 301])
    monkeypatch.setattr(availability.time, "monotonic", lambda: next(times))
    calls = []
    with pytest.raises(availability.OffseasonHoldLookupError):
        _build(game_log_fetcher=lambda *args: calls.append(args) or [])
    assert calls == []


def test_alternating_failures_and_successes_stop_at_budget(monkeypatch):
    times = iter([0, 0, 0, 60, 120, 180, 240, 301])
    monkeypatch.setattr(availability.time, "monotonic", lambda: next(times))
    calls = []

    def logs(*args):
        calls.append(args)
        return [] if len(calls) % 2 == 0 else _failed()

    with pytest.raises(availability.OffseasonHoldLookupError):
        _many_players(10, logs)
    assert len(calls) == 5


@pytest.mark.parametrize("failure", ["schedule", "threshold", "budget", "aggregate"])
def test_lookup_abort_leaves_artifact_and_archive_bytes_untouched(tmp_path, monkeypatch, failure):
    players = range(101, 121) if failure == "aggregate" else [101]
    projection = tmp_path / "projection.json"
    projection.write_text(json.dumps([
        {"metadata": {"mlbam_id": str(player)}} for player in players
    ]), encoding="utf-8")
    transactions = [
        dict(row, person={"id": player}) for player in players for row in [_placed(), _activated()]
    ]
    artifact = tmp_path / "availability.json"
    artifact.write_bytes(b"existing artifact bytes\n")
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "existing.json").write_bytes(b"existing archive bytes\n")
    before = {path.name: path.read_bytes() for path in archive.iterdir()}
    if failure == "threshold":
        monkeypatch.setattr(availability, "HOLD_MAX_CONSECUTIVE_FAILURES", 1)
    if failure == "budget":
        times = iter([0, 0, 301])
        monkeypatch.setattr(availability.time, "monotonic", lambda: next(times))

    def logs(player, *args):
        return _failed() if failure == "threshold" or (failure == "aggregate" and int(player) % 2) else []

    with pytest.raises(
        availability.OffseasonHoldLookupError,
        match="season 2026, 10 of 20" if failure == "aggregate" else None,
    ):
        run_mlb_availability(
            projection_path=projection, metadata_path=tmp_path / "missing.json",
            artifact_path=artifact, cache_path=tmp_path / "cache.json", archive_dir=archive,
            generated_at="2026-11-03", season=2026,
            fetcher=lambda start, end: transactions,
            schedule_fetcher=_failed if failure == "schedule" else lambda year: SCHEDULE,
            game_log_fetcher=logs,
        )
    assert artifact.read_bytes() == b"existing artifact bytes\n"
    assert {path.name: path.read_bytes() for path in archive.iterdir()} == before
    assert not artifact.with_suffix(".json.tmp").exists()


def test_daily_build_step_timeout_stops_real_child_process(monkeypatch):
    from scripts import run_daily_public_build as daily

    monkeypatch.setattr(daily, "STAGES", {"build": [("-c", "import time; time.sleep(30)")]})
    monkeypatch.setattr(daily, "STEP_TIMEOUT_SECONDS", {"-c": 1})
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        daily.run_stage("build")
    assert time.monotonic() - started < 10


def test_build_script_prints_hold_counts(monkeypatch, capsys):
    from scripts import build_mlb_availability as builder

    monkeypatch.setattr(builder, "run_mlb_availability", lambda **kwargs: {
        "profile_count": 3, "risk_profile_count": 2, "transaction_count": 100,
        "archive_changed": False, "fetched": False, "artifact_path": "synthetic.json",
        "ready_for_mlb_dynasty_layer": True,
        "offseason_hold": {
            "held_count": 1, "stale_count": 2, "cleared_by_appearance": 3,
            "lookup_failure_count": 4,
        },
    })
    monkeypatch.setattr("sys.argv", ["build_mlb_availability.py"])
    builder.main()
    output = capsys.readouterr().out
    assert "held=1 stale=2 cleared=3 lookup_failures=4" in output


def test_validator_prints_individual_warnings_without_failing(tmp_path, monkeypatch, capsys):
    from scripts import validate_mlb_availability as validator

    payload = _build(game_log_fetcher=_failed)
    payload["validation"]["transaction_count"] = 100
    payload["validation"]["offseason_hold_error"].append("game_log 202: another failure")
    path = tmp_path / "availability.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    validate = validator.validate_mlb_availability
    monkeypatch.setattr(validator, "ARTIFACT_PATH", path)
    monkeypatch.setattr(validator, "validate_mlb_availability", lambda: validate(path))
    assert validator.main() == 0
    output = capsys.readouterr().out.splitlines()
    assert output[0].startswith("MLB availability contract valid:")
    assert output[1:] == [
        "WARNING: game_log 101: synthetic fetch failure",
        "WARNING: game_log 202: another failure",
    ]
