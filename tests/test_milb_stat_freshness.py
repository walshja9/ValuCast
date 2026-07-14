"""Tests for the ValuCast MiLB stat freshness audit."""
import json

from prospects.milb_stat_freshness import build_milb_stat_freshness_audit
from prospects.milb_stat_freshness import run_milb_stat_freshness_audit
from scripts.validate_milb_stat_freshness_audit import (
    validate_milb_stat_freshness_audit,
)


def _inputs():
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
                    "source_kind": "current_season",
                    "sample_season": 2026,
                    "sample_fetched_date": "2026-06-15",
                },
                {
                    "name": "Current Prospect",
                    "mlbam_id": 2,
                    "role": "hitter",
                    "level": "AA",
                    "source_kind": "current_season",
                    "sample_season": 2026,
                },
            ],
            "pitchers": [
                {
                    "name": "History Pitcher",
                    "mlbam_id": 3,
                    "role": "pitcher",
                    "level": "AA",
                    "source_kind": "latest_milb_history",
                    "sample_season": 2025,
                    "sample_fetched_date": "2026-06-14",
                }
            ],
        },
    }


def _rank_payload(history_rank=80):
    return {
        "generated_at": "2026-06-14T00:00:00+00:00",
        "board": [
            {
                "name": "Cooper Pratt",
                "mlbam_id": 806198,
                "role": "hitter",
                "level": "AAA",
                "rank": 8,
                "score": 50.0,
                "score_source": "prospect_model_v0_6",
                "components": {
                    "factual_current_context": {
                        "source_kind": "current_season",
                        "sample": 261,
                        "sample_unit": "PA",
                        "sample_season": 2026,
                    },
                    "availability": {"sample_fetched_date": "2026-06-15"},
                },
            },
            {
                "name": "History Pitcher",
                "mlbam_id": 3,
                "role": "pitcher",
                "level": "AA",
                "rank": history_rank,
                "score": 35.0,
                "score_source": "universal_fallback",
                "components": {
                    "factual_current_context": {
                        "source_kind": "latest_milb_history",
                        "sample": 33.0,
                        "sample_unit": "IP",
                        "sample_season": 2025,
                    },
                    "availability": {"sample_fetched_date": "2026-06-14"},
                },
            },
        ],
    }


def _snapshot():
    return {
        "generated_at": "2026-06-14T00:00:00+00:00",
        "players": [
            {
                "player_type": "prospect",
                "name": "Cooper Pratt",
                "mlbam_id": 806198,
                "role": "hitter",
                "rank": 165,
                "prospect_rank": 8,
                "components": {
                    "factual_current_context": {
                        "source_kind": "current_season",
                        "sample": 261,
                        "sample_season": 2026,
                    }
                },
                "context": {
                    "stat_line_source": "valucast_input_contract",
                    "stat_line_source_kind": "current_season",
                    "stat_line_sample": 261,
                    "stat_line_sample_season": 2026,
                },
            }
        ],
    }


def test_milb_stat_freshness_allows_targeted_refresh_without_blocking():
    payload = build_milb_stat_freshness_audit(
        _inputs(),
        _rank_payload(history_rank=80),
        _snapshot(),
    )

    assert payload["status"] == "candidate_ready"
    assert payload["metrics"]["targeted_row_refresh_count"] == 1
    assert payload["metrics"]["top50_history_fallback_count"] == 0
    assert payload["samples"]["targeted_row_refreshes"][0]["name"] == "Cooper Pratt"


def test_milb_stat_freshness_blocks_top50_history_fallbacks():
    payload = build_milb_stat_freshness_audit(
        _inputs(),
        _rank_payload(history_rank=20),
        _snapshot(),
    )

    assert payload["status"] == "blocked"
    assert payload["metrics"]["top50_history_fallback_count"] == 1
    assert "top-50 prospect card context uses latest_milb_history fallback" in payload[
        "blockers"
    ]


def test_validate_milb_stat_freshness_audit_rejects_blocked_with_fallback_rows(tmp_path):
    payload = build_milb_stat_freshness_audit(
        _inputs(),
        _rank_payload(history_rank=20),
        _snapshot(),
    )
    assert payload["status"] == "blocked"
    assert payload["metrics"]["top50_history_fallback_count"] == 1

    artifact_path = tmp_path / "blocked_with_fallback.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    _, problems = validate_milb_stat_freshness_audit(artifact_path)
    assert any(
        "status=blocked feed is serving 1 top50_history_fallback rows" in problem
        for problem in problems
    )

    clean_payload = dict(payload)
    clean_payload["metrics"] = dict(payload["metrics"], top50_history_fallback_count=0)
    clean_path = tmp_path / "blocked_without_fallback.json"
    clean_path.write_text(json.dumps(clean_payload), encoding="utf-8")
    _, clean_problems = validate_milb_stat_freshness_audit(clean_path)
    assert not any("top50_history_fallback rows" in problem for problem in clean_problems)


def test_run_and_validate_milb_stat_freshness_audit(tmp_path):
    inputs_path = tmp_path / "inputs.json"
    rank_path = tmp_path / "rank.json"
    snapshot_path = tmp_path / "snapshot.json"
    artifact_path = tmp_path / "audit.json"
    inputs_path.write_text(json.dumps(_inputs()), encoding="utf-8")
    rank_path.write_text(json.dumps(_rank_payload(history_rank=80)), encoding="utf-8")
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")

    result = run_milb_stat_freshness_audit(
        inputs_path=inputs_path,
        rank_path=rank_path,
        public_snapshot_path=snapshot_path,
        artifact_path=artifact_path,
    )
    payload, problems = validate_milb_stat_freshness_audit(artifact_path)

    assert result["status"] == "candidate_ready"
    assert payload["artifact"] == "valucast_milb_stat_freshness_audit"
    assert problems == []
