import copy
import json
from pathlib import Path

import pytest

import prospects.model as model
from prospects.model import (
    OUTCOME_FEATURE_NAMES,
    _outcome_feature_vector,
    _predict_model,
    _regress_current_features,
    _sample,
    score_current,
)


USAGE = "pooled_line_shadow_observe_only_not_live_score_or_value"


def _hitter_row(level: str, plate_appearances: int, **overrides) -> dict:
    row = {
        "mlbam_id": 1001,
        "name": "Pooled Hitter",
        "normalized_name": "pooled hitter",
        "team": f"{level} Club",
        "role": "hitter",
        "position": "SS",
        "level": level,
        "age": 21 if level == "A+" else 22,
        "sample_season": 2026,
        "source_kind": "current_season",
        "plate_appearances": plate_appearances,
        "iso": 0.120,
        "k_pct": 20.0,
        "bb_pct": 10.0,
        "ops": 0.700,
        "avg": 0.250,
        "obp": 0.340,
        "slg": 0.360,
        "babip": 0.300,
        "home_runs": 6,
        "stolen_bases": 4,
        "walks": 12,
        "hits": 28,
        "games": 30,
        "games_played": 30,
        "draft_pick_number": 50,
        "draft_round": 2,
        "signing_bonus": 1_000_000,
        "school_type": "college",
        "bats": "L",
        "throws": "R",
        "rule4_drafted": True,
        "draft_record_known": True,
        "pick_value": 0.8,
    }
    row.update(overrides)
    return row


def _contract(current_hitters: list[dict]) -> dict:
    return {
        "current": {"hitters": current_hitters, "pitchers": []},
        "mlb_service": [
            {
                "mlbam_id": 1001,
                "role": "hitter",
                "ab": 0,
                "ip": 0,
                "graduated": False,
            }
        ],
    }


def _models() -> tuple[dict, dict]:
    def role_model(role: str, intercept: float) -> dict:
        names = OUTCOME_FEATURE_NAMES[role]
        weights = [intercept] + [0.0] * len(names)
        if role == "hitter":
            weights[names.index("ops") + 1] = 0.5
        else:
            weights[names.index("era") + 1] = -0.02
        runtime = {
            "model_kind": "ridge",
            "weights": weights,
            "means": [0.0] * len(names),
            "stds": [1.0] * len(names),
        }
        return {
            "role": role,
            "feature_names": list(names),
            "prediction_model": runtime,
            "weights": weights,
            "means": [0.0] * len(names),
            "stds": [1.0] * len(names),
            "gate": {"status": "active"},
        }

    role_models = {
        "hitter": role_model("hitter", 0.05),
        "pitcher": role_model("pitcher", 0.20),
    }
    impact_models = {
        "hitter": role_model("hitter", 0.10),
        "pitcher": role_model("pitcher", 0.10),
    }
    return role_models, impact_models


def _multi_level_contract() -> dict:
    return _contract(
        [
            _hitter_row("A+", 110),
            _hitter_row(
                "AA",
                80,
                iso=0.240,
                k_pct=16.0,
                bb_pct=12.0,
                ops=0.950,
                avg=0.290,
                obp=0.380,
                slg=0.570,
                babip=0.330,
                home_runs=9,
                stolen_bases=1,
                walks=11,
                hits=31,
                games=22,
                games_played=22,
            ),
        ]
    )


def _strip_shadow(rows: list[dict]) -> list[dict]:
    return [{key: value for key, value in row.items() if key != "pooled_shadow"} for row in rows]


def _manual_pooled_hitter_record(contract: dict) -> dict:
    rows = contract["current"]["hitters"]
    samples = [row["plate_appearances"] for row in rows]
    total_sample = sum(samples)
    high = next(row for row in rows if row["level"] == "AA")
    pooled = dict(high)
    for key in ("iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip"):
        pooled[key] = sum(row[key] * row["plate_appearances"] for row in rows) / total_sample
    for key in ("home_runs", "stolen_bases", "walks", "hits", "games", "games_played"):
        pooled[key] = sum(row.get(key, 0) for row in rows)
    pooled["plate_appearances"] = total_sample
    return pooled


def test_multi_level_hitter_emits_nontrivial_pooled_shadow_with_pinned_math(monkeypatch):
    monkeypatch.setattr(model, "POOLED_SHADOW_ENABLED", True)
    contract = _multi_level_contract()
    role_models, impact_models = _models()

    row = score_current(contract, role_models, impact_models)[0]

    assert row["sample"] == 110.0
    shadow = row["pooled_shadow"]
    assert shadow["usage"] == USAGE
    assert shadow["served_score"] == row["expected_outcome_score"]
    assert shadow["pooled_sample"] == 190.0
    assert shadow["pooled_sample"] > shadow["served_sample"]
    assert shadow["n_levels"] == 2
    assert shadow["levels_pooled"] == ["AA", "A+"]
    assert abs(shadow["delta"]) > 0

    pooled_record = _manual_pooled_hitter_record(contract)
    role_model = role_models["hitter"]
    pooled_raw = _outcome_feature_vector(pooled_record, "hitter")
    pooled_regressed, _ = _regress_current_features(
        pooled_raw, role_model, "hitter", _sample(pooled_record, "hitter")
    )
    expected_score = round(
        _predict_model(role_model["prediction_model"], pooled_regressed), 4
    )
    assert shadow["pooled_score"] == expected_score


def test_single_level_hitter_omits_pooled_shadow(monkeypatch):
    monkeypatch.setattr(model, "POOLED_SHADOW_ENABLED", True)
    role_models, impact_models = _models()

    rows = score_current(_contract([_hitter_row("A+", 110)]), role_models, impact_models)

    assert "pooled_shadow" not in rows[0]


def test_pooled_shadow_firewall_preserves_served_board_byte_identity(monkeypatch):
    contract = _multi_level_contract()
    role_models, impact_models = _models()

    monkeypatch.setattr(model, "POOLED_SHADOW_ENABLED", True)
    shadow_on = score_current(copy.deepcopy(contract), role_models, impact_models)
    monkeypatch.setattr(model, "POOLED_SHADOW_ENABLED", False)
    shadow_off = score_current(copy.deepcopy(contract), role_models, impact_models)

    assert json.dumps(_strip_shadow(shadow_on), sort_keys=True) == json.dumps(
        shadow_off, sort_keys=True
    )
    assert [
        (
            row["mlbam_id"],
            row["valucast_prospect_rank"],
            row["valucast_impact_rank"],
            row["expected_outcome_score"],
            row["expected_category_impact_score"],
        )
        for row in _strip_shadow(shadow_on)
    ] == [
        (
            row["mlbam_id"],
            row["valucast_prospect_rank"],
            row["valucast_impact_rank"],
            row["expected_outcome_score"],
            row["expected_category_impact_score"],
        )
        for row in shadow_off
    ]


def test_pooled_shadow_fail_safe_keeps_served_row_intact(monkeypatch):
    contract = _multi_level_contract()
    contract["current"]["hitters"][1]["iso"] = None
    role_models, impact_models = _models()

    monkeypatch.setattr(model, "POOLED_SHADOW_ENABLED", True)
    shadow_on = score_current(copy.deepcopy(contract), role_models, impact_models)
    monkeypatch.setattr(model, "POOLED_SHADOW_ENABLED", False)
    shadow_off = score_current(copy.deepcopy(contract), role_models, impact_models)

    assert shadow_on
    assert json.dumps(_strip_shadow(shadow_on), sort_keys=True) == json.dumps(
        shadow_off, sort_keys=True
    )


def test_pooled_shadow_artifact_and_validator_round_trip(tmp_path, monkeypatch):
    from prospects.pooled_shadow import run_pooled_shadow
    from scripts.validate_pooled_shadow import validate_pooled_shadow

    blocked_result = run_pooled_shadow(
        model_path=tmp_path / "missing-model.json",
        artifact_path=tmp_path / "blocked.json",
        archive_dir=tmp_path / "blocked-archive",
        generated_at="2026-06-25T12:00:00+00:00",
    )
    blocked_payload = json.loads(Path(blocked_result["artifact_path"]).read_text())
    assert blocked_payload["status"] == "blocked"
    assert blocked_payload["validation"]["blockers"]

    monkeypatch.setattr(model, "POOLED_SHADOW_ENABLED", True)
    role_models, impact_models = _models()
    ranked = score_current(_multi_level_contract(), role_models, impact_models)
    model_path = tmp_path / "model.json"
    model_path.write_text(json.dumps({"ranked": ranked}), encoding="utf-8")
    artifact_path = tmp_path / "shadow.json"
    archive_dir = tmp_path / "archive"

    result = run_pooled_shadow(
        model_path=model_path,
        artifact_path=artifact_path,
        archive_dir=archive_dir,
        generated_at="2026-06-25T12:00:00+00:00",
    )

    payload, problems = validate_pooled_shadow(artifact_path)
    assert problems == []
    assert result["status"] == "candidate_ready"
    assert payload["artifact"] == "valucast_pooled_shadow"
    assert payload["shadow_version"] == "0.1.0"
    assert payload["summary"]["scored_count"] == 1
    assert payload["summary"]["shadowed_count"] == 1
    assert payload["summary"]["multi_level_count"] == 1
    assert payload["shadows"][0]["usage"] == USAGE
    assert (archive_dir / "2026-06-25.json").exists()

    payload["source_policy"]["feeds_buy_score"] = True
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    _payload, problems = validate_pooled_shadow(artifact_path)
    assert any("feeds_buy_score" in problem for problem in problems)


def test_pooled_shadow_is_wired_into_public_build_and_shadow_workflow():
    from scripts import run_daily_public_build
    from scripts import validate_public_data_freshness as freshness

    workflow = Path(".github/workflows/prospect-shadow.yml").read_text(encoding="utf-8")
    build_steps = [" ".join(step) for step in run_daily_public_build.BUILD_STEPS]
    validate_steps = [" ".join(step) for step in run_daily_public_build.VALIDATE_STEPS]

    assert build_steps.index("scripts/build_pooled_shadow.py") == (
        build_steps.index("scripts/build_prospect_model.py") + 1
    )
    assert "scripts/validate_pooled_shadow.py" in validate_steps
    assert hasattr(freshness, "POOLED_SHADOW")
    assert "tests/test_pooled_shadow.py" in workflow
    assert "data/models/valucast_pooled_shadow.json" in workflow
    assert "data/prediction_archive/valucast_pooled_shadow" in workflow
    # The workflow must actually BUILD the artifact it git-adds, or the commit
    # step fails with "pathspec did not match any files" (exit 128).
    assert "scripts/build_pooled_shadow.py" in workflow
