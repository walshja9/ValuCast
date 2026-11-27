import hashlib
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BLOBS = {
    "data/validation/valucast_prospect_v2_development_contract.json": "2bd549347227235061c51444fdd709bd69153dee",
    "data/models/valucast_prospect_model_v0_9.json": "788ba04a054474430a4cdb01e3ac783795cfa088",
    "data/validation/valucast_prospect_rank_v2_1_development.json": "195febb61a0867da213d2fca096d02e58289a218",
    "data/validation/valucast_prospect_rank_v2_2_development.json": "44e7d8a26259f06cdc9b5cfa5c48c9b5c9c4b214",
}
EXPECTED_SOURCE_BLOBS = {
    "prospects/prospect_v2_target.py": "abb5b89bff8d41ca9079c2389f0da9a17eaf284b",
    "prospects/prospect_v2_candidate.py": "e81583a336d6f64089887b0f3bdbefa38eb63909",
    "prospects/prospect_v09.py": "592d1fbc93e4bb0b13a10fae87507116acdb41c9",
    "prospects/cross_role_calibration.py": "bd83d626b8e039f3202e72ccf8c06a98fb7a3899",
    "prospects/rank_v2.py": "5907fe49246dc247eb777bfaab5fbcd2b3cb6d31",
}
RECEIPT_PATH = ROOT / "data/validation/valucast_prospect_rank_v2_3_development.json"
MAP_PATH = ROOT / "data/models/valucast_prospect_joint_ladder_calibrator_v5.json"


def _git_blob(relative_path: str, path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", f"--path={relative_path}", str(path)],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def test_frozen_phase_a_dependencies_have_registered_git_content():
    for relative_path, expected_blob in {**EXPECTED_BLOBS, **EXPECTED_SOURCE_BLOBS}.items():
        path = ROOT / relative_path
        assert path.is_file(), f"missing frozen Phase A dependency: {relative_path}"
        assert _git_blob(relative_path, path) == expected_blob


def _canonical_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sealed_map_sha256(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    seal = payload.pop("artifact_sha256", None)
    assert isinstance(seal, str) and len(seal) == 64
    assert seal == _canonical_sha256(payload)
    return seal


def _assert_v23_output_state(
    receipt_path: Path,
    map_path: Path,
    *,
    is_tracked=lambda _path: False,
):
    if not receipt_path.exists():
        assert not map_path.exists()
        return

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] in {"qualified", "failed", "spent_error"}
    if receipt["status"] == "qualified":
        assert receipt["development_qualified"] is True
        assert map_path.exists()
        assert receipt["result"]["pooled_fit"]["map_artifact_sha256"] == _sealed_map_sha256(map_path)
    elif receipt["status"] == "failed":
        assert receipt["development_qualified"] is False
        assert not map_path.exists()
    else:
        assert receipt["development_qualified"] is False
        assert receipt.get("result") is None
        if map_path.exists():
            assert not is_tracked(map_path), (
                "spent_error may retain only an explicitly untrusted, untracked orphan map"
            )


def _is_tracked(path: Path) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_v23_output_state_is_consistent_before_or_after_execution():
    _assert_v23_output_state(RECEIPT_PATH, MAP_PATH, is_tracked=_is_tracked)


def test_v23_terminal_output_contracts_are_fail_closed(tmp_path):
    receipt_path = tmp_path / "receipt.json"
    map_path = tmp_path / "map.json"
    map_payload = {"artifact": "valucast_prospect_joint_ladder_calibrator_v5"}
    map_payload["artifact_sha256"] = _canonical_sha256(map_payload)
    map_path.write_text(json.dumps(map_payload), encoding="utf-8")

    receipt_path.write_text(
        json.dumps({
            "status": "qualified",
            "development_qualified": True,
            "result": {"pooled_fit": {"map_artifact_sha256": map_payload["artifact_sha256"]}},
        }),
        encoding="utf-8",
    )
    _assert_v23_output_state(receipt_path, map_path)

    receipt_path.write_text(
        json.dumps({"status": "failed", "development_qualified": False}),
        encoding="utf-8",
    )
    map_path.unlink()
    _assert_v23_output_state(receipt_path, map_path)

    map_path.write_text(json.dumps(map_payload), encoding="utf-8")
    receipt_path.write_text(
        json.dumps({"status": "spent_error", "development_qualified": False, "result": None}),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="untracked orphan"):
        _assert_v23_output_state(receipt_path, map_path, is_tracked=lambda _path: True)
    _assert_v23_output_state(receipt_path, map_path, is_tracked=lambda _path: False)
