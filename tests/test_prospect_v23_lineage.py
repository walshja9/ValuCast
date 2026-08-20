import json
import subprocess
from pathlib import Path


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


def test_v23_output_state_is_consistent_before_or_after_execution():
    if not RECEIPT_PATH.exists():
        assert not MAP_PATH.exists()
        return

    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    assert receipt["status"] in {"qualified", "failed", "spent_error"}
    if receipt["status"] == "qualified":
        assert receipt["development_qualified"] is True
        assert MAP_PATH.exists()
    elif receipt["status"] == "failed":
        assert receipt["development_qualified"] is False
        assert not MAP_PATH.exists()
    else:
        assert receipt["development_qualified"] is False
