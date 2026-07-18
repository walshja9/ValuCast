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


def test_validate_governor_fails_when_dynasty_surface_blocked(tmp_path):
    path = _write(
        tmp_path,
        status="blocked",
        ready_for_public_snapshot=False,
        surface_readiness={"dynasty": False, "buys": True, "movers": True, "prospects": True},
        surface_blockers={"dynasty": ["top MLB value gap too wide"], "buys": [], "movers": [], "prospects": []},
        blockers=["top MLB value gap too wide"],
    )
    payload, problems = validate_governor(path)
    assert payload is not None
    assert any("Dynasty board" in problem for problem in problems)
    assert any("top MLB value gap too wide" in problem for problem in problems)


def test_validate_governor_allows_prospects_only_block(tmp_path):
    """A prospects-surface-only failure must NOT block the daily commit: app.py
    serves /?mode=dd_dynasty and /?mode=prospects from the same store gated only
    on surface_readiness['dynasty'] (commit 75e2878), so a prospect-board content
    issue has no live-serving consequence and shouldn't stall actuals/buys/movers."""
    path = _write(
        tmp_path,
        status="blocked",
        ready_for_public_snapshot=False,
        surface_readiness={"dynasty": True, "buys": True, "movers": True, "prospects": False},
        surface_blockers={
            "dynasty": [], "buys": [], "movers": [],
            "prospects": ["Top prospect board is too pitcher-heavy for public promotion."],
        },
        blockers=["Top prospect board is too pitcher-heavy for public promotion."],
    )
    payload, problems = validate_governor(path)
    assert payload is not None
    assert problems == []


def test_validate_governor_fails_blocked_transition_continuity_veto(tmp_path):
    path = _write(
        tmp_path,
        status="blocked",
        ready_for_public_snapshot=False,
        checks=[
            {
                "id": "prospect_transition_continuity",
                "status": "blocked",
                "message": "Stable model scores produced material prospect transition calibration cliffs.",
                "metrics": {"samples": [{"name": "Josue Briceno"}]},
            }
        ],
        surface_readiness={"dynasty": True, "buys": True, "movers": True, "prospects": False},
        surface_blockers={
            "dynasty": [], "buys": [], "movers": [],
            "prospects": ["Stable model scores produced material prospect transition calibration cliffs."],
        },
        blockers=["Stable model scores produced material prospect transition calibration cliffs."],
    )

    payload, problems = validate_governor(path)

    assert payload is not None
    assert any("prospect transition continuity veto" in problem.lower() for problem in problems)
    assert any("Josue Briceno" in problem for problem in problems)


def test_validate_governor_fails_when_buys_surface_blocked(tmp_path):
    path = _write(
        tmp_path,
        status="blocked",
        ready_for_public_snapshot=False,
        surface_readiness={"dynasty": True, "buys": False, "movers": True, "prospects": True},
        surface_blockers={"dynasty": [], "buys": ["buy history limited rate too high"], "movers": [], "prospects": []},
        blockers=[],
    )
    payload, problems = validate_governor(path)
    assert any("Buys" in problem for problem in problems)


def test_validate_governor_fails_bad_shape(tmp_path):
    path = _write(tmp_path, status="candidate_ready", checks=[])
    payload, problems = validate_governor(path)
    assert problems
