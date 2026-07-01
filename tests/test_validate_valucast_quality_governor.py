import json

from scripts.validate_valucast_quality_governor import validate_governor

_BASE_PAYLOAD = {
    "artifact": "valucast_quality_governor",
    "governor_version": "1",
    "generated_at": "2026-06-30T00:00:00+00:00",
    "checks": [{"name": "example", "passed": True}],
    "surface_readiness": {"dynasty": True},
    "ready_for_public_snapshot": True,
    "blockers": [],
}


def _write(tmp_path, **overrides):
    payload = {**_BASE_PAYLOAD, **overrides}
    path = tmp_path / "governor.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_validate_governor_passes_candidate_ready(tmp_path):
    path = _write(tmp_path, status="candidate_ready")
    payload, problems = validate_governor(path)
    assert payload is not None
    assert problems == []


def test_validate_governor_fails_blocked_status(tmp_path):
    path = _write(
        tmp_path,
        status="blocked",
        ready_for_public_snapshot=False,
        blockers=["pitcher-heavy top board"],
    )
    payload, problems = validate_governor(path)
    assert payload is not None
    assert any("blocked" in problem for problem in problems)
    assert any("pitcher-heavy top board" in problem for problem in problems)


def test_validate_governor_fails_bad_shape(tmp_path):
    path = _write(tmp_path, status="candidate_ready", checks=[])
    payload, problems = validate_governor(path)
    assert problems
