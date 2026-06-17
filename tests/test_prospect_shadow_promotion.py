"""Tests for the ValuCast shadow-model promotion harness."""
import json

from prospects.shadow_promotion import build_shadow_promotion
from prospects.shadow_promotion import run_shadow_promotion
from scripts.validate_prospect_shadow_promotion import validate_shadow_promotion


def _seed_archive(archive_base, name, dates):
    directory = archive_base / name
    directory.mkdir(parents=True, exist_ok=True)
    for day in dates:
        (directory / f"{day}.json").write_text(json.dumps({"date": day}), encoding="utf-8")


def test_no_realized_data_yields_insufficient_sample_and_is_ready(tmp_path):
    archive_base = tmp_path / "archive"
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    _seed_archive(archive_base, "valucast_playing_time_role_tracker", ["2026-06-15", "2026-06-17"])

    payload = build_shadow_promotion(
        archive_base=archive_base, models_dir=models_dir, generated_at="2026-06-17T00:00:00+00:00"
    )

    role = next(m for m in payload["models"] if m["key"] == "playing_time_role_v2")
    assert role["observation_count"] == 2
    assert role["span_days"] == 2
    assert role["gate"]["status"] == "insufficient_sample"
    # Honest: not a card-promotion blocker, just no graded evidence yet.
    assert payload["validation"]["ready"] is True
    assert payload["summary"]["insufficient_sample_count"] == len(payload["models"])
    assert payload["source_policy"]["feeds_card"] is False


def test_card_promotion_without_active_gate_is_blocked(tmp_path):
    archive_base = tmp_path / "archive"
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    _seed_archive(archive_base, "valucast_prospect_peak_projection_v1", ["2026-06-17"])
    # Live peak artifact illegally promoted to the card while its gate is insufficient.
    (models_dir / "valucast_prospect_peak_projection_v1.json").write_text(
        json.dumps({"v2": {"feeds_card": True}}), encoding="utf-8"
    )

    payload = build_shadow_promotion(
        archive_base=archive_base, models_dir=models_dir, generated_at="2026-06-17T00:00:00+00:00"
    )

    peak = next(m for m in payload["models"] if m["key"] == "peak_projection_v2")
    assert peak["feeds_card"] is True
    assert peak["gate"]["status"] != "active"
    assert payload["validation"]["ready"] is False
    assert any("feeds the card" in b for b in payload["validation"]["blockers"])


def test_run_and_validate_shadow_promotion(tmp_path):
    archive_base = tmp_path / "archive"
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = tmp_path / "shadow.json"
    self_archive_dir = tmp_path / "self_archive"
    _seed_archive(archive_base, "valucast_prospect_dynasty_layer", ["2026-06-13", "2026-06-17"])

    result = run_shadow_promotion(
        archive_base=archive_base,
        models_dir=models_dir,
        artifact_path=artifact_path,
        self_archive_dir=self_archive_dir,
    )
    payload, problems = validate_shadow_promotion(artifact_path)

    assert result["ready"] is True
    assert result["archive_changed"] is True
    assert problems == []
    assert payload["artifact"] == "valucast_prospect_shadow_promotion"
