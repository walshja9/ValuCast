import json

from scripts import refresh_milb_card_history as refresh


HITTER_FIELDS = {
    "age",
    "avg",
    "bb_pct",
    "home_runs",
    "iso",
    "k_pct",
    "level",
    "mlbam_id",
    "obp",
    "plate_appearances",
    "role",
    "season",
    "slg",
    "stolen_bases",
    "team",
}

PITCHER_FIELDS = {
    "age",
    "bb_per_9",
    "era",
    "games_started",
    "innings_pitched",
    "is_starter",
    "k_bb_pct",
    "k_per_9",
    "level",
    "mlbam_id",
    "role",
    "season",
    "team",
    "whip",
}


def _hitter(name, mlbam_id, season, level):
    return {
        "age": 20,
        "avg": 0.275,
        "bb_pct": 10.0,
        "home_runs": 12,
        "iso": 0.180,
        "k_pct": 22.0,
        "level": level,
        "mlbam_id": mlbam_id,
        "name": name,
        "normalized_name": name.lower(),
        "obp": 0.350,
        "plate_appearances": 320,
        "role": "hitter",
        "slg": 0.455,
        "stolen_bases": 8,
        "team": "Test Bats",
        "walks": 32,
    }


def _pitcher(name, mlbam_id, season, level):
    return {
        "age": 21,
        "bb_per_9": 3.1,
        "era": 3.45,
        "games_started": 10,
        "innings_pitched": 60.0,
        "is_starter": True,
        "k_bb_pct": 18.5,
        "k_per_9": 10.2,
        "level": level,
        "mlbam_id": mlbam_id,
        "name": name,
        "normalized_name": name.lower(),
        "role": "pitcher",
        "team": "Test Arms",
        "whip": 1.18,
        "wins": 4,
    }


def _season(season, hitters=(), pitchers=()):
    return {"season": season, "hitters": list(hitters), "pitchers": list(pitchers)}


def _universe():
    return {
        "artifact": "valucast_prospect_universe",
        "players": [
            {"name": "Keep Hitter", "normalized_name": "keep hitter"},
            {"name": "Keep Pitcher", "normalized_name": "keep pitcher"},
            {"name": "Rookie Filter", "normalized_name": "rookie filter"},
        ],
    }


def test_build_card_history_filters_slims_and_orders_rows():
    artifact = refresh.build_card_history(
        [
            _season(
                2024,
                hitters=[
                    _hitter("Keep Hitter", 101, 2024, "AA"),
                    _hitter("Excluded Hitter", 999, 2024, "AA"),
                ],
                pitchers=[_pitcher("Keep Pitcher", 202, 2024, "AAA")],
            ),
            _season(
                2025,
                hitters=[
                    _hitter("Keep Hitter", 101, 2025, "AAA"),
                    _hitter("Rookie Filter", 303, 2025, "ROK"),
                ],
                pitchers=[
                    _pitcher("Keep Pitcher", 202, 2025, "A+"),
                    _pitcher("DSL Pitcher", 404, 2025, "DSL"),
                ],
            ),
        ],
        _universe(),
    )

    assert set(artifact["players"]) == {"keep hitter", "keep pitcher"}
    assert artifact["_meta"] == {"artifact": "milb_card_history", "players": 2}

    hitter_rows = artifact["players"]["keep hitter"]
    pitcher_rows = artifact["players"]["keep pitcher"]
    assert [row["season"] for row in hitter_rows] == [2025, 2024]
    assert [row["season"] for row in pitcher_rows] == [2025, 2024]

    assert set(hitter_rows[0]) == HITTER_FIELDS
    assert set(pitcher_rows[0]) == PITCHER_FIELDS
    assert all(row["mlbam_id"] for row in hitter_rows + pitcher_rows)
    assert {row["role"] for row in hitter_rows} == {"hitter"}
    assert {row["role"] for row in pitcher_rows} == {"pitcher"}
    assert all(row["level"] in refresh.LEVELS for row in hitter_rows + pitcher_rows)


def test_card_history_bytes_are_minified_and_deterministic():
    season_payloads = [
        _season(2025, hitters=[_hitter("Keep Hitter", 101, 2025, "AA")])
    ]

    first = refresh.card_history_bytes(
        refresh.build_card_history(season_payloads, _universe())
    )
    second = refresh.card_history_bytes(
        refresh.build_card_history(season_payloads, _universe())
    )

    assert first == second
    assert b"\n" not in first
    assert b": " not in first
    assert json.loads(first)["_meta"]["players"] == 1
