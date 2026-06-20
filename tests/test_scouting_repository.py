import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scouting.repository import build_scouting_repository
from scripts.validate_scouting_repository import validate_scouting_repository


def _write_snapshot(tmp_path):
    payload = {
        "schema_version": "1.1",
        "artifact": "valucast_public_dynasty_snapshot",
        "generated_at": "2026-06-16T00:00:00+00:00",
        "generated_by": "valucast",
        "source_policy": {
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used_for_score": False,
            "market_values_used_for_score": False,
        },
        "validation": {
            "ready_for_live_consumers": False,
            "duplicate_identity_count": 0,
            "required_fields_complete": True,
        },
        "players": [
            {
                "id": "vc_prospect_1_hitter",
                "player_type": "prospect",
                "name": "Model Strong",
                "mlbam_id": 1,
                "role": "hitter",
                "bats": "L",
                "throws": "R",
                "positions": ["SS"],
                "team": "BOS",
                "mlb_team": "BOS",
                "age": 20,
                "rank": 1,
                "value": 55.5,
                "value_scale": "0_100_valucast_dynasty_score",
                "value_source": "prospect_model_v0_6",
                "confidence": "medium",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "status": "candidate_ready",
                "prospect_rank": 1,
                "level": "AA",
                "eta": 2027,
                "score_source": "prospect_model_v0_6",
                "stat_line": {
                    "pa": 224,
                    "ops": 0.976,
                    "iso": 0.261,
                    "k_pct": 12.9,
                    "bb_pct": 9.8,
                    "avg": 0.318,
                    "obp": 0.397,
                    "slg": 0.579,
                },
                "context": {
                    "stat_line_source": "valucast_input_contract",
                    "stat_line_source_kind": "current_season",
                    "stat_line_sample": 224,
                    "stat_line_sample_unit": "PA",
                    "stat_line_sample_season": 2026,
                },
            },
            {
                "id": "vc_prospect_2_pitcher",
                "player_type": "prospect",
                "name": "Starter Arm",
                "mlbam_id": 2,
                "role": "pitcher",
                "bats": "L",
                "throws": "L",
                "positions": ["SP"],
                "team": "SEA",
                "mlb_team": "SEA",
                "age": 21,
                "rank": 2,
                "value": 50.0,
                "value_scale": "0_100_valucast_dynasty_score",
                "value_source": "prospect_model_v0_6",
                "confidence": "medium",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "status": "candidate_ready",
                "prospect_rank": 2,
                "level": "AA",
                "eta": 2027,
                "score_source": "prospect_model_v0_6",
                "stat_line": {
                    "ip": 55.7,
                    "k_per_9": 13.3,
                    "bb_per_9": 1.1,
                    "k_bb_pct": 37.7,
                    "era": 1.13,
                    "whip": 0.66,
                },
                "context": {
                    "stat_line_source": "valucast_input_contract",
                    "stat_line_source_kind": "current_season",
                    "stat_line_sample": 55.7,
                    "stat_line_sample_unit": "IP",
                    "stat_line_sample_season": 2026,
                },
            },
        ],
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_scouting_repository_builds_stat_grounded_reports(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)

    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )

    assert payload["artifact"] == "valucast_scouting_report_repository"
    assert payload["source_policy"]["llm_generated"] is False
    assert payload["source_policy"]["external_rankings_used_for_report"] is False
    assert payload["validation"]["ready_for_repository"] is True
    assert payload["summary"]["report_count"] == 2
    assert payload["reports"][0]["report"]
    assert payload["reports"][0]["usage"] == "scouting_repository_context_not_live_rank_or_value"


def test_scouting_repository_default_covers_deeper_prospect_cards(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    deep_card = json.loads(json.dumps(data["players"][0]))
    deep_card.update(
        {
            "id": "vc_prospect_384_hitter",
            "name": "Deep Card",
            "mlbam_id": 384,
            "rank": 384,
            "prospect_rank": 384,
            "value": 27.2,
        }
    )
    outside_coverage = json.loads(json.dumps(data["players"][0]))
    outside_coverage.update(
        {
            "id": "vc_prospect_501_hitter",
            "name": "Outside Coverage",
            "mlbam_id": 501,
            "rank": 501,
            "prospect_rank": 501,
            "value": 18.0,
        }
    )
    data["players"].extend([deep_card, outside_coverage])
    snapshot_path.write_text(json.dumps(data), encoding="utf-8")

    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )

    names = {report["name"] for report in payload["reports"]}
    assert payload["summary"]["max_prospect_rank"] == 500
    assert "Deep Card" in names
    assert "Outside Coverage" not in names


def test_scouting_repository_publishes_valid_llm_reports(tmp_path, monkeypatch):
    from scouting import report_generator, repository

    class _FakeMessages:
        def create(self, **_kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text="A model-written read with the same ValuCast facts.",
                    )
                ]
            )

    class _FakeClient:
        messages = _FakeMessages()

    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    with patch.object(report_generator, "default_client", return_value=_FakeClient()), patch.object(
        repository, "LLM_CACHE_PATH", Path(tmp_path) / "llm_cache.json"
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    assert payload["source_policy"]["llm_generated"] is True
    assert payload["source_policy"]["llm_generated_for_report_text_only"] is True
    assert payload["source_policy"]["feeds_live_rank"] is False
    assert payload["source_policy"]["feeds_live_value"] is False
    assert payload["summary"]["llm_published_report_count"] == 2
    assert payload["reports"][0]["published_report"] == (
        "A model-written read with the same ValuCast facts."
    )
    assert payload["reports"][0]["published_report_source"] == "llm"


def test_scouting_repository_publishes_valid_llm_rows_with_row_level_fallback(
    tmp_path, monkeypatch
):
    from scouting import report_generator, repository

    class _FakeMessages:
        def __init__(self):
            self._responses = [
                "Model Strong is a left-handed AA bat with a direct scouting read.",
                "Starter Arm is a right-hander with a direct pitching read.",
                "Starter Arm is a right-hander with a direct pitching read.",
            ]

        def create(self, **_kwargs):
            text = self._responses.pop(0)
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text=text,
                    )
                ]
            )

    class _FakeClient:
        def __init__(self):
            self.messages = _FakeMessages()

    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    with patch.object(report_generator, "default_client", return_value=_FakeClient()), patch.object(
        repository, "LLM_CACHE_PATH", Path(tmp_path) / "llm_cache.json"
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    pitcher = next(report for report in payload["reports"] if report["name"] == "Starter Arm")
    assert pitcher["throws"] == "L"
    assert pitcher["report_llm"]["valid"] is False
    assert pitcher["report_llm"]["hard_ok"] is False
    assert pitcher["report_llm"]["handedness_problems"]
    assert payload["summary"]["llm_published_report_count"] == 1
    assert payload["summary"]["deterministic_published_report_count"] == 1
    assert {report["published_report_source"] for report in payload["reports"]} == {
        "deterministic",
        "llm",
    }
    hitter = next(report for report in payload["reports"] if report["name"] == "Model Strong")
    assert hitter["published_report_source"] == "llm"
    assert hitter["published_report"] == "Model Strong is a left-handed AA bat with a direct scouting read."
    assert pitcher["published_report_source"] == "deterministic"
    assert "right-hander" not in pitcher["published_report"]


def test_scouting_repository_caps_uncached_llm_generation(tmp_path, monkeypatch):
    from scouting import report_generator, repository

    class _FakeMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text="A model-written read with the same ValuCast facts.",
                    )
                ]
            )

    class _FakeClient:
        def __init__(self):
            self.messages = _FakeMessages()

    snapshot_path = _write_snapshot(tmp_path)
    client = _FakeClient()
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM_MAX_GENERATE", "1")
    with patch.object(report_generator, "default_client", return_value=client), patch.object(
        repository, "LLM_CACHE_PATH", Path(tmp_path) / "llm_cache.json"
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    assert client.messages.calls == 1
    assert payload["summary"]["llm_shadow"]["generated"] == 1
    assert payload["summary"]["llm_shadow"]["skipped_due_to_budget"] == 1
    assert payload["summary"]["llm_published_report_count"] == 1
    assert payload["summary"]["deterministic_published_report_count"] == 1


def test_scouting_repository_reuses_cached_llm_when_generation_budget_is_zero(
    tmp_path, monkeypatch
):
    from scouting import report_generator, repository

    class _FailMessages:
        def create(self, **_kwargs):
            raise AssertionError("generation budget should prevent API calls")

    class _FakeClient:
        messages = _FailMessages()

    snapshot_path = _write_snapshot(tmp_path)
    cache_path = Path(tmp_path) / "llm_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "artifact": "valucast_scouting_llm_cache",
                "entries": {
                    "1_hitter": {
                        "hash": "same",
                        "text": "Model Strong is a left-handed AA bat with a cached LLM read.",
                        "model": "test",
                        "valid": True,
                        "hard_ok": True,
                        "problems": {"ok": True, "hard_ok": True},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM_MAX_GENERATE", "0")
    with (
        patch.object(report_generator, "default_client", return_value=_FakeClient()),
        patch.object(report_generator, "grounding_hash", return_value="same"),
        patch.object(repository, "LLM_CACHE_PATH", cache_path),
    ):
        payload = build_scouting_repository(
            snapshot_path=snapshot_path,
            generated_at="2026-06-16T00:00:00+00:00",
        )

    assert payload["summary"]["llm_shadow"]["generated"] == 0
    assert payload["summary"]["llm_shadow"]["reused"] == 1
    assert payload["summary"]["llm_shadow"]["skipped_due_to_budget"] == 1
    hitter = next(report for report in payload["reports"] if report["name"] == "Model Strong")
    pitcher = next(report for report in payload["reports"] if report["name"] == "Starter Arm")
    assert hitter["published_report_source"] == "llm"
    assert pitcher["published_report_source"] == "deterministic"


def test_scouting_repository_publish_rechecks_stale_llm_handedness():
    from scouting import repository

    report = {
        "name": "Starter Arm",
        "role": "pitcher",
        "throws": "L",
        "report": "The deterministic lefty-safe report.",
        "report_llm": {
            "text": "Starter Arm is a right-hander with a direct pitching read.",
            "valid": True,
            "hard_ok": True,
            "model": "test",
        },
    }

    repository._publish_report_fields([report])

    assert report["published_report_source"] == "deterministic"
    assert report["published_report"] == "The deterministic lefty-safe report."


def test_scouting_repository_validator_blocks_robotic_copy(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    payload["reports"][0]["report"] = "This display-only artifact is useful."
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert any("display-only" in problem for problem in problems)


def test_scouting_repository_validator_allows_guarded_row_level_fallback(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    llm_text = "Model Strong is a left-handed AA bat with a guarded LLM read."
    payload["reports"][0]["report_llm"] = {
        "text": llm_text,
        "valid": True,
        "hard_ok": True,
        "model": "test",
    }
    payload["reports"][0]["published_report_source"] = "llm"
    payload["reports"][0]["published_report"] = llm_text
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert problems == []


def test_scouting_repository_validator_blocks_llm_source_without_valid_guard(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    for report in payload["reports"]:
        report["published_report_source"] = "llm"
        report["published_report"] = "LLM report text."
        report["report_llm"] = {
            "text": "LLM report text.",
            "valid": True,
            "hard_ok": True,
            "model": "test",
        }
    payload["reports"][0]["report_llm"]["valid"] = False
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert any("published as llm without valid report_llm" in problem for problem in problems)


def test_scouting_repository_validator_checks_reports_beyond_old_top_300(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    base_report = payload["reports"][0]
    payload["reports"] = []
    for index in range(301):
        report = json.loads(json.dumps(base_report))
        report.update(
            {
                "mlbam_id": 1000 + index,
                "name": f"Report {index + 1}",
                "prospect_rank": index + 1,
            }
        )
        payload["reports"].append(report)
    payload["reports"][-1]["published_report_source"] = "llm"
    payload["reports"][-1]["published_report"] = "Bad unguarded LLM text."
    payload["reports"][-1]["report_llm"] = {
        "text": "Bad unguarded LLM text.",
        "valid": False,
        "hard_ok": False,
        "model": "test",
    }
    payload["summary"]["report_count"] = len(payload["reports"])
    payload["validation"]["report_count"] = len(payload["reports"])
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert any("report 301 published as llm without valid report_llm" in problem for problem in problems)


def test_scouting_repository_validator_blocks_wrong_pitcher_handedness(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    payload["reports"][1]["published_report"] = (
        "Starter Arm is a right-hander with a direct pitching read."
    )
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert any("handedness" in problem for problem in problems)
