import json

from scripts import build_valucast_hp_run as hp


def _hitter(stats):
    return {
        "id": "mlbam_101_H",
        "name": "Test Hitter",
        "pool": "hitter",
        "positions": ["OF"],
        "team": "BOS",
        "stats": stats,
        "metadata": {"mlbam_id": "101"},
    }


def _pitcher(stats):
    return {
        "id": "mlbam_202_P",
        "name": "Test Pitcher",
        "pool": "starter",
        "positions": ["SP"],
        "team": "LAD",
        "stats": stats,
        "metadata": {"mlbam_id": "202"},
    }


def test_apply_actuals_to_remaining_recomputes_hitter_rates():
    projection = _hitter({
        "PA": 100, "AB": 90, "H": 30, "1B": 20, "2B": 5, "3B": 1, "HR": 4,
        "R": 20, "RBI": 25, "SB": 5, "CS": 1, "BB": 8, "SO": 20,
        "HBP": 1, "SF": 1, "TB": 49, "NSB": 4, "AVG": 0.333,
        "OBP": 0.390, "SLG": 0.544, "OPS": 0.934,
    })
    actual = _hitter({
        "PA": 40, "AB": 35, "H": 10, "1B": 7, "2B": 2, "3B": 0, "HR": 1,
        "R": 6, "RBI": 7, "SB": 2, "CS": 0, "BB": 4, "SO": 8,
        "HBP": 1, "SF": 0,
    })

    row = hp.apply_actuals_to_remaining([projection], [actual], "2026-06-18")[0]
    stats = row["stats"]

    assert stats["PA"] == 60
    assert stats["AB"] == 55
    assert stats["H"] == 20
    assert stats["HR"] == 3
    assert stats["R"] == 14
    assert stats["RBI"] == 18
    assert stats["SB"] == 3
    assert stats["TB"] == 34
    assert stats["NSB"] == 2
    assert stats["AVG"] == 0.364
    assert stats["OBP"] == 0.4
    assert stats["SLG"] == 0.618
    assert stats["OPS"] == 1.018
    assert row["metadata"]["actuals_as_of"] == "2026-06-18"


def test_apply_actuals_to_remaining_recomputes_pitcher_rates():
    projection = _pitcher({
        "IP": 60, "ER": 20, "BB": 15, "H_ALLOWED": 50, "K": 70,
        "W": 5, "L": 2, "SV": 3, "HLD": 5, "GS": 10, "G": 30,
        "QS": 6, "SV_HLD": 8, "ERA": 3.0, "WHIP": 1.083,
        "K_9": 10.5, "BB_9": 2.25, "K_BB": 4.667,
    })
    actual = _pitcher({
        "IP": 12, "ER": 4, "BB": 3, "H_ALLOWED": 10, "K": 15,
        "W": 1, "L": 1, "SV": 1, "HLD": 0, "GS": 2, "G": 3,
        "QS": 1,
    })

    stats = hp.apply_actuals_to_remaining([projection], [actual], "2026-06-18")[0]["stats"]

    assert stats["IP"] == 48
    assert stats["ER"] == 16
    assert stats["BB"] == 12
    assert stats["H_ALLOWED"] == 40
    assert stats["K"] == 55
    assert stats["W"] == 4
    assert stats["SV"] == 2
    assert stats["HLD"] == 5
    assert stats["SV_HLD"] == 7
    assert stats["ERA"] == 3.0
    assert stats["WHIP"] == 1.083
    assert stats["K_9"] == 10.312


def test_apply_actuals_to_remaining_records_match_and_volume_clamp_metadata():
    projection = _hitter({"PA": 20, "AB": 18, "1B": 4, "2B": 1, "3B": 0, "HR": 1,
                          "BB": 2, "HBP": 0, "SF": 0})
    actual = _hitter({"PA": 40, "AB": 35, "1B": 7, "2B": 2, "3B": 0, "HR": 1,
                      "BB": 4, "HBP": 1, "SF": 0})

    matched, unmatched = hp.apply_actuals_to_remaining(
        [projection, _pitcher({"IP": 50})], [actual], "2026-07-18",
    )

    assert matched["metadata"]["actuals_applied"] is True
    assert matched["metadata"]["remaining_opportunity_clamped"] is True
    assert unmatched["metadata"]["actuals_applied"] is False
    assert unmatched["metadata"]["remaining_opportunity_clamped"] is False


def test_manifest_reports_remaining_opportunity_diagnostics_and_holds_clamps():
    rows = hp.apply_actuals_to_remaining(
        [_hitter({"PA": 20, "AB": 18}), _pitcher({"IP": 50})],
        [_hitter({"PA": 40, "AB": 35})],
        "2026-07-18",
    )

    manifest = hp.build_manifest(rows, "2026-07-18T12:00:00+00:00", "2026-07-18")

    assert manifest["remaining_opportunity_diagnostics"] == {
        "hitters": {"rows": 1, "actuals_matched": 1, "zero_remaining": 1, "clamped_to_zero": 1},
        "pitchers": {"rows": 1, "actuals_matched": 0, "zero_remaining": 0, "clamped_to_zero": 0},
    }
    assert manifest["public_skill_metric_gate"] == {
        "status": "held",
        "affects_live_outputs": False,
        "reason": "remaining-opportunity clamping is present",
    }


def test_manifest_skill_metric_gate_requires_positive_remaining_opportunity():
    rows = hp.apply_actuals_to_remaining(
        [_hitter({"PA": 0}), _pitcher({"IP": 50})], [], "2026-07-18",
    )

    manifest = hp.build_manifest(rows, "2026-07-18T12:00:00+00:00", "2026-07-18")

    assert manifest["public_skill_metric_gate"]["status"] == "held"
    assert manifest["public_skill_metric_gate"]["reason"] == "zero remaining opportunity is present"


def test_manifest_skill_metric_gate_is_display_only_eligible_without_zero_or_clamp():
    rows = hp.apply_actuals_to_remaining(
        [_hitter({"PA": 100, "AB": 90}), _pitcher({"IP": 60})],
        [_hitter({"PA": 40, "AB": 35}), _pitcher({"IP": 12})],
        "2026-07-18",
    )

    manifest = hp.build_manifest(rows, "2026-07-18T12:00:00+00:00", "2026-07-18")

    assert manifest["public_skill_metric_gate"] == {
        "status": "display_only_eligible",
        "affects_live_outputs": False,
        "reason": "remaining-opportunity inputs have positive coverage",
    }


def test_write_live_hp_run_replaces_existing_files_atomically(tmp_path):
    run_dir = tmp_path / "valucast_hp_2026_v2"
    rows = [_hitter({"PA": 60}), _pitcher({"IP": 48})]
    manifest = hp.build_manifest(rows, "2026-07-01T00:00:00+00:00", "2026-07-01")

    result = hp.write_live_hp_run(rows, manifest, run_dir)

    assert result["changed"] is True
    assert json.loads((run_dir / "projections.json").read_text(encoding="utf-8")) == rows
    assert json.loads((run_dir / "metadata.json").read_text(encoding="utf-8")) == {
        "as_of": "2026-07-01T00:00:00+00:00"
    }
    assert not (run_dir / "projections.json.tmp").exists()


def test_write_historical_hp_snapshot_uses_actuals_override_without_live_write(tmp_path, monkeypatch):
    actuals_path = tmp_path / "actuals" / "2026-06-18.json"
    universe_path = tmp_path / "current.json"
    called = {}

    def fake_build(*, actuals_path, projection_universe_path, generated_at):
        called.update(
            {
                "actuals_path": actuals_path,
                "projection_universe_path": projection_universe_path,
                "generated_at": generated_at,
            }
        )
        return [_hitter({"PA": 60}), _pitcher({"IP": 48})]

    monkeypatch.setattr(hp, "build_valucast_hp_rows", fake_build)

    result = hp.write_historical_hp_snapshot(
        "2026-06-18",
        actuals_path=actuals_path,
        projection_universe_path=universe_path,
        archive_dir=tmp_path / "archive",
    )

    assert called == {
        "actuals_path": actuals_path,
        "projection_universe_path": universe_path,
        "generated_at": "2026-06-18T00:00:00+00:00",
    }
    assert result["archive_changed"] is True
    assert result["row_count"] == 2
    assert result["archive_path"].endswith("2026-06-18.json")
    assert not (tmp_path / "valucast_hp_2026_v2").exists()
