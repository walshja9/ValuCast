"""Execute the registered Stage 1 maturation re-run (one look).

Registration: docs/registration-2026-08-14-stage1-maturation-rerun.md
(study id ``stage1_outcome_proof_maturation_v2``). This runner enforces the
registered population pins, executes the single registered look, and applies
the pre-registered resolution mapping mechanically. It is executed exactly
once, by hand, for the registered look — it is not part of any workflow and
CI never runs it (machinery tests use synthetic fixtures only).

Any pin violation raises before a single metric is viewed; adjudication
belongs to the owner, not this script.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prospects.model as prospect_model
from prospects.model import _historical_rows, outcome_oof_rows
from prospects.outcome_oof import ARTIFACT_PATH as LIVE_OOF_PATH
from prospects.outcome_oof import (
    build_outcome_oof_artifact,
    validate_outcome_oof_artifact,
)
from prospects.probability_reliability import (
    build_probability_reliability,
    validate_probability_reliability,
)
from prospects.universal import INPUT_PATH, load_input_contract

STUDY_ID = "stage1_outcome_proof_maturation_v2"
REGISTRATION_PATH = ROOT / "docs/registration-2026-08-14-stage1-maturation-rerun.md"
SEED = 36061
# Reserved exclusively for the rule-4 terminal increment (~Oct 2026); using
# it for this look would be a registration violation.
RULE4_RESERVED_SEED = 37083
FORBIDDEN_SEEDS = frozenset(
    {
        34041,  # proof v1
        35021,  # Plan 035
        # Plan 035's pinned held/spent/exploratory/reserved list:
        28013, 28014, 28015, 28017, 29001, 29016, 31013, 31017,
        32019, 33021, 34021, 34027, 34031, 72127,
    }
)
MATURE_THROUGH_RESEARCH = 2021
ROLES = ("hitter", "pitcher")
EXPECTED_ELIGIBLE_2021 = {"hitter": 386, "pitcher": 365}
EXPECTED_POOLED = {"hitter": 1765, "pitcher": 1887}
EXPECTED_COHORTS = [2016, 2017, 2018, 2019, 2021]
PINNED_LIVE_FOLDS = (2016, 2017, 2018, 2019)
METRICS = ("spearman_rho", "kendall_tau_b", "roc_auc")
BASELINES = ("level_age_prior", "historical_neighbors_25")

OOF_OUT = ROOT / "data/validation/valucast_outcome_oof_scores_maturation2021.json"
RELIABILITY_OUT = (
    ROOT / "data/validation/valucast_probability_reliability_maturation2021.json"
)
BACKTEST_SNAPSHOT = (
    ROOT / "data/validation/valucast_prospect_dynasty_backtest_maturation2021.json"
)
SCORECARD_SNAPSHOT = (
    ROOT / "data/validation/valucast_ahead_of_consensus_scorecard_maturation2021.json"
)
LIVE_BACKTEST = ROOT / "data/models/valucast_prospect_dynasty_backtest.json"
LIVE_SCORECARD = ROOT / "data/models/valucast_ahead_of_consensus_scorecard.json"


class RegistrationHalt(RuntimeError):
    """A registered pin failed; the look must not proceed."""


def _halt(message: str) -> None:
    raise RegistrationHalt(
        "REGISTERED PIN VIOLATED - owner adjudication required before any "
        f"look: {message}"
    )


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def apply_resolution_mapping(proof_payload: dict) -> dict:
    """The pre-registered four-rule mapping, mechanically applied."""
    pitcher_metrics = proof_payload["historical"]["roles"]["pitcher"]["metrics"]
    deltas = {}
    for metric in METRICS:
        cell = pitcher_metrics[metric]["model_minus_baseline"][
            "historical_neighbors_25"
        ]
        deltas[metric] = {
            "point": cell["point"],
            "low": cell["low"],
            "high": cell["high"],
            "evidence_status": cell["evidence_status"],
        }
    if any(
        value is None
        for cell in deltas.values()
        for value in (cell["point"], cell["low"], cell["high"])
    ):
        rule = "VOID_OWNER_ADJUDICATION"
    elif all(
        cell["evidence_status"] == "supported_retrospective"
        for cell in deltas.values()
    ):
        rule = "RULE_1_VALIDATED"
    elif any(cell["high"] < 0.0 for cell in deltas.values()):
        rule = "RULE_2_REJECTED_NOW"
    elif any(
        cell["low"] <= 0.0 and cell["point"] <= 0.0 for cell in deltas.values()
    ):
        rule = "RULE_3_REJECTED_NOW"
    else:
        rule = "RULE_4_BOUNDED_2022_INCREMENT"

    hitter_metrics = proof_payload["historical"]["roles"]["hitter"]["metrics"]
    hitter_deltas = {}
    weakened = False
    for metric in METRICS:
        for baseline in BASELINES:
            cell = hitter_metrics[metric]["model_minus_baseline"][baseline]
            hitter_deltas[f"{metric}:{baseline}"] = {
                "point": cell["point"],
                "low": cell["low"],
                "high": cell["high"],
            }
            if cell["low"] is None or cell["low"] <= 0.0:
                weakened = True
    return {
        "study_id": STUDY_ID,
        "seed": SEED,
        "mature_through": MATURE_THROUGH_RESEARCH,
        "pitcher_vs_neighbors": deltas,
        "rule": rule,
        "hitter_monitoring": {
            "weakened_triggers_owner_review": weakened,
            "deltas": hitter_deltas,
        },
    }


def main() -> int:
    if SEED in FORBIDDEN_SEEDS or SEED == RULE4_RESERVED_SEED:
        _halt("bootstrap seed is not fresh")
    if prospect_model.MATURE_THROUGH != 2019:
        _halt("live MATURE_THROUGH constant has been modified")

    contract = load_input_contract(INPUT_PATH)
    dataset_rows = contract["historical"]["rows"]

    # Pin (a): pre-prediction eligibility counts — no model output computed.
    for role, expected in EXPECTED_ELIGIBLE_2021.items():
        eligible = [
            row
            for row in _historical_rows(dataset_rows, role, MATURE_THROUGH_RESEARCH)
            if int(row["cohort_year"]) == MATURE_THROUGH_RESEARCH
        ]
        if len(eligible) != expected:
            _halt(
                f"2021 eligible {role}s = {len(eligible)}, registered {expected}"
            )

    role_rows = {
        role: outcome_oof_rows(role, dataset_rows, MATURE_THROUGH_RESEARCH)
        for role in ROLES
    }

    # Pin (b): pooled totals and exact cohort set.
    for role, expected in EXPECTED_POOLED.items():
        if len(role_rows[role]) != expected:
            _halt(
                f"pooled {role} OOF rows = {len(role_rows[role])}, "
                f"registered {expected}"
            )
    cohorts = sorted(
        {row["test_cohort"] for rows in role_rows.values() for row in rows}
    )
    if cohorts != EXPECTED_COHORTS:
        _halt(f"closed cohorts = {cohorts}, registered {EXPECTED_COHORTS}")

    oof_payload = build_outcome_oof_artifact(
        role_rows,
        input_sha256=hashlib.sha256(INPUT_PATH.read_bytes()).hexdigest(),
    )
    problems = validate_outcome_oof_artifact(oof_payload)
    if problems:
        _halt("maturation OOF artifact invalid: " + "; ".join(problems))

    # Pin (c): 2016-2019 fold populations must match the committed live
    # artifact, so the v1 comparison basis cannot silently shift.
    live_folds = {
        fold["test_cohort"]: fold
        for fold in json.loads(LIVE_OOF_PATH.read_text(encoding="utf-8"))["folds"]
    }
    new_folds = {fold["test_cohort"]: fold for fold in oof_payload["folds"]}
    for cohort in PINNED_LIVE_FOLDS:
        for role in ROLES:
            live_hash = live_folds[cohort]["roles"][role]["identity_sha256"]
            new_hash = new_folds[cohort]["roles"][role]["identity_sha256"]
            if live_hash != new_hash:
                _halt(
                    f"{role} fold {cohort} population diverged from the "
                    "committed live OOF artifact"
                )

    _write(OOF_OUT, oof_payload)

    oof_bytes = OOF_OUT.read_bytes()
    reliability = build_probability_reliability(
        json.loads(oof_bytes),
        oof_sha256=hashlib.sha256(oof_bytes).hexdigest(),
        source_path=str(OOF_OUT.relative_to(ROOT)).replace("\\", "/"),
    )
    problems = validate_probability_reliability(reliability)
    if problems:
        _halt("maturation reliability artifact invalid: " + "; ".join(problems))
    _write(RELIABILITY_OUT, reliability)

    # Frozen snapshots of the claim-time archives (daily-mutable live copies).
    BACKTEST_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LIVE_BACKTEST, BACKTEST_SNAPSHOT)
    shutil.copyfile(LIVE_SCORECARD, SCORECARD_SNAPSHOT)

    # The single registered look.
    from scripts.build_stage1_outcome_proof import run

    proof_payload = run(
        seed=SEED,
        input_paths={
            "oof": OOF_OUT,
            "reliability": RELIABILITY_OUT,
            "backtest": BACKTEST_SNAPSHOT,
            "scorecard": SCORECARD_SNAPSHOT,
        },
    )
    summary = apply_resolution_mapping(proof_payload)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
