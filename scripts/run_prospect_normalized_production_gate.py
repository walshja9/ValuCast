"""Execute the registered normalized-production prospect look exactly once."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.challenger_eval import (  # noqa: E402
    RegisteredLookSpentError,
    build_aaa_disagreement,
    eligible_fold_years,
    prepare_fold,
    run_registered_replay,
    score_current_variants,
)

PLAN_PATH = ROOT / "plans/033-prospect-normalized-production-gate.md"
INPUT_PATH = ROOT / "data/prospects/prospect_model_inputs.json"
AAA_PATH = ROOT / "data/models/valucast_aaa_statcast_features.json"
OUTPUT_PATH = ROOT / "data/validation/valucast_prospect_normalized_production_gate.json"

EXPECTED_GIT_BLOBS = {
    "data/prospects/prospect_model_inputs.json": "4ce139871ae456b5289c68dad1e15d8191ff7ef5",
    "data/models/valucast_aaa_statcast_features.json": "37533ad816d86bcf392ccce75bb15f0b745f0f74",
    "data/models/valucast_prospect_model.json": "7a9b9d12ae0866ae3b460f3f02395a0e30949844",
    "data/models/valucast_prospect_rank_v1.json": "4ed3f2603b93e5ecf319f501519303f6ff7c18fa",
    "prospects/competition_benchmark.py": "85a1c2ff43ee7c050da75f43ae1f3382058d1ed3",
}

_PIN_FIELDS = {
    "data/prospects/prospect_model_inputs.json": "prospect_input_git_blob",
    "data/models/valucast_aaa_statcast_features.json": "aaa_statcast_git_blob",
    "data/models/valucast_prospect_model.json": "incumbent_model_git_blob",
    "data/models/valucast_prospect_rank_v1.json": "live_rank_git_blob",
    "prospects/competition_benchmark.py": "competition_benchmark_git_blob",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _content_sha256(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _seal(payload: dict) -> dict:
    sealed = dict(payload)
    sealed["content_sha256"] = _content_sha256(sealed)
    return sealed


def _registration() -> dict:
    text = PLAN_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"<!-- normalized-production-registration:start -->\s*```json\s*(\{.*?\})\s*```\s*"
        r"<!-- normalized-production-registration:end -->",
        text,
        flags=re.S,
    )
    if not match:
        raise ValueError("frozen Plan 033 registration marker is missing")
    registration = json.loads(match.group(1))
    if registration.get("registration_status") != "registered_unspent":
        raise ValueError("Plan 033 registration is not registered_unspent")
    return registration


def _validate_pins(registration: dict) -> dict[str, str]:
    actual = {}
    for relative, expected in EXPECTED_GIT_BLOBS.items():
        if registration.get(_PIN_FIELDS[relative]) != expected:
            raise ValueError(f"registration pin differs for {relative}")
        actual[relative] = subprocess.run(
            ["git", "hash-object", "--", relative],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if actual[relative] != expected:
            raise ValueError(f"Git blob pin mismatch for {relative}")
    return actual


def _validate_readiness(readiness: dict, registration: dict) -> None:
    if readiness.get("content_sha256") != _content_sha256(readiness):
        raise ValueError("readiness artifact seal is invalid")
    required = registration["realized_value_readiness"]
    if readiness.get("status") != required["required_status"]:
        raise ValueError("readiness artifact status changed")
    if (
        readiness.get("replay", {}).get("realized_value_regret_ready")
        is not required["required_ready"]
    ):
        raise ValueError("realized-value readiness changed")
    if readiness.get("blockers") != required["required_blockers"]:
        raise ValueError("readiness blockers changed")


def _write_once(path: Path, payload: dict) -> bool:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise ValueError("existing output artifact is not identical")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def _fsync_directory(path: Path) -> None:
    """Persist a directory entry where the platform permits directory fsync."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _reserve_output(path: Path, payload: dict) -> None:
    """Atomically reserve the only durable output path before scoring."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ValueError("one-shot output artifact already exists") from error
    _fsync_directory(path.parent)


def _replace_reserved(path: Path, payload: dict) -> None:
    """Atomically replace our reservation; failure leaves its prior state intact."""
    if not path.exists():
        raise ValueError("one-shot output reservation is missing")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _finalize_reserved(path: Path, payload: dict) -> dict:
    sealed = _seal(payload)
    _validate_final_artifact(sealed)
    _replace_reserved(path, sealed)
    return sealed


def _validate_pre_score(contract: dict, registration: dict) -> None:
    scored_years = eligible_fold_years(contract)
    if scored_years != registration["scored_fold_years"]:
        raise ValueError("derived scored folds differ from frozen registration")
    minimum = float(registration["minimum_exercised_coverage"])
    for year in registration["reference_fold_years"]:
        prepared = prepare_fold(contract, int(year))
        for role in ("hitter", "pitcher"):
            if float(prepared["coverage"][role]["exercised_coverage"]) < minimum:
                raise ValueError(f"fold {year} {role}: normalization coverage below registration")


def _validate_final_artifact(artifact: dict) -> None:
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"status", "statistical_status"} and item == "validated_superiority":
                    raise ValueError("forbidden final status: validated_superiority")
                if key in {"claim_authorized", "public_claim_eligible"} and item is not False:
                    raise ValueError(f"{key} must remain false")
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(artifact)


def _base_artifact(registration: dict, pins: dict) -> dict:
    return {
        "schema": "valucast_prospect_normalized_production_gate",
        "protocol": registration["protocol"],
        "registered_at": registration["registered_at"],
        "registration_base_commit": registration["base_commit"],
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "git_blob_pins": pins,
        "claim_authorized": False,
        "public_claim_eligible": False,
    }


def main() -> int:
    if OUTPUT_PATH.exists():
        raise ValueError("one-shot output artifact already exists")
    registration = _registration()
    pins = _validate_pins(registration)
    readiness_path = ROOT / registration["realized_value_readiness"]["artifact"]
    readiness = _load(readiness_path)
    _validate_readiness(readiness, registration)
    contract = _load(INPUT_PATH)
    _validate_pre_score(contract, registration)
    base = _base_artifact(registration, pins)
    _reserve_output(
        OUTPUT_PATH,
        _seal(
            {
                **base,
                "status": "collecting",
                "registered_look_spent": False,
                "run_completed": False,
                "phase": "pre_score_reserved",
            }
        ),
    )
    _replace_reserved(
        OUTPUT_PATH,
        _seal(
            {
                **base,
                "status": "collecting",
                "registered_look_spent": True,
                "run_completed": False,
                "phase": "outcome_scoring_started",
            }
        ),
    )

    try:
        replay = run_registered_replay(contract, registration)
    except RegisteredLookSpentError as error:
        _finalize_reserved(
            OUTPUT_PATH, {**base, **error.report, "run_completed": False}
        )
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        _finalize_reserved(
            OUTPUT_PATH,
            {
                **base,
                "status": "collecting",
                "registered_look_spent": True,
                "run_completed": False,
                "failure": f"runner_error:{type(error).__name__}:{error}",
            },
        )
        print(str(error), file=sys.stderr)
        return 1
    if replay["registered_look_spent"] is not True:
        _finalize_reserved(OUTPUT_PATH, {**base, **replay, "run_completed": False})
        print(json.dumps(replay, sort_keys=True), file=sys.stderr)
        return 2

    try:
        control_ranks, candidate_ranks, current_coverage = score_current_variants(
            contract
        )
        current_rows = list(contract["current"].get("hitters") or []) + list(
            contract["current"].get("pitchers") or []
        )
        aaa = build_aaa_disagreement(
            control_ranks,
            candidate_ranks,
            _load(AAA_PATH),
            current_rows,
        )
        artifact = {
            **base,
            **replay,
            "run_completed": True,
            "realized_value_readiness": {
                "status": readiness["status"],
                "realized_value_regret_ready": readiness["replay"][
                    "realized_value_regret_ready"
                ],
                "blockers": readiness["blockers"],
                "content_sha256": readiness["content_sha256"],
            },
            "current_research_ranks": {
                "control": control_ranks,
                "normalized_production": candidate_ranks,
                "identity_set_equal": True,
                "usage": "model_component_research_context_not_live_rank_v1",
            },
            "current_population_coverage": current_coverage,
            "aaa_component_disagreement": aaa,
        }
    except Exception as error:
        artifact = {
            **base,
            **replay,
            "status": "collecting",
            "run_completed": False,
            "failure": f"post_score_report_error:{type(error).__name__}:{error}",
        }
        _finalize_reserved(OUTPUT_PATH, artifact)
        print(str(error), file=sys.stderr)
        return 1

    artifact = _finalize_reserved(OUTPUT_PATH, artifact)
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "registered_look_spent": artifact["registered_look_spent"],
                "run_completed": artifact["run_completed"],
                "content_sha256": artifact["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
