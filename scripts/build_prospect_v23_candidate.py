"""Pure Phase A reconstruction and screening helpers for Prospect Rank v2.3."""
from __future__ import annotations

import math
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from prospects.rank_v1 import _score_source_sort_order
from prospects.rank_v2 import build_fold_contract, reconstruct_fold_ladders
from prospects.role_slope_joint_calibration import (
    fit_role_slope_joint_map,
    score_role_slope_joint_ladders,
)
from prospects.prospect_v2_target import canonical_sha256, validate_development_contract


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_READ_PATHS = (
    "data/validation/valucast_prospect_rank_v2_3_registration.json",
    "data/validation/valucast_prospect_v2_development_contract.json",
    "data/models/valucast_prospect_model_v0_9.json",
    "data/validation/valucast_prospect_rank_v2_1_development.json",
    "data/validation/valucast_prospect_rank_v2_2_development.json",
)
REGISTRATION_PATH = ROOT / CANONICAL_READ_PATHS[0]
RECEIPT_PATH = ROOT / "data" / "validation" / "valucast_prospect_rank_v2_3_development.json"
CALIBRATOR_PATH = ROOT / "data" / "models" / "valucast_prospect_joint_ladder_calibrator_v5.json"
# Tests replace this with a D: temporary common-dir token.  The production value is
# resolved lazily so importing this pure evaluator never touches repository state.
SPEND_TOKEN_PATH: Path | None = None
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_TERMINAL = {"qualified", "failed", "spent_error"}


class ProtocolError(RuntimeError):
    """A pre-spend or receipt-protocol refusal (always exit code 2)."""


DEVELOPMENT_FOLDS = (2018, 2019, 2021)
TRAINING_FOLDS_BY_TEST = {
    2018: (2019, 2021),
    2019: (2018, 2021),
    2021: (2018, 2019),
}
ROLES = ("hitter", "pitcher")
BOOTSTRAP_METRICS = (
    "candidate_control_mae_delta",
    "candidate_control_concordance_delta",
    "candidate_product_concordance_delta",
)
FOLD_GATE_ORDER = (
    "candidate_control_mae",
    "candidate_control_concordance",
    "candidate_concordance_floor",
    "candidate_product_concordance",
    "candidate_control_top25",
    "candidate_product_top25",
)
STRUCTURAL_STAGES = (
    "identity_alignment",
    "target_alignment",
    "candidate_map",
    "control_map",
    "product_reconstruction",
    "metric_contract",
    "top25_contract",
)
BOOTSTRAP_MINIMUM = 9_900

_REGISTRATION_CONTRACT = {
    "static_sha256": "6759d1323318be846a6f382edad8553ab9eb9777dc5eafaebca5fe2d11ebc6c6",
    "source_binding_keys": {"git_blob", "normalized_sha256"},
    "history_evidence_keys": {
        "scope_tip", "standalone_pattern", "inventory_schema", "object_count",
        "sorted_object_ids_sha256", "inventory_entry_count", "inventory_sha256",
        "classification_schema", "classifications", "classification_sha256",
        "result_artifact_entries", "runner_invocation_entries",
    },
    "classification_keys": {
        "object_id", "path", "byte_offset", "line_sha256", "classification",
    },
}

# Exact seed-bearing rows retained only through the superseded local PR lineage.
_REVIEWED_POST_REGISTRATION_SEED_ROWS = frozenset({
    (
        "660d69986baa81a259f0794df28d712da9be1952",
        "tests/fixtures/prospect_v23_registration_static_preimage.json",
        15868,
        "ce1bd7ec0b6feed55d327eefa8d7d80fcf304fe4f64c6918d042513d4c6ae127",
    ),
    (
        "660d69986baa81a259f0794df28d712da9be1952",
        "tests/fixtures/prospect_v23_registration_static_preimage.json",
        16936,
        "2f1c2dd62c3f5777f6370ea34ff52747d67265194f665704299499b3ffd7f2e1",
    ),
    (
        "660d69986baa81a259f0794df28d712da9be1952",
        "tests/fixtures/prospect_v23_registration_static_preimage.json",
        16982,
        "96b70f3c108ae1555d7099d0e653fdc84cc8c08b45f7ee5f9a8bb8c62596d719",
    ),
    (
        "992a84bc47468ee5977845b0e0504ac732c15afd",
        "scripts/build_prospect_v23_candidate.py",
        31578,
        "886d5848fe58889fcf29467eb9ed5a6fb32fe0f6cb1182dfdb9bdd15debb1322",
    ),
    (
        "992a84bc47468ee5977845b0e0504ac732c15afd",
        "scripts/build_prospect_v23_candidate.py",
        35344,
        "0cf93db39d79ae8c2b26d073ce06eb4a245975d24c17798d6e83ea04f2c3f26a",
    ),
    (
        "992a84bc47468ee5977845b0e0504ac732c15afd",
        "scripts/build_prospect_v23_candidate.py",
        77669,
        "c1cae6362c23b10e7426c8c2e43bf0fb7d3d5cb59da4c8cff926150b03a17665",
    ),
    (
        "c1724605674cbfdc8057e0034d8e320a48743757",
        "scripts/build_prospect_v23_candidate.py",
        31578,
        "886d5848fe58889fcf29467eb9ed5a6fb32fe0f6cb1182dfdb9bdd15debb1322",
    ),
    (
        "c1724605674cbfdc8057e0034d8e320a48743757",
        "scripts/build_prospect_v23_candidate.py",
        35344,
        "0cf93db39d79ae8c2b26d073ce06eb4a245975d24c17798d6e83ea04f2c3f26a",
    ),
    (
        "c1724605674cbfdc8057e0034d8e320a48743757",
        "scripts/build_prospect_v23_candidate.py",
        78169,
        "c1cae6362c23b10e7426c8c2e43bf0fb7d3d5cb59da4c8cff926150b03a17665",
    ),
})


def _identity(row: dict, label: str) -> tuple[str, str]:
    try:
        identity = (str(row["mlbam_id"]), str(row["role"]))
    except (KeyError, TypeError):
        raise ValueError(f"{label} has an invalid identity") from None
    if identity[0] in {"", "None"} or identity[1] not in {"hitter", "pitcher"}:
        raise ValueError(f"{label} has an invalid identity")
    return identity


def _number(row: dict, field: str, label: str) -> float:
    try:
        value = row[field]
        if isinstance(value, bool):
            raise ValueError
        value = float(value)
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{label} has an invalid {field}") from None
    if not math.isfinite(value):
        raise ValueError(f"{label} has an invalid {field}")
    return value


def reconstruct_development_ladders(contract: dict, v09_model: dict) -> dict[int, dict]:
    """Rebuild the registered folds with sealed v0.9 pitcher OOF rows only."""
    oof_rows = v09_model.get("oof_rows") if isinstance(v09_model, dict) else None
    if not isinstance(oof_rows, list):
        raise ValueError("sealed v0.9 model is missing oof_rows")
    ladders = {}
    for year in DEVELOPMENT_FOLDS:
        pitchers = [
            deepcopy(row)
            for row in oof_rows
            if row.get("role") == "pitcher" and row.get("test_cohort") == year
        ]
        if any(row.get("score_source") != "prospect_model_v0_9" for row in pitchers):
            raise ValueError("sealed v0.9 pitcher rows have an invalid score source")
        ladders[year] = reconstruct_fold_ladders(
            build_fold_contract(contract, year), pitchers, year
        )
    return ladders


def reconstruct_product_board(
    incumbent_hitters: list[dict], incumbent_pitchers: list[dict]
) -> list[dict]:
    """Merge the incumbent emitted role ladders using product's exact tie order."""
    rows = [deepcopy(row) for row in [*incumbent_hitters, *incumbent_pitchers]]
    identities = [_identity(row, "product board") for row in rows]
    if len(set(identities)) != len(identities):
        raise ValueError("product board has duplicate identities")
    for row in rows:
        _number(row, "score", "product board")
    rows.sort(
        key=lambda row: (
            -round(float(row["score"]), 2),
            _score_source_sort_order(row.get("score_source")),
            row["role"],
            str(row.get("name") or ""),
            int(row["mlbam_id"]),
        )
    )
    ranks = [row.get("rank") for row in rows]
    if any(type(rank) is not int for rank in ranks) or ranks != list(range(1, len(rows) + 1)):
        raise ValueError("product board emitted ranks must be exactly 1..n")
    return rows


def align_by_identity(reference: list[dict], rows: list[dict], label: str) -> list[dict]:
    """Return rows in reference identity order after exact target validation."""
    if not isinstance(reference, list) or not isinstance(rows, list):
        raise ValueError(f"{label} identity rows must be lists")
    reference_keys = [_identity(row, "reference") for row in reference]
    row_keys = [_identity(row, label) for row in rows]
    if len(set(reference_keys)) != len(reference_keys) or len(set(row_keys)) != len(row_keys):
        raise ValueError(f"{label} has duplicate identities")
    if set(reference_keys) != set(row_keys):
        raise ValueError(f"{label} identity mismatch")
    by_key = dict(zip(row_keys, rows))
    aligned = []
    for key, expected in zip(reference_keys, reference):
        actual = by_key[key]
        if _number(expected, "target", "reference") != _number(actual, "target", label):
            raise ValueError(f"{label} target mismatch")
        aligned.append(deepcopy(actual))
    return aligned


def mae(rows: list[dict], score_field: str) -> float:
    """Return mean absolute error against the registered numeric target."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("MAE requires rows")
    return sum(abs(_number(row, score_field, "MAE") - _number(row, "target", "MAE")) for row in rows) / len(rows)


def cross_role_concordance(rows: list[dict], score_field: str) -> float | None:
    """Score only unequal-target hitter/pitcher pairs, with half-credit score ties."""
    if not isinstance(rows, list):
        raise ValueError("concordance requires rows")
    hitters = [row for row in rows if row.get("role") == "hitter"]
    pitchers = [row for row in rows if row.get("role") == "pitcher"]
    points = []
    for hitter in hitters:
        for pitcher in pitchers:
            hitter_target = _number(hitter, "target", "concordance")
            pitcher_target = _number(pitcher, "target", "concordance")
            if hitter_target == pitcher_target:
                continue
            hitter_score = _number(hitter, score_field, "concordance")
            pitcher_score = _number(pitcher, score_field, "concordance")
            if hitter_score == pitcher_score:
                points.append(0.5)
            else:
                points.append(float((hitter_score > pitcher_score) == (hitter_target > pitcher_target)))
    return sum(points) / len(points) if points else None


def top25_target_sum(rows: list[dict], *, product: bool = False) -> float:
    """Return the target total for exactly the registered top twenty-five."""
    if not isinstance(rows, list) or len(rows) < 25:
        raise ValueError("top-25 selection requires exactly 25 selected rows")
    if product:
        ranks = [_number(row, "rank", "product top-25") for row in rows]
        if sorted(ranks) != list(range(1, len(rows) + 1)):
            raise ValueError("product top-25 ranks must be exactly 1..n")
        selected = sorted(rows, key=lambda row: int(row["rank"]))[:25]
    else:
        selected = sorted(
            rows,
            key=lambda row: (
                -_number(row, "calibrated_expected_tier", "top-25"),
                int(row.get("source_ladder_position", 0)),
                int(row.get("mlbam_id", 0)),
            ),
        )[:25]
    if len(selected) != 25:
        raise ValueError("top-25 selection requires exactly 25 selected rows")
    return sum(_number(row, "target", "top-25") for row in selected)


def _training_rows(year: int, ladders: dict[int, dict], prefix: str) -> list[dict]:
    if year not in TRAINING_FOLDS_BY_TEST:
        raise ValueError("unknown development fold")
    rows = []
    for training_year in TRAINING_FOLDS_BY_TEST[year]:
        try:
            source = ladders[training_year]
            role_rows = [source[f"{prefix}_hitters"], source[f"{prefix}_pitchers"]]
        except (KeyError, TypeError):
            raise ValueError("development ladders are missing a training fold") from None
        for row in [*role_rows[0], *role_rows[1]]:
            if row.get("test_cohort") != training_year:
                raise ValueError("development training row cohort marker mismatch")
            try:
                rows.append({
                    "mlbam_id": row["mlbam_id"],
                    "role": row["role"],
                    "source_ladder_position": row["source_ladder_position"],
                    "ladder_score": row["ladder_score"],
                    "outcome": row["outcome"],
                    "target": row["target"],
                    "test_cohort": training_year,
                })
            except (KeyError, TypeError):
                raise ValueError("development ladder has an invalid training row") from None
    return rows


def fit_fold_maps(year: int, ladders: dict[int, dict]) -> tuple[dict, dict]:
    """Independently fit candidate and control maps on the exact fold complement."""
    return (
        fit_role_slope_joint_map(_training_rows(year, ladders, "candidate")),
        fit_role_slope_joint_map(_training_rows(year, ladders, "incumbent")),
    )


def build_fold_result(
    year: int, ladders: dict[int, dict], candidate_map: dict, control_map: dict
) -> dict:
    """Score one held-out combined board and calculate its six independent gates."""
    if year not in DEVELOPMENT_FOLDS or year not in ladders:
        raise ValueError("unknown development fold")
    expected_candidate_map, expected_control_map = fit_fold_maps(year, ladders)
    if candidate_map != expected_candidate_map or control_map != expected_control_map:
        raise ValueError("supplied maps do not match the exact fold-complement fits")
    ladder = ladders[year]
    candidate = score_role_slope_joint_ladders(
        ladder["candidate_hitters"], ladder["candidate_pitchers"], candidate_map
    )
    control = score_role_slope_joint_ladders(
        ladder["incumbent_hitters"], ladder["incumbent_pitchers"], control_map
    )
    product = reconstruct_product_board(
        ladder["incumbent_hitters"], ladder["incumbent_pitchers"]
    )
    control = align_by_identity(candidate, control, "control")
    product = align_by_identity(candidate, product, "product")
    result = {
        "year": year,
        "candidate": candidate,
        "control": control,
        "product": product,
        "candidate_mae": mae(candidate, "calibrated_expected_tier"),
        "control_mae": mae(control, "calibrated_expected_tier"),
        "product_mae": None,
        "candidate_concordance": cross_role_concordance(candidate, "calibrated_expected_tier"),
        "control_concordance": cross_role_concordance(control, "calibrated_expected_tier"),
        "product_concordance": cross_role_concordance(product, "score"),
        "candidate_top25_target_sum": top25_target_sum(candidate),
        "control_top25_target_sum": top25_target_sum(control),
        "product_top25_target_sum": top25_target_sum(product, product=True),
    }
    return {**result, "gates": _fold_gates(result), "qualified": all(_fold_gates(result).values())}


def _fold_gates(fold: dict) -> dict[str, bool]:
    try:
        candidate_mae = _number(fold, "candidate_mae", "fold")
        control_mae = _number(fold, "control_mae", "fold")
        candidate_concordance = _number(fold, "candidate_concordance", "fold")
        control_concordance = _number(fold, "control_concordance", "fold")
        product_concordance = _number(fold, "product_concordance", "fold")
        candidate_top25 = _number(fold, "candidate_top25_target_sum", "fold")
        control_top25 = _number(fold, "control_top25_target_sum", "fold")
        product_top25 = _number(fold, "product_top25_target_sum", "fold")
    except ValueError:
        return {name: False for name in (
            "mae_improves", "control_concordance_improves", "candidate_concordance_above_half",
            "product_concordance_improves", "control_top25_matches", "product_top25_matches",
        )}
    return {
        "mae_improves": candidate_mae - control_mae < 0,
        "control_concordance_improves": candidate_concordance - control_concordance > 0,
        "candidate_concordance_above_half": candidate_concordance > 0.5,
        "product_concordance_improves": candidate_concordance - product_concordance > 0,
        "control_top25_matches": candidate_top25 >= control_top25,
        "product_top25_matches": candidate_top25 >= product_top25,
    }


def development_qualification(report: dict) -> dict:
    """Fail closed unless every registered fold clears every gate independently."""
    folds = report.get("folds") if isinstance(report, dict) else None
    if not isinstance(folds, dict):
        raise ValueError("development report is missing folds")
    verdicts = {}
    for year in DEVELOPMENT_FOLDS:
        fold = folds.get(year, folds.get(str(year)))
        gates = _fold_gates(fold) if isinstance(fold, dict) else _fold_gates({})
        verdicts[year] = {"gates": gates, "qualified": all(gates.values())}
    return {"folds": verdicts, "qualified": all(item["qualified"] for item in verdicts.values())}


def _identity_rows(rows: list[dict], role: str) -> list[int]:
    ids = sorted(int(row["mlbam_id"]) for row in rows if row.get("role") == role)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("fold identities must be nonempty and unique by role")
    return ids


def _fold_provenance(candidate_rows: list[dict]) -> tuple[dict, dict, str]:
    counts, hashes = _identity_provenance(candidate_rows)
    targets = sorted(
        [[int(row["mlbam_id"]), row["role"], _number(row, "target", "target hash")]
         for row in candidate_rows],
        key=lambda row: (row[0], row[1]),
    )
    return (
        counts,
        hashes,
        canonical_sha256(targets),
    )


def _identity_provenance(candidate_rows: list[dict]) -> tuple[dict, dict]:
    identities = {
        role: [[mlbam_id, role] for mlbam_id in _identity_rows(candidate_rows, role)]
        for role in ROLES
    }
    return (
        {role: len(identities[role]) for role in ROLES},
        {role: canonical_sha256(identities[role]) for role in ROLES},
    )


def _validate_registered_identities(ladders: dict[int, dict], registration: dict) -> None:
    try:
        expected = registration["folds"]["identity_receipts"]
        for year in DEVELOPMENT_FOLDS:
            for prefix in ("candidate", "incumbent"):
                rows = [
                    *ladders[year][f"{prefix}_hitters"],
                    *ladders[year][f"{prefix}_pitchers"],
                ]
                counts, hashes = _identity_provenance(rows)
                for role in ROLES:
                    receipt = expected[str(year)][role]
                    if receipt != {"count": counts[role], "sha256": hashes[role]}:
                        raise ValueError(
                            f"registered identity mismatch: {year} {prefix} {role}"
                        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ValueError) and "registered identity" in str(error):
            raise
        raise ValueError("registered identity receipt is invalid") from None


def _empty_fold_receipt(candidate_rows: list[dict] | None = None) -> dict:
    counts = hashes = target_hash = None
    if candidate_rows:
        counts, hashes = _identity_provenance(candidate_rows)
        try:
            _, _, target_hash = _fold_provenance(candidate_rows)
        except ValueError:
            pass
    return {
        "status": "structural_failure",
        "failure_stage": None,
        "identity_count_by_role": counts,
        "identity_sha256_by_role": hashes,
        "target_sha256": target_hash,
        "metrics": {
            "candidate_mae": None, "control_mae": None,
            "candidate_control_mae_delta": None,
            "candidate_concordance": None, "control_concordance": None,
            "product_concordance": None,
            "candidate_control_concordance_delta": None,
            "candidate_product_concordance_delta": None,
            "candidate_top25_target_sum": None,
            "control_top25_target_sum": None,
            "product_top25_target_sum": None,
        },
        "gates": {name: None for name in FOLD_GATE_ORDER},
        "structural_checks": {
            "identity_sets_equal": None, "targets_equal": None,
            "candidate_map_valid": None, "control_map_valid": None,
            "product_rank_reproduced": None, "top25_complete": None,
        },
        "failed_gates": [],
        "failed_structural": [],
    }


def _failed_fold_receipt(stage: str, candidate_rows: list[dict] | None = None) -> dict:
    if stage not in STRUCTURAL_STAGES:
        raise ValueError("unknown structural failure stage")
    receipt = _empty_fold_receipt(candidate_rows)
    receipt["failure_stage"] = stage
    receipt["failed_structural"] = [stage]
    checks = receipt["structural_checks"]
    order = (
        ("identity_alignment", "identity_sets_equal"),
        ("target_alignment", "targets_equal"),
        ("candidate_map", "candidate_map_valid"),
        ("control_map", "control_map_valid"),
        ("product_reconstruction", "product_rank_reproduced"),
        ("metric_contract", None),
        ("top25_contract", "top25_complete"),
    )
    for current, check in order:
        if current == stage:
            if check is not None:
                checks[check] = False
            break
        if check is not None:
            checks[check] = True
    return receipt


def _fold_metrics(values: dict) -> dict:
    candidate = values["candidate"]
    control = values["control"]
    product = values["product"]
    metrics = {
        "candidate_mae": mae(candidate, "calibrated_expected_tier"),
        "control_mae": mae(control, "calibrated_expected_tier"),
        "candidate_concordance": cross_role_concordance(candidate, "calibrated_expected_tier"),
        "control_concordance": cross_role_concordance(control, "calibrated_expected_tier"),
        "product_concordance": cross_role_concordance(product, "score"),
        "candidate_top25_target_sum": top25_target_sum(candidate),
        "control_top25_target_sum": top25_target_sum(control),
        "product_top25_target_sum": top25_target_sum(product, product=True),
    }
    if any(value is None or not math.isfinite(value) for value in metrics.values()):
        raise ValueError("fold metric is undefined")
    return {
        **metrics,
        "candidate_control_mae_delta": metrics["candidate_mae"] - metrics["control_mae"],
        "candidate_control_concordance_delta": metrics["candidate_concordance"] - metrics["control_concordance"],
        "candidate_product_concordance_delta": metrics["candidate_concordance"] - metrics["product_concordance"],
    }


def _completed_fold_receipt(values: dict) -> dict:
    metrics = _fold_metrics(values)
    counts, hashes, target_hash = _fold_provenance(values["candidate"])
    gates = {
        "candidate_control_mae": metrics["candidate_control_mae_delta"] < 0,
        "candidate_control_concordance": metrics["candidate_control_concordance_delta"] > 0,
        "candidate_concordance_floor": metrics["candidate_concordance"] > 0.5,
        "candidate_product_concordance": metrics["candidate_product_concordance_delta"] > 0,
        "candidate_control_top25": metrics["candidate_top25_target_sum"] >= metrics["control_top25_target_sum"],
        "candidate_product_top25": metrics["candidate_top25_target_sum"] >= metrics["product_top25_target_sum"],
    }
    return {
        "status": "completed",
        "failure_stage": None,
        "identity_count_by_role": counts,
        "identity_sha256_by_role": hashes,
        "target_sha256": target_hash,
        "metrics": metrics,
        "gates": gates,
        "structural_checks": {
            "identity_sets_equal": True, "targets_equal": True,
            "candidate_map_valid": True, "control_map_valid": True,
            "product_rank_reproduced": True, "top25_complete": True,
        },
        "failed_gates": [name for name in FOLD_GATE_ORDER if not gates[name]],
        "failed_structural": [],
    }


def _record_structural_failure(receipt: dict, stage: str) -> tuple[dict, None]:
    downstream_checks = {
        "identity_alignment": ("candidate_map_valid", "control_map_valid", "product_rank_reproduced", "top25_complete"),
        "target_alignment": ("candidate_map_valid", "control_map_valid", "product_rank_reproduced", "top25_complete"),
        "candidate_map": ("control_map_valid", "product_rank_reproduced", "top25_complete"),
        "control_map": ("product_rank_reproduced", "top25_complete"),
        "product_reconstruction": ("top25_complete",),
        "metric_contract": ("top25_complete",),
        "top25_contract": (),
    }
    for check in downstream_checks[stage]:
        receipt["structural_checks"][check] = None
    if stage != "top25_contract":
        receipt["metrics"] = {name: None for name in receipt["metrics"]}
        receipt["gates"] = {name: None for name in receipt["gates"]}
    receipt["status"] = "structural_failure"
    receipt["failure_stage"] = stage
    receipt["failed_structural"] = [stage]
    receipt["failed_gates"] = [
        name for name in FOLD_GATE_ORDER if receipt["gates"][name] is False
    ]
    return receipt, None


def _raw_identity_and_target_checks(candidate_rows: list[dict], control_rows: list[dict]) -> str | None:
    try:
        candidate_keys = [_identity(row, "candidate") for row in candidate_rows]
        control_keys = [_identity(row, "control") for row in control_rows]
        if len(set(candidate_keys)) != len(candidate_keys) or len(set(control_keys)) != len(control_keys):
            return "identity_alignment"
        if set(candidate_keys) != set(control_keys):
            return "identity_alignment"
        control_by_key = dict(zip(control_keys, control_rows))
    except (KeyError, TypeError, ValueError):
        return "identity_alignment"
    try:
        if any(
            _number(row, "target", "candidate") != _number(control_by_key[key], "target", "control")
            for key, row in zip(candidate_keys, candidate_rows)
        ):
            return "target_alignment"
    except (KeyError, TypeError, ValueError):
        return "target_alignment"
    return None


def _upstream_metrics(values: dict) -> dict:
    candidate = values["candidate"]
    control = values["control"]
    product = values["product"]
    metrics = {
        "candidate_mae": mae(candidate, "calibrated_expected_tier"),
        "control_mae": mae(control, "calibrated_expected_tier"),
        "candidate_concordance": cross_role_concordance(candidate, "calibrated_expected_tier"),
        "control_concordance": cross_role_concordance(control, "calibrated_expected_tier"),
        "product_concordance": cross_role_concordance(product, "score"),
    }
    if any(value is None or not math.isfinite(value) for value in metrics.values()):
        raise ValueError("fold metric is undefined")
    return {
        **metrics,
        "candidate_control_mae_delta": metrics["candidate_mae"] - metrics["control_mae"],
        "candidate_control_concordance_delta": metrics["candidate_concordance"] - metrics["control_concordance"],
        "candidate_product_concordance_delta": metrics["candidate_concordance"] - metrics["product_concordance"],
    }


def _upstream_gates(metrics: dict) -> dict:
    return {
        "candidate_control_mae": metrics["candidate_control_mae_delta"] < 0,
        "candidate_control_concordance": metrics["candidate_control_concordance_delta"] > 0,
        "candidate_concordance_floor": metrics["candidate_concordance"] > 0.5,
        "candidate_product_concordance": metrics["candidate_product_concordance_delta"] > 0,
    }


def _build_fold_receipt(year: int, ladders: dict[int, dict]) -> tuple[dict, dict | None]:
    ladder = ladders[year]
    candidate_rows = [*ladder.get("candidate_hitters", []), *ladder.get("candidate_pitchers", [])]
    try:
        receipt = _empty_fold_receipt(candidate_rows)
    except (KeyError, TypeError, ValueError):
        return _failed_fold_receipt("identity_alignment"), None
    control_rows = [*ladder.get("incumbent_hitters", []), *ladder.get("incumbent_pitchers", [])]
    stage = _raw_identity_and_target_checks(candidate_rows, control_rows)
    if stage == "identity_alignment":
        receipt["structural_checks"]["identity_sets_equal"] = False
        return _record_structural_failure(receipt, stage)
    receipt["structural_checks"]["identity_sets_equal"] = True
    if stage == "target_alignment":
        receipt["structural_checks"]["targets_equal"] = False
        return _record_structural_failure(receipt, stage)
    receipt["structural_checks"]["targets_equal"] = True
    try:
        candidate_map = fit_role_slope_joint_map(_training_rows(year, ladders, "candidate"))
        candidate = score_role_slope_joint_ladders(
            ladder["candidate_hitters"], ladder["candidate_pitchers"], candidate_map
        )
    except (KeyError, TypeError, ValueError):
        receipt["structural_checks"]["candidate_map_valid"] = False
        return _record_structural_failure(receipt, "candidate_map")
    receipt["structural_checks"]["candidate_map_valid"] = True
    try:
        control_map = fit_role_slope_joint_map(_training_rows(year, ladders, "incumbent"))
        control = score_role_slope_joint_ladders(
            ladder["incumbent_hitters"], ladder["incumbent_pitchers"], control_map
        )
    except (KeyError, TypeError, ValueError):
        receipt["structural_checks"]["control_map_valid"] = False
        return _record_structural_failure(receipt, "control_map")
    receipt["structural_checks"]["control_map_valid"] = True
    try:
        product = reconstruct_product_board(ladder["incumbent_hitters"], ladder["incumbent_pitchers"])
    except (KeyError, TypeError, ValueError):
        receipt["structural_checks"]["product_rank_reproduced"] = False
        return _record_structural_failure(receipt, "product_reconstruction")
    receipt["structural_checks"]["product_rank_reproduced"] = True
    try:
        control = align_by_identity(candidate, control, "control")
        product = align_by_identity(candidate, product, "product")
    except ValueError as error:
        stage = "target_alignment" if "target mismatch" in str(error) else "identity_alignment"
        receipt["structural_checks"]["targets_equal" if stage == "target_alignment" else "identity_sets_equal"] = False
        return _record_structural_failure(receipt, stage)
    values = {"year": year, "candidate": candidate, "control": control, "product": product}
    try:
        receipt["metrics"].update(_upstream_metrics(values))
    except ValueError:
        return _record_structural_failure(receipt, "metric_contract")
    receipt["gates"].update(_upstream_gates(receipt["metrics"]))
    try:
        top_metrics = {
            "candidate_top25_target_sum": top25_target_sum(candidate),
            "control_top25_target_sum": top25_target_sum(control),
            "product_top25_target_sum": top25_target_sum(product, product=True),
        }
    except ValueError:
        receipt["structural_checks"]["top25_complete"] = False
        return _record_structural_failure(receipt, "top25_contract")
    receipt["metrics"].update(top_metrics)
    receipt["gates"].update({
        "candidate_control_top25": top_metrics["candidate_top25_target_sum"] >= top_metrics["control_top25_target_sum"],
        "candidate_product_top25": top_metrics["candidate_top25_target_sum"] >= top_metrics["product_top25_target_sum"],
    })
    receipt["structural_checks"]["top25_complete"] = True
    receipt["status"] = "completed"
    receipt["failed_gates"] = [name for name in FOLD_GATE_ORDER if not receipt["gates"][name]]
    return receipt, values


def _bootstrap_fold_rows(fold: dict) -> tuple[list[dict], list[dict], list[dict]]:
    try:
        candidate, control, product = fold["candidate"], fold["control"], fold["product"]
        for rows in (candidate, control, product):
            if not isinstance(rows, list):
                raise ValueError
        control = align_by_identity(candidate, control, "bootstrap control")
        product = align_by_identity(candidate, product, "bootstrap product")
        return candidate, control, product
    except (KeyError, TypeError, ValueError):
        raise ValueError("bootstrap folds must contain aligned candidate, control, and product rows") from None


def _bootstrap_metric_rows(candidate: list[dict], control: list[dict], product: list[dict]) -> dict:
    candidate_mae = mae(candidate, "calibrated_expected_tier")
    control_mae = mae(control, "calibrated_expected_tier")
    candidate_concordance = cross_role_concordance(candidate, "calibrated_expected_tier")
    control_concordance = cross_role_concordance(control, "calibrated_expected_tier")
    product_concordance = cross_role_concordance(product, "score")
    return {
        "candidate_control_mae_delta": candidate_mae - control_mae,
        "candidate_control_concordance_delta": None if candidate_concordance is None or control_concordance is None else candidate_concordance - control_concordance,
        "candidate_product_concordance_delta": None if candidate_concordance is None or product_concordance is None else candidate_concordance - product_concordance,
    }


def _bootstrap_empty_metric() -> dict:
    return {"point": None, "lower": None, "upper": None, "valid_replicates": None, "gate_passed": None}


def build_bootstrap_summary(
    folds: dict, *, seed: int = 39017, replicates: int = 10_000,
) -> dict:
    """Bootstrap fixed fold maps with a single deterministic identity sample stream."""
    if not isinstance(replicates, int) or isinstance(replicates, bool) or replicates <= 0:
        raise ValueError("bootstrap replicate count must be positive")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("bootstrap seed must be an integer")
    prepared = {}
    for year in DEVELOPMENT_FOLDS:
        fold = folds.get(year, folds.get(str(year))) if isinstance(folds, dict) else None
        prepared[year] = _bootstrap_fold_rows(fold)
    point = {name: 0.0 for name in BOOTSTRAP_METRICS}
    for year in DEVELOPMENT_FOLDS:
        metrics = _bootstrap_metric_rows(*prepared[year])
        for name, value in metrics.items():
            if value is not None:
                point[name] += value / len(DEVELOPMENT_FOLDS)
            else:
                point[name] = None
    rng = np.random.default_rng(seed)
    samples = []
    values = {name: [] for name in BOOTSTRAP_METRICS}
    for _ in range(replicates):
        replicate = []
        per_fold = {name: [] for name in BOOTSTRAP_METRICS}
        for year in DEVELOPMENT_FOLDS:
            candidate, control, product = prepared[year]
            by_key = {
                label: {(int(row["mlbam_id"]), row["role"]): row for row in rows}
                for label, rows in (("candidate", candidate), ("control", control), ("product", product))
            }
            sample_keys = []
            for role in ROLES:
                ids = _identity_rows(candidate, role)
                draw = [int(value) for value in rng.choice(ids, size=len(ids), replace=True)]
                replicate.append({"fold": year, "role": role, "mlbam_ids": draw})
                sample_keys.extend((player_id, role) for player_id in draw)
            try:
                sampled = [[by_key[label][key] for key in sample_keys] for label in ("candidate", "control", "product")]
            except KeyError:
                raise ValueError("bootstrap comparator identity mismatch") from None
            metrics = _bootstrap_metric_rows(*sampled)
            for name, value in metrics.items():
                if value is not None and math.isfinite(value):
                    per_fold[name].append(value)
        samples.append(replicate)
        for name in BOOTSTRAP_METRICS:
            if len(per_fold[name]) == len(DEVELOPMENT_FOLDS):
                values[name].append(sum(per_fold[name]) / len(DEVELOPMENT_FOLDS))
    minimum = BOOTSTRAP_MINIMUM
    gates = {
        "candidate_control_mae_delta": lambda lower, upper: upper < 0,
        "candidate_control_concordance_delta": lambda lower, upper: lower > 0,
        "candidate_product_concordance_delta": lambda lower, upper: lower > 0,
    }
    summary = {}
    for name in BOOTSTRAP_METRICS:
        valid = len(values[name])
        if valid:
            lower, upper = (float(value) for value in np.percentile(values[name], [2.5, 97.5], method="linear"))
            passed = valid >= minimum and gates[name](lower, upper)
        else:
            lower = upper = None
            passed = False
        summary[name] = {
            "point": point[name], "lower": lower, "upper": upper,
            "valid_replicates": valid, "gate_passed": passed,
        }
    return {
        "status": "completed", "seed": seed, "replicates": replicates,
        "minimum_valid_replicates": minimum,
        "interval": {"lower_percentile": 2.5, "upper_percentile": 97.5, "method": "linear"},
        "sample_plan_sha256": canonical_sha256(samples), "metrics": summary,
    }


def _not_attempted_bootstrap() -> dict:
    return {
        "status": "not_attempted_fold_failure", "seed": 39017, "replicates": 10_000,
        "minimum_valid_replicates": BOOTSTRAP_MINIMUM,
        "interval": {"lower_percentile": 2.5, "upper_percentile": 97.5, "method": "linear"},
        "sample_plan_sha256": None,
        "metrics": {name: _bootstrap_empty_metric() for name in BOOTSTRAP_METRICS},
    }


def _pooled_candidate_rows(ladders: dict[int, dict]) -> list[dict]:
    rows = []
    for year in DEVELOPMENT_FOLDS:
        for role in ROLES:
            for row in ladders[year][f"candidate_{role}s"]:
                rows.append({
                    "mlbam_id": row["mlbam_id"], "role": row["role"],
                    "source_ladder_position": row["source_ladder_position"],
                    "ladder_score": row["ladder_score"], "outcome": row["outcome"],
                    "target": row["target"], "test_cohort": year,
                })
    return rows


def _validate_pooled_map(mapping: dict, rows: list[dict]) -> dict:
    score_role_slope_joint_ladders([], [], mapping)
    expected_hash = canonical_sha256(sorted(
        rows,
        key=lambda row: (DEVELOPMENT_FOLDS.index(row["test_cohort"]), ROLES.index(row["role"]), row["source_ladder_position"], int(row["mlbam_id"])),
    ))
    if mapping.get("training_rows_sha256") != expected_hash:
        raise ValueError("pooled map training rows do not validate")
    return mapping


def build_development_artifacts(
    contract: dict, model: dict, registration: dict,
) -> tuple[dict, dict | None]:
    """Build the deterministic scientific result and, only on qualification, its pooled map."""
    ladders = reconstruct_development_ladders(contract, model)
    _validate_registered_identities(ladders, registration)
    receipts, bootstrap_folds = {}, {}
    for year in DEVELOPMENT_FOLDS:
        receipt, values = _build_fold_receipt(year, ladders)
        receipts[year] = receipt
        if values is not None:
            bootstrap_folds[year] = values
    all_completed = all(receipts[year]["status"] == "completed" for year in DEVELOPMENT_FOLDS)
    bootstrap = build_bootstrap_summary(bootstrap_folds) if all_completed else _not_attempted_bootstrap()
    failed_folds = [
        year for year in DEVELOPMENT_FOLDS
        if receipts[year]["status"] != "completed" or receipts[year]["failed_gates"]
    ]
    failed_bootstrap = [name for name in BOOTSTRAP_METRICS if not bootstrap["metrics"][name]["gate_passed"]] if all_completed else []
    failed_structural = [
        f"{year}:{stage}" for year in DEVELOPMENT_FOLDS for stage in receipts[year]["failed_structural"]
    ]
    pooled_fit = {
        "attempted": False, "status": "not_attempted_qualification_failure", "row_count": 0,
        "training_rows_sha256": None, "map_artifact_sha256": None,
    }
    pooled_map = None
    if not failed_folds and not failed_bootstrap:
        rows = _pooled_candidate_rows(ladders)
        training_hash = canonical_sha256(sorted(
            rows,
            key=lambda row: (DEVELOPMENT_FOLDS.index(row["test_cohort"]), ROLES.index(row["role"]), row["source_ladder_position"], int(row["mlbam_id"])),
        ))
        try:
            pooled_map = _validate_pooled_map(fit_role_slope_joint_map(rows), rows)
        except ValueError:
            pooled_fit = {
                "attempted": True, "status": "failed", "row_count": len(rows),
                "training_rows_sha256": training_hash, "map_artifact_sha256": None,
            }
            failed_structural.append("pooled_final_fit")
            pooled_map = None
        else:
            pooled_fit = {
                "attempted": True, "status": "validated", "row_count": len(rows),
                "training_rows_sha256": pooled_map["training_rows_sha256"],
                "map_artifact_sha256": pooled_map["artifact_sha256"],
            }
    result = {
        "fold_order": list(DEVELOPMENT_FOLDS), "folds": receipts, "bootstrap": bootstrap,
        "failed_folds": failed_folds, "failed_bootstrap": failed_bootstrap,
        "failed_structural": failed_structural, "pooled_fit": pooled_fit,
    }
    return _json_stable(result), pooled_map


# The wrapper below intentionally stays separate from the pure evaluator above:
# nothing in the evaluator decides whether an outcome-bearing payload may be read.
def _head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    value = result.stdout.strip()
    if result.returncode or not _SHA1.fullmatch(value):
        raise ProtocolError("cannot resolve a lowercase 40-character HEAD")
    return value


def _common_git_dir() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=ROOT, capture_output=True, text=True,
    )
    value = result.stdout.strip()
    if result.returncode or not value:
        raise ProtocolError("cannot resolve Git common directory")
    return Path(value).resolve()


def _common_lock_path() -> Path:
    return _common_git_dir() / "valucast-prospect-v23.lock"


def _spend_path() -> Path:
    return SPEND_TOKEN_PATH or (_common_git_dir() / "valucast-prospect-v23-spent.json")


@contextmanager
def _locked():
    """Hold the repository-common one-byte nonblocking lock for this invocation."""
    path = _common_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        try:
            handle.seek(0)
            if not handle.read(1):
                handle.seek(0)
                handle.write(b"0")
            handle.truncate(1)
            handle.flush()
            os.fsync(handle.fileno())
        except OSError as error:
            raise ProtocolError("v2.3 lock is already held") from error
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ProtocolError("v2.3 lock is already held") from error
            def unlock():
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ProtocolError("v2.3 lock is already held") from error
            def unlock():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        try:
            yield
        finally:
            unlock()
    finally:
        handle.close()


def _runtime_tuple() -> dict:
    import scipy

    return {
        "implementation": platform.python_implementation(),
        "compiler": platform.python_compiler(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": list(sys.version_info[:3]),
        "releaselevel": sys.version_info.releaselevel,
        "serial": sys.version_info.serial,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }


def _sealed(payload: dict) -> dict:
    unsigned = dict(payload)
    unsigned.pop("artifact_sha256", None)
    return {**unsigned, "artifact_sha256": canonical_sha256(unsigned)}


def _json_stable(payload: dict) -> dict:
    """Freeze the exact JSON object that a receipt will later reload."""
    return json.loads(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))


def _require_seal(payload: object, label: str) -> dict:
    if not isinstance(payload, dict):
        raise ProtocolError(f"{label} must be an object")
    seal = payload.get("artifact_sha256")
    if not isinstance(seal, str) or not _SHA256.fullmatch(seal):
        raise ProtocolError(f"{label} has an invalid seal")
    unsigned = dict(payload)
    unsigned.pop("artifact_sha256")
    if seal != canonical_sha256(unsigned):
        raise ProtocolError(f"{label} seal does not match")
    return payload


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as error:
        raise ProtocolError("application-data read escaped repository root") from error


def _load_json(path: Path, *, outcome: bool = False) -> dict:
    logical_paths = {
        REGISTRATION_PATH: CANONICAL_READ_PATHS[0],
        ROOT / CANONICAL_READ_PATHS[1]: CANONICAL_READ_PATHS[1],
        ROOT / CANONICAL_READ_PATHS[2]: CANONICAL_READ_PATHS[2],
        ROOT / CANONICAL_READ_PATHS[3]: CANONICAL_READ_PATHS[3],
        ROOT / CANONICAL_READ_PATHS[4]: CANONICAL_READ_PATHS[4],
        RECEIPT_PATH: "data/validation/valucast_prospect_rank_v2_3_development.json",
        CALIBRATOR_PATH: "data/models/valucast_prospect_joint_ladder_calibrator_v5.json",
    }
    relative = logical_paths.get(path)
    if relative is None:
        relative = _relative(path)
    allowed = set(CANONICAL_READ_PATHS)
    if outcome:
        allowed.update({
            "data/validation/valucast_prospect_rank_v2_3_development.json",
            "data/models/valucast_prospect_joint_ladder_calibrator_v5.json",
        })
    if relative not in allowed:
        raise ProtocolError(f"application-data read is not allowlisted: {relative}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"cannot read {relative}") from error


def _git_blob(relative: str, path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", f"--path={relative}", str(path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    value = result.stdout.strip()
    if result.returncode or not _SHA1.fullmatch(value):
        raise ProtocolError(f"cannot resolve Git blob for {relative}")
    return value


def _git_blob_at(revision: str, relative: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}:{relative}"],
        cwd=ROOT, capture_output=True, text=True,
    )
    value = result.stdout.strip()
    if result.returncode or not _SHA1.fullmatch(value):
        raise ProtocolError(f"cannot resolve {relative} at {revision}")
    return value


def _git_object_ids(tip: str) -> list[str]:
    result = subprocess.run(
        ["git", "rev-list", "--objects", "--no-object-names", tip],
        cwd=ROOT, capture_output=True, text=True,
    )
    values = sorted(set(result.stdout.splitlines()))
    if result.returncode or not values or any(not _SHA1.fullmatch(value) for value in values):
        raise ProtocolError("cannot inventory registered Git object scope")
    return values


def _git_blob_inventory(
    tip: str, token: int, *, exclude_tip: str | None = None,
) -> tuple[list[list], list[list]]:
    command = ["git", "rev-list", "--objects", tip, *([f"^{exclude_tip}"] if exclude_tip else [])]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise ProtocolError("cannot enumerate registered Git history")
    objects = [
        (object_id, path)
        for line in result.stdout.splitlines()
        for object_id, _, path in [line.partition(" ")]
        if _SHA1.fullmatch(object_id) and path
    ]
    pattern = re.compile(rf"(?<![0-9]){token}(?![0-9])".encode())
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"], cwd=ROOT, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    rows, structured = [], []
    try:
        if process.stdin is None or process.stdout is None:
            raise ProtocolError("cannot open Git object reader")
        for object_id, path in objects:
            process.stdin.write(f"{object_id}\n".encode())
            process.stdin.flush()
            header = process.stdout.readline().decode("ascii", errors="strict").strip().split()
            if len(header) != 3 or header[0] != object_id or not header[2].isdigit():
                raise ProtocolError("Git object inventory is malformed")
            size = int(header[2])
            payload = process.stdout.read(size)
            if len(payload) != size or process.stdout.read(1) != b"\n":
                raise ProtocolError("Git object inventory is truncated")
            if header[1] != "blob":
                continue
            for match in pattern.finditer(payload):
                line_start = payload.rfind(b"\n", 0, match.start()) + 1
                line_end = payload.find(b"\n", match.end())
                if line_end < 0:
                    line_end = len(payload)
                line = payload[line_start:line_end]
                row = [object_id, path.replace("\\", "/"), match.start(), hashlib.sha256(line).hexdigest()]
                rows.append(row)
                if re.search(rb"seed", line, flags=re.IGNORECASE):
                    structured.append(row)
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.terminate()
        process.wait()
    return sorted(rows), sorted(structured)


def _git_blob_bytes(object_id: str) -> bytes:
    if not _SHA1.fullmatch(str(object_id)):
        raise ProtocolError("Git blob id is malformed")
    result = subprocess.run(
        ["git", "cat-file", "blob", object_id], cwd=ROOT, capture_output=True,
    )
    if result.returncode:
        raise ProtocolError("cannot read registered Git blob")
    return result.stdout


def _normalized_source_sha256(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeDecodeError) as error:
        raise ProtocolError(f"cannot read source {path}") from error
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _verify_source_bindings(registration: dict) -> str:
    implementation = registration["candidate"]["implementation_commit"]
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", implementation, "HEAD"], cwd=ROOT
    )
    if ancestor.returncode:
        raise ProtocolError("final implementation commit is not an ancestor of HEAD")
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{implementation}..HEAD"],
        cwd=ROOT, capture_output=True, text=True,
    )
    allowed = {"tests/test_prospect_v23_development.py"}
    if changed.returncode or any(
        (path := raw.replace("\\", "/")) not in allowed
        and path.lower().endswith((".py", ".pyi", ".pyc", ".pyo", ".pyd", ".so"))
        for raw in changed.stdout.splitlines()
    ):
        raise ProtocolError("post-implementation code changed")
    for relative, binding in registration["sources"].items():
        expected = binding["git_blob"]
        if (
            _git_blob_at(implementation, relative) != expected
            or _git_blob_at("HEAD", relative) != expected
            or _git_blob(relative, ROOT / relative) != expected
            or _normalized_source_sha256(ROOT / relative) != binding["normalized_sha256"]
        ):
            raise ProtocolError(f"source binding changed: {relative}")
    return implementation


def _verify_predecessor_bindings(registration: dict, implementation: str) -> None:
    object_ids = _git_object_ids(implementation)
    object_digest = canonical_sha256(object_ids)
    for name in ("plan_031", "plan_034"):
        row = registration["predecessors"][name]
        relative = row["plan_path"]
        before = _git_blob_bytes(row["pre_transition_blob"])
        try:
            current = (ROOT / relative).read_bytes()
        except OSError as error:
            raise ProtocolError(f"cannot read predecessor plan: {relative}") from error
        if (
            _git_blob_at(implementation, relative) != row["pre_transition_blob"]
            or len(before) != row["append_only_prefix_bytes"]
            or not current.startswith(before)
            or _git_blob(relative, ROOT / relative) != row["post_transition_blob"]
            or _git_blob_at("HEAD", relative) != row["post_transition_blob"]
        ):
            raise ProtocolError(f"predecessor plan binding changed: {relative}")
        evidence = row["history_evidence"]
        inventory, _structured = _git_blob_inventory(
            implementation, row["held_seed"]
        )
        classifications = evidence["classifications"]
        classified_keys = sorted([
            [
                item["object_id"], item["path"], item["byte_offset"],
                item["line_sha256"],
            ]
            for item in classifications
        ])
        if (
            evidence["object_count"] != len(object_ids)
            or evidence["sorted_object_ids_sha256"] != object_digest
            or evidence["inventory_entry_count"] != len(inventory)
            or evidence["inventory_sha256"] != canonical_sha256(inventory)
            or classified_keys != inventory
            or any(
                item["classification"] in {"result_artifact", "runner_invocation"}
                for item in classifications
            )
        ):
            raise ProtocolError(f"predecessor history evidence changed: {name}")
    index = registration["predecessors"]["plan_index"]
    relative = index["plan_path"]
    if (
        _git_blob_at(implementation, relative) != index["pre_transition_blob"]
        or _git_blob_at("HEAD", relative) != index["post_transition_blob"]
        or _git_blob(relative, ROOT / relative) != index["post_transition_blob"]
    ):
        raise ProtocolError("plan index binding changed")


def _verify_seed_hygiene(registration: dict, implementation: str) -> None:
    # ponytail: bind reviewed rows; add a registered parser only if seed-set syntax is standardized.
    hygiene = registration["bootstrap"]["seed_hygiene"]
    pre_design = hygiene["pre_design"]
    object_ids = _git_object_ids(hygiene["pre_design_tip"])
    if (
        pre_design["object_count"] != len(object_ids)
        or pre_design["sorted_object_ids_sha256"] != canonical_sha256(object_ids)
        or pre_design["match_count"] != 0
    ):
        raise ProtocolError("pre-design seed-hygiene evidence changed")
    inventory, structured = _git_blob_inventory(
        implementation, hygiene["token"], exclude_tip=hygiene["pre_design_tip"]
    )
    post_design = hygiene["post_design"]
    if (
        post_design["entry_count"] != len(inventory)
        or post_design["inventory_sha256"] != canonical_sha256(inventory)
        or any(row[1] not in post_design["allowed_paths"] for row in inventory)
        or post_design["unexpected_path_count"] != 0
        or hygiene["structured_seed_fields"]["inventory_sha256"]
        != canonical_sha256(structured)
        or hygiene["structured_seed_fields"]["pre_design_match_count"] != 0
        or hygiene["structured_seed_fields"][
            "forbidden_held_spent_reserved_membership"
        ] is not False
    ):
        raise ProtocolError("post-design seed-hygiene evidence changed")
    current, _structured = _git_blob_inventory(
        "HEAD", hygiene["token"], exclude_tip=implementation
    )
    if any(
        row[1] not in hygiene["post_registration_policy"]["allowed_paths"]
        and tuple(row) not in _REVIEWED_POST_REGISTRATION_SEED_ROWS
        for row in current
    ):
        raise ProtocolError("post-registration seed occurrence escaped allowlist")


def _verify_dynamic_registration(registration: dict) -> None:
    implementation = _verify_source_bindings(registration)
    _verify_predecessor_bindings(registration, implementation)
    _verify_seed_hygiene(registration, implementation)


def _registration_static_view(payload: dict) -> tuple[dict, dict]:
    static = deepcopy(payload)
    try:
        implementation = static["candidate"]["implementation_commit"]
        static["candidate"]["implementation_commit"] = None
        sources = payload["sources"]
        static["sources"] = {
            path: {key: None for key in binding}
            for path, binding in sources.items()
        }
        predecessors = {}
        for name in ("plan_031", "plan_034"):
            row = static["predecessors"][name]
            evidence = payload["predecessors"][name]["history_evidence"]
            predecessors[name] = payload["predecessors"][name]
            row["pre_transition_blob"] = None
            row["post_transition_blob"] = None
            row["append_only_prefix_bytes"] = None
            row["history_evidence"] = {key: None for key in evidence}
        index = static["predecessors"]["plan_index"]
        predecessors["plan_index"] = payload["predecessors"]["plan_index"]
        index["pre_transition_blob"] = None
        index["post_transition_blob"] = None
        hygiene = static["bootstrap"]["seed_hygiene"]
        pre_design = hygiene["pre_design"]
        post_design = hygiene["post_design"]
        structured = hygiene["structured_seed_fields"]
        for key in ("object_count", "sorted_object_ids_sha256", "match_count"):
            pre_design[key] = None
        for key in (
            "scope_tip", "entry_count", "inventory_sha256", "unexpected_path_count",
        ):
            post_design[key] = None
        for key in (
            "inventory_sha256", "pre_design_match_count",
            "forbidden_held_spent_reserved_membership",
        ):
            structured[key] = None
        static["artifact_sha256"] = None
    except (KeyError, TypeError, AttributeError):
        raise ProtocolError("registration dynamic structure is invalid") from None
    return static, {
        "implementation": implementation,
        "sources": sources,
        "predecessors": predecessors,
        "seed_hygiene": payload["bootstrap"]["seed_hygiene"],
    }


def _validate_dynamic_fields(dynamic: dict) -> None:
    implementation = dynamic["implementation"]
    if not _SHA1.fullmatch(str(implementation)):
        raise ProtocolError("registration implementation commit is invalid")
    sources = dynamic["sources"]
    if not isinstance(sources, dict) or not sources:
        raise ProtocolError("registration source bindings are invalid")
    for relative, binding in sources.items():
        if (
            not isinstance(relative, str)
            or not isinstance(binding, dict)
            or set(binding) != _REGISTRATION_CONTRACT["source_binding_keys"]
            or not _SHA1.fullmatch(str(binding.get("git_blob")))
            or not _SHA256.fullmatch(str(binding.get("normalized_sha256")))
        ):
            raise ProtocolError("registration source bindings are invalid")
    for name in ("plan_031", "plan_034"):
        row = dynamic["predecessors"][name]
        if not isinstance(row, dict):
            raise ProtocolError("registration predecessor evidence is invalid")
        for key in ("pre_transition_blob", "post_transition_blob"):
            if not _SHA1.fullmatch(str(row.get(key))):
                raise ProtocolError("registration predecessor evidence is invalid")
        prefix = row.get("append_only_prefix_bytes")
        evidence = row.get("history_evidence")
        if (
            not isinstance(prefix, int)
            or isinstance(prefix, bool)
            or prefix <= 0
            or not isinstance(evidence, dict)
            or set(evidence) != _REGISTRATION_CONTRACT["history_evidence_keys"]
            or evidence.get("scope_tip") != implementation
            or evidence.get("standalone_pattern")
            != rf"(^|[^0-9]){row.get('held_seed')}([^0-9]|$)"
            or evidence.get("inventory_schema") != "git_blob_path_offset_v1"
            or evidence.get("classification_schema")
            != "git_blob_path_offset_line_sha256_classification_v1"
            or not isinstance(evidence.get("object_count"), int)
            or isinstance(evidence.get("object_count"), bool)
            or evidence["object_count"] <= 0
            or not _SHA256.fullmatch(str(evidence.get("sorted_object_ids_sha256")))
            or not isinstance(evidence.get("inventory_entry_count"), int)
            or isinstance(evidence.get("inventory_entry_count"), bool)
            or evidence["inventory_entry_count"] < 0
            or not _SHA256.fullmatch(str(evidence.get("inventory_sha256")))
        ):
            raise ProtocolError("registration predecessor evidence is invalid")
        classifications = evidence.get("classifications")
        if not isinstance(classifications, list) or any(
            not isinstance(item, dict)
            or set(item) != _REGISTRATION_CONTRACT["classification_keys"]
            or not _SHA1.fullmatch(str(item.get("object_id")))
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("byte_offset"), int)
            or isinstance(item.get("byte_offset"), bool)
            or item["byte_offset"] < 0
            or not _SHA256.fullmatch(str(item.get("line_sha256")))
            or not isinstance(item.get("classification"), str)
            or not item["classification"]
            for item in classifications
        ):
            raise ProtocolError("registration predecessor classifications are invalid")
        if (
            evidence["inventory_entry_count"] != len(classifications)
            or not _SHA256.fullmatch(str(evidence.get("classification_sha256")))
            or evidence["classification_sha256"] != canonical_sha256(classifications)
            or evidence.get("result_artifact_entries") != []
            or evidence.get("runner_invocation_entries") != []
            or any(
                item["classification"] in {"result_artifact", "runner_invocation"}
                for item in classifications
            )
        ):
            raise ProtocolError("registration predecessor classifications are invalid")
    index = dynamic["predecessors"].get("plan_index")
    if (
        not isinstance(index, dict)
        or set(index) != {
            "plan_path", "transition", "pre_transition_blob", "post_transition_blob",
        }
        or index.get("plan_path") != "plans/README.md"
        or index.get("transition")
        != "update_plan_031_plan_034_model_track_status_and_add_plan_038"
        or not _SHA1.fullmatch(str(index.get("pre_transition_blob")))
        or not _SHA1.fullmatch(str(index.get("post_transition_blob")))
    ):
        raise ProtocolError("registration plan index evidence is invalid")
    hygiene = dynamic["seed_hygiene"]
    try:
        pre_design = hygiene["pre_design"]
        post_design = hygiene["post_design"]
        structured = hygiene["structured_seed_fields"]
        valid = (
            isinstance(pre_design["object_count"], int)
            and not isinstance(pre_design["object_count"], bool)
            and pre_design["object_count"] > 0
            and _SHA256.fullmatch(str(pre_design["sorted_object_ids_sha256"]))
            and type(pre_design["match_count"]) is int
            and pre_design["match_count"] == 0
            and post_design["scope_tip"] == implementation
            and isinstance(post_design["entry_count"], int)
            and not isinstance(post_design["entry_count"], bool)
            and post_design["entry_count"] >= 0
            and _SHA256.fullmatch(str(post_design["inventory_sha256"]))
            and type(post_design["unexpected_path_count"]) is int
            and post_design["unexpected_path_count"] == 0
            and _SHA256.fullmatch(str(structured["inventory_sha256"]))
            and type(structured["pre_design_match_count"]) is int
            and structured["pre_design_match_count"] == 0
            and structured["forbidden_held_spent_reserved_membership"] is False
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise ProtocolError("registration seed-hygiene evidence is invalid")


def _registration(registration: object) -> dict:
    payload = _require_seal(registration, "registration")
    static, dynamic = _registration_static_view(payload)
    _validate_dynamic_fields(dynamic)
    if payload.get("runtime") != _runtime_tuple():
        raise ProtocolError("runtime does not match registration")
    if canonical_sha256(static) != _REGISTRATION_CONTRACT["static_sha256"]:
        raise ProtocolError("registration does not exactly match Plan 038")
    return payload


def _approved_sha(expected: str | None = None) -> str:
    value = os.environ.get("VALUCAST_V23_APPROVED_EXECUTION_SHA", "")
    if not _SHA1.fullmatch(value):
        raise ProtocolError("approved execution SHA is missing or malformed")
    if value != _head() or (expected is not None and value != expected):
        raise ProtocolError("approved execution SHA does not match execution")
    return value


def _pre_marker(registration: dict, execution_sha: str, *, receipt: dict | None = None) -> None:
    if _spend_path().exists():
        raise ProtocolError("immutable spend token already exists")
    if CALIBRATOR_PATH.exists() or (receipt is None and RECEIPT_PATH.exists()):
        raise ProtocolError("canonical output already exists")
    if receipt is not None:
        _validate_receipt(receipt)
        if receipt["status"] != "reserved" or receipt["execution_sha"] != execution_sha:
            raise ProtocolError("receipt is not resumable for this execution SHA")
        if receipt.get("registration_sha256") != registration["artifact_sha256"] or receipt.get("runtime") != _runtime_tuple() or receipt.get("execution_worktree") != str(ROOT.resolve()):
            raise ProtocolError("receipt registration does not match")
    _verify_dynamic_registration(registration)
    for relative, binding in registration["inputs"].items():
        if _git_blob(relative, ROOT / relative) != binding["git_blob"]:
            raise ProtocolError(f"input Git blob changed: {relative}")


def _receipt(registration: dict, execution_sha: str, status: str, stage: str, **extra) -> dict:
    terminal = status in _TERMINAL
    if status not in {"reserved", "outcome_access_spent", *_TERMINAL}:
        raise ProtocolError("unknown receipt status")
    exit_code = {"qualified": 0, "failed": 1, "spent_error": 2}.get(status)
    qualified = True if status == "qualified" else False if terminal else None
    return _sealed({
        "schema": "valucast_prospect_rank_v2_3_development_v1",
        "registration_id": registration["registration_id"],
        "registration_sha256": registration["artifact_sha256"],
        "execution_sha": execution_sha,
        "execution_worktree": str(ROOT.resolve()),
        "runtime": _runtime_tuple(),
        "status": status, "stage": stage,
        "development_qualified": qualified, "cli_exit_code": exit_code,
        "feeds_live_rank": False, "feeds_value": False,
        **extra,
    })


def _validate_receipt(receipt: object) -> dict:
    payload = _require_seal(receipt, "receipt")
    required = {
        "schema", "registration_id", "registration_sha256", "execution_sha", "execution_worktree",
        "runtime", "status", "stage", "development_qualified", "cli_exit_code",
        "feeds_live_rank", "feeds_value", "artifact_sha256",
    }
    if not required <= set(payload) or payload.get("schema") != "valucast_prospect_rank_v2_3_development_v1":
        raise ProtocolError("receipt schema is invalid")
    status = payload.get("status")
    if status not in {"reserved", "outcome_access_spent", *_TERMINAL} or not _SHA1.fullmatch(str(payload.get("execution_sha"))):
        raise ProtocolError("receipt state is invalid")
    if payload.get("feeds_live_rank") is not False or payload.get("feeds_value") is not False:
        raise ProtocolError("receipt must be non-serving")
    terminal = status in _TERMINAL
    expected_fields = set(required)
    if status in {"qualified", "failed"}:
        expected_fields.update({"spend_token_sha256", "result", "map_artifact_sha256"})
    elif status == "spent_error":
        expected_fields.update({"spend_token_sha256", "result", "error"})
    elif status == "outcome_access_spent":
        expected_fields.add("spend_token_sha256")
    if set(payload) != expected_fields:
        raise ProtocolError("receipt fields are invalid")
    stages = {
        "reserved": {"reserved"}, "outcome_access_spent": {"outcome_access_spent"},
        "qualified": {"completed"}, "failed": {"completed"},
        "spent_error": {"post_marker", "interrupted_spend"},
    }
    if payload.get("registration_id") != "plan_038_prospect_vnext_phase_a" or not _SHA256.fullmatch(str(payload.get("registration_sha256"))) or not isinstance(payload.get("execution_worktree"), str) or not Path(payload["execution_worktree"]).is_absolute() or not isinstance(payload.get("runtime"), dict) or payload.get("stage") not in stages[status]:
        raise ProtocolError("receipt bindings or stage are invalid")
    if terminal:
        expected_exit = {"qualified": 0, "failed": 1, "spent_error": 2}[status]
        expected_qualified = status == "qualified"
        if payload.get("cli_exit_code") != expected_exit or payload.get("development_qualified") is not expected_qualified:
            raise ProtocolError("terminal receipt exit or qualification is invalid")
    elif payload.get("cli_exit_code") is not None or payload.get("development_qualified") is not None:
        raise ProtocolError("non-terminal receipt has a result")
    if status == "qualified" and (not _SHA256.fullmatch(str(payload["spend_token_sha256"])) or not _SHA256.fullmatch(str(payload["map_artifact_sha256"]))):
        raise ProtocolError("qualified receipt hashes are invalid")
    if status in {"failed", "spent_error", "outcome_access_spent"} and not _SHA256.fullmatch(str(payload["spend_token_sha256"])):
        raise ProtocolError("receipt spend-token hash is invalid")
    if status == "failed" and payload["map_artifact_sha256"] is not None:
        raise ProtocolError("failed receipt must not bind a map")
    if status in {"qualified", "failed"}:
        _validate_result(payload["result"], qualified=status == "qualified", map_sha=payload["map_artifact_sha256"])
    if status == "spent_error" and (payload["result"] is not None or not isinstance(payload["error"], dict) or set(payload["error"]) != {"stage", "type", "message"} or not all(isinstance(payload["error"][key], str) for key in ("stage", "type", "message")) or payload["error"]["stage"] != payload["stage"]):
        raise ProtocolError("spent error receipt payload is invalid")
    return payload


def _validate_result(result: object, *, qualified: bool, map_sha: object) -> None:
    if not isinstance(result, dict) or set(result) != {
        "fold_order", "folds", "bootstrap", "failed_folds", "failed_bootstrap",
        "failed_structural", "pooled_fit",
    } or result.get("fold_order") != list(DEVELOPMENT_FOLDS):
        raise ProtocolError("completed receipt result is invalid")
    folds = result["folds"]
    if not isinstance(folds, dict) or set(folds) != {str(year) for year in DEVELOPMENT_FOLDS}:
        raise ProtocolError("completed receipt result folds are invalid")
    fold_keys = {
        "status", "failure_stage", "identity_count_by_role", "identity_sha256_by_role",
        "target_sha256", "metrics", "gates", "structural_checks", "failed_gates",
        "failed_structural",
    }
    metric_keys = {
        "candidate_mae", "control_mae", "candidate_control_mae_delta",
        "candidate_concordance", "control_concordance", "product_concordance",
        "candidate_control_concordance_delta", "candidate_product_concordance_delta",
        "candidate_top25_target_sum", "control_top25_target_sum", "product_top25_target_sum",
    }
    check_keys = {
        "identity_sets_equal", "targets_equal", "candidate_map_valid", "control_map_valid",
        "product_rank_reproduced", "top25_complete",
    }
    def finite(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def hash_string(value: object) -> bool:
        return isinstance(value, str) and bool(_SHA256.fullmatch(value))

    def valid_provenance(fold: dict, *, required: bool, stage: str | None = None) -> bool:
        counts, hashes, target = (fold["identity_count_by_role"], fold["identity_sha256_by_role"], fold["target_sha256"])
        if required and (counts is None or hashes is None or target is None):
            return False
        if (counts is None) != (hashes is None):
            return False
        if counts is None:
            return not required and stage == "identity_alignment" and target is None
        if not (isinstance(counts, dict) and set(counts) == set(ROLES) and all(type(value) is int and value > 0 for value in counts.values())):
            return False
        if not (isinstance(hashes, dict) and set(hashes) == set(ROLES) and all(hash_string(value) for value in hashes.values())):
            return False
        return hash_string(target) if required or stage in STRUCTURAL_STAGES[2:] else target is None or hash_string(target)

    structural_checks = (
        ("identity_sets_equal", "identity_alignment"),
        ("targets_equal", "target_alignment"),
        ("candidate_map_valid", "candidate_map"),
        ("control_map_valid", "control_map"),
        ("product_rank_reproduced", "product_reconstruction"),
        (None, "metric_contract"),
        ("top25_complete", "top25_contract"),
    )
    upstream_metric_names = (
        "candidate_mae", "control_mae", "candidate_control_mae_delta",
        "candidate_concordance", "control_concordance", "product_concordance",
        "candidate_control_concordance_delta", "candidate_product_concordance_delta",
    )
    top_metric_names = (
        "candidate_top25_target_sum", "control_top25_target_sum", "product_top25_target_sum",
    )
    for fold in folds.values():
        if not isinstance(fold, dict) or set(fold) != fold_keys or fold.get("status") not in {"completed", "structural_failure"} or not isinstance(fold.get("metrics"), dict) or set(fold["metrics"]) != metric_keys or not isinstance(fold.get("gates"), dict) or set(fold["gates"]) != set(FOLD_GATE_ORDER) or not isinstance(fold.get("structural_checks"), dict) or set(fold["structural_checks"]) != check_keys or not isinstance(fold.get("failed_gates"), list) or not isinstance(fold.get("failed_structural"), list):
            raise ProtocolError("completed receipt fold schema is invalid")
        if fold["status"] == "completed":
            metrics = fold["metrics"]
            if (
                fold["failure_stage"] is not None
                or fold["failed_structural"]
                or not valid_provenance(fold, required=True)
                or any(not finite(value) for value in metrics.values())
            ):
                raise ProtocolError("completed receipt fold state is invalid")
            expected_gates = {
                **_upstream_gates(metrics),
                "candidate_control_top25": metrics["candidate_top25_target_sum"] >= metrics["control_top25_target_sum"],
                "candidate_product_top25": metrics["candidate_top25_target_sum"] >= metrics["product_top25_target_sum"],
            }
            if (
                metrics["candidate_control_mae_delta"] != metrics["candidate_mae"] - metrics["control_mae"]
                or metrics["candidate_control_concordance_delta"] != metrics["candidate_concordance"] - metrics["control_concordance"]
                or metrics["candidate_product_concordance_delta"] != metrics["candidate_concordance"] - metrics["product_concordance"]
                or fold["gates"] != expected_gates
                or fold["failed_gates"] != [name for name in FOLD_GATE_ORDER if not expected_gates[name]]
                or any(value is not True for value in fold["structural_checks"].values())
            ):
                raise ProtocolError("completed receipt fold state is invalid")
        else:
            stage = fold["failure_stage"]
            if stage not in STRUCTURAL_STAGES or fold["failed_structural"] != [stage] or not valid_provenance(fold, required=False, stage=stage):
                raise ProtocolError("completed receipt structural fold state is invalid")
            stage_index = STRUCTURAL_STAGES.index(stage)
            expected_checks = {}
            for check, check_stage in structural_checks:
                if check is None:
                    continue
                index = STRUCTURAL_STAGES.index(check_stage)
                expected_checks[check] = None if check is None else (False if index == stage_index else True if index < stage_index else None)
            if stage == "identity_alignment" and fold["structural_checks"]["targets_equal"] is True:
                if not valid_provenance(fold, required=True):
                    raise ProtocolError("completed receipt structural fold state is invalid")
                expected_checks["targets_equal"] = True
            if fold["structural_checks"] != expected_checks:
                raise ProtocolError("completed receipt structural fold state is invalid")
            if stage == "top25_contract":
                metrics = fold["metrics"]
                if (
                    any(not finite(metrics[name]) for name in upstream_metric_names)
                    or any(metrics[name] is not None for name in top_metric_names)
                    or metrics["candidate_control_mae_delta"] != metrics["candidate_mae"] - metrics["control_mae"]
                    or metrics["candidate_control_concordance_delta"] != metrics["candidate_concordance"] - metrics["control_concordance"]
                    or metrics["candidate_product_concordance_delta"] != metrics["candidate_concordance"] - metrics["product_concordance"]
                ):
                    raise ProtocolError("completed receipt structural fold state is invalid")
                expected_gates = _upstream_gates(metrics)
                if (
                    any(fold["gates"][name] != expected_gates[name] for name in expected_gates)
                    or any(fold["gates"][name] is not None for name in FOLD_GATE_ORDER[4:])
                ):
                    raise ProtocolError("completed receipt structural fold state is invalid")
            elif any(value is not None for value in fold["metrics"].values()) or any(value is not None for value in fold["gates"].values()):
                raise ProtocolError("completed receipt structural fold state is invalid")
            if fold["failed_gates"] != [name for name in FOLD_GATE_ORDER if fold["gates"][name] is False]:
                raise ProtocolError("completed receipt structural fold state is invalid")
    bootstrap = result["bootstrap"]
    bootstrap_keys = {"status", "seed", "replicates", "minimum_valid_replicates", "interval", "sample_plan_sha256", "metrics"}
    if not isinstance(bootstrap, dict) or set(bootstrap) != bootstrap_keys or bootstrap.get("status") not in {"completed", "not_attempted_fold_failure"} or bootstrap.get("seed") != 39017 or bootstrap.get("replicates") != 10_000 or bootstrap.get("minimum_valid_replicates") != BOOTSTRAP_MINIMUM or bootstrap.get("interval") != {"lower_percentile": 2.5, "upper_percentile": 97.5, "method": "linear"} or not isinstance(bootstrap.get("metrics"), dict) or set(bootstrap["metrics"]) != set(BOOTSTRAP_METRICS):
        raise ProtocolError("completed receipt bootstrap schema is invalid")
    metric_keys = {"point", "lower", "upper", "valid_replicates", "gate_passed"}
    for metric in bootstrap["metrics"].values():
        if not isinstance(metric, dict) or set(metric) != metric_keys:
            raise ProtocolError("completed receipt bootstrap metric schema is invalid")
    all_completed = all(fold["status"] == "completed" for fold in folds.values())
    if bootstrap["status"] == "completed":
        if not all_completed or not hash_string(bootstrap["sample_plan_sha256"]):
            raise ProtocolError("completed receipt bootstrap state is invalid")
        for name, metric in bootstrap["metrics"].items():
            valid = metric["valid_replicates"]
            if type(metric["gate_passed"]) is not bool or type(valid) is not int or not 0 <= valid <= bootstrap["replicates"] or not finite(metric["point"]):
                raise ProtocolError("completed receipt bootstrap state is invalid")
            lower, upper = metric["lower"], metric["upper"]
            if valid:
                if not finite(lower) or not finite(upper) or lower > upper:
                    raise ProtocolError("completed receipt bootstrap state is invalid")
                gate = upper < 0 if name == "candidate_control_mae_delta" else lower > 0
            elif lower is not None or upper is not None:
                raise ProtocolError("completed receipt bootstrap state is invalid")
            else:
                gate = False
            point = 0.0
            for year in DEVELOPMENT_FOLDS:
                point += folds[str(year)]["metrics"][name] / len(DEVELOPMENT_FOLDS)
            if metric["point"] != point or metric["gate_passed"] != (valid >= BOOTSTRAP_MINIMUM and gate):
                raise ProtocolError("completed receipt bootstrap state is invalid")
    elif all_completed or bootstrap != _not_attempted_bootstrap():
        raise ProtocolError("not-attempted bootstrap state is invalid")
    pooled = result["pooled_fit"]
    if not isinstance(pooled, dict) or set(pooled) != {"attempted", "status", "row_count", "training_rows_sha256", "map_artifact_sha256"} or pooled.get("status") not in {"not_attempted_qualification_failure", "failed", "validated"}:
        raise ProtocolError("completed receipt pooled-fit schema is invalid")
    failed_folds = [
        year for year in DEVELOPMENT_FOLDS
        if folds[str(year)]["status"] != "completed" or folds[str(year)]["failed_gates"]
    ]
    failed_bootstrap = [
        name for name in BOOTSTRAP_METRICS
        if bootstrap["status"] == "completed" and not bootstrap["metrics"][name]["gate_passed"]
    ]
    failed_structural = [
        f"{year}:{stage}" for year in DEVELOPMENT_FOLDS for stage in folds[str(year)]["failed_structural"]
    ]
    eligible_for_pooled_fit = not failed_folds and not failed_bootstrap
    if not isinstance(pooled["attempted"], bool) or type(pooled["row_count"]) is not int:
        raise ProtocolError("completed receipt pooled-fit state is invalid")
    if not eligible_for_pooled_fit:
        expected_pooled = {"attempted": False, "status": "not_attempted_qualification_failure", "row_count": 0, "training_rows_sha256": None, "map_artifact_sha256": None}
        if pooled != expected_pooled:
            raise ProtocolError("completed receipt pooled-fit state is invalid")
    elif pooled["status"] == "failed":
        if not pooled["attempted"] or pooled["row_count"] <= 0 or not hash_string(pooled["training_rows_sha256"]) or pooled["map_artifact_sha256"] is not None:
            raise ProtocolError("completed receipt pooled-fit state is invalid")
        failed_structural.append("pooled_final_fit")
    elif pooled["status"] == "validated":
        if not pooled["attempted"] or pooled["row_count"] <= 0 or not hash_string(pooled["training_rows_sha256"]) or not hash_string(pooled["map_artifact_sha256"]):
            raise ProtocolError("completed receipt pooled-fit state is invalid")
    else:
        raise ProtocolError("completed receipt pooled-fit state is invalid")
    if result["failed_folds"] != failed_folds or result["failed_bootstrap"] != failed_bootstrap or result["failed_structural"] != failed_structural:
        raise ProtocolError("completed receipt failure lists are invalid")
    qualified_result = not failed_folds and not failed_bootstrap and not failed_structural and pooled["status"] == "validated"
    if qualified != qualified_result or (qualified and (pooled["map_artifact_sha256"] != map_sha or not _SHA256.fullmatch(str(map_sha)))) or (not qualified and map_sha is not None):
        raise ProtocolError("terminal receipt result is invalid")


def _atomic_json(path: Path, payload: dict, *, expected_state: str | None | object = ... ) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_state is None and path.exists():
            raise ProtocolError("expected absent receipt already exists")
        if expected_state is not ... and expected_state is not None:
            if not path.exists() or _validate_receipt(_load_json(path, outcome=True)).get("status") != expected_state:
                raise ProtocolError("prior durable receipt state does not match")
        os.replace(temporary, path)
        temporary = None
        try:
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _token(registration: dict, execution_sha: str) -> dict:
    return _sealed({
        "schema": "valucast_prospect_rank_v2_3_spend_v1",
        "registration_id": registration["registration_id"],
        "registration_sha256": registration["artifact_sha256"],
        "execution_sha": execution_sha,
        "execution_worktree": str(ROOT.resolve()),
        "runtime": _runtime_tuple(),
    })


def _publish_token(token: dict) -> str:
    path = _spend_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(token, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        # link is an atomic create: unlike replace it can never weaken an existing
        # immutable token, and the repository-common lock serializes cooperating runs.
        os.link(temporary, path)
    except FileExistsError as error:
        raise ProtocolError("immutable spend token already exists") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
    try:
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass
    return hashlib.sha256(encoded).hexdigest()


def _internal_value(payload: dict, dotted: str) -> object:
    value: object = payload
    for key in dotted.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ProtocolError(f"registered internal field is absent: {dotted}")
        value = value[key]
    return value


def _outcomes(registration: dict) -> tuple[dict, dict, dict, dict]:
    """Open each frozen payload once, only after the durable receipt marker."""
    payloads = {}
    for relative, binding in registration["inputs"].items():
        payload = _load_json(ROOT / relative, outcome=True)
        if canonical_sha256(payload) != binding["canonical_sha256"]:
            raise ProtocolError(f"canonical payload hash changed: {relative}")
        if _internal_value(payload, binding["internal_field"]) != binding["internal_sha256"]:
            raise ProtocolError(f"internal receipt hash changed: {relative}")
        payloads[relative] = payload
    contract = payloads[CANONICAL_READ_PATHS[1]]
    errors = validate_development_contract(contract)
    if errors != []:
        raise ProtocolError(f"development contract is invalid: {errors[0]}")
    for relative in CANONICAL_READ_PATHS[3:]:
        predecessor = payloads[relative]
        if predecessor.get("status") not in _TERMINAL or predecessor.get("feeds_live_rank") is not False or predecessor.get("feeds_value") is not False:
            raise ProtocolError(f"predecessor is not terminal/non-serving: {relative}")
    return (
        contract,
        payloads[CANONICAL_READ_PATHS[2]],
        payloads[CANONICAL_READ_PATHS[3]],
        payloads[CANONICAL_READ_PATHS[4]],
    )


def _terminal_failure(registration: dict, execution_sha: str, stage: str, error: BaseException, token_sha: str | None) -> int:
    receipt = _receipt(
        registration, execution_sha, "spent_error", stage,
        spend_token_sha256=token_sha,
        result=None,
        error={"stage": stage, "type": type(error).__name__, "message": str(error)},
    )
    _atomic_json(RECEIPT_PATH, receipt, expected_state="outcome_access_spent")
    return 2


def _spend_and_evaluate(registration: dict, execution_sha: str) -> int:
    token_sha = _publish_token(_token(registration, execution_sha))
    spent = _receipt(
        registration, execution_sha, "outcome_access_spent", "outcome_access_spent",
        spend_token_sha256=token_sha,
    )
    _atomic_json(RECEIPT_PATH, spent, expected_state="reserved")
    try:
        contract, model, _v21, _v22 = _outcomes(registration)
        result, pooled_map = build_development_artifacts(contract, model, registration)
        qualified = bool(pooled_map) and not result.get("failed_folds") and not result.get("failed_bootstrap") and not result.get("failed_structural")
        if qualified:
            if not isinstance(pooled_map, dict):
                raise ProtocolError("qualified result is missing its pooled map")
            _require_seal(pooled_map, "pooled map")
            _atomic_json(CALIBRATOR_PATH, pooled_map, expected_state=...)
            terminal = _receipt(
                registration, execution_sha, "qualified", "completed",
                spend_token_sha256=token_sha, result=result,
                map_artifact_sha256=pooled_map["artifact_sha256"],
            )
            _atomic_json(RECEIPT_PATH, terminal, expected_state="outcome_access_spent")
            return 0
        terminal = _receipt(
            registration, execution_sha, "failed", "completed",
            spend_token_sha256=token_sha, result=result, map_artifact_sha256=None,
        )
        _atomic_json(RECEIPT_PATH, terminal, expected_state="outcome_access_spent")
        return 1
    except BaseException as error:
        return _terminal_failure(registration, execution_sha, "post_marker", error, token_sha)


def _read_registration() -> dict:
    if not REGISTRATION_PATH.is_file():
        raise ProtocolError("canonical registration is absent")
    return _registration(_load_json(REGISTRATION_PATH))


def _normal() -> int:
    registration = _read_registration()
    execution_sha = _approved_sha()
    _pre_marker(registration, execution_sha)
    _atomic_json(
        RECEIPT_PATH,
        _receipt(registration, execution_sha, "reserved", "reserved"),
        expected_state=None,
    )
    return _spend_and_evaluate(registration, execution_sha)


def _resume() -> int:
    registration = _read_registration()
    if not RECEIPT_PATH.is_file():
        raise ProtocolError("reserved receipt is absent")
    receipt = _validate_receipt(_load_json(RECEIPT_PATH, outcome=True))
    execution_sha = _approved_sha(receipt.get("execution_sha"))
    _pre_marker(registration, execution_sha, receipt=receipt)
    return _spend_and_evaluate(registration, execution_sha)


def _read_token() -> dict:
    path = _spend_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError("immutable spend token is unreadable") from error
    token = _require_seal(payload, "spend token")
    if set(token) != {
        "schema", "registration_id", "registration_sha256", "execution_sha",
        "execution_worktree", "runtime", "artifact_sha256",
    } or token.get("schema") != "valucast_prospect_rank_v2_3_spend_v1" or not _SHA1.fullmatch(str(token.get("execution_sha"))) or not _SHA256.fullmatch(str(token.get("registration_sha256"))) or not isinstance(token.get("execution_worktree"), str) or not isinstance(token.get("runtime"), dict):
        raise ProtocolError("spend token binding is invalid")
    return token


def _seal_interrupted() -> int:
    registration = _read_registration()
    token = _read_token()
    if not RECEIPT_PATH.is_file():
        raise ProtocolError("bound execution receipt is absent")
    receipt = _validate_receipt(_load_json(RECEIPT_PATH, outcome=True))
    execution_sha = _approved_sha(token.get("execution_sha"))
    token_sha = hashlib.sha256(_spend_path().read_bytes()).hexdigest()
    if token.get("registration_id") != registration["registration_id"] or token.get("registration_sha256") != registration["artifact_sha256"] or token.get("runtime") != _runtime_tuple() or token.get("execution_worktree") != str(ROOT.resolve()) or receipt.get("registration_id") != token.get("registration_id") or receipt.get("registration_sha256") != token.get("registration_sha256") or receipt.get("execution_sha") != execution_sha or receipt.get("execution_worktree") != token.get("execution_worktree") or receipt.get("runtime") != token.get("runtime") or receipt.get("status") not in {"reserved", "outcome_access_spent"} or (receipt["status"] == "outcome_access_spent" and receipt.get("spend_token_sha256") != token_sha):
        raise ProtocolError("interrupted spend binding does not match")
    terminal = _receipt(
        registration, execution_sha, "spent_error", "interrupted_spend",
        spend_token_sha256=token_sha, result=None,
        error={"stage": "interrupted_spend", "type": "InterruptedSpend", "message": "sealed without reopening outcomes"},
    )
    _atomic_json(RECEIPT_PATH, terminal, expected_state=receipt["status"])
    return 2


def _reproduce() -> int:
    if not RECEIPT_PATH.is_file():
        raise ProtocolError("terminal receipt is absent")
    receipt = _validate_receipt(_load_json(RECEIPT_PATH, outcome=True))
    if receipt["status"] not in {"qualified", "failed"}:
        raise ProtocolError("only completed scientific receipts reproduce")
    registration = _read_registration()
    if receipt.get("registration_id") != registration["registration_id"] or receipt.get("registration_sha256") != registration["artifact_sha256"]:
        raise ProtocolError("terminal receipt registration does not match")
    _pre_marker_for_reproduction(registration, receipt)
    contract, model, _v21, _v22 = _outcomes(registration)
    result, pooled_map = build_development_artifacts(contract, model, registration)
    if receipt.get("result") != result:
        raise ProtocolError("reproduction result is not byte/payload exact")
    if receipt["status"] == "qualified":
        if not isinstance(pooled_map, dict) or not CALIBRATOR_PATH.is_file():
            raise ProtocolError("reproduction pooled map is not byte/payload exact")
        disk_map = _load_json(CALIBRATOR_PATH, outcome=True)
        if disk_map.get("artifact_sha256") != receipt.get("map_artifact_sha256") or disk_map != pooled_map:
            raise ProtocolError("reproduction pooled map is not byte/payload exact")
    elif pooled_map is not None or CALIBRATOR_PATH.exists():
        raise ProtocolError("failed receipt unexpectedly has a pooled map")
    return 0


def _pre_marker_for_reproduction(registration: dict, receipt: dict) -> None:
    if receipt.get("runtime") != _runtime_tuple() or not _SHA1.fullmatch(str(receipt.get("execution_sha"))):
        raise ProtocolError("terminal runtime/execution binding is invalid")
    for relative, binding in registration["inputs"].items():
        if _git_blob(relative, ROOT / relative) != binding["git_blob"]:
            raise ProtocolError(f"reproduction input Git blob changed: {relative}")
    for relative, binding in registration["sources"].items():
        path = ROOT / relative
        if _git_blob(relative, path) != binding["git_blob"] or _normalized_source_sha256(path) != binding["normalized_sha256"]:
            raise ProtocolError(f"reproduction source binding changed: {relative}")


def run(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments not in ([], ["--resume-reserved"], ["--seal-interrupted-spend"], ["--reproduce"]):
        return 2
    try:
        with _locked():
            if not arguments:
                return _normal()
            if arguments[0] == "--resume-reserved":
                return _resume()
            if arguments[0] == "--seal-interrupted-spend":
                return _seal_interrupted()
            return _reproduce()
    except (ProtocolError, OSError):
        return 2


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
