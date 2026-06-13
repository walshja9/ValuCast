import copy
import json

import pytest

from prospects.dd_lens_feed import build_feed, run_feed
from prospects.dd_adapter import build_dd_adapter


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


def _backtest():
    return {
        "universal_model_version": "0.4.0",
        "generated_at": "2026-06-13T00:00:00+00:00",
        "adapter_preset": "dd_7x7",
        "validation_contract": {"outcome_horizon_years": 4},
        "roles": {
            "hitter": {"role_research_gate": "active", "fold_count": 3},
            "pitcher": {"role_research_gate": "active", "fold_count": 3},
        },
        "promotion": {"adapter_research_gate": "active", "reason": "Evidence passed."},
    }


def _inputs():
    universal = _universal()
    universal["status"] = "shadow_only"
    universal["input_contract"]["source_policy"] = {
        "kind": "factual_only",
        "external_rankings_used": False,
        "external_projections_used": False,
        "market_values_used": False,
        "dynasty_values_used": False,
    }
    return build_dd_adapter(universal, _backtest()), universal


def test_feed_is_slim_versioned_and_mlbam_keyed():
    adapter, universal = _inputs()
    feed = build_feed(adapter, universal, published_at="2026-06-13T12:00:00+00:00")

    assert feed["_meta"]["schema_version"] == 2
    assert feed["_meta"]["sources"] == [
        "valucast_universal_prospect_model",
        "valucast_dd_7x7_prospect_adapter",
    ]
    assert feed["adapter_contract"]["identity"] == "mlbam_id_plus_role"
    assert feed["adapter_contract"]["rank_scope"] == "within_role"
    assert feed["promotion"]["feeds_live_dd_value"] is False
    assert feed["historical_evidence"]["role_gates"] == {
        "hitter": "active",
        "pitcher": "active",
    }
    assert set(feed["players"][0]) == {
        "mlbam_id",
        "name",
        "role",
        "age",
        "level",
        "adapter_rank",
        "adapter_score",
        "projected_volume",
        "categories",
    }


def test_feed_rejects_mismatched_or_prohibited_sources():
    adapter, universal = _inputs()
    adapter["generated_at"] = "2026-06-12T00:00:00+00:00"
    with pytest.raises(ValueError, match="snapshots do not match"):
        build_feed(adapter, universal)

    adapter, universal = _inputs()
    universal["input_contract"]["source_policy"]["external_rankings_used"] = True
    with pytest.raises(ValueError, match="prohibited"):
        build_feed(adapter, universal)

    adapter, universal = _inputs()
    adapter["historical_evidence"]["role_gates"]["hitter"] = "unknown"
    with pytest.raises(ValueError, match="historical evidence"):
        build_feed(adapter, universal)


def test_feed_rejects_duplicate_identity_and_incomplete_categories():
    adapter, universal = _inputs()
    adapter["roles"]["hitter"]["players"].append(
        copy.deepcopy(adapter["roles"]["hitter"]["players"][0])
    )
    with pytest.raises(ValueError, match="duplicate MLBAM"):
        build_feed(adapter, universal)

    adapter, universal = _inputs()
    del adapter["roles"]["hitter"]["players"][0]["categories"]["RBI"]
    with pytest.raises(ValueError, match="invalid player row"):
        build_feed(adapter, universal)


def test_run_feed_writes_artifact(tmp_path):
    adapter, universal = _inputs()
    adapter_path = tmp_path / "adapter.json"
    universal_path = tmp_path / "universal.json"
    output_path = tmp_path / "feed.json"
    adapter_path.write_text(json.dumps(adapter), encoding="utf-8")
    universal_path.write_text(json.dumps(universal), encoding="utf-8")

    result = run_feed(
        adapter_path=adapter_path,
        universal_path=universal_path,
        artifact_path=output_path,
        published_at="2026-06-13T12:00:00+00:00",
    )

    assert result["candidate_count"] == 4
    assert "payload" not in result
    assert json.loads(output_path.read_text(encoding="utf-8"))["_meta"]["artifact"] == (
        "valucast_dd_prospect_lens"
    )
