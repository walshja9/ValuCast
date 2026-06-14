import json
from pathlib import Path
from urllib.error import URLError

import pytest

from scripts import sync_dd_feed
from scripts import validate_public_data_freshness as freshness


def _valid_feed(generated_at="2026-06-13T11:00:00-04:00"):
    return {
        "schema_version": "1.1",
        "generated_at": generated_at,
        "player_count": 1,
        "prospect_count": 0,
        "players": [
            {
                "id": "dd_mlb_test",
                "player_type": "mlb",
                "name": "Test Player",
                "dynasty_rank": 1,
                "dynasty_value": 50.0,
            }
        ],
    }


def test_sync_feed_validates_then_replaces(tmp_path, monkeypatch):
    output = tmp_path / "feed.json"
    output.write_text('{"old":true}', encoding="utf-8")
    monkeypatch.setattr(
        sync_dd_feed,
        "fetch_feed",
        lambda _url: json.dumps(_valid_feed()).encode(),
    )

    payload = sync_dd_feed.sync_feed("https://example.test/feed", output)

    assert payload["generated_at"].startswith("2026-06-13")
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert not output.with_suffix(".json.tmp").exists()


def test_sync_feed_keeps_last_good_artifact_on_download_failure(tmp_path, monkeypatch):
    output = tmp_path / "feed.json"
    output.write_text('{"old":true}', encoding="utf-8")

    def fail(_url):
        raise URLError("offline")

    monkeypatch.setattr(sync_dd_feed, "fetch_feed", fail)

    with pytest.raises(URLError):
        sync_dd_feed.sync_feed("https://example.test/feed", output)

    assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}


def test_validate_public_data_requires_same_day_dates(tmp_path, monkeypatch):
    paths = {
        "DD_FEED": tmp_path / "dd.json",
        "PUBLIC_SNAPSHOT": tmp_path / "public_snapshot.json",
        "REDRAFT_METADATA": tmp_path / "metadata.json",
        "REDRAFT_CURRENT": tmp_path / "current.json",
        "REDRAFT_ROS": tmp_path / "ros.json",
        "ACTUALS": tmp_path / "actuals.json",
        "STATCAST": tmp_path / "statcast.json",
        "MLB_TRACK_RECORD": tmp_path / "mlb_track_record.json",
        "MLB_DYNASTY_LAYER": tmp_path / "mlb_dynasty_layer.json",
        "VALUCAST_BUYS": tmp_path / "valucast_buys.json",
        "VALUCAST_QUALITY_GOVERNOR": tmp_path / "valucast_quality_governor.json",
        "PROSPECT_AVAILABILITY": tmp_path / "prospect_availability.json",
        "PROSPECT_CALIBRATION_REPORT": tmp_path / "prospect_calibration_report.json",
        "PROSPECT_COVERAGE_AUDIT": tmp_path / "prospect_coverage_audit.json",
    }
    paths["DD_FEED"].write_text(json.dumps(_valid_feed()), encoding="utf-8")
    paths["PUBLIC_SNAPSHOT"].write_text(
        json.dumps(
            {
                "artifact": "valucast_public_dynasty_snapshot",
                "generated_at": "2026-06-13T11:00:00-04:00",
                "schema_version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    paths["REDRAFT_METADATA"].write_text(
        json.dumps({"as_of": "2026-06-13"}), encoding="utf-8"
    )
    paths["STATCAST"].write_text(
        json.dumps({"as_of": "2026-06-12"}), encoding="utf-8"
    )
    paths["MLB_DYNASTY_LAYER"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["MLB_TRACK_RECORD"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["VALUCAST_BUYS"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["VALUCAST_QUALITY_GOVERNOR"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_AVAILABILITY"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_CALIBRATION_REPORT"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_COVERAGE_AUDIT"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    for key in ("REDRAFT_CURRENT", "REDRAFT_ROS", "ACTUALS"):
        paths[key].write_text('[{"name":"Test"}]', encoding="utf-8")
    monkeypatch.setattr(freshness, "ROOT", tmp_path)
    for key, path in paths.items():
        monkeypatch.setattr(freshness, key, path)

    problems = freshness.validate_public_data("2026-06-13")

    assert problems == [
        "statcast.json as_of=2026-06-12, expected 2026-06-13"
    ]


def test_daily_public_workflow_requires_manual_buy_approval():
    workflow = Path(".github/workflows/daily-public-data.yml").read_text(
        encoding="utf-8"
    )

    assert "approve_valucast_buys" in workflow
    assert "type: boolean" in workflow
    assert "python scripts/build_mlb_track_record.py" in workflow
    assert "python scripts/validate_mlb_track_record.py" in workflow
    assert "python scripts/build_prospect_availability.py" in workflow
    assert "python scripts/build_prospect_calibration_report.py" in workflow
    assert "python scripts/validate_prospect_calibration_report.py" in workflow
    assert "data/models/valucast_mlb_track_record.json" in workflow
    assert "data/mlb/mlb_track_record_cache.json" in workflow
    assert "data/models/valucast_prospect_availability.json" in workflow
    assert "data/models/valucast_prospect_calibration_report.json" in workflow
    assert (
        "VALUCAST_BUYS_REVIEW_APPROVED: "
        "${{ github.event_name == 'workflow_dispatch' "
        "&& inputs.approve_valucast_buys && '1' || '0' }}"
    ) in workflow
