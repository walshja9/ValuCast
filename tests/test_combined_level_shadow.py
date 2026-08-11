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


# These three exercise the LIVE combined-level shadow build. They assert the
# structural invariants on whatever players currently exhibit them rather than
# pinning specific mlbam_ids / exact scores -- those drift every day as prospects
# graduate to MLB rosters (Sean Keys -> TOR) and the served board regenerates. The
# exact per-level weighting math is pinned separately + deterministically in
# test_combined_level_weighting_helper_uses_sample_weights.
def test_combined_level_shadow_weights_by_sample_not_naive_high_level_pooling():
    from prospects.combined_level_shadow import build_combined_level_shadow

    payload = build_combined_level_shadow(generated_at="2026-06-27T12:00:00+00:00")
    assert payload["status"] == "candidate_ready"

    multi = [row for row in payload["shadows"] if len(row["levels_scored"]) >= 2]
    assert multi, "expected at least one multi-level shadow on the live board"

    # Observe-only: a shadow never feeds the served model score or public rank.
    for row in payload["shadows"]:
        assert row["usage"] == USAGE
        assert row["source_policy"]["feeds_model_score"] is False
        assert row["source_policy"]["feeds_public_rank"] is False

    for row in multi:
        weights = [leg["weight"] for leg in row["level_weights"]]
        assert abs(sum(weights) - 1.0) < 0.01  # proper sample weights, sum to 1
        # larger sample -> larger weight (sample-weighted, not naive high-level)
        ordered = sorted(row["level_weights"], key=lambda leg: leg["sample"])
        assert all(a["weight"] <= b["weight"] + 1e-9 for a, b in zip(ordered, ordered[1:]))

    # The Sean-Keys class: a small gaudy high level is pulled DOWN off naive
    # highest-level pooling by the larger lower-level sample.
    assert any(
        row["naive_highest_level_combined_score"] is not None
        and row["naive_highest_level_combined_score"] >= 50.0
        and row["shadow_score"] <= row["naive_highest_level_combined_score"] - 10.0
        for row in multi
    )


def test_combined_level_shadow_keeps_served_rank_stage_penalties():
    from prospects.combined_level_shadow import build_combined_level_shadow

    payload = build_combined_level_shadow(generated_at="2026-06-27T12:00:00+00:00")
    penalized = [
        row
        for row in payload["shadows"]
        if ((row.get("rank_adjustments") or {}).get("bucket_calibration") or {}).get(
            "bucket"
        )
        == "thin_current_sample_confidence"
    ]
    assert penalized, "expected a thin-current-sample penalized shadow on the live board"

    # The rank-stage penalties are RECOMPUTED on the shadow blend (that is the
    # shadow's purpose: a fuller combined sample earns a smaller thin haircut,
    # especially after epoch-batch item A's taper -- the old fixed >=5.0
    # magnitude pinned the un-tapered penalty scale). The emitted bucket is now
    # exactly the SHADOW's application (the served row's bucket no longer leaks
    # into the metadata), so the invariant is exact flow-through arithmetic:
    # availability discount first, then the bucket total, floored at zero.
    for row in penalized:
        bucket = row["rank_adjustments"]["bucket_calibration"]
        thin = [
            rule
            for rule in bucket.get("rules", [])
            if rule["bucket"] == "thin_current_sample_confidence"
        ]
        assert thin and thin[0]["adjustment"] < 0
        rules_total = round(
            sum(rule["adjustment"] for rule in bucket.get("rules", [])), 2
        )
        assert bucket["adjustment"] == rules_total  # total, honestly labeled
        after_availability = row["rank_adjustments"][
            "score_after_availability_adjustment"
        ]
        expected = max(0.0, after_availability + rules_total)  # floors at 0
        assert abs(row["shadow_score"] - expected) <= 0.05, (
            row["mlbam_id"],
            row["shadow_score"],
            after_availability,
            rules_total,
        )
        # Penalties only ever subtract within the shadow row itself. (The old
        # cross-check `served_score <= shadow_score_before_rank_adjustments`
        # was a heuristic, not arithmetic: once mid-season samples grow, a hot
        # current level can outrun the prior-level-diluted blend, so the served
        # penalized score legitimately exceeds the fuller-sample blend -- 11
        # live AA/AAA thin-sample rows crossed that line on 2026-07-16.)
        assert row["shadow_score"] <= row["shadow_score_before_rank_adjustments"]


def test_combined_level_shadow_excludes_prior_year_served_model_lines(tmp_path):
    # The live-board invariant catches any stale line that is emitted. A
    # deterministic stale copy below proves the exclusion gate is exercised even
    # on days when every naturally served model line is current.
    import json

    from prospects.combined_level_shadow import (
        _current_rows_by_key,
        _identity,
        _served_model_line_is_current,
        build_combined_level_shadow,
    )
    from prospects.model import ARTIFACT_PATH as MODEL_PATH, INPUT_PATH

    payload = build_combined_level_shadow(generated_at="2026-06-27T12:00:00+00:00")

    # Positive control: current-season multi-level prospects ARE shadowed (so the
    # exclusion invariant below is meaningful, not vacuous).
    assert any(len(row["levels_scored"]) >= 2 for row in payload["shadows"])

    model_payload = json.loads(Path(MODEL_PATH).read_text(encoding="utf-8"))
    input_payload = json.loads(Path(INPUT_PATH).read_text(encoding="utf-8"))
    model_by_key = {
        key: row
        for row in model_payload.get("ranked", [])
        if (key := _identity(row)) is not None
    }
    current_by_key = _current_rows_by_key(input_payload)

    # Every shadowed prospect's served model line must match a current-season
    # line -- i.e. no prospect whose served line is a prior-year (stale) line is
    # ever shadowed. Removing that gate in build_combined_level_shadow would
    # admit stale-served prospects and fail this assertion.
    for row in payload["shadows"]:
        key = (row["mlbam_id"], row["role"])
        model_row = model_by_key.get(key)
        current_rows = current_by_key.get(key)
        assert model_row is not None and current_rows is not None
        assert _served_model_line_is_current(model_row, current_rows, row["role"]), (
            f"shadowed prospect {key} has a stale (non-current) served model line"
        )

    target_key = (payload["shadows"][0]["mlbam_id"], payload["shadows"][0]["role"])
    target_model_row = model_by_key[target_key]
    target_current_rows = current_by_key[target_key]
    assert _served_model_line_is_current(
        target_model_row, target_current_rows, target_key[1]
    )

    # Preserve every other real model input and make only the served sample
    # impossible to match. Without the production gate this player would still
    # have two valid current levels and would incorrectly enter the shadow.
    target_model_row["sample"] = float(target_model_row["sample"]) + 10_000.0
    assert not _served_model_line_is_current(
        target_model_row, target_current_rows, target_key[1]
    )
    stale_model_path = tmp_path / "prospect-model-with-stale-served-line.json"
    stale_model_path.write_text(json.dumps(model_payload), encoding="utf-8")

    stale_payload = build_combined_level_shadow(
        model_path=stale_model_path,
        generated_at="2026-06-27T12:00:00+00:00",
    )
    stale_shadowed_keys = {
        (row["mlbam_id"], row["role"]) for row in stale_payload["shadows"]
    }
    assert target_key not in stale_shadowed_keys


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
