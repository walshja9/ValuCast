import json
from pathlib import Path


USAGE = "combined_level_shadow_observe_only_not_live_score_or_value"


def test_combined_level_weighting_helper_uses_sample_weights():
    from prospects.combined_level_shadow import (
        _sample_reliability,
        _weighted_model_score,
    )

    score, weights = _weighted_model_score(
        [
            {"level": "AA", "sample": 209, "model_score": 28.78},
            {"level": "AAA", "sample": 77, "model_score": 47.45},
        ]
    )

    assert score == 33.81
    assert weights == [
        {"level": "AA", "sample": 209.0, "weight": 0.7308, "model_score": 28.78},
        {"level": "AAA", "sample": 77.0, "weight": 0.2692, "model_score": 47.45},
    ]
    assert _sample_reliability(286, "hitter") == 58.85


def test_sean_keys_shadow_scores_each_level_without_naive_high_level_pooling():
    from prospects.combined_level_shadow import build_combined_level_shadow

    payload = build_combined_level_shadow(generated_at="2026-06-27T12:00:00+00:00")
    keys = next(
        row
        for row in payload["shadows"]
        if row["mlbam_id"] == 815873 and row["role"] == "hitter"
    )

    assert payload["status"] == "candidate_ready"
    assert keys["usage"] == USAGE
    assert keys["served_rank"] == 160
    assert keys["served_score"] == 31.19
    assert keys["served_level"] == "AAA"
    assert keys["served_sample"] == 77.0
    assert keys["total_sample"] == 286.0
    assert keys["levels_scored"] == ["AA", "AAA"]
    assert keys["level_weights"] == [
        {"level": "AA", "sample": 209.0, "weight": 0.7308, "model_score": 28.78},
        {"level": "AAA", "sample": 77.0, "weight": 0.2692, "model_score": 47.45},
    ]
    assert 35.0 <= keys["shadow_score"] <= 37.0
    assert keys["naive_highest_level_combined_score"] >= 50.0
    assert keys["shadow_score"] <= keys["naive_highest_level_combined_score"] - 10.0
    assert keys["rank_if_live"] < keys["served_rank"]
    assert keys["delta_rank"] < 0
    assert keys["source_policy"]["feeds_model_score"] is False
    assert keys["source_policy"]["feeds_public_rank"] is False


def test_combined_level_shadow_keeps_served_rank_stage_penalties():
    from prospects.combined_level_shadow import build_combined_level_shadow

    payload = build_combined_level_shadow(generated_at="2026-06-27T12:00:00+00:00")
    castillo = next(
        row
        for row in payload["shadows"]
        if row["mlbam_id"] == 691913 and row["role"] == "hitter"
    )

    assert castillo["served_score"] == 0.0
    assert castillo["shadow_score_before_rank_adjustments"] >= 20.0
    assert castillo["shadow_score"] < 5.0
    assert castillo["rank_adjustments"]["availability_risk_discount"] == 0.03
    bucket = castillo["rank_adjustments"]["bucket_calibration"]
    assert bucket["bucket"] == "thin_current_sample_confidence"
    assert bucket["adjustment"] < 0


def test_combined_level_shadow_excludes_prior_year_served_model_lines():
    from prospects.combined_level_shadow import build_combined_level_shadow

    payload = build_combined_level_shadow(generated_at="2026-06-27T12:00:00+00:00")
    keys = {(row["mlbam_id"], row["role"]) for row in payload["shadows"]}

    assert (815873, "hitter") in keys  # Sean Keys: served model line is 2026 AA.
    assert (808825, "pitcher") not in keys  # Andrew Sears: served line is 2025 A+.
    assert (686628, "pitcher") not in keys  # Blake Burkhalter: served line is 2025 AA.
    assert (811291, "pitcher") not in keys  # Eriq Swan: served line is 2025 A+.


def test_combined_level_shadow_artifact_and_validator_round_trip(tmp_path):
    from prospects.combined_level_shadow import run_combined_level_shadow
    from scripts.validate_combined_level_shadow import validate_combined_level_shadow

    blocked_result = run_combined_level_shadow(
        model_path=tmp_path / "missing-model.json",
        rank_path=tmp_path / "missing-rank.json",
        input_path=tmp_path / "missing-input.json",
        artifact_path=tmp_path / "blocked.json",
        archive_dir=tmp_path / "blocked-archive",
        generated_at="2026-06-27T12:00:00+00:00",
    )
    blocked_payload = json.loads(Path(blocked_result["artifact_path"]).read_text())
    assert blocked_payload["status"] == "blocked"
    assert blocked_payload["validation"]["blockers"]

    artifact_path = tmp_path / "shadow.json"
    archive_dir = tmp_path / "archive"
    result = run_combined_level_shadow(
        artifact_path=artifact_path,
        archive_dir=archive_dir,
        generated_at="2026-06-27T12:00:00+00:00",
    )

    payload, problems = validate_combined_level_shadow(artifact_path)
    assert problems == []
    assert result["status"] == "candidate_ready"
    assert payload["artifact"] == "valucast_combined_level_shadow"
    assert payload["shadow_version"] == "0.1.0"
    assert payload["summary"]["shadowed_count"] > 0
    assert payload["summary"]["multi_level_count"] == payload["summary"]["shadowed_count"]
    assert payload["shadows"][0]["usage"] == USAGE
    assert (archive_dir / "2026-06-27.json").exists()

    payload["source_policy"]["feeds_buy_score"] = True
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    _payload, problems = validate_combined_level_shadow(artifact_path)
    assert any("feeds_buy_score" in problem for problem in problems)


def test_combined_level_shadow_is_wired_into_build_and_shadow_workflow():
    from scripts import run_daily_public_build

    workflow = Path(".github/workflows/prospect-shadow.yml").read_text(encoding="utf-8")
    build_steps = [" ".join(step) for step in run_daily_public_build.BUILD_STEPS]
    validate_steps = [" ".join(step) for step in run_daily_public_build.VALIDATE_STEPS]

    assert build_steps.index("scripts/build_combined_level_shadow.py") == (
        build_steps.index("scripts/build_prospect_rank_v1.py") + 1
    )
    assert "scripts/validate_combined_level_shadow.py" in validate_steps
    assert "tests/test_combined_level_shadow.py" in workflow
    assert "data/models/valucast_combined_level_shadow.json" in workflow
    assert "data/prediction_archive/valucast_combined_level_shadow" in workflow
