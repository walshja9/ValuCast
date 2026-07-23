from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from prospects import realized_value_readiness as readiness
from prospects.realized_value_readiness import (
    audit_realized_value_readiness,
    audit_stage2_realized_value_readiness,
)


def _contract() -> dict:
    return {
        "historical": {
            "rows": [
                {
                    "cohort_year": 2018,
                    "mlbam_id": 10,
                    "role": "hitter",
                    "outcome": "role",
                },
                {
                    "cohort_year": 2018,
                    "mlbam_id": 20,
                    "role": "pitcher",
                    "outcome": "star",
                },
            ]
        },
        "historical_mlb_seasons": {
            "10_hitter": [
                {
                    "year": 2019,
                    "pa": 500,
                    "r": 70,
                    "hr": 20,
                    "rbi": 75,
                    "sb": 8,
                    "avg": 0.270,
                    "ops": 0.800,
                    "so": 120,
                }
            ],
            "20_pitcher": [
                {
                    "year": 2019,
                    "ip": 150,
                    "so": 170,
                    "sv": 0,
                    "hld": 0,
                    "era": 3.50,
                    "whip": 1.20,
                    "k_bb": 3.2,
                    "l": 8,
                }
            ],
        },
    }


def _model() -> dict:
    return {
        "impact_target_contract": {
            "canonical_hitter_categories": [
                "r",
                "hr",
                "rbi",
                "sb",
                "avg",
                "ops",
                "so",
            ],
            "canonical_pitcher_categories": [
                "so",
                "qs",
                "sv_hld",
                "era",
                "whip",
                "k_bb",
                "l",
            ],
            "direct_7x7": False,
            "missing_hitter_categories": [],
            "missing_pitcher_categories": ["qs"],
        }
    }


def _canonical_hash(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _seal_sidecar(sidecar: dict) -> dict:
    sidecar["content_sha256"] = _canonical_hash(sidecar)
    return sidecar


def _sidecar(*, quality_starts: int = 12, games_started: int = 25) -> dict:
    return _seal_sidecar(
        {
            "schema": "valucast_stage2_quality_starts",
            "version": "1.0.0",
            "status": "ready",
            "input": {
                "path": "data/prospects/prospect_model_inputs.json",
                "sha256": "contract-hash",
                "cutoff_date": "2026-07-23",
            },
            "coverage": {},
            "validation": {"current_season_values_superseded": []},
            "rows": [
                {
                    "mlbam_id": 20,
                    "season": 2019,
                    "games_started": games_started,
                    "quality_starts": quality_starts,
                    "provenance": "derived_game_log",
                }
            ],
            "blockers": [],
        }
    )


def _stage2_report(
    contract: dict | None = None,
    sidecar: dict | None = None,
) -> dict:
    selected_contract = deepcopy(contract or _contract())
    selected_contract.setdefault("current", {})["fetched_date"] = "2026-07-23"
    return audit_stage2_realized_value_readiness(
        selected_contract,
        _model(),
        deepcopy(sidecar or _sidecar()),
        contract_sha256="contract-hash",
    )


def test_missing_qs_blocks_realized_value_regret():
    report = audit_realized_value_readiness(_contract(), _model())
    assert report["status"] == "blocked"
    assert report["replay"]["realized_value_regret_ready"] is False
    assert report["category_coverage"]["pitcher"]["missing"] == ["qs"]
    assert "missing_pitcher_category:qs" in report["blockers"]


def test_partial_qs_rows_are_counted_without_unblocking_qs():
    contract = _contract()
    contract["historical_mlb_seasons"]["20_pitcher"] = [
        {"year": 2019, "ip": 150, "qs": 18},
        {"year": 2020, "ip": 120},
    ]

    report = audit_realized_value_readiness(contract, _model())
    coverage = report["category_coverage"]["pitcher"]

    assert coverage["season_rows"] == 2
    assert coverage["season_rows_with_category"]["qs"] == 1
    assert coverage["missing"] == ["qs"]
    assert report["status"] == "blocked"
    assert report["replay"]["realized_value_regret_ready"] is False


def test_conflicting_same_cohort_roles_fail_that_cohort_closed():
    contract = _contract()
    contract["historical"]["rows"].append(
        {"cohort_year": 2018, "mlbam_id": 20, "role": "hitter", "outcome": "role"}
    )
    report = audit_realized_value_readiness(contract, _model())
    assert report["cohorts"]["2018"]["identity_status"] == "blocked"
    assert report["identity_audit"]["conflicting_cohort_roles"] == ["2018:20"]


def test_later_role_change_is_disclosed_without_relabeling_prior_cohort():
    contract = _contract()
    contract["historical"]["rows"].append(
        {"cohort_year": 2019, "mlbam_id": 20, "role": "hitter", "outcome": "role"}
    )
    report = audit_realized_value_readiness(contract, _model())
    assert report["identity_audit"]["later_role_changes"] == [
        {"mlbam_id": "20", "roles_by_cohort": {"2018": "pitcher", "2019": "hitter"}}
    ]
    assert (
        report["identity_policy"]["historical_role"]
        == "frozen_from_cohort_cutoff_row"
    )


def test_zero_opportunity_is_counted_not_promoted_to_success():
    contract = deepcopy(_contract())
    contract["historical_mlb_seasons"]["10_hitter"] = []
    report = audit_realized_value_readiness(contract, _model())
    assert report["cohorts"]["2018"]["zero_opportunity"]["hitter"] == 1


def test_stage2_evidence_is_ready_without_overstating_overall_readiness():
    report = _stage2_report()

    assert report["outcome_evidence"]["status"] == "ready"
    assert report["outcome_evidence"][
        "retrospective_direct_7x7_evidence_ready"
    ] is True
    assert report["outcome_evidence"]["pitcher"]["active"] == [
        "so",
        "qs",
        "sv_hld",
        "era",
        "whip",
        "k_bb",
        "l",
    ]
    assert report["incumbent_impact_target"][
        "incumbent_direct_7x7_target_ready"
    ] is False
    assert report["prospective_replay"]["exact_prospective_replay_ready"] is False
    assert report["realized_value_regret_ready"] is False
    assert report["status"] == "blocked"
    assert report["blockers"] == [
        "impact_target_not_direct_7x7",
        "exact_prospective_replay_not_reconstructable",
    ]
    assert "missing_pitcher_category:qs" not in report["blockers"]


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("schema", "wrong", "qs_sidecar_schema_invalid"),
        ("version", "9.0.0", "qs_sidecar_version_unsupported"),
        ("status", "blocked", "qs_sidecar_status_not_ready"),
        ("content_sha256", "wrong", "qs_sidecar_content_sha256_mismatch"),
    ],
)
def test_stage2_sidecar_metadata_fails_closed(field, value, blocker):
    sidecar = _sidecar()
    sidecar[field] = value

    assert blocker in _stage2_report(sidecar=sidecar)["blockers"]


def test_stage2_sidecar_binding_fails_closed():
    wrong_hash = _sidecar()
    wrong_hash["input"]["sha256"] = "wrong"
    wrong_hash = _seal_sidecar(wrong_hash)
    wrong_cutoff = _sidecar()
    wrong_cutoff["input"]["cutoff_date"] = "2026-07-22"
    wrong_cutoff = _seal_sidecar(wrong_cutoff)
    wrong_path = _sidecar()
    wrong_path["input"]["path"] = "wrong.json"
    wrong_path = _seal_sidecar(wrong_path)
    malformed_input = _sidecar()
    malformed_input["input"] = []
    malformed_input = _seal_sidecar(malformed_input)

    assert "qs_sidecar_input_sha256_mismatch" in _stage2_report(
        sidecar=wrong_hash
    )["blockers"]
    assert "qs_sidecar_cutoff_mismatch" in _stage2_report(
        sidecar=wrong_cutoff
    )["blockers"]
    assert "qs_sidecar_input_path_mismatch" in _stage2_report(
        sidecar=wrong_path
    )["blockers"]
    assert "qs_sidecar_input_path_mismatch" in _stage2_report(
        sidecar=malformed_input
    )["blockers"]


def test_stage2_sidecar_identity_and_value_errors_fail_closed():
    missing = _sidecar()
    missing["rows"] = []
    missing = _seal_sidecar(missing)
    extra = _sidecar()
    extra["rows"].append(
        {
            "mlbam_id": 99,
            "season": 2019,
            "games_started": 1,
            "quality_starts": 0,
            "provenance": "derived_game_log",
        }
    )
    extra = _seal_sidecar(extra)
    duplicate = _sidecar()
    duplicate["rows"].append(deepcopy(duplicate["rows"][0]))
    duplicate = _seal_sidecar(duplicate)
    invalid = _sidecar(quality_starts=26, games_started=25)

    assert "qs_sidecar_missing_identity:20:2019" in _stage2_report(
        sidecar=missing
    )["blockers"]
    assert "qs_sidecar_extra_identity:99:2019" in _stage2_report(
        sidecar=extra
    )["blockers"]
    assert "qs_sidecar_duplicate_identity:20:2019" in _stage2_report(
        sidecar=duplicate
    )["blockers"]
    assert "qs_sidecar_invalid_row:0" in _stage2_report(
        sidecar=invalid
    )["blockers"]


def test_stage2_declared_sidecar_blocker_is_preserved():
    sidecar = _sidecar()
    sidecar["blockers"] = ["fetch_failed:20:2019"]
    sidecar = _seal_sidecar(sidecar)

    report = _stage2_report(sidecar=sidecar)

    assert "qs_sidecar_declared_blocker:fetch_failed:20:2019" in report["blockers"]


def test_stage2_current_season_supersession_must_be_disclosed():
    contract = _contract()
    contract["historical_mlb_seasons"]["20_pitcher"][0].update(
        {"year": 2026, "qs": 1}
    )
    sidecar = _sidecar(quality_starts=3)
    sidecar["rows"][0]["season"] = 2026
    sidecar["validation"]["current_season_values_superseded"] = [
        {
            "mlbam_id": 20,
            "season": 2026,
            "existing": 1,
            "derived": 3,
        }
    ]
    sidecar = _seal_sidecar(sidecar)

    disclosed = _stage2_report(contract=contract, sidecar=sidecar)
    sidecar["validation"]["current_season_values_superseded"] = []
    sidecar = _seal_sidecar(sidecar)
    undisclosed = _stage2_report(contract=contract, sidecar=sidecar)

    assert not any(
        blocker.startswith("qs_source_conflict:")
        for blocker in disclosed["blockers"]
    )
    assert "qs_source_conflict:20:2026" in undisclosed["blockers"]


def test_stage2_completed_season_qs_conflict_blocks():
    contract = _contract()
    contract["historical_mlb_seasons"]["20_pitcher"][0]["qs"] = 1

    assert "qs_source_conflict:20:2019" in _stage2_report(
        contract=contract
    )["blockers"]


def test_stage2_non_qs_category_below_coverage_blocks():
    contract = _contract()
    contract["historical_mlb_seasons"]["20_pitcher"][0]["k_bb"] = None

    report = _stage2_report(contract=contract)

    assert report["outcome_evidence"]["pitcher"]["missing"] == ["k_bb"]
    assert "missing_pitcher_category:k_bb" in report["blockers"]
    assert report["outcome_evidence"][
        "retrospective_direct_7x7_evidence_ready"
    ] is False


def test_stage2_report_and_hash_are_deterministic():
    first = _stage2_report()
    second = _stage2_report()

    assert first == second
    assert first["content_sha256"] == _canonical_hash(first)


def test_stage2_source_hash_is_line_ending_independent():
    assert readiness.source_sha256(b'{"value":1}\r\n') == hashlib.sha256(
        b'{"value":1}\n'
    ).hexdigest()


def test_stage2_builder_writes_only_requested_output(tmp_path):
    root = Path(__file__).resolve().parents[1]
    protected = [
        root / "data/validation/valucast_prospect_realized_value_readiness.json",
        root / "data/prospects/prospect_model_inputs.json",
        root / "data/models/valucast_prospect_model.json",
        root / "data/validation/valucast_stage2_quality_starts.json",
    ]
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected
    }
    output = tmp_path / "readiness.json"

    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/build_stage2_realized_value_readiness.py"),
            "--output",
            str(output),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.exists()
    assert before == {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected
    }
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == "valucast_stage2_realized_value_readiness"
    assert report["outcome_evidence"]["status"] == "ready"
    assert report["blockers"] == [
        "impact_target_not_direct_7x7",
        "exact_prospective_replay_not_reconstructable",
    ]
