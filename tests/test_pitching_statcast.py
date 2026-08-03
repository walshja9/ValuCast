import copy
import json

import pytest

from projections.data.pitching_statcast import (
    MIN_INPUT_PITCHES,
    add_pitch,
    finalize_season,
    merge_accumulators,
    normalize_pitch_type,
)


def _pitch(pitcher=101, **overrides):
    row = {
        "pitcher": pitcher,
        "pitch_type": "FF",
        "description": "ball",
        "plate_x": 0.0,
        "plate_z": 2.5,
        "sz_top": 3.5,
        "sz_bot": 1.5,
        "release_speed": 95.0,
        "pfx_x": -0.5,
        "pfx_z": 1.25,
        "release_spin_rate": 2400,
        "release_extension": 6.5,
        "release_pos_x": -2.0,
        "release_pos_z": 5.8,
    }
    row.update(overrides)
    return row


def _aggregate(rows, eligible=("101",)):
    acc = {}
    for row in rows:
        add_pitch(acc, row, set(eligible))
    return acc


def _repeat(row, count):
    return [dict(row) for _ in range(count)]


def test_normalize_pitch_type_uses_the_registered_mapping():
    expected = {
        "FF": "four_seam",
        "FA": "four_seam",
        "SI": "sinker",
        "FC": "cutter",
        "SL": "slider",
        "ST": "sweeper",
        "CU": "curveball",
        "KC": "curveball",
        "CS": "curveball",
        "CH": "changeup",
        "FS": "splitter",
        "FO": "splitter",
        "KN": "knuckleball",
        "EP": "other",
        "": "other",
        None: "other",
    }

    assert {code: normalize_pitch_type(code) for code in expected} == expected
    assert normalize_pitch_type(" ff ") == "four_seam"


def test_add_pitch_uses_string_mlbam_identity_and_filters_the_universe():
    acc = {}

    add_pitch(acc, _pitch(pitcher=101), {"101"})
    add_pitch(acc, _pitch(pitcher="202"), {"101"})

    assert set(acc["pitchers"]) == {"101"}
    assert acc["pitchers"]["101"]["pitch_count"] == 1


def test_foul_tip_family_uses_the_savant_whiff_convention():
    descriptions = [
        "foul_tip",
        "bunt_foul_tip",
        "swinging_strike",
        "foul",
        "called_strike",
    ] + ["ball"] * (MIN_INPUT_PITCHES - 5)
    rows = [_pitch(description=description) for description in descriptions]

    result = finalize_season(_aggregate(rows), 2024)[0]

    assert result["outcomes"] == {
        "swing_count": 4,
        "whiff_count": 3,
        "called_strike_count": 1,
        "whiff_rate": pytest.approx(0.75),
        "csw_rate": pytest.approx(4 / MIN_INPUT_PITCHES),
        "called_strike_rate": pytest.approx(1 / MIN_INPUT_PITCHES),
    }


def test_location_rates_use_each_pitch_zone_and_registered_geometry():
    rows = []
    cases = [
        _pitch(plate_x=0.0, plate_z=2.5),  # zone + central-50% heart
        _pitch(plate_x=0.82, plate_z=2.5),  # zone + edge inside
        _pitch(plate_x=0.84, plate_z=2.5),  # edge outside
        _pitch(plate_x=2.0, plate_z=2.5),  # waste outside
        _pitch(plate_x=0.0, plate_z=4.0, sz_top=4.2, sz_bot=2.0),  # own zone + edge
    ]
    for case in cases:
        rows.extend(_repeat(case, 100))

    location = finalize_season(_aggregate(rows), 2024)[0]["location"]

    assert location["sample_count"] == MIN_INPUT_PITCHES
    assert location["missing_count"] == 0
    assert location["zone_count"] == 300
    assert location["heart_count"] == 100
    assert location["edge_count"] == 300
    assert location["waste_count"] == 100
    assert location["zone_rate"] == pytest.approx(0.6)
    assert location["heart_rate"] == pytest.approx(0.2)
    assert location["edge_rate"] == pytest.approx(0.6)
    assert location["waste_rate"] == pytest.approx(0.2)


def test_diagonal_outside_pitch_uses_clamped_rectangle_distance():
    rows = _repeat(_pitch(plate_x=3.0, plate_z=3.39), MIN_INPUT_PITCHES)

    location = finalize_season(_aggregate(rows), 2024)[0]["location"]

    assert location["edge_count"] == 0
    assert location["waste_count"] == MIN_INPUT_PITCHES


def test_merge_is_associative_and_does_not_mutate_inputs():
    left = _aggregate([_pitch(release_speed=95.1)])
    middle = _aggregate([_pitch(pitch_type="CH", release_speed=84.7)])
    right = _aggregate([_pitch(description="foul_tip", plate_x=None)])
    originals = copy.deepcopy((left, middle, right))

    left_grouped = merge_accumulators(merge_accumulators(left, middle), right)
    right_grouped = merge_accumulators(left, merge_accumulators(middle, right))

    assert left_grouped == right_grouped
    assert (left, middle, right) == originals


def test_total_and_pitch_type_sample_gates_are_both_enforced():
    below = _aggregate(_repeat(_pitch(), MIN_INPUT_PITCHES - 1))
    assert finalize_season(below, 2024) == []

    rows = []
    rows.extend(_repeat(_pitch(pitch_type="FF"), 401))
    rows.extend(_repeat(_pitch(pitch_type="SL"), 50))
    rows.extend(_repeat(_pitch(pitch_type="CH"), 49))
    result = finalize_season(_aggregate(rows), 2024)[0]
    assert set(result["pitch_types"]) == {"four_seam", "slider"}
    assert result["pitch_type_counts"]["changeup"] == 49

    usage_rows = []
    usage_rows.extend(_repeat(_pitch(pitch_type="FF"), 1081))
    usage_rows.extend(_repeat(_pitch(pitch_type="SL"), 60))
    usage_rows.extend(_repeat(_pitch(pitch_type="FC"), 59))
    usage_result = finalize_season(_aggregate(usage_rows), 2024)[0]
    assert set(usage_result["pitch_types"]) == {"four_seam", "slider"}
    assert usage_result["pitch_type_counts"]["cutter"] == 59


def test_finalization_is_order_independent_and_retains_compact_sufficient_stats():
    rows = []
    rows.extend(
        _repeat(
            _pitch(
                pitch_type="FF",
                release_speed=96.2,
                pfx_x=-0.6,
                pfx_z=1.4,
                release_spin_rate=2500,
                release_extension=6.7,
                release_pos_x=-2.1,
                release_pos_z=5.9,
                plate_x=-0.2,
                plate_z=2.4,
            ),
            300,
        )
    )
    rows.extend(
        _repeat(
            _pitch(
                pitch_type="CH",
                release_speed=86.1,
                pfx_x=0.8,
                pfx_z=0.5,
                release_spin_rate=None,
                release_extension=6.2,
                release_pos_x=-2.0,
                release_pos_z=5.7,
                plate_x=0.3,
                plate_z=2.1,
            ),
            200,
        )
    )

    forward = finalize_season(_aggregate(rows), 2024)
    reverse = finalize_season(_aggregate(list(reversed(rows))), 2024)

    assert forward == reverse
    result = forward[0]
    assert result["mlbam_id"] == "101"
    assert result["season"] == 2024
    assert result["pitch_count"] == MIN_INPUT_PITCHES
    assert result["pitch_type_counts"] == {"changeup": 200, "four_seam": 300}
    fastball = result["pitch_types"]["four_seam"]
    assert fastball["usage"] == pytest.approx(0.6)
    assert fastball["shape"]["velocity"] == {
        "sample_count": 300,
        "missing_count": 0,
        "sum": pytest.approx(28860.0),
        "sum_squares": pytest.approx(2776332.0),
        "mean": pytest.approx(96.2),
        "stddev": pytest.approx(0.0),
    }
    assert result["pitch_types"]["changeup"]["shape"]["spin"]["missing_count"] == 200
    assert fastball["location"]["plate_x"]["sample_count"] == 300
    assert result["arsenal"]["count"] == 2
    assert result["arsenal"]["usage_hhi"] == pytest.approx(0.52)
    assert result["arsenal"]["fastball_share"] == pytest.approx(0.6)
    assert result["arsenal"]["max_velocity_separation"] == pytest.approx(10.1)
    assert result["arsenal"]["max_movement_separation"] > 0


def test_final_rows_never_store_names_or_raw_pitch_rows():
    row = _pitch(
        player_name="Do Not Store",
        pitcher_name="Do Not Store",
        game_pk=999,
        at_bat_number=7,
    )
    result = finalize_season(_aggregate(_repeat(row, MIN_INPUT_PITCHES)), 2024)
    encoded = json.dumps(result, sort_keys=True)

    assert "Do Not Store" not in encoded
    assert "player_name" not in encoded
    assert "pitcher_name" not in encoded
    assert "game_pk" not in encoded
    assert "at_bat_number" not in encoded
    assert "raw" not in encoded
