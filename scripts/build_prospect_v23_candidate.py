"""Pure Phase A reconstruction and screening helpers for Prospect Rank v2.3."""
from __future__ import annotations

import math
from copy import deepcopy

from prospects.rank_v1 import _score_source_sort_order
from prospects.rank_v2 import build_fold_contract, reconstruct_fold_ladders
from prospects.role_slope_joint_calibration import (
    fit_role_slope_joint_map,
    score_role_slope_joint_ladders,
)


DEVELOPMENT_FOLDS = (2018, 2019, 2021)
TRAINING_FOLDS_BY_TEST = {
    2018: (2019, 2021),
    2019: (2018, 2021),
    2021: (2018, 2019),
}


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
