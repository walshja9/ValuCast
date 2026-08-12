import hashlib
import json
import re

from pathlib import Path

from scripts.run_pre2014_cross_role_gate import _validate_execution_registration


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "plans" / "036-pre2014-cross-role-calibration-gate.md"
README_PATH = ROOT / "plans" / "README.md"
READINESS_PATH = (
    ROOT / "data" / "validation" / "valucast_pre2014_cross_role_readiness.json"
)
READINESS_SHA256 = "12a1023bd1000e54520c2ac445aebbe603c27c69f2bcc0badf3cbbf1fae7e610"
IMPLEMENTATION_BASE_COMMIT = "f7d3304bde6e57a02db4a5c7347ce9fc5e4c0af3"
REGISTRATION_START = "<!-- plan036-registration:start -->"
REGISTRATION_END = "<!-- plan036-registration:end -->"


def _registration() -> dict:
    text = PLAN_PATH.read_text(encoding="utf-8")
    assert text.count(REGISTRATION_START) == 1
    assert text.count(REGISTRATION_END) == 1
    start = text.index(REGISTRATION_START) + len(REGISTRATION_START)
    end = text.index(REGISTRATION_END, start)
    match = re.fullmatch(
        r"```json\s*(\{.*\})\s*```",
        text[start:end].strip(),
        flags=re.DOTALL,
    )
    assert match, "Plan 036 must contain one exact registered JSON block"
    return json.loads(match.group(1))


def test_plan036_registration_matches_the_ready_immutable_contract():
    readiness_bytes = READINESS_PATH.read_bytes()
    assert hashlib.sha256(readiness_bytes).hexdigest() == READINESS_SHA256
    readiness = json.loads(readiness_bytes)
    assert readiness["implementation_base_commit"] == IMPLEMENTATION_BASE_COMMIT
    assert readiness["status"] == "ready"
    assert readiness["execution_authorized"] is True
    assert readiness["look_spent"] is False
    assert readiness["blockers"] == []

    sources = readiness["hashes"]["source_files"]
    registration = _registration()
    assert registration == {
        "protocol": "plan_036_pre2014_cross_role_calibration",
        "registered_at": "2026-08-11T00:00:00Z",
        "status": "registered",
        "look_spent": False,
        "execution_authorized": True,
        "research_only": True,
        "automatic_promotion": False,
        "claim_authorized": False,
        "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
        "readiness": {
            "path": "data/validation/valucast_pre2014_cross_role_readiness.json",
            "sha256": READINESS_SHA256,
        },
        "result_path": "data/validation/valucast_pre2014_cross_role_gate.json",
        "source_contract": {
            "prepared_path": sources["prepared_artifact"]["path"],
            "prepared_sha256": sources["prepared_artifact"]["sha256"],
            "prepared_manifest_path": sources["prepared_manifest"]["path"],
            "prepared_manifest_sha256": sources["prepared_manifest"]["sha256"],
            "draft_facts_path": sources["draft_facts"]["path"],
            "draft_facts_sha256": sources["draft_facts"]["sha256"],
            "cohorts": [*range(2009, 2020), 2021, 2022],
            "declared_omissions": [2020],
            "outcome_complete_through": 2025,
            "outcome_horizon_years": 4,
            "identity_key": "mlbam_id+role",
            "parity": {
                "status": "ready",
                "cohort_year": 2014,
                "candidate_count": 1559,
                "committed_count": 1559,
                "extra": [],
                "missing": [],
            },
        },
        "candidate": {
            "candidate_count": 1,
            "pitcher_investment_feature_mode": "drop_raw_pick_value",
            "rank_model_score_mode": "common_target",
            "calibration": "fold_trained_role_head_isotonic",
            "head_blend": {"outcome": 0.58, "impact": 0.42},
            "governor_thresholds_changed": False,
            "forbidden_substitutions": [
                "raw_pick_value",
                "live_role_quantile",
                "governor_relaxation",
            ],
        },
        "outer_folds": [2017, 2018, 2019, 2021],
        "bootstrap": {
            "seed": 35011,
            "resamples": 10000,
            "interval": "two_sided_95_percentile",
            "direct_mae": {
                "unit": "player_within_cohort_hierarchical",
                "point_statistic": "relative_mae_improvement",
            },
            "cross_role_concordance": {
                "unit": "cohort_then_identity_within_role",
                "point_statistic": "incumbent_discordance_reduction",
            },
        },
        "primary_endpoint": "direct_7x7_target_percentile_rank_mae",
        "thresholds": {
            "minimum_outer_folds": 4,
            "minimum_unique_players_per_role": 250,
            "minimum_fold_role_coverage": 0.9,
            "minimum_direct_mae_relative_improvement": 0.02,
            "direct_mae_bootstrap_lower_strictly_gt": 0.0,
            "maximum_fold_relative_regression": 0.05,
            "maximum_role_concordance_relative_regression": 0.01,
            "top25_direct_regret_no_worse": True,
            "top25_ordinal_regret_no_worse": True,
            "minimum_cross_role_concordance_relative_improvement": 0.02,
            "cross_role_bootstrap_lower_strictly_gt": 0.0,
            "current_governor_required": True,
        },
        "governor": {
            "check_id": "prospect_top_board_role_shape",
            "max_top25_pitcher_count": 7,
            "max_top50_pitcher_rate": 0.3,
        },
        "hashes": readiness["hashes"],
        "result_contract": {
            "single_use": True,
            "claim_authorized": False,
            "automatic_promotion": False,
            "terminal_evidence_path": (
                "data/validation/valucast_pre2014_cross_role_evidence.json"
            ),
            "acquisition_checkpoint_path": (
                "data/research/extended_prospect_history/"
                "sealed-acquisition-checkpoint.json"
            ),
            "outcome_cutoff_date": "2025-12-31",
        },
        "limitations": ["cohort-season-completion pseudo-replay"],
    }
    assert _validate_execution_registration(registration, readiness) == (
        READINESS_SHA256,
        IMPLEMENTATION_BASE_COMMIT,
    )


def test_plan036_readme_registers_the_unspent_research_only_look():
    readme = README_PATH.read_text(encoding="utf-8")
    assert readme.count("| 036  | Pre-2014 Cross-Role Calibration Gate") == 1
    assert "REGISTERED — UNSPENT; RESEARCH ONLY" in readme
