import hashlib
import json
import re
from pathlib import Path

import scripts.run_pre2014_cross_role_supersession_gate as runner


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "plans/037-pre2014-cross-role-calibration-supersession.md"
README_PATH = ROOT / "plans/README.md"
READINESS_PATH = (
    ROOT
    / "data"
    / "validation"
    / "valucast_pre2014_cross_role_supersession_readiness.json"
)
READINESS_SHA256 = (
    "0bd86c7d15a460d415de00be5c9e05906d63459e7f8f2d3b079c0f3971032fa2"
)
IMPLEMENTATION_BASE_COMMIT = "b4a5b2bfd4bb324e7b8d6e7d249fb91fea9f0708"


def _registration() -> dict:
    text = PLAN_PATH.read_text(encoding="utf-8")
    assert text.count(runner.REGISTRATION_START) == 1
    assert text.count(runner.REGISTRATION_END) == 1
    start = text.index(runner.REGISTRATION_START) + len(runner.REGISTRATION_START)
    end = text.index(runner.REGISTRATION_END, start)
    match = re.fullmatch(
        r"```json\s*(\{.*\})\s*```", text[start:end].strip(), flags=re.DOTALL
    )
    assert match, "Plan 037 must contain one exact registered JSON block"
    return json.loads(match.group(1))


def test_plan037_registration_matches_the_ready_corrective_contract():
    readiness_bytes = READINESS_PATH.read_bytes()
    assert hashlib.sha256(readiness_bytes).hexdigest() == READINESS_SHA256
    readiness = json.loads(readiness_bytes)
    assert readiness["implementation_base_commit"] == IMPLEMENTATION_BASE_COMMIT
    assert readiness["status"] == "ready"
    assert readiness["blockers"] == []
    assert readiness["execution_authorized"] is True
    assert readiness["look_spent"] is False

    registration = _registration()
    assert set(registration) == runner.EXPECTED_REGISTRATION_KEYS
    assert registration == {
        "protocol": runner.PROTOCOL,
        "registered_at": "2026-08-12T02:42:34Z",
        "status": "registered",
        "look_spent": False,
        "execution_authorized": True,
        "research_only": True,
        "automatic_promotion": False,
        "claim_authorized": False,
        "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
        "readiness": {
            "path": (
                "data/validation/"
                "valucast_pre2014_cross_role_supersession_readiness.json"
            ),
            "sha256": READINESS_SHA256,
        },
        "result_path": (
            "data/validation/valucast_pre2014_cross_role_supersession_gate.json"
        ),
        "supersedes": readiness["supersedes"],
        "candidate": readiness["candidate"],
        "outer_folds": readiness["outer_folds"],
        "bootstrap": readiness["bootstrap"],
        "primary_endpoint": readiness["primary_endpoint"],
        "thresholds": readiness["thresholds"],
        "governor": readiness["governor"],
        "result_contract": {
            "single_use": True,
            "claim_authorized": False,
            "automatic_promotion": False,
            "terminal_evidence_path": (
                "data/validation/"
                "valucast_pre2014_cross_role_supersession_evidence.json"
            ),
            "network_refetch_forbidden": True,
        },
        "limitations": ["cohort-season-completion pseudo-replay"],
    }
    assert runner.validate_registered_readiness(
        readiness, readiness_sha256=READINESS_SHA256
    ) == IMPLEMENTATION_BASE_COMMIT
    assert runner._validate_registration(
        registration, readiness, readiness_sha256=READINESS_SHA256
    ) == IMPLEMENTATION_BASE_COMMIT


def test_plan037_readme_records_spent_plan036_and_unspent_supersession():
    readme = README_PATH.read_text(encoding="utf-8")
    assert readme.count("| 036  | Pre-2014 Cross-Role Calibration Gate") == 1
    assert readme.count("| 037  | Pre-2014 Cross-Role Calibration Supersession") == 1
    assert "SPENT — EXECUTION ERROR; NO ADJUDICATION" in readme
    assert "REGISTERED — UNSPENT; RESEARCH ONLY" in readme
