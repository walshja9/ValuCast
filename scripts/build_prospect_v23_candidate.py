"""Pure Phase A reconstruction and screening helpers for Prospect Rank v2.3."""
from __future__ import annotations

import math
from copy import deepcopy

import numpy as np

from prospects.rank_v1 import _score_source_sort_order
from prospects.rank_v2 import build_fold_contract, reconstruct_fold_ladders
from prospects.role_slope_joint_calibration import (
    fit_role_slope_joint_map,
    score_role_slope_joint_ladders,
)
from prospects.prospect_v2_target import canonical_sha256


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
    ids = {role: _identity_rows(candidate_rows, role) for role in ROLES}
    targets = sorted(
        [[int(row["mlbam_id"]), row["role"], _number(row, "target", "target hash")]
         for row in candidate_rows],
        key=lambda row: (row[0], row[1]),
    )
    return (
        {role: len(ids[role]) for role in ROLES},
        {role: canonical_sha256(ids[role]) for role in ROLES},
        canonical_sha256(targets),
    )


def _empty_fold_receipt(candidate_rows: list[dict] | None = None) -> dict:
    counts = hashes = target_hash = None
    if candidate_rows:
        counts, hashes, target_hash = _fold_provenance(candidate_rows)
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


def _build_fold_receipt(year: int, ladders: dict[int, dict]) -> tuple[dict, dict | None]:
    ladder = ladders[year]
    candidate_rows = [*ladder.get("candidate_hitters", []), *ladder.get("candidate_pitchers", [])]
    try:
        _fold_provenance(candidate_rows)
    except (KeyError, TypeError, ValueError):
        return _failed_fold_receipt("identity_alignment"), None
    try:
        candidate_map = fit_role_slope_joint_map(_training_rows(year, ladders, "candidate"))
        candidate = score_role_slope_joint_ladders(
            ladder["candidate_hitters"], ladder["candidate_pitchers"], candidate_map
        )
    except (KeyError, TypeError, ValueError):
        return _failed_fold_receipt("candidate_map", candidate_rows), None
    try:
        control_map = fit_role_slope_joint_map(_training_rows(year, ladders, "incumbent"))
        control = score_role_slope_joint_ladders(
            ladder["incumbent_hitters"], ladder["incumbent_pitchers"], control_map
        )
    except (KeyError, TypeError, ValueError):
        return _failed_fold_receipt("control_map", candidate_rows), None
    try:
        product = reconstruct_product_board(ladder["incumbent_hitters"], ladder["incumbent_pitchers"])
    except (KeyError, TypeError, ValueError):
        return _failed_fold_receipt("product_reconstruction", candidate_rows), None
    try:
        control = align_by_identity(candidate, control, "control")
        product = align_by_identity(candidate, product, "product")
    except ValueError as error:
        stage = "target_alignment" if "target mismatch" in str(error) else "identity_alignment"
        return _failed_fold_receipt(stage, candidate_rows), None
    values = {"year": year, "candidate": candidate, "control": control, "product": product}
    try:
        receipt = _completed_fold_receipt(values)
    except ValueError as error:
        stage = "top25_contract" if "top-25" in str(error) else "metric_contract"
        return _failed_fold_receipt(stage, candidate_rows), None
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
    minimum = 9_900
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
        "minimum_valid_replicates": 9_900,
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
    del registration  # Phase A registration is consumed by the outer state machine.
    ladders = reconstruct_development_ladders(contract, model)
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
    return result, pooled_map
