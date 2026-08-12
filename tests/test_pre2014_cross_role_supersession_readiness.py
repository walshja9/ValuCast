"""Outcome-blind tests for the Plan 037 supersession readiness receipt."""
from __future__ import annotations

from copy import deepcopy

import pytest

from scripts import build_pre2014_cross_role_supersession_readiness as readiness


def _metadata(path: str) -> dict[str, str]:
    return {
        "path": path,
        "git_blob": "a" * 40,
        "binding": readiness.OUTCOME_METADATA_BINDING,
    }


def _ready_report(**overrides):
    arguments = {
        "implementation_commit": "b" * 40,
        "result_path": (
            "data/validation/valucast_pre2014_cross_role_"
            "supersession_gate.json"
        ),
        "result_exists": False,
        "implementation_files": [
            {"path": "prospects/direct_7x7.py", "git_blob": "c" * 40, "sha256": "d" * 64}
        ],
        "plan036_registration": {
            "path": readiness.PLAN036_REGISTRATION_PATH,
            "git_blob": "e" * 40,
            "sha256": "f" * 64,
        },
        "plan036_readiness": {
            "path": readiness.PLAN036_READINESS_PATH,
            "git_blob": "1" * 40,
            "sha256": "2" * 64,
        },
        "outcome_blob_records": [
            _metadata(path) for path in readiness.PLAN036_OUTCOME_PATHS
        ],
        "current_contract": _metadata(readiness.CURRENT_CONTRACT_PATH),
    }
    arguments.update(overrides)
    return readiness.build_readiness(**arguments)


def test_ready_report_is_same_lineage_metadata_only_and_keeps_gate_frozen():
    report = _ready_report()

    assert report["status"] == "ready"
    assert report["execution_authorized"] is True
    assert report["look_spent"] is False
    assert report["supersedes"]["same_look_lineage"] is True
    assert report["supersedes"]["network_refetch_forbidden"] is True
    assert report["outer_folds"] == [2017, 2018, 2019, 2021]
    assert report["bootstrap"]["seed"] == 35011
    assert report["bootstrap"]["resamples"] == 10_000
    assert report["governor"] == {
        "check_id": "prospect_top_board_role_shape",
        "max_top25_pitcher_count": 7,
        "max_top50_pitcher_rate": 0.3,
    }
    assert report["corrections"]["row_or_identity_drops"] == 0
    assert report["corrections"]["threshold_changes"] == 0
    assert report["hashes"]["implementation_change_paths"] == list(
        readiness.PLAN037_IMPLEMENTATION_CHANGE_PATHS
    )


def test_result_collision_blocks_execution():
    report = _ready_report(result_exists=True)

    assert report["status"] == "blocked"
    assert report["execution_authorized"] is False
    assert report["look_spent"] is False
    assert report["result"] == {
        "path": (
            "data/validation/valucast_pre2014_cross_role_"
            "supersession_gate.json"
        ),
        "exists": True,
        "unspent": False,
    }


def test_outcome_binding_rejects_content_hashes_and_path_drift():
    records = [_metadata(path) for path in readiness.PLAN036_OUTCOME_PATHS]
    records[0]["sha256"] = "f" * 64
    report = _ready_report(outcome_blob_records=records)
    assert report["status"] == "blocked"
    assert "metadata-only" in report["blockers"][0]

    reordered = deepcopy(records)
    reordered[0].pop("sha256")
    reordered.reverse()
    report = _ready_report(outcome_blob_records=reordered)
    assert report["status"] == "blocked"
    assert any("incomplete or reordered" in blocker for blocker in report["blockers"])


def test_tree_blob_record_uses_ls_tree_and_never_cat_file(monkeypatch):
    calls = []

    def fake_git(*args):
        calls.append(args)
        return (
            "100644 blob " + "a" * 40 + "\t" + readiness.PLAN036_OUTCOME_PATHS[0] + "\0"
        )

    monkeypatch.setattr(readiness, "_git", fake_git)
    monkeypatch.setattr(
        readiness,
        "_git_bytes",
        lambda *args: pytest.fail("metadata-only binding opened blob bytes"),
    )

    assert readiness._tree_blob_record(
        readiness.PLAN036_OUTCOME_PATHS[0],
        commit=readiness.PLAN036_ARTIFACT_COMMIT,
    )["git_blob"] == "a" * 40
    assert calls == [
        (
            "ls-tree",
            "-z",
            readiness.PLAN036_ARTIFACT_COMMIT,
            "--",
            readiness.PLAN036_OUTCOME_PATHS[0],
        )
    ]


def test_topology_requires_i037_directly_after_exact_s036(monkeypatch):
    parents = {
        "i": [readiness.PLAN036_ARTIFACT_COMMIT],
        readiness.PLAN036_ARTIFACT_COMMIT: [readiness.PLAN036_EXECUTION_COMMIT],
        readiness.PLAN036_EXECUTION_COMMIT: [readiness.PLAN036_IMPLEMENTATION_COMMIT],
    }
    monkeypatch.setattr(readiness, "_parents", parents.__getitem__)
    def fake_git(*args):
        if args[:2] == ("diff-tree", "--no-commit-id"):
            return "\n".join(
                f"A\t{path}" for path in readiness.PLAN036_OUTCOME_PATHS
            )
        if args[:2] == ("diff", "--name-status"):
            return "\n".join(
                f"{status}\t{path}"
                for path, status in readiness.PLAN037_IMPLEMENTATION_CHANGE_STATUSES.items()
            )
        raise AssertionError(args)

    monkeypatch.setattr(readiness, "_git", fake_git)
    readiness._require_topology("i")

    parents["i"] = ["0" * 40]
    with pytest.raises(ValueError, match="direct child of S036"):
        readiness._require_topology("i")


def test_topology_rejects_extra_non_addition_in_s036(monkeypatch):
    parents = {
        "i": [readiness.PLAN036_ARTIFACT_COMMIT],
        readiness.PLAN036_ARTIFACT_COMMIT: [readiness.PLAN036_EXECUTION_COMMIT],
        readiness.PLAN036_EXECUTION_COMMIT: [readiness.PLAN036_IMPLEMENTATION_COMMIT],
    }
    monkeypatch.setattr(readiness, "_parents", parents.__getitem__)

    def fake_git(*args):
        if args[:2] == ("diff-tree", "--no-commit-id"):
            expected = [f"A\t{path}" for path in readiness.PLAN036_OUTCOME_PATHS]
            return "\n".join([*expected, "M\tprospects/direct_7x7.py"])
        if args[:2] == ("diff", "--name-status"):
            return "\n".join(
                f"{status}\t{path}"
                for path, status in readiness.PLAN037_IMPLEMENTATION_CHANGE_STATUSES.items()
            )
        raise AssertionError(args)

    monkeypatch.setattr(readiness, "_git", fake_git)

    with pytest.raises(ValueError, match="exact A-only receipt"):
        readiness._require_topology("i")
