"""Tests for automated prospect forward-shadow tracking."""
import json

from prospects.forward_shadow import (
    _portable_output,
    build_report,
    compare_dd_adapter_snapshots,
    compare_index_snapshots,
    compare_snapshots,
    input_fingerprint,
    run_pipeline,
    should_run,
)


def _profile(mlbam_id=1, tier=0.8):
    return {
        "mlbam_id": mlbam_id,
        "name": f"Player {mlbam_id}",
        "role": "hitter",
        "dynasty_signal": {
            "bust_risk": 0.4,
            "role_or_better_probability": 0.6,
            "star_ceiling_probability": tier / 2,
            "expected_factual_outcome_tier": tier,
            "outcome_uncertainty": 0.8,
        },
    }


def _snapshot(date_str, profiles):
    return {
        "date": date_str,
        "candidate_count": len(profiles),
        "profiles": profiles,
    }


def _index_snapshot(date_str, profiles):
    board = [
        {
            "mlbam_id": profile["mlbam_id"],
            "name": profile["name"],
            "role": profile["role"],
            "universal_rank": index + 1,
            "universal_prospect_index": round(80.0 - index * 10.0, 2),
        }
        for index, profile in enumerate(profiles)
    ]
    return {
        "date": date_str,
        "candidate_count": len(board),
        "board": board,
    }


def _dd_adapter_snapshot(date_str, profiles):
    roles = {}
    for role in ("hitter", "pitcher"):
        players = [
            {
                "mlbam_id": profile["mlbam_id"],
                "name": profile["name"],
                "role": role,
                "adapter_rank": index + 1,
                "adapter_score": round(8.0 - index, 2),
            }
            for index, profile in enumerate(
                item for item in profiles if item["role"] == role
            )
        ]
        roles[role] = {
            "status": "research_ranked",
            "candidate_count": len(players),
            "players": players,
        }
    return {
        "date": date_str,
        "candidate_count": len(profiles),
        "roles": roles,
    }


def _manifest(date_str, fingerprint):
    return {
        "status": "completed",
        "date": date_str,
        "input_fingerprint": fingerprint,
        "input_contract": {"generated_at": f"{date_str}T00:00:00+00:00"},
    }


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_input_fingerprint_and_fresh_input_guard(tmp_path):
    input_path = tmp_path / "inputs.json"
    input_path.write_text('{"a":1}', encoding="utf-8")
    fingerprint = input_fingerprint(input_path)
    input_path.write_text('{\n  "a": 1\n}', encoding="utf-8")
    assert input_fingerprint(input_path) == fingerprint
    run_dir = tmp_path / "runs"
    _write(run_dir / "2026-06-13.json", _manifest("2026-06-13", fingerprint))

    assert should_run(fingerprint, run_dir) == (False, "unchanged_input")
    assert should_run(fingerprint, run_dir, force=True) == (True, "forced")
    input_path.write_text('{"a":2}', encoding="utf-8")
    assert should_run(input_fingerprint(input_path), run_dir) == (True, "fresh_input")


def test_persisted_output_summary_drops_machine_specific_paths():
    assert _portable_output(
        {
            "artifact_path": "C:/workspace/model.json",
            "archive_path": "/tmp/archive.json",
            "archive_changed": True,
            "candidate_count": 10,
        }
    ) == {"archive_changed": True, "candidate_count": 10}


def test_changed_fingerprint_cannot_move_input_contract_backward(tmp_path):
    run_dir = tmp_path / "runs"
    _write(run_dir / "2026-06-13.json", _manifest("2026-06-13", "newer"))

    assert should_run(
        "different",
        run_dir,
        input_generated_at="2026-06-12T23:59:59+00:00",
    ) == (False, "stale_input_contract")


def test_snapshot_comparison_tracks_identity_and_signal_movement():
    comparison = compare_snapshots(
        _snapshot("2026-06-13", [_profile(1, 0.8), _profile(2, 0.4)]),
        _snapshot("2026-06-20", [_profile(1, 1.0), _profile(3, 0.5)]),
    )
    assert comparison["overlap_count"] == 1
    assert comparison["overlap_rate"] == 0.5
    assert comparison["new_identity_count"] == 1
    assert comparison["exited_identity_count"] == 1
    assert comparison["signal_movement"]["expected_factual_outcome_tier"][
        "max_absolute_change"
    ] == 0.2
    assert comparison["largest_expected_tier_movers"][0]["mlbam_id"] == 1


def test_index_snapshot_comparison_tracks_rank_and_score_movement():
    previous = _index_snapshot("2026-06-13", [_profile(1), _profile(2)])
    current = _index_snapshot("2026-06-20", [_profile(2), _profile(1)])
    comparison = compare_index_snapshots(previous, current)
    assert comparison["overlap_rate"] == 1.0
    assert comparison["rank_movement"]["max_absolute_change"] == 1
    assert comparison["index_movement"]["max_absolute_change"] == 10.0


def test_dd_adapter_comparison_tracks_role_rank_and_score_movement():
    previous = _dd_adapter_snapshot("2026-06-13", [_profile(1), _profile(2)])
    current = _dd_adapter_snapshot("2026-06-20", [_profile(2), _profile(1)])
    comparison = compare_dd_adapter_snapshots(previous, current)
    assert comparison["overlap_rate"] == 1.0
    assert comparison["rank_movement"]["max_absolute_change"] == 1
    assert comparison["score_movement"]["max_absolute_change"] == 1.0


def test_report_collects_observations_but_never_authorizes_live_use(tmp_path):
    run_dir = tmp_path / "runs"
    dynasty_dir = tmp_path / "dynasty"
    index_dir = tmp_path / "index"
    dd_adapter_dir = tmp_path / "dd-adapter"
    for date_str, fingerprint, tier in (
        ("2026-06-13", "one", 0.8),
        ("2026-06-20", "two", 0.9),
    ):
        _write(run_dir / f"{date_str}.json", _manifest(date_str, fingerprint))
        _write(dynasty_dir / f"{date_str}.json", _snapshot(date_str, [_profile(1, tier)]))
        _write(index_dir / f"{date_str}.json", _index_snapshot(date_str, [_profile(1)]))
        _write(
            dd_adapter_dir / f"{date_str}.json",
            _dd_adapter_snapshot(date_str, [_profile(1)]),
        )

    report = build_report(run_dir, dynasty_dir, index_dir, dd_adapter_dir)
    assert report["status"] == "collecting"
    assert report["summary"]["completed_observation_count"] == 2
    assert report["integrity"]["status"] == "active"
    assert report["observation_contract"]["is_outcome_accuracy_evidence"] is False
    assert report["promotion"]["live_consumer"] == "blocked"
    assert report["promotion"]["feeds_live_dd_value"] is False
    assert report["promotion"]["feeds_live_valucast_rank"] is False


def test_report_blocks_duplicate_identity_integrity_failure(tmp_path):
    run_dir = tmp_path / "runs"
    dynasty_dir = tmp_path / "dynasty"
    index_dir = tmp_path / "index"
    dd_adapter_dir = tmp_path / "dd-adapter"
    date_str = "2026-06-13"
    _write(run_dir / f"{date_str}.json", _manifest(date_str, "one"))
    _write(
        dynasty_dir / f"{date_str}.json",
        _snapshot(date_str, [_profile(1), _profile(1)]),
    )
    _write(index_dir / f"{date_str}.json", _index_snapshot(date_str, [_profile(1)]))
    _write(
        dd_adapter_dir / f"{date_str}.json",
        _dd_adapter_snapshot(date_str, [_profile(1)]),
    )

    report = build_report(run_dir, dynasty_dir, index_dir, dd_adapter_dir)
    assert report["status"] == "blocked_integrity"
    assert report["integrity"]["duplicate_identity_count"] == 1


def test_report_blocks_invalid_index_rank_ordering(tmp_path):
    run_dir = tmp_path / "runs"
    dynasty_dir = tmp_path / "dynasty"
    index_dir = tmp_path / "index"
    dd_adapter_dir = tmp_path / "dd-adapter"
    date_str = "2026-06-13"
    _write(run_dir / f"{date_str}.json", _manifest(date_str, "one"))
    _write(dynasty_dir / f"{date_str}.json", _snapshot(date_str, [_profile(1)]))
    invalid_index = _index_snapshot(date_str, [_profile(1), _profile(2)])
    invalid_index["board"][1]["universal_rank"] = 1
    _write(index_dir / f"{date_str}.json", invalid_index)
    _write(
        dd_adapter_dir / f"{date_str}.json",
        _dd_adapter_snapshot(date_str, [_profile(1)]),
    )

    report = build_report(run_dir, dynasty_dir, index_dir, dd_adapter_dir)
    assert report["status"] == "blocked_integrity"
    assert report["integrity"]["index_rank_ordering_failure_count"] == 1


def test_report_blocks_invalid_dd_adapter_rank_ordering(tmp_path):
    run_dir = tmp_path / "runs"
    dynasty_dir = tmp_path / "dynasty"
    index_dir = tmp_path / "index"
    dd_adapter_dir = tmp_path / "dd-adapter"
    date_str = "2026-06-13"
    profiles = [_profile(1), _profile(2)]
    _write(run_dir / f"{date_str}.json", _manifest(date_str, "one"))
    _write(dynasty_dir / f"{date_str}.json", _snapshot(date_str, profiles))
    _write(index_dir / f"{date_str}.json", _index_snapshot(date_str, profiles))
    invalid_dd_adapter = _dd_adapter_snapshot(date_str, profiles)
    invalid_dd_adapter["roles"]["hitter"]["players"][1]["adapter_rank"] = 1
    _write(dd_adapter_dir / f"{date_str}.json", invalid_dd_adapter)

    report = build_report(run_dir, dynasty_dir, index_dir, dd_adapter_dir)
    assert report["status"] == "blocked_integrity"
    assert report["integrity"]["dd_adapter_rank_ordering_failure_count"] == 1


def test_review_ready_still_blocks_live_consumers(tmp_path):
    run_dir = tmp_path / "runs"
    dynasty_dir = tmp_path / "dynasty"
    index_dir = tmp_path / "index"
    dd_adapter_dir = tmp_path / "dd-adapter"
    start = 1
    for index in range(30):
        month = 1 + (index * 3) // 28
        day = 1 + (index * 3) % 28
        date_str = f"2026-{month:02d}-{day:02d}"
        _write(run_dir / f"{date_str}.json", _manifest(date_str, str(index)))
        _write(
            dynasty_dir / f"{date_str}.json",
            _snapshot(date_str, [_profile(start, 0.8 + index / 1000)]),
        )
        _write(
            index_dir / f"{date_str}.json",
            _index_snapshot(date_str, [_profile(start)]),
        )
        _write(
            dd_adapter_dir / f"{date_str}.json",
            _dd_adapter_snapshot(date_str, [_profile(start)]),
        )

    report = build_report(run_dir, dynasty_dir, index_dir, dd_adapter_dir)
    assert report["status"] == "review_ready"
    assert report["promotion"]["next_allowed_step"] == "human_consumer_design_review"
    assert report["promotion"]["live_consumer"] == "blocked"


def test_pipeline_skips_unchanged_input_without_calling_builders(tmp_path, monkeypatch):
    input_path = tmp_path / "inputs.json"
    input_path.write_text('{"schema_version":"test"}', encoding="utf-8")
    fingerprint = input_fingerprint(input_path)
    run_dir = tmp_path / "runs"
    dynasty_dir = tmp_path / "dynasty"
    index_dir = tmp_path / "index"
    dd_adapter_dir = tmp_path / "dd-adapter"
    _write(run_dir / "2026-06-13.json", _manifest("2026-06-13", fingerprint))

    monkeypatch.setattr(
        "prospects.forward_shadow.load_input_contract",
        lambda path: {"schema_version": "test"},
    )
    monkeypatch.setattr(
        "prospects.forward_shadow.run_model",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not build")),
    )

    result = run_pipeline(
        input_path=input_path,
        run_archive_dir=run_dir,
        dynasty_archive_dir=dynasty_dir,
        index_archive_dir=index_dir,
        dd_adapter_archive_dir=dd_adapter_dir,
        report_path=tmp_path / "report.json",
        now="2026-06-14T00:00:00+00:00",
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "unchanged_input"


def test_pipeline_anchors_observation_to_factual_contract_time(tmp_path, monkeypatch):
    input_path = tmp_path / "inputs.json"
    input_path.write_text('{"schema_version":"test"}', encoding="utf-8")
    run_dir = tmp_path / "runs"
    universal_archive_dir = tmp_path / "universal"
    dynasty_archive_dir = tmp_path / "dynasty"
    index_archive_dir = tmp_path / "index"
    dd_adapter_archive_dir = tmp_path / "dd-adapter"
    seen = {}

    monkeypatch.setattr(
        "prospects.forward_shadow.load_input_contract",
        lambda path: {
            "schema_version": "test",
            "generated_at": "2026-06-12T08:30:00+00:00",
            "current": {"fetched_date": "2026-06-12"},
            "source_policy": {"kind": "factual_only"},
        },
    )

    def fake_model(**kwargs):
        seen["model_now"] = kwargs["now"]
        return {"candidates": 1}

    def fake_backtest(**kwargs):
        seen["backtest_now"] = kwargs["now"]
        return {"research_gate": "active"}

    def fake_layer(**kwargs):
        _write(
            dynasty_archive_dir / "2026-06-12.json",
            _snapshot("2026-06-12", [_profile()]),
        )
        return {"candidate_count": 1, "research_gate": "active"}

    def fake_index_backtest(**kwargs):
        seen["index_backtest_now"] = kwargs["now"]
        return {"research_gate": "active"}

    def fake_index(**kwargs):
        _write(
            index_archive_dir / "2026-06-12.json",
            _index_snapshot("2026-06-12", [_profile()]),
        )
        return {"candidate_count": 1, "research_gate": "active"}

    def fake_adapter_backtest(**kwargs):
        seen["dd_adapter_backtest_now"] = kwargs["now"]
        return {"adapter_research_gate": "active"}

    def fake_dd_adapter(**kwargs):
        _write(
            dd_adapter_archive_dir / "2026-06-12.json",
            _dd_adapter_snapshot("2026-06-12", [_profile()]),
        )
        return {"candidate_count": 1, "research_gate": "active"}

    monkeypatch.setattr("prospects.forward_shadow.run_model", fake_model)
    monkeypatch.setattr("prospects.forward_shadow.run_backtest", fake_backtest)
    monkeypatch.setattr("prospects.forward_shadow.run_layer", fake_layer)
    monkeypatch.setattr(
        "prospects.forward_shadow.run_index_backtest", fake_index_backtest
    )
    monkeypatch.setattr("prospects.forward_shadow.run_index", fake_index)
    monkeypatch.setattr(
        "prospects.forward_shadow.run_adapter_backtest", fake_adapter_backtest
    )
    monkeypatch.setattr("prospects.forward_shadow.run_dd_adapter", fake_dd_adapter)

    result = run_pipeline(
        input_path=input_path,
        universal_archive_dir=universal_archive_dir,
        dynasty_archive_dir=dynasty_archive_dir,
        index_archive_dir=index_archive_dir,
        dd_adapter_archive_dir=dd_adapter_archive_dir,
        run_archive_dir=run_dir,
        report_path=tmp_path / "report.json",
        now=None,
    )

    assert result["date"] == "2026-06-12"
    assert seen == {
        "model_now": "2026-06-12T08:30:00+00:00",
        "backtest_now": "2026-06-12T08:30:00+00:00",
        "index_backtest_now": "2026-06-12T08:30:00+00:00",
        "dd_adapter_backtest_now": "2026-06-12T08:30:00+00:00",
    }
    assert (run_dir / "2026-06-12.json").exists()
    assert result["forward_observation_status"] == "collecting"
