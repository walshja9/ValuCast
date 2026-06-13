"""Tests for the evidence-gated Diamond Dynasties 7x7 prospect adapter."""
import json

from prospects.dd_adapter import build_dd_adapter, run_dd_adapter


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
        "model_version": "0.4.0",
        "input_contract": {"generated_at": "2026-06-13T00:00:00+00:00"},
        "profiles": [
            _profile(1, "hitter", 0.8),
            _profile(2, "hitter", 0.3),
            _profile(3, "pitcher", 0.8),
            _profile(4, "pitcher", 0.3),
        ],
    }


def _backtest(gate="active"):
    return {
        "universal_model_version": "0.4.0",
        "generated_at": "2026-06-13T00:00:00+00:00",
        "adapter_preset": "dd_7x7",
        "validation_contract": {"outcome_horizon_years": 4},
        "roles": {
            "hitter": {"role_research_gate": gate, "fold_count": 3},
            "pitcher": {"role_research_gate": gate, "fold_count": 3},
        },
        "promotion": {"adapter_research_gate": gate, "reason": "Evidence passed."},
    }


def test_dd_adapter_is_separate_from_universal_index_and_live_dd_value():
    payload = build_dd_adapter(_universal(), _backtest())
    contract = payload["adapter_contract"]
    assert payload["status"] == "shadow_only"
    assert contract["universal_index_relationship"].startswith("Sibling consumer")
    assert contract["cross_role_rank"] is False
    assert contract["dd_values_used"] is False
    assert payload["historical_evidence"]["outcome_horizon_years"] == 4
    assert payload["promotion"]["research_gate"] == "active"
    assert payload["promotion"]["live_consumer"] == "blocked"
    assert payload["promotion"]["feeds_live_dd_value"] is False


def test_dd_adapter_rejects_stale_historical_evidence():
    backtest = _backtest()
    backtest["generated_at"] = "2026-06-12T00:00:00+00:00"
    payload = build_dd_adapter(_universal(), backtest)
    assert payload["promotion"]["research_gate"] == "hold"


def test_dd_adapter_fails_closed_when_current_category_contract_is_incomplete():
    universal = _universal()
    del universal["profiles"][0]["outcomes"]["representative_rbi_per_600"]
    payload = build_dd_adapter(universal, _backtest())
    assert payload["promotion"]["research_gate"] == "hold"
    assert payload["promotion"]["current_category_contract"] == "hold"
    assert all(
        "adapter_rank" not in player
        for player in payload["roles"]["hitter"]["players"]
    )


def test_dd_adapter_emits_role_scoped_ranks():
    payload = build_dd_adapter(_universal(), _backtest())
    assert payload["candidate_count"] == 4
    assert payload["roles"]["hitter"]["players"][0]["mlbam_id"] == 1
    assert payload["roles"]["pitcher"]["players"][0]["mlbam_id"] == 3
    assert payload["roles"]["hitter"]["players"][0]["adapter_rank"] == 1


def test_run_dd_adapter_writes_separate_artifact_and_archive(tmp_path):
    universal_path = tmp_path / "universal.json"
    backtest_path = tmp_path / "backtest.json"
    artifact_path = tmp_path / "dd-adapter.json"
    universal_path.write_text(json.dumps(_universal()), encoding="utf-8")
    backtest_path.write_text(json.dumps(_backtest()), encoding="utf-8")
    result = run_dd_adapter(
        universal_path=universal_path,
        backtest_path=backtest_path,
        artifact_path=artifact_path,
        archive_dir=tmp_path / "archive",
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert result["archive_changed"] is True
    assert payload["adapter_contract"]["preset"] == "dd_7x7"
    assert (tmp_path / "archive" / "2026-06-13.json").exists()
