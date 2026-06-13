"""Tests for rank-free universal profiles and guarded league adapters."""
import json

import pytest

from prospects.adapters import (
    adapt_categories,
    build_adapter_artifact,
    project_categories,
    run_adapters,
)


def _profile(mlbam_id, role, strength):
    if role == "hitter":
        outcomes = {
            "established_probability": {"prediction": strength},
            "representative_pa": {"prediction": 600},
            "representative_r_per_600": {"prediction": 100 * strength},
            "representative_hr_per_600": {"prediction": 30 * strength},
            "representative_rbi_per_600": {"prediction": 110 * strength},
            "representative_sb_per_600": {"prediction": 20 * strength},
            "representative_avg": {"prediction": 0.230 + 0.060 * strength},
            "representative_ops": {"prediction": 0.650 + 0.250 * strength},
            "representative_k_pct": {"prediction": 30 - 10 * strength},
        }
    else:
        outcomes = {
            "established_probability": {"prediction": strength},
            "rotation_probability": {"prediction": strength * 0.75},
            "representative_ip": {"prediction": 180},
            "representative_k_per_9": {"prediction": 7 + 4 * strength},
            "representative_qs_per_180": {"prediction": 25 * strength},
            "representative_sv_hld_per_60": {"prediction": 35 * strength},
            "representative_era": {"prediction": 5 - 2 * strength},
            "representative_whip": {"prediction": 1.5 - 0.4 * strength},
            "representative_k_bb": {"prediction": 2 + 3 * strength},
            "representative_l_per_180": {"prediction": 15 - 8 * strength},
        }
    return {
        "mlbam_id": mlbam_id,
        "name": f"Player {mlbam_id}",
        "role": role,
        "level": "AA",
        "age": 21,
        "outcomes": outcomes,
    }


def _universal():
    return {
        "model_name": "ValuCast Universal Prospect Model",
        "model_version": "0.3.0",
        "profiles": [
            _profile(1, "hitter", 0.8),
            _profile(2, "hitter", 0.3),
            _profile(3, "pitcher", 0.8),
            _profile(4, "pitcher", 0.3),
        ],
    }


def test_dd_adapter_ranks_complete_profile_but_5x5_refuses_missing_pitcher_stats():
    payload = build_adapter_artifact(_universal())
    assert payload["scoring_contract"]["rank_scope"] == "within_role"
    assert payload["scoring_contract"]["is_dynasty_value"] is False
    assert payload["scoring_contract"]["feeds_live_dd_value"] is False
    dd = payload["presets"]["dd_7x7"]
    assert dd["status"] == "research_ranked"
    assert all(role["missing_categories"] == [] for role in dd["roles"].values())
    assert dd["roles"]["hitter"]["players"][0]["mlbam_id"] == 1
    assert dd["roles"]["pitcher"]["players"][0]["mlbam_id"] == 3
    assert dd["roles"]["hitter"]["players"][0]["adapter_rank"] == 1

    standard = payload["presets"]["roto_5x5"]
    assert standard["status"] == "insufficient_category_coverage"
    assert standard["roles"]["pitcher"]["missing_categories"] == ["SV", "W"]
    assert all(
        "adapter_rank" not in player
        for player in standard["roles"]["pitcher"]["players"]
    )


def test_adapter_refuses_rank_when_artifact_lacks_a_supported_target():
    universal = _universal()
    del universal["profiles"][0]["outcomes"]["representative_rbi_per_600"]
    dd = build_adapter_artifact(universal)["presets"]["dd_7x7"]
    assert dd["status"] == "insufficient_category_coverage"
    assert dd["roles"]["hitter"]["missing_categories"] == ["RBI"]
    assert all(
        "adapter_rank" not in player for player in dd["roles"]["hitter"]["players"]
    )


def test_pitcher_role_probability_splits_starter_and_reliever_categories():
    profile = _profile(3, "pitcher", 0.8)
    projected = project_categories(profile)
    # 0.6 rotation probability / 0.8 establishment probability = 75% starter share.
    assert projected["QS"] == pytest.approx(12.0)
    assert projected["SV+HLD"] == pytest.approx(16.8)


def test_supported_custom_categories_can_create_research_ranks():
    result = adapt_categories(
        _universal()["profiles"],
        name="Supported research format",
        categories={
            "hitter": {"HR": 1, "SB": 1, "AVG": 1, "OPS": 1, "SO": -1},
            "pitcher": {"K": 1, "ERA": -1, "WHIP": -1, "K/BB": 1},
        },
    )
    assert result["status"] == "research_ranked"
    assert result["roles"]["hitter"]["players"][0]["mlbam_id"] == 1
    assert result["roles"]["pitcher"]["players"][0]["mlbam_id"] == 3
    assert result["roles"]["hitter"]["players"][0]["adapter_rank"] == 1


def test_run_adapters_writes_separate_artifact(tmp_path):
    universal_path = tmp_path / "universal.json"
    universal_path.write_text(json.dumps(_universal()), encoding="utf-8")
    result = run_adapters(universal_path, tmp_path / "adapters.json")
    payload = json.loads((tmp_path / "adapters.json").read_text(encoding="utf-8"))
    assert result["candidate_count"] == 4
    assert payload["status"] == "shadow_only"
    assert payload["rule"].startswith("No adapter rank")
