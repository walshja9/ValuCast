import json
import sys
from pathlib import Path
from urllib.error import URLError

import pytest

from scripts import sync_dd_prospect_inputs
from scripts import run_daily_public_build
from scripts import validate_public_data_freshness as freshness


def test_prospect_shadow_workflow_serializes_with_daily_refresh_and_syncs_master():
    workflow = Path(".github/workflows/prospect-shadow.yml").read_text(encoding="utf-8")

    assert "group: daily-public-data-refresh" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "uses: actions/checkout@" in workflow
    assert "uses: actions/setup-python@" in workflow
    assert "git fetch origin" in workflow
    assert "git checkout -B master origin/master" in workflow


def _valid_prospect_inputs(generated_at="2026-06-13T11:00:00-04:00"):
    return {
        "schema_version": "1.1",
        "generated_at": generated_at,
        "source_policy": {
            "kind": "factual_only",
            "sources": [
                "valucast_universal_prospect_dataset",
                "milb_season_stats",
                "fantrax_mlb_actuals",
                "mlb_prospect_seasons_cache",
                "mlb_statsapi_draft",
            ],
            "external_rankings_used": False,
            "external_projections_used": False,
            "market_values_used": False,
            "dynasty_values_used": False,
        },
        "historical": {"rows": []},
        "current": {"hitters": [], "pitchers": []},
        "mlb_service": [
            {
                "mlbam_id": 101,
                "role": "hitter",
                "pa": 500.0,
                "ab": 500.0,
                "ip": 0.0,
                "graduated": True,
            }
        ],
    }


def test_sync_prospect_inputs_validates_then_replaces(tmp_path, monkeypatch):
    output = tmp_path / "prospect_model_inputs.json"
    output.write_text('{"old":true}', encoding="utf-8")
    monkeypatch.setattr(
        sync_dd_prospect_inputs,
        "fetch_contract",
        lambda _url: json.dumps(_valid_prospect_inputs()).encode(),
    )

    payload = sync_dd_prospect_inputs.sync_contract(
        "https://example.test/prospect-inputs",
        output,
    )

    assert payload["source_policy"]["kind"] == "factual_only"
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert not output.with_suffix(".json.tmp").exists()


def test_sync_prospect_inputs_accepts_v12_factual_roster_status_source(tmp_path, monkeypatch):
    output = tmp_path / "prospect_model_inputs.json"
    output.write_text('{"old":true}', encoding="utf-8")
    payload = _valid_prospect_inputs()
    payload["schema_version"] = "1.2"
    payload["source_policy"]["sources"].append("fantrax_roster_status")
    payload["current"]["hitters"].append(
        {
            "mlbam_id": 101,
            "name": "Injured Prospect",
            "role": "hitter",
            "availability_status": "injured",
            "availability_source": "fantrax_roster_status",
            "roster_status": "Inj Res",
        }
    )
    monkeypatch.setattr(
        sync_dd_prospect_inputs,
        "fetch_contract",
        lambda _url: json.dumps(payload).encode(),
    )

    synced = sync_dd_prospect_inputs.sync_contract(
        "https://example.test/prospect-inputs",
        output,
    )

    assert synced["schema_version"] == "1.2"
    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_sync_prospect_inputs_keeps_last_good_artifact_on_failure(tmp_path, monkeypatch):
    output = tmp_path / "prospect_model_inputs.json"
    output.write_text('{"old":true}', encoding="utf-8")

    def fail(_url):
        raise URLError("offline")

    monkeypatch.setattr(sync_dd_prospect_inputs, "fetch_contract", fail)

    with pytest.raises(URLError):
        sync_dd_prospect_inputs.sync_contract(
            "https://example.test/prospect-inputs",
            output,
        )

    assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}


def test_sync_prospect_inputs_rejects_non_factual_contract(tmp_path, monkeypatch):
    output = tmp_path / "prospect_model_inputs.json"
    output.write_text('{"old":true}', encoding="utf-8")
    payload = _valid_prospect_inputs()
    payload["source_policy"]["dynasty_values_used"] = True
    monkeypatch.setattr(
        sync_dd_prospect_inputs,
        "fetch_contract",
        lambda _url: json.dumps(payload).encode(),
    )

    with pytest.raises(ValueError, match="dynasty_values_used"):
        sync_dd_prospect_inputs.sync_contract(
            "https://example.test/prospect-inputs",
            output,
        )

    assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}


def test_sync_prospect_inputs_rejects_invalid_service_rows(tmp_path, monkeypatch):
    output = tmp_path / "prospect_model_inputs.json"
    output.write_text('{"old":true}', encoding="utf-8")
    payload = _valid_prospect_inputs()
    payload["mlb_service"] = [{"mlbam_id": 101, "role": "hitter"}]
    monkeypatch.setattr(
        sync_dd_prospect_inputs,
        "fetch_contract",
        lambda _url: json.dumps(payload).encode(),
    )

    with pytest.raises(ValueError, match="graduated must be boolean"):
        sync_dd_prospect_inputs.sync_contract(
            "https://example.test/prospect-inputs",
            output,
        )

    assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}


def test_validate_public_data_requires_same_day_dates(tmp_path, monkeypatch):
    paths = {
        "VALUCAST_PROSPECT_INPUTS": tmp_path / "valucast_prospect_inputs.json",
        "PUBLIC_SNAPSHOT": tmp_path / "public_snapshot.json",
        "REDRAFT_METADATA": tmp_path / "metadata.json",
        "REDRAFT_CURRENT": tmp_path / "current.json",
        "REDRAFT_ROS": tmp_path / "ros.json",
        "ACTUALS": tmp_path / "actuals.json",
        "STATCAST": tmp_path / "statcast.json",
        "MLB_TRACK_RECORD": tmp_path / "mlb_track_record.json",
        "MLB_AVAILABILITY": tmp_path / "mlb_availability.json",
        "MLB_ROSTER_STATUS": tmp_path / "mlb_roster_status.json",
        "MLB_DYNASTY_LAYER": tmp_path / "mlb_dynasty_layer.json",
        "VALUCAST_MOVERS": tmp_path / "valucast_movers.json",
        "VALUCAST_RECEIPTS": tmp_path / "valucast_receipts.json",
        "VALUCAST_BUYS": tmp_path / "valucast_buys.json",
        "PROSPECT_LEAGUE_ADAPTERS": tmp_path / "valucast_prospect_league_adapters.json",
        "VALUCAST_BUYS_MONITOR": tmp_path / "valucast_buys_monitor.json",
        "VALUCAST_QUALITY_GOVERNOR": tmp_path / "valucast_quality_governor.json",
        "MILB_STAT_FRESHNESS_AUDIT": tmp_path / "milb_stat_freshness.json",
        "PROSPECT_CARD_DATA_AUDIT": tmp_path / "prospect_card_data_audit.json",
        "RECENT_SIGNAL_REPORT": tmp_path / "recent_signal_report.json",
        "POOLED_SHADOW": tmp_path / "pooled_shadow.json",
        "PIPELINE_OBSERVABILITY": tmp_path / "pipeline_observability.json",
        "PROSPECT_MODEL_V07": tmp_path / "prospect_model_v07.json",
        "PROSPECT_OUTCOME_BACKTEST": tmp_path / "prospect_outcome_backtest.json",
        "PROSPECT_CROSS_ROLE_SHADOW": tmp_path / "prospect_cross_role_shadow.json",
        "RAW_DATA_INDEPENDENCE_AUDIT": tmp_path / "raw_data_independence.json",
        "FRONT_OFFICE_REPORT": tmp_path / "front_office_report.json",
        "FRONT_OFFICE_FAILURES": tmp_path / "front_office_failures.json",
        "PROSPECT_AVAILABILITY": tmp_path / "prospect_availability.json",
        "PROSPECT_CALIBRATION_REPORT": tmp_path / "prospect_calibration_report.json",
        "PROSPECT_PEAK_PROJECTION": tmp_path / "prospect_peak_projection.json",
        "PROSPECT_PEAK_CALIBRATION": tmp_path / "prospect_peak_calibration.json",
        "PROSPECT_FORWARD_VALIDATION": tmp_path / "prospect_forward_validation.json",
        "PROSPECT_COVERAGE_AUDIT": tmp_path / "prospect_coverage_audit.json",
        "PLAYING_TIME_ROLE_TRACKER": tmp_path / "playing_time_role_tracker.json",
        "SCOUTING_REPORTS": tmp_path / "scouting_reports.json",
        "RECENT_FORM_SIGNAL": tmp_path / "recent_form_signal.json",
        "CALL_UP_PULSE": tmp_path / "call_up_pulse.json",
        "AHEAD_OF_CONSENSUS_SCORECARD": tmp_path / "aotc_scorecard.json",
        "VALUCAST_PROSPECT_COMPS": tmp_path / "valucast_prospect_comps.json",
        "VALUCAST_CONSENSUS_GAP": tmp_path / "valucast_consensus_gap.json",
        "VALUCAST_PROSPECT_RANK_V1": tmp_path / "valucast_prospect_rank_v1.json",
    }
    paths["VALUCAST_PROSPECT_INPUTS"].write_text(
        json.dumps(_valid_prospect_inputs()), encoding="utf-8"
    )
    paths["PUBLIC_SNAPSHOT"].write_text(
        json.dumps(
            {
                "artifact": "valucast_public_dynasty_snapshot",
                "generated_at": "2026-06-13T11:00:00-04:00",
                "schema_version": "1.1",
            }
        ),
        encoding="utf-8",
    )
    paths["REDRAFT_METADATA"].write_text(
        json.dumps({"as_of": "2026-06-13", "season": 2026}), encoding="utf-8"
    )
    paths["STATCAST"].write_text(
        json.dumps({"as_of": "2026-06-12"}), encoding="utf-8"
    )
    paths["MLB_DYNASTY_LAYER"].write_text(
        json.dumps({"generated_at": "2026-06-13", "players": [{}] * 300}),
        encoding="utf-8",
    )
    paths["MLB_TRACK_RECORD"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["MLB_AVAILABILITY"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["MLB_ROSTER_STATUS"].write_text(
        json.dumps({"generated_at": "2026-06-13", "profiles": [{}] * 300}),
        encoding="utf-8",
    )
    paths["VALUCAST_MOVERS"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["VALUCAST_RECEIPTS"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["VALUCAST_BUYS"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["VALUCAST_BUYS_MONITOR"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["VALUCAST_QUALITY_GOVERNOR"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["MILB_STAT_FRESHNESS_AUDIT"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_CARD_DATA_AUDIT"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["RECENT_SIGNAL_REPORT"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["POOLED_SHADOW"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["RECENT_FORM_SIGNAL"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["CALL_UP_PULSE"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["AHEAD_OF_CONSENSUS_SCORECARD"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PIPELINE_OBSERVABILITY"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_MODEL_V07"].write_text(
        json.dumps({"generated_at": "2026-06-13", "candidates": [{}] * 500}),
        encoding="utf-8",
    )
    paths["PROSPECT_OUTCOME_BACKTEST"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_CROSS_ROLE_SHADOW"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["RAW_DATA_INDEPENDENCE_AUDIT"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["FRONT_OFFICE_REPORT"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["FRONT_OFFICE_FAILURES"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_AVAILABILITY"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_CALIBRATION_REPORT"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_PEAK_PROJECTION"].write_text(
        json.dumps({"generated_at": "2026-06-13", "projections": [{}] * 500}),
        encoding="utf-8",
    )
    paths["PROSPECT_PEAK_CALIBRATION"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_FORWARD_VALIDATION"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PROSPECT_COVERAGE_AUDIT"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["PLAYING_TIME_ROLE_TRACKER"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["SCOUTING_REPORTS"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    paths["VALUCAST_PROSPECT_COMPS"].write_text(
        json.dumps({"generated_at": "2026-06-13", "players": [{}] * 20}),
        encoding="utf-8",
    )
    paths["VALUCAST_CONSENSUS_GAP"].write_text(
        json.dumps(
            {"generated_at": "2026-06-13", "higher": [{}] * 3, "lower": [{}] * 3}
        ),
        encoding="utf-8",
    )
    paths["VALUCAST_PROSPECT_RANK_V1"].write_text(
        json.dumps({"generated_at": "2026-06-13", "board": [{}] * 1500}),
        encoding="utf-8",
    )
    paths["PROSPECT_LEAGUE_ADAPTERS"].write_text(
        json.dumps({"generated_at": "2026-06-13"}), encoding="utf-8"
    )
    for key in ("REDRAFT_CURRENT", "REDRAFT_ROS"):
        paths[key].write_text('[{"name":"Test"}]', encoding="utf-8")
    paths["ACTUALS"].write_text(
        '[{"name":"Test","metadata":{"as_of":"2026-06-13"}}]', encoding="utf-8"
    )
    monkeypatch.setattr(freshness, "ROOT", tmp_path)
    for key, path in paths.items():
        monkeypatch.setattr(freshness, key, path)

    problems = freshness.validate_public_data("2026-06-13")

    assert problems == [
        "statcast.json as_of=2026-06-12, expected 2026-06-13"
    ]

    # {"generated_at": today, "players": []} used to validate "fresh" -- the
    # date-only gate certified semantically-empty artifacts (7/2 audit).
    paths["MLB_DYNASTY_LAYER"].write_text(
        json.dumps({"generated_at": "2026-06-13", "players": []}), encoding="utf-8"
    )
    problems = freshness.validate_public_data("2026-06-13")
    assert any("semantically empty" in p for p in problems)


def test_daily_public_workflow_approves_scheduled_buys_and_omits_retired_dd_feed():
    workflow = Path(".github/workflows/daily-public-data.yml").read_text(
        encoding="utf-8"
    )
    build_commands = [" ".join(step) for step in run_daily_public_build.BUILD_STEPS]
    validate_commands = [" ".join(step) for step in run_daily_public_build.VALIDATE_STEPS]

    assert "approve_valucast_buys" in workflow
    assert "type: boolean" in workflow
    assert "python scripts/sync_dd_feed.py" not in workflow
    assert "python scripts/sync_dd_prospect_inputs.py" not in workflow
    assert "data/dd/dd_dynasty_feed.json" not in workflow
    assert "python scripts/refresh_milb_season_stats.py" in workflow
    assert "python scripts/build_valucast_prospect_inputs.py --refresh-service-cache" in workflow
    assert "python scripts/run_daily_public_build.py --only build" in workflow
    assert "python scripts/run_daily_public_build.py --only validate" in workflow
    assert "scripts/backfill_projection_identities.py" in build_commands
    # 7/1: league adapters joined the nightly chain (the artifact had frozen at a
    # June manual build) — step ordered after the shadow pipeline, artifact committed.
    assert build_commands.count("scripts/build_prospect_league_adapters.py") == 1
    assert "data/models/valucast_prospect_league_adapters.json" in workflow
    assert workflow.count(
        "data/prediction_archive/valucast_prospect_league_adapters"
    ) == 1
    # 7/2: scheduled fallbacks skip when today's refresh already published.
    assert "needs: preflight" in workflow
    assert "needs.preflight.outputs.proceed == 'true'" in workflow
    assert "data: daily public refresh $today" in workflow
    assert (
        "scripts/backfill_projection_identities.py "
        "--projection-path projections/runs/valucast_hp_2026_v2/projections.json"
    ) in build_commands
    assert "scripts/build_valucast_hp_run.py" in build_commands
    assert build_commands.index("scripts/build_valucast_hp_run.py") < build_commands.index(
        "scripts/build_mlb_dynasty_layer.py"
    )
    assert "scripts/archive_valucast_actuals_snapshot.py" in build_commands
    assert "scripts/build_mlb_track_record.py" in build_commands
    assert "scripts/build_mlb_availability.py" in build_commands
    assert "scripts/build_hp_promotion_sanity_report.py" in build_commands
    assert "scripts/build_playing_time_role_tracker.py" in build_commands
    assert "scripts/build_mlb_roster_status.py" in build_commands
    assert "scripts/validate_hp_promotion_sanity_report.py" in validate_commands
    assert "scripts/validate_mlb_availability.py" in validate_commands
    assert "scripts/validate_playing_time_role_tracker.py" in validate_commands
    assert "scripts/validate_mlb_roster_status.py" in validate_commands
    assert "scripts/validate_mlb_track_record.py" in validate_commands
    assert "scripts/validate_feed.py" not in validate_commands
    assert "scripts/validate_valucast_prospect_inputs.py" in validate_commands
    assert "scripts/run_prospect_shadow_pipeline.py" in build_commands
    assert "scripts/build_prospect_availability.py" in build_commands
    assert "scripts/build_prospect_model_v07.py" in build_commands
    assert build_commands.count("scripts/build_prospect_model_v07.py") == 1
    assert "scripts/build_prospect_calibration_report.py" in build_commands
    assert "scripts/build_prospect_peak_calibration_report.py" in build_commands
    assert "scripts/build_prospect_forward_validation.py" in build_commands
    assert "scripts/build_valucast_buys_monitor.py" in build_commands
    assert "scripts/build_valucast_movers.py" in build_commands
    assert "scripts/build_prospect_outcome_backtest.py" in build_commands
    assert "scripts/build_prospect_cross_role_shadow.py" in build_commands
    assert build_commands.index(
        "scripts/build_aaa_statcast_features.py"
    ) < build_commands.index("scripts/build_prospect_cross_role_shadow.py")
    assert build_commands.index(
        "scripts/build_prospect_cross_role_shadow.py"
    ) < build_commands.index("scripts/build_prospect_outcome_backtest.py")
    # 7/16 (plan 030 S3): forward-ledger scoreboard builds right after the gaps claim
    # ledger and validates after the ledger validator; the manually-registered cohort
    # registry is NEVER built nightly.
    assert "scripts/build_forward_scoreboard.py" in build_commands
    assert build_commands.index("scripts/build_gaps_claim_ledger.py") < build_commands.index(
        "scripts/build_forward_scoreboard.py"
    )
    assert "scripts/validate_forward_scoreboard.py" in validate_commands
    assert "data/models/valucast_forward_scoreboard.json" in workflow
    assert not any("build_forward_cohort_registry.py" in cmd for cmd in build_commands)
    assert "valucast_forward_cohort_registry.json" not in workflow
    # AAA-Statcast season-stamped vintage archive lands right after the feature build.
    assert "scripts/archive_aaa_statcast_features.py" in build_commands
    assert build_commands.index("scripts/build_aaa_statcast_features.py") < build_commands.index(
        "scripts/archive_aaa_statcast_features.py"
    )
    assert "data/aaa_statcast_archive/" in workflow
    assert "scripts/build_raw_data_independence_audit.py" in build_commands
    assert "scripts/build_front_office_failures.py" in build_commands
    assert "scripts/build_milb_stat_freshness_audit.py" in build_commands
    assert "scripts/build_pipeline_observability.py" in build_commands
    assert "scripts/validate_milb_stat_freshness_audit.py" in validate_commands
    assert "scripts/validate_pipeline_observability.py" in validate_commands
    assert "scripts/build_front_office_report.py" in build_commands
    assert "scripts/build_scouting_repository.py" in build_commands
    assert "scripts/validate_prospect_availability.py" in validate_commands
    assert "scripts/validate_prospect_model_v07.py" in validate_commands
    assert "scripts/validate_prospect_calibration_report.py" in validate_commands
    assert "scripts/validate_prospect_peak_calibration_report.py" in validate_commands
    assert "scripts/validate_prospect_forward_validation.py" in validate_commands
    assert "scripts/validate_prospect_outcome_backtest.py" in validate_commands
    assert "scripts/validate_prospect_cross_role_shadow.py" in validate_commands
    assert "scripts/validate_front_office_failures.py" in validate_commands
    assert "scripts/validate_raw_data_independence_audit.py" in validate_commands
    assert "scripts/validate_valucast_buys_monitor.py" in validate_commands
    assert "scripts/validate_valucast_movers.py" in validate_commands
    assert "scripts/validate_front_office_report.py" in validate_commands
    assert "scripts/validate_scouting_repository.py" in validate_commands
    assert "data/models/valucast_mlb_track_record.json" in workflow
    assert "data/models/valucast_mlb_availability.json" in workflow
    assert "data/models/valucast_hp_promotion_sanity_report.json" in workflow
    assert "data/models/valucast_playing_time_role_tracker.json" in workflow
    assert "data/models/valucast_mlb_roster_status.json" in workflow
    assert "data/mlb/mlb_availability_transactions_cache.json" in workflow
    assert "data/mlb/mlb_roster_status_cache.json" in workflow
    assert "data/mlb/mlb_track_record_cache.json" in workflow
    assert "data/prospects/prospect_model_inputs.json" in workflow
    assert "data/prospects/raw" in workflow
    assert "data/models/valucast_universal_prospect_model.json" in workflow
    assert "data/models/valucast_prospect_dynasty_layer.json" in workflow
    assert "data/models/valucast_prospect_availability.json" in workflow
    assert "data/models/valucast_prospect_model_v0_7.json" in workflow
    assert "data/models/valucast_prospect_calibration_report.json" in workflow
    assert "data/models/valucast_prospect_peak_projection_calibration.json" in workflow
    assert "data/models/valucast_prospect_forward_validation.json" in workflow
    assert "data/models/valucast_prospect_buys_monitor.json" in workflow
    assert "data/models/valucast_prospect_movers.json" in workflow
    assert "data/models/valucast_prospect_outcome_backtest.json" in workflow
    assert "data/models/valucast_prospect_cross_role_shadow.json" in workflow
    assert "data/models/valucast_front_office_failures.json" in workflow
    assert "data/models/valucast_raw_data_independence_audit.json" in workflow
    assert "data/models/valucast_front_office_report.json" in workflow
    assert "data/models/valucast_scouting_reports.json" in workflow
    assert "data/models/valucast_ahead_of_consensus.json" in workflow
    assert "data/prediction_archive/valucast_actuals_snapshot" in workflow
    assert "projections/runs/valucast_hp_2026_v2/projections.json" in workflow
    assert "projections/runs/valucast_hp_2026_v2/run_manifest.json" in workflow
    assert "projections/runs/valucast_hp_2026_v2/metadata.json" in workflow
    assert (
        "VALUCAST_BUYS_REVIEW_APPROVED: "
        "${{ (github.event_name == 'schedule' || inputs.approve_valucast_buys) "
        "&& '1' || '0' }}"
    ) in workflow
    assert 'VALUCAST_SCOUTING_LLM_MAX_GENERATE: "300"' in workflow
    assert 'VALUCAST_SCOUTING_LLM_TIMEOUT_SECONDS: "10"' in workflow
    # 379015c replaced the cross-run rebase-merge recovery (which silently dropped
    # this run's freshly built artifacts) with: sync to the latest origin/master
    # right after checkout, build on it, then a single fail-loud push. Assert the
    # new contract AND that the old rebase/retry recovery is gone for good.
    assert "git checkout -B master origin/master" in workflow
    assert "git push origin master" in workflow
    assert "git rebase" not in workflow
    assert "for attempt in" not in workflow

    # A long/manual run may cross UTC midnight. Build, validation, and the
    # marker commit must keep using the date captured for that one run.
    pin_date = workflow.index("VALUCAST_REFRESH_DATE=$(date -u +%F)")
    build = workflow.index("python scripts/run_daily_public_build.py --only build")
    validate = workflow.index("python scripts/run_daily_public_build.py --only validate")
    commit = workflow.index(
        'git commit -m "data: daily public refresh $VALUCAST_REFRESH_DATE"'
    )
    assert pin_date < build < validate < commit


def test_freshness_cli_uses_pinned_refresh_date(monkeypatch):
    calls = []
    monkeypatch.setenv("VALUCAST_REFRESH_DATE", "2026-08-06")
    monkeypatch.setattr(sys, "argv", ["validate_public_data_freshness.py"])
    monkeypatch.setattr(
        freshness,
        "validate_public_data",
        lambda expected_date, max_age_days=0: calls.append(
            (expected_date, max_age_days)
        ) or [],
    )

    assert freshness.main() == 0
    assert calls == [("2026-08-06", 0)]


def test_daily_public_workflow_retries_and_preserves_scouting_progress():
    workflow = Path(".github/workflows/daily-public-data.yml").read_text(
        encoding="utf-8"
    )
    cache_sha = "0400d5f644dc74513175e3cd8d07132dd4860809"
    cache_path = "data/models/valucast_scouting_llm_cache.json"
    restore_name = "- name: Restore LLM scouting cache"
    build_name = "- name: Build ValuCast public snapshot gate"
    save_name = "- name: Save LLM scouting cache"

    assert '- cron: "30 11-19 * * *"' in workflow
    assert workflow.count("- cron:") == 1
    assert workflow.count(cache_path) >= 2
    assert f"uses: actions/cache/restore@{cache_sha} # v4.2.4" in workflow
    assert f"uses: actions/cache/save@{cache_sha} # v4.2.4" in workflow
    assert "scouting-llm-v1-${{ runner.os }}-${{ github.run_id }}" in workflow
    assert "key: ${{ steps.scouting-llm-cache.outputs.cache-primary-key }}" in workflow

    restore = workflow.index(restore_name)
    build = workflow.index(build_name)
    save = workflow.index(save_name)
    assert restore < build < save
    save_step = workflow[save : workflow.find("\n      - name:", save + 1)]
    assert "if: always()" in save_step


def test_daily_public_build_orchestrator_has_no_duplicate_steps():
    run_daily_public_build.validate_steps()
    build_steps = [" ".join(step) for step in run_daily_public_build.BUILD_STEPS]
    validate_steps = [" ".join(step) for step in run_daily_public_build.VALIDATE_STEPS]
    assert len(build_steps) == len(set(build_steps))
    assert len(validate_steps) == len(set(validate_steps))
    assert "scripts/sync_dd_feed.py" not in build_steps
    assert "scripts/validate_feed.py" not in validate_steps


def test_prospect_shadow_workflow_keys_off_valucast_inputs():
    workflow = Path(".github/workflows/prospect-shadow.yml").read_text(
        encoding="utf-8"
    )

    assert "data/prospects/prospect_model_inputs.json" in workflow
    assert "data/prospects/raw/**" in workflow
    assert "data/dd/prospect_model_inputs.json" not in workflow
    assert "dd_7x7" not in workflow
    assert "valucast_dd_7x7_prospect_adapter" not in workflow
    assert "test_dd_7x7_prospect_adapter.py" not in workflow
