import json

from projections.promotion_sanity import build_promotion_sanity_report
from projections.promotion_sanity import run_promotion_sanity_report
from scripts.validate_hp_promotion_sanity_report import (
    validate_hp_promotion_sanity_report,
)


def _hitter(mlbam_id="1"):
    return {
        "id": f"mlbam_{mlbam_id}_H",
        "name": "Hitter",
        "pool": "hitter",
        "stats": {"PA": 500},
        "metadata": {"mlbam_id": mlbam_id},
    }


def _pitcher(mlbam_id="2"):
    return {
        "id": f"mlbam_{mlbam_id}_P",
        "name": "Pitcher",
        "pool": "starter",
        "stats": {"IP": 160},
        "metadata": {"mlbam_id": mlbam_id},
    }


def _manifest():
    return {
        "run_id": "valucast_hp_2026_v1",
        "source_name": "valucast",
        "as_of_season": 2026,
        "hitter_count": 1,
        "pitcher_count": 1,
        "eligibility_source": (
            "current.json used for names/teams/positions; NO projection stats copied"
        ),
    }


def _scorecard():
    return {
        "version": "ValuCast H+P v1",
        "generated_at": "2026-06-15T00:00:00+00:00",
        "hitting": {"baseline": "classic Marcel"},
        "pitching": {"baseline": "persistence"},
    }


def test_promotion_report_keeps_default_promotion_human_gated():
    payload = build_promotion_sanity_report(
        projections=[_hitter(), _pitcher()],
        manifest=_manifest(),
        scorecard=_scorecard(),
        generated_at="2026-06-16T00:00:00+00:00",
    )

    assert payload["artifact"] == "valucast_hp_promotion_sanity_report"
    assert payload["promotion"]["ready_for_opt_in_source"] is True
    assert payload["promotion"]["ready_for_default_promotion"] is False
    assert payload["promotion"]["human_approval_required_for_default"] is True
    assert payload["source_policy"]["external_projection_stats_copied"] is False
    assert payload["track_record"]["hitting_baseline"] == "classic Marcel"
    assert payload["validation"]["blockers"] == []


def test_validator_rejects_silent_default_promotion(tmp_path):
    payload = build_promotion_sanity_report(
        projections=[_hitter(), _pitcher()],
        manifest=_manifest(),
        scorecard=_scorecard(),
        generated_at="2026-06-16T00:00:00+00:00",
    )
    payload["promotion"]["ready_for_default_promotion"] = True
    path = tmp_path / "hp.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_hp_promotion_sanity_report(path)

    assert any("ready_for_default_promotion" in problem for problem in problems)


def test_run_and_validate_hp_promotion_report(tmp_path):
    run_path = tmp_path / "projections.json"
    manifest_path = tmp_path / "manifest.json"
    scorecard_path = tmp_path / "scorecard.json"
    artifact_path = tmp_path / "report.json"
    run_path.write_text(json.dumps([_hitter(), _pitcher()]), encoding="utf-8")
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    scorecard_path.write_text(json.dumps(_scorecard()), encoding="utf-8")

    result = run_promotion_sanity_report(
        run_path=run_path,
        manifest_path=manifest_path,
        scorecard_path=scorecard_path,
        artifact_path=artifact_path,
    )
    _, problems = validate_hp_promotion_sanity_report(artifact_path)

    assert result["ready_for_opt_in_source"] is True
    assert problems == []
