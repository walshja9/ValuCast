import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

import pytest

from scripts.archive_milb_observations import build_snapshot, write_snapshot


def _contract():
    return {
        "current": {
            "fetched_date": "2026-07-20",
            "season": 2026,
            "hitters": [
                {
                    "mlbam_id": 10,
                    "role": "hitter",
                    "team": "Erie SeaWolves",
                    "level": "AA",
                    "source_kind": "current_season",
                    "age": 20,
                    "plate_appearances": 120,
                    "iso": 0.190,
                    "k_pct": 18.0,
                    "bb_pct": 11.0,
                    "ops": 0.820,
                    "avg": 0.270,
                    "obp": 0.360,
                    "slg": 0.460,
                    "babip": 0.310,
                }
            ],
            "pitchers": [
                {
                    "mlbam_id": 20,
                    "role": "pitcher",
                    "team": "Toledo Mud Hens",
                    "level": "AAA",
                    "source_kind": "current_season",
                    "age": 23,
                    "innings_pitched": 50.0,
                    "k_per_9": 10.5,
                    "bb_per_9": 2.7,
                    "k_bb_pct": 24.0,
                    "era": 3.10,
                    "whip": 1.08,
                    "games_started": 8,
                    "is_starter": True,
                }
            ],
        }
    }


def _write_concurrently(monkeypatch, output_dir, snapshots):
    path = output_dir / "2026-07-20.json"
    real_exists = Path.exists
    real_fsync = os.fsync
    real_link = os.link
    exists_barrier = Barrier(len(snapshots))
    publication_barrier = Barrier(len(snapshots))
    start_barrier = Barrier(len(snapshots))
    event_lock = Lock()
    fsynced_files = set()
    publication_sources = []

    def synchronized_exists(candidate):
        if candidate == path:
            exists_barrier.wait(timeout=5)
            return False
        return real_exists(candidate)

    def recording_fsync(fd):
        real_fsync(fd)
        stat = os.fstat(fd)
        with event_lock:
            fsynced_files.add((stat.st_dev, stat.st_ino))

    def synchronized_link(source, destination):
        source = Path(source)
        with event_lock:
            publication_sources.append(source)
        publication_barrier.wait(timeout=5)
        stat = source.stat()
        assert (stat.st_dev, stat.st_ino) in fsynced_files
        return real_link(source, destination)

    def attempt(snapshot):
        start_barrier.wait(timeout=5)
        try:
            return snapshot, write_snapshot(snapshot, output_dir)
        except Exception as exc:
            return snapshot, exc

    with monkeypatch.context() as patch:
        patch.setattr(Path, "exists", synchronized_exists)
        patch.setattr(os, "fsync", recording_fsync)
        patch.setattr(os, "link", synchronized_link)
        with ThreadPoolExecutor(max_workers=len(snapshots)) as executor:
            attempts = list(executor.map(attempt, snapshots))
    return path, attempts, publication_sources


def test_snapshot_contains_only_registered_factual_fields_and_a_seal():
    snapshot = build_snapshot(_contract())
    assert set(snapshot) == {
        "artifact",
        "schema_version",
        "observation_date",
        "season",
        "source",
        "input_sha256",
        "rows",
        "content_sha256",
    }
    assert snapshot["observation_date"] == "2026-07-20"
    assert [row["mlbam_id"] for row in snapshot["rows"]] == [10, 20]
    hitter, pitcher = snapshot["rows"]
    hitter_fields = {
        "mlbam_id",
        "role",
        "organization",
        "organization_status",
        "minor_team",
        "level",
        "source_kind",
        "observation_date",
        "season",
        "age",
        "sample",
        "sample_unit",
        "rates",
    }
    assert set(hitter) == hitter_fields
    assert set(pitcher) == hitter_fields | {"role_facts"}
    assert set(hitter["rates"]) == {
        "iso",
        "k_pct",
        "bb_pct",
        "ops",
        "avg",
        "obp",
        "slg",
        "babip",
    }
    assert set(pitcher["rates"]) == {
        "k_per_9",
        "bb_per_9",
        "k_bb_pct",
        "era",
        "whip",
    }
    assert set(pitcher["role_facts"]) == {"games_started", "is_starter"}
    assert hitter["sample_unit"] == "PA"
    assert pitcher["sample_unit"] == "IP"
    forbidden_fragments = {
        "promotion",
        "transaction",
        "injur",
        "rank",
        "value",
        "outcome",
        "market",
        "availability",
        "external",
        "signal",
    }
    keys = set(snapshot) | set(hitter) | set(hitter["rates"]) | set(pitcher)
    keys |= set(pitcher["rates"]) | set(pitcher["role_facts"])
    assert not {
        key for key in keys if any(fragment in key for fragment in forbidden_fragments)
    }
    assert len(snapshot["input_sha256"]) == 64
    assert len(snapshot["content_sha256"]) == 64


def test_same_date_same_content_is_noop_but_changed_content_fails(tmp_path):
    snapshot = build_snapshot(_contract())
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8"
    )
    expected_bytes = expected_path.read_bytes()
    expected_path.unlink()

    path, status = write_snapshot(snapshot, tmp_path)
    assert status == "created"
    assert path.read_bytes() == expected_bytes
    assert write_snapshot(snapshot, tmp_path) == (path, "unchanged")
    changed_contract = _contract()
    changed_contract["current"]["hitters"][0]["iso"] = 0.999
    changed = build_snapshot(changed_contract)
    with pytest.raises(ValueError, match="sealed date"):
        write_snapshot(changed, tmp_path)


def test_concurrent_identical_writers_create_once_without_temps(monkeypatch, tmp_path):
    snapshot = build_snapshot(_contract())

    path, attempts, publication_sources = _write_concurrently(
        monkeypatch, tmp_path, [snapshot, copy.deepcopy(snapshot)]
    )

    assert len(set(publication_sources)) == 2
    assert {source.parent for source in publication_sources} == {tmp_path}
    results = [result for _, result in attempts]
    assert all(isinstance(result, tuple) for result in results)
    assert sorted(result[1] for result in results) == ["created", "unchanged"]
    assert json.loads(path.read_text(encoding="utf-8")) == snapshot
    assert not [
        candidate for candidate in tmp_path.iterdir() if candidate.suffix == ".tmp"
    ]


def test_concurrent_different_writers_never_replace_winner(monkeypatch, tmp_path):
    first = build_snapshot(_contract())
    changed_contract = _contract()
    changed_contract["current"]["hitters"][0]["iso"] = 0.999
    second = build_snapshot(changed_contract)

    path, attempts, publication_sources = _write_concurrently(
        monkeypatch, tmp_path, [first, second]
    )

    assert len(set(publication_sources)) == 2
    assert {source.parent for source in publication_sources} == {tmp_path}
    created = [
        snapshot
        for snapshot, result in attempts
        if isinstance(result, tuple) and result[1] == "created"
    ]
    errors = [result for _, result in attempts if isinstance(result, Exception)]
    assert len(created) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert str(errors[0]) == "sealed date changed"
    assert json.loads(path.read_text(encoding="utf-8")) == created[0]
    assert not [
        candidate for candidate in tmp_path.iterdir() if candidate.suffix == ".tmp"
    ]


def test_unknown_organization_stays_null_not_invented():
    contract = _contract()
    contract["current"]["hitters"][0]["team"] = "Unknown Club"
    row = build_snapshot(contract)["rows"][0]
    assert row["organization"] is None
    assert row["organization_status"] == "unknown"


def test_excluded_source_fields_do_not_change_snapshot_or_seals():
    baseline = build_snapshot(_contract())
    contract = _contract()
    contract["current"]["hitters"][0].update(
        {
            "availability_status": "injured",
            "availability_reason": "transaction",
            "pick_value": 9_999_999,
        }
    )

    changed = build_snapshot(contract)

    assert changed["input_sha256"] == baseline["input_sha256"]
    assert changed["content_sha256"] == baseline["content_sha256"]
    assert changed == baseline


def test_duplicate_id_multi_level_rows_are_order_independent():
    forward = _contract()
    second_level = copy.deepcopy(forward["current"]["hitters"][0])
    second_level.update(
        {
            "team": "West Michigan Whitecaps",
            "level": "A+",
            "plate_appearances": 80,
            "iso": 0.150,
        }
    )
    forward["current"]["hitters"].append(second_level)
    reversed_sources = copy.deepcopy(forward)
    reversed_sources["current"]["hitters"].reverse()

    forward_snapshot = build_snapshot(forward)
    reversed_snapshot = build_snapshot(reversed_sources)

    assert forward_snapshot["input_sha256"] == reversed_snapshot["input_sha256"]
    assert forward_snapshot["content_sha256"] == reversed_snapshot["content_sha256"]
    assert forward_snapshot == reversed_snapshot
