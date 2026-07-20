"""Contract tests for the plan-030 forward-scoreboard + AAA-Statcast-vintage wiring.

Two concerns:
  1. The nightly build/validate graph (scripts/run_daily_public_build.py) and the
     workflow git-add allowlist (.github/workflows/daily-public-data.yml) actually wire
     the new steps in the right ORDER, publish the right artifacts, and NEVER add a
     nightly cohort-registry build (the registry is registered manually/quarterly).
  2. The AAA-Statcast vintage archival hash-skip logic is append-only and correctly
     no-ops when the substantive payload is unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import archive_aaa_statcast_features as arch
from scripts import run_daily_public_build


WORKFLOW_PATH = Path(".github/workflows/daily-public-data.yml")


def _build_commands() -> list[str]:
    return [" ".join(step) for step in run_daily_public_build.BUILD_STEPS]


def _validate_commands() -> list[str]:
    return [" ".join(step) for step in run_daily_public_build.VALIDATE_STEPS]


# ---------------------------------------------------------------------------
# 1. Nightly wiring contract
# ---------------------------------------------------------------------------
def test_scoreboard_build_step_runs_after_gaps_claim_ledger():
    build = _build_commands()
    assert "scripts/build_forward_scoreboard.py" in build
    assert "scripts/build_gaps_claim_ledger.py" in build
    assert build.index("scripts/build_gaps_claim_ledger.py") < build.index(
        "scripts/build_forward_scoreboard.py"
    )


def test_scoreboard_validate_step_present_after_gaps_claim_ledger_validator():
    validate = _validate_commands()
    assert "scripts/validate_forward_scoreboard.py" in validate
    assert validate.index("scripts/validate_gaps_claim_ledger.py") < validate.index(
        "scripts/validate_forward_scoreboard.py"
    )


def test_aaa_vintage_archive_step_runs_after_feature_build():
    build = _build_commands()
    assert "scripts/archive_aaa_statcast_features.py" in build
    assert build.index("scripts/build_aaa_statcast_features.py") < build.index(
        "scripts/archive_aaa_statcast_features.py"
    )


def test_milb_observation_archive_runs_after_prospect_input_pipeline():
    build = _build_commands()
    assert build.index("scripts/run_prospect_shadow_pipeline.py") < build.index(
        "scripts/archive_milb_observations.py"
    )


def test_allowlist_publishes_milb_observation_archive_with_guard():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert (
        "if [ -d data/milb_observation_archive ]; then\n"
        "            git add data/milb_observation_archive/\n"
        "          fi"
    ) in workflow


def test_no_nightly_step_builds_the_forward_cohort_registry():
    # The cohort registry is registered manually/quarterly; a nightly rebuild would
    # silently re-freeze the frozen cohort. It must appear in NEITHER stage.
    build = _build_commands()
    validate = _validate_commands()
    assert not any("build_forward_cohort_registry.py" in cmd for cmd in build)
    assert not any("build_forward_cohort_registry.py" in cmd for cmd in validate)


def test_allowlist_publishes_scoreboard_and_aaa_vintage_archive():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "data/models/valucast_forward_scoreboard.json" in workflow
    assert "data/aaa_statcast_archive/" in workflow
    # The cohort registry artifact is committed manually — it must NOT be in the
    # nightly git-add allowlist.
    assert "valucast_forward_cohort_registry.json" not in workflow


def test_math_provability_validators_wired_nightly_but_not_their_builds():
    # FIX 4: the outcome-OOF / probability-reliability / gate-multiplicity
    # artifacts (audit repairs R6/R4/R3) are NOT rebuilt nightly — like the
    # dynasty backtest they change only when the fold data changes, and their
    # builds run manually alongside the model program (artifacts committed). The
    # nightly pipeline re-VALIDATES the committed copies only.
    build = _build_commands()
    validate = _validate_commands()
    for validator in (
        "scripts/validate_outcome_oof_scores.py",
        "scripts/validate_probability_reliability.py",
        "scripts/validate_universal_gate_multiplicity.py",
    ):
        assert validator in validate
    for builder in (
        "scripts/build_outcome_oof_scores.py",
        "scripts/build_probability_reliability.py",
        "scripts/build_universal_gate_multiplicity.py",
    ):
        assert builder not in build
    # outcome_oof is the source the other two read, so it validates first.
    assert validate.index("scripts/validate_outcome_oof_scores.py") < validate.index(
        "scripts/validate_probability_reliability.py"
    )


def test_math_provability_artifacts_not_in_nightly_git_add_allowlist():
    # FIX 4: builds are manual, so CI never regenerates these three — they must
    # NOT be in the nightly git-add allowlist (a stray entry would let a manual
    # local edit be auto-committed by an unrelated refresh).
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    for artifact in (
        "data/models/valucast_outcome_oof_scores.json",
        "data/models/valucast_probability_reliability.json",
        "data/models/valucast_universal_gate_multiplicity.json",
    ):
        assert artifact not in workflow


def test_forward_scoreboard_git_add_is_guarded():
    # FIX 5: the forward-scoreboard artifact is not yet tracked, so its git-add
    # must be guarded by an existence check (matching the pitch-discipline /
    # AAA-Statcast precedent) rather than an unconditional pathspec that only
    # "works" because a failed build aborts the job first.
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert (
        "if [ -f data/models/valucast_forward_scoreboard.json ]; then\n"
        "            git add data/models/valucast_forward_scoreboard.json\n"
        "          fi" in workflow
    )
    # And it is NOT still present as a bare backslash-continued pathspec.
    assert "            data/models/valucast_forward_scoreboard.json \\\n" not in workflow


def test_no_duplicate_steps_after_wiring():
    # The orchestrator's own guard must still pass with the new steps added.
    run_daily_public_build.validate_steps()


# ---------------------------------------------------------------------------
# 2. AAA-Statcast vintage archival hash-skip logic
# ---------------------------------------------------------------------------
def _features(*, generated_at="2026-07-16T11:00:00+00:00", as_of="2026-07-16", extra=None):
    payload = {
        "artifact": "valucast_aaa_statcast_features",
        "schema_version": 1,
        "generated_at": generated_at,
        "as_of": as_of,
        "season": 2026,
        "counts": {"games": 10, "pitchers": 2, "hitters": 3},
        "pitchers": {"101": {"n_pitches": 300}, "102": {"n_pitches": 250}},
        "hitters": {"201": {"n_pitches": 200}, "202": {}, "203": {}},
    }
    if extra:
        payload.update(extra)
    return payload


def test_content_hash_ignores_volatile_envelope():
    a = _features(generated_at="2026-07-16T11:00:00+00:00", as_of="2026-07-16")
    b = _features(generated_at="2026-07-17T11:00:00+00:00", as_of="2026-07-17")
    # Same measurements, different generated_at/as_of -> identical content hash.
    assert arch.content_hash(a) == arch.content_hash(b)


def test_content_hash_changes_when_measurements_change():
    a = _features()
    b = _features(extra={"pitchers": {"101": {"n_pitches": 999}}})
    assert arch.content_hash(a) != arch.content_hash(b)


def test_archive_writes_first_vintage(tmp_path):
    features = _features()
    path, written = arch.archive_features(features, "2026-07-16", archive_dir=tmp_path)
    assert written is True
    assert path == tmp_path / "2026-07-16.json"
    snap = json.loads(path.read_text(encoding="utf-8"))
    assert snap["artifact"] == "valucast_aaa_statcast_features_vintage"
    assert snap["source_generated_at"] == features["generated_at"]
    assert snap["season"] == 2026
    assert snap["row_count"] == 5  # 2 pitchers + 3 hitters
    assert snap["content_hash"] == arch.content_hash(features)
    assert "bat-tracking" in snap["bat_tracking_coverage"]
    assert snap["features"] == features


def test_archive_skips_when_content_unchanged(tmp_path):
    a = _features(generated_at="2026-07-16T11:00:00+00:00", as_of="2026-07-16")
    path1, written1 = arch.archive_features(a, "2026-07-16", archive_dir=tmp_path)
    assert written1 is True

    # Next night: identical measurements, only the envelope stamp moved -> skip.
    b = _features(generated_at="2026-07-17T11:00:00+00:00", as_of="2026-07-17")
    path2, written2 = arch.archive_features(b, "2026-07-17", archive_dir=tmp_path)
    assert written2 is False
    # No new file was created; caller's path points at the existing latest vintage.
    assert path2 == path1
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["2026-07-16.json"]


def test_archive_appends_new_vintage_when_content_changes(tmp_path):
    a = _features(as_of="2026-07-16")
    arch.archive_features(a, "2026-07-16", archive_dir=tmp_path)

    b = _features(as_of="2026-07-18", extra={"pitchers": {"101": {"n_pitches": 999}}})
    path, written = arch.archive_features(b, "2026-07-18", archive_dir=tmp_path)
    assert written is True
    assert path == tmp_path / "2026-07-18.json"
    # Append-only: both vintages persist, older one untouched.
    assert sorted(p.name for p in tmp_path.glob("*.json")) == [
        "2026-07-16.json",
        "2026-07-18.json",
    ]


def test_archive_skip_compares_against_latest_not_any(tmp_path):
    # Content goes A -> B -> A. The final A must NOT be skipped just because an OLDER
    # snapshot matched: the skip compares only against the LATEST archived vintage.
    a = _features(as_of="2026-07-16")
    b = _features(as_of="2026-07-17", extra={"pitchers": {"101": {"n_pitches": 999}}})
    arch.archive_features(a, "2026-07-16", archive_dir=tmp_path)
    arch.archive_features(b, "2026-07-17", archive_dir=tmp_path)

    a_again = _features(as_of="2026-07-18")
    path, written = arch.archive_features(a_again, "2026-07-18", archive_dir=tmp_path)
    assert written is True
    assert path == tmp_path / "2026-07-18.json"
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_archive_refuses_backdated_vintage(tmp_path):
    # A regressed upstream `as_of` (stale cache / replay) must not write an
    # older-dated file behind the latest vintage -- that would corrupt the
    # "latest == lexical max" invariant the hash-skip relies on.
    a = _features(as_of="2026-07-16")
    arch.archive_features(a, "2026-07-16", archive_dir=tmp_path)

    stale = _features(as_of="2026-07-10", extra={"pitchers": {"101": {"n_pitches": 7}}})
    path, written = arch.archive_features(stale, "2026-07-10", archive_dir=tmp_path)
    assert written is False
    assert path == tmp_path / "2026-07-16.json"
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["2026-07-16.json"]


def test_archive_current_features_noops_without_artifact(tmp_path):
    result = arch.archive_current_features(
        features_path=tmp_path / "missing.json", archive_dir=tmp_path / "archive"
    )
    assert result["archive_written"] is False
    assert result["reason"] == "no features artifact"
    assert not (tmp_path / "archive").exists()
