import copy
import csv
import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import projections.data.pitching_statcast as pitching_statcast
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


def _csv_stream(rows):
    fields = list(_pitch())
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    stream.seek(0)
    return stream


def _qualified_accumulator(count=250, *, unknown_pitches=0):
    rows = _repeat(_pitch(), MIN_INPUT_PITCHES - unknown_pitches)
    rows.extend(_repeat(_pitch(pitch_type="EP"), unknown_pitches))
    base = _aggregate(rows)["pitchers"]["101"]
    return {
        "pitchers": {
            str(100000 + index): copy.deepcopy(base) for index in range(count)
        }
    }


def _chunk_payload(start, end, accumulator=None, eligible_ids=("101",)):
    accumulator = accumulator or _aggregate([_pitch()])
    return {
        "schema_version": 1,
        "feature_contract_version": "mlb_pitcher_statcast_v1",
        "eligible_pitcher_ids_sha256": (
            pitching_statcast.eligible_pitcher_ids_sha256(set(eligible_ids))
        ),
        "start": start,
        "end": end,
        "complete": True,
        "response_row_count": 1,
        "parseable_pitch_count": 1,
        "accumulator": accumulator,
    }


def _tree_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


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


def test_date_chunks_are_inclusive_five_day_windows():
    assert pitching_statcast.date_chunks("2025-03-28", "2025-04-07") == [
        ("2025-03-28", "2025-04-01"),
        ("2025-04-02", "2025-04-06"),
        ("2025-04-07", "2025-04-07"),
    ]


def test_pull_chunks_is_resumable_and_retries_are_bounded(tmp_path):
    calls = []

    def fetch(start, end, eligible_ids):
        calls.append((start, end, frozenset(eligible_ids)))
        if len(calls) < 3:
            raise OSError("temporary source failure")
        return _chunk_payload(start, end)

    pitching_statcast.pull_chunks(
        "2025-04-01",
        "2025-04-05",
        tmp_path,
        {"101"},
        fetch=fetch,
        max_retries=3,
        retry_sleep_seconds=0,
    )
    assert len(calls) == 3

    pitching_statcast.pull_chunks(
        "2025-04-01",
        "2025-04-05",
        tmp_path,
        {"101"},
        fetch=lambda *_: pytest.fail("complete cached chunk was fetched again"),
        retry_sleep_seconds=0,
    )
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_source_url_contains_the_registered_pitcher_query():
    parsed = urlparse(
        pitching_statcast.source_url("2025-04-01", "2025-04-05")
    )
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://baseballsavant.mlb.com/statcast_search/csv"
    )
    assert parse_qs(parsed.query) == {
        "all": ["true"],
        "type": ["details"],
        "player_type": ["pitcher"],
        "game_date_gt": ["2025-04-01"],
        "game_date_lt": ["2025-04-05"],
    }


def test_stream_reduction_refuses_likely_truncation_and_empty_game_ranges():
    rows = [_pitch(), _pitch(pitcher=202)]
    with pytest.raises(ValueError, match="likely truncated"):
        pitching_statcast.build_chunk_accumulator(
            _csv_stream(rows),
            {"101", "202"},
            "2025-04-01",
            "2025-04-05",
            truncation_row_limit=2,
        )

    with pytest.raises(ValueError, match="no parseable pitches"):
        pitching_statcast.build_chunk_accumulator(
            _csv_stream([_pitch(pitcher="")]),
            {"101"},
            "2025-04-01",
            "2025-04-05",
        )


def test_stream_reduction_keeps_only_compact_accumulator_data():
    row = _pitch()
    row.update(player_name="Never Store", game_pk=123, at_bat_number=9)
    payload = pitching_statcast.build_chunk_accumulator(
        _csv_stream([row]), {"101"}, "2025-04-01", "2025-04-05"
    )
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["complete"] is True
    assert payload["response_row_count"] == 1
    assert payload["parseable_pitch_count"] == 1
    assert payload["eligible_pitcher_ids_sha256"] == (
        pitching_statcast.eligible_pitcher_ids_sha256({"101"})
    )
    assert payload["accumulator"]["pitchers"]["101"]["pitch_count"] == 1
    assert "Never Store" not in encoded
    assert "game_pk" not in encoded
    assert "at_bat_number" not in encoded


def test_loading_cached_season_fails_when_an_expected_chunk_is_missing(tmp_path):
    first = tmp_path / "2025-04-01_2025-04-05.json"
    first.write_text(
        json.dumps(_chunk_payload("2025-04-01", "2025-04-05")),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing expected chunk"):
        pitching_statcast.load_cached_season(
            tmp_path, "2025-04-01", "2025-04-10", {"101"}
        )


def test_loading_cached_season_refuses_raw_or_unexpected_cache_files(tmp_path):
    expected = tmp_path / "2025-04-01_2025-04-05.json"
    expected.write_text(
        json.dumps(_chunk_payload("2025-04-01", "2025-04-05")),
        encoding="utf-8",
    )
    (tmp_path / "raw.csv").write_text("pitcher,game_pk\n101,1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="raw or unexpected cache file"):
        pitching_statcast.load_cached_season(
            tmp_path, "2025-04-01", "2025-04-05", {"101"}
        )


@pytest.mark.parametrize(
    ("field", "replacement", "match"),
    [
        ("schema_version", 999, "schema version"),
        ("feature_contract_version", "wrong", "feature contract"),
        ("eligible_pitcher_ids_sha256", "0" * 64, "eligible pitcher universe"),
    ],
)
def test_cached_chunks_are_bound_to_schema_contract_and_eligible_universe(
    tmp_path, field, replacement, match
):
    path = tmp_path / "2025-04-01_2025-04-05.json"
    payload = _chunk_payload("2025-04-01", "2025-04-05")
    payload[field] = replacement
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        pitching_statcast.pull_chunks(
            "2025-04-01",
            "2025-04-05",
            tmp_path,
            {"101"},
            fetch=lambda *_: pytest.fail("stale compact evidence was fetched/used"),
            retry_sleep_seconds=0,
        )

    with pytest.raises(ValueError, match=match):
        pitching_statcast.load_cached_season(
            tmp_path, "2025-04-01", "2025-04-05", {"101"}
        )


def test_canonical_hash_is_independent_of_mapping_order():
    left = {"b": 2, "a": [{"y": 4, "x": 3}]}
    right = {"a": [{"x": 3, "y": 4}], "b": 2}

    assert pitching_statcast.canonical_sha256(left) == (
        pitching_statcast.canonical_sha256(right)
    )


def test_seal_fails_closed_on_coverage_and_unknown_pitch_gates(tmp_path):
    with pytest.raises(ValueError, match="qualified rows 249 < 250"):
        pitching_statcast.seal_season(
            _qualified_accumulator(249),
            season=2024,
            start="2024-03-20",
            end="2024-09-30",
            expected_chunk_count=1,
            completed_chunk_count=1,
            eligible_ids={str(100000 + index) for index in range(249)},
            output_dir=tmp_path,
        )

    with pytest.raises(ValueError, match="unknown pitch share"):
        pitching_statcast.seal_season(
            _qualified_accumulator(250, unknown_pitches=15),
            season=2024,
            start="2024-03-20",
            end="2024-09-30",
            expected_chunk_count=1,
            completed_chunk_count=1,
            eligible_ids={str(100000 + index) for index in range(250)},
            output_dir=tmp_path,
        )


def test_sealed_seasons_are_immutable_and_manifest_is_complete(tmp_path):
    accumulator = _qualified_accumulator(250)
    eligible_ids = {str(100000 + index) for index in range(250)}
    entry = pitching_statcast.seal_season(
        accumulator,
        season=2024,
        start="2024-03-20",
        end="2024-09-30",
        expected_chunk_count=40,
        completed_chunk_count=40,
        eligible_ids=eligible_ids,
        output_dir=tmp_path,
    )
    season_path = tmp_path / "pitching_statcast_2024.json"
    original = season_path.read_bytes()

    assert entry == {
        "season": 2024,
        "regular_season_start": "2024-03-20",
        "regular_season_end": "2024-09-30",
        "source_query_template": pitching_statcast.SOURCE_QUERY_TEMPLATE,
        "expected_chunk_count": 40,
        "completed_chunk_count": 40,
        "eligible_pitcher_count": 250,
        "eligible_pitcher_ids_sha256": (
            pitching_statcast.eligible_pitcher_ids_sha256(eligible_ids)
        ),
        "qualified_feature_row_count": 250,
        "unknown_pitch_count": 0,
        "unknown_pitch_share": 0.0,
        "schema_version": 1,
        "feature_contract_version": "mlb_pitcher_statcast_v1",
        "canonical_sha256": pitching_statcast.canonical_sha256(
            json.loads(original)
        ),
    }
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))[
        "seasons"
    ]["2024"] == entry

    assert (
        pitching_statcast.seal_season(
            accumulator,
            season=2024,
            start="2024-03-20",
            end="2024-09-30",
            expected_chunk_count=40,
            completed_chunk_count=40,
            eligible_ids=eligible_ids,
            output_dir=tmp_path,
        )
        == entry
    )
    assert season_path.read_bytes() == original

    changed = copy.deepcopy(accumulator)
    changed["pitchers"]["100000"]["whiff_count"] += 1
    with pytest.raises(ValueError, match="Refusing to overwrite finalized"):
        pitching_statcast.seal_season(
            changed,
            season=2024,
            start="2024-03-20",
            end="2024-09-30",
            expected_chunk_count=40,
            completed_chunk_count=40,
            eligible_ids=eligible_ids,
            output_dir=tmp_path,
        )


@pytest.mark.parametrize(
    ("field", "replacement", "match"),
    [
        ("schema_version", 999, "manifest schema version"),
        ("feature_contract_version", "wrong", "manifest feature contract"),
    ],
)
def test_seal_preflights_manifest_contract_before_writing_any_season_file(
    tmp_path, field, replacement, match
):
    manifest = {
        "schema_version": 1,
        "feature_contract_version": "mlb_pitcher_statcast_v1",
        "seasons": {},
    }
    manifest[field] = replacement
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    before = _tree_bytes(tmp_path)
    eligible_ids = {str(100000 + index) for index in range(250)}

    with pytest.raises(ValueError, match=match):
        pitching_statcast.seal_season(
            _qualified_accumulator(250),
            season=2024,
            start="2024-03-20",
            end="2024-09-30",
            expected_chunk_count=40,
            completed_chunk_count=40,
            eligible_ids=eligible_ids,
            output_dir=tmp_path,
        )

    assert _tree_bytes(tmp_path) == before
    assert not (tmp_path / "pitching_statcast_2024.json").exists()


def test_seal_preflights_conflicting_manifest_entry_without_orphaning_season(tmp_path):
    manifest = {
        "schema_version": 1,
        "feature_contract_version": "mlb_pitcher_statcast_v1",
        "seasons": {"2024": {"canonical_sha256": "conflict"}},
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    before = _tree_bytes(tmp_path)
    eligible_ids = {str(100000 + index) for index in range(250)}

    with pytest.raises(ValueError, match="conflicting manifest season 2024"):
        pitching_statcast.seal_season(
            _qualified_accumulator(250),
            season=2024,
            start="2024-03-20",
            end="2024-09-30",
            expected_chunk_count=40,
            completed_chunk_count=40,
            eligible_ids=eligible_ids,
            output_dir=tmp_path,
        )

    assert _tree_bytes(tmp_path) == before
    assert not (tmp_path / "pitching_statcast_2024.json").exists()


def test_generated_cache_and_output_trees_contain_no_raw_pitch_files(tmp_path):
    cache_dir = tmp_path / "cache"
    output_dir = tmp_path / "output"
    accumulator = _qualified_accumulator(250)
    eligible_ids = {str(100000 + index) for index in range(250)}
    pitching_statcast.pull_chunks(
        "2024-03-20",
        "2024-03-24",
        cache_dir,
        eligible_ids,
        fetch=lambda start, end, _: _chunk_payload(
            start, end, accumulator, eligible_ids
        ),
        retry_sleep_seconds=0,
    )
    merged, completed = pitching_statcast.load_cached_season(
        cache_dir, "2024-03-20", "2024-03-24", eligible_ids
    )
    pitching_statcast.seal_season(
        merged,
        season=2024,
        start="2024-03-20",
        end="2024-03-24",
        expected_chunk_count=1,
        completed_chunk_count=completed,
        eligible_ids=eligible_ids,
        output_dir=output_dir,
    )

    assert {path.suffix for path in tmp_path.rglob("*") if path.is_file()} == {
        ".json"
    }
    encoded = "".join(
        path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json")
    )
    assert "player_name" not in encoded
    assert "game_pk" not in encoded
    assert "at_bat_number" not in encoded


def test_eligible_pitchers_come_from_same_season_backbone_at_100_bf(tmp_path):
    pitching_dir = tmp_path / "pitching"
    pitching_dir.mkdir()
    (pitching_dir / "pitching_2024.json").write_text(
        json.dumps(
            [
                {"mlbam_id": "1", "BF": 99},
                {"mlbam_id": 2, "BF": 100},
                {"mlbam_id": "3", "BF": 101},
            ]
        ),
        encoding="utf-8",
    )

    assert pitching_statcast.load_eligible_pitcher_ids(2024, tmp_path) == {
        "2",
        "3",
    }


def test_cli_requires_exactly_one_explicit_supported_mode():
    from scripts.fetch_mlb_pitcher_statcast import parse_args

    assert parse_args(["--season", "2024"]).seasons == [2024]
    assert parse_args(
        ["--start-season", "2023", "--end-season", "2025"]
    ).seasons == [2023, 2024, 2025]

    for argv in (
        [],
        ["--season", "2024", "--start-season", "2023", "--end-season", "2025"],
        ["--start-season", "2023"],
        ["--end-season", "2025"],
        ["--season", "24"],
        ["--season", "2026"],
        ["--start-season", "2025", "--end-season", "2024"],
    ):
        with pytest.raises(SystemExit):
            parse_args(argv)
