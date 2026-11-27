"""Tests for ValuCast daily pipeline observability."""
import json

from ops.pipeline_observability import build_pipeline_observability
from ops.pipeline_observability import run_pipeline_observability
from scripts.validate_pipeline_observability import validate_pipeline_observability


def _snapshot():
    return {"generated_at": "2026-06-14T00:00:00+00:00"}


def _prospect_inputs():
    return {
        "generated_at": "2026-06-14T00:00:00+00:00",
        "current": {
            "fetched_date": "2026-06-14",
            "hitters": [
                {
                    "name": "Cooper Pratt",
                    "mlbam_id": 806198,
                    "role": "hitter",
                    "level": "AAA",
                    "sample_fetched_date": "2026-06-15",
                }
            ],
            "pitchers": [],
        },
    }


def test_pipeline_observability_reports_targeted_refreshes(monkeypatch, tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps({"generated_at": "2026-06-14"}), encoding="utf-8")
    second.write_text(json.dumps({"as_of": "2026-06-14"}), encoding="utf-8")
    import ops.pipeline_observability as module

    monkeypatch.setattr(
        module,
        "DATED_ARTIFACTS",
        ((first, "generated_at", "first"), (second, "as_of", "second")),
    )

    payload = build_pipeline_observability(_snapshot(), _prospect_inputs())

    assert payload["status"] == "candidate_ready"
    assert payload["validation"]["ready_for_daily_publication"] is True
    assert payload["validation"]["targeted_row_refresh_count"] == 1
    assert payload["targeted_row_refreshes"][0]["name"] == "Cooper Pratt"


def test_pipeline_observability_blocks_date_mismatches(monkeypatch, tmp_path):
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8")
    import ops.pipeline_observability as module

    monkeypatch.setattr(
        module,
        "DATED_ARTIFACTS",
        ((stale, "generated_at", "stale"),),
    )

    payload = build_pipeline_observability(_snapshot(), _prospect_inputs())

    assert payload["status"] == "blocked"
    assert payload["validation"]["date_mismatch_count"] == 1
    assert payload["date_mismatches"][0]["label"] == "stale"


def test_run_and_validate_pipeline_observability(monkeypatch, tmp_path):
    public_snapshot = tmp_path / "snapshot.json"
    prospect_inputs = tmp_path / "inputs.json"
    dated = tmp_path / "dated.json"
    artifact = tmp_path / "observability.json"
    public_snapshot.write_text(json.dumps(_snapshot()), encoding="utf-8")
    prospect_inputs.write_text(json.dumps(_prospect_inputs()), encoding="utf-8")
    dated.write_text(json.dumps({"generated_at": "2026-06-14"}), encoding="utf-8")
    import ops.pipeline_observability as module

    monkeypatch.setattr(module, "DATED_ARTIFACTS", ((dated, "generated_at", "dated"),))

    result = run_pipeline_observability(
        public_snapshot_path=public_snapshot,
        prospect_inputs_path=prospect_inputs,
        artifact_path=artifact,
    )
    payload, problems = validate_pipeline_observability(artifact)

    assert result["status"] == "candidate_ready"
    assert payload["artifact"] == "valucast_pipeline_observability"
    assert problems == []
