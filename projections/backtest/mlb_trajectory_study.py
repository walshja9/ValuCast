"""Registered MLB trajectory study machinery; importing this module reads no data."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite
from statistics import mean, pstdev

import numpy as np


PINNED_REGISTRATION_HASH = "8d5e4f3b51975795f81ba950aa628577d1fb76c72826fcfbb5afbc81560720f1"
BUILDER_INPUT_MANIFEST = (
    "projections/data/historical/hitting_2010.json",
    "projections/data/historical/hitting_2011.json",
    "projections/data/historical/hitting_2012.json",
    "projections/data/historical/hitting_2013.json",
    "projections/data/historical/hitting_2014.json",
    "projections/data/historical/hitting_2015.json",
    "projections/data/historical/hitting_2016.json",
    "projections/data/historical/hitting_2017.json",
    "projections/data/historical/hitting_2018.json",
    "projections/data/historical/hitting_2019.json",
    "projections/data/historical/hitting_2020.json",
    "projections/data/historical/hitting_2021.json",
    "projections/data/historical/hitting_2022.json",
    "projections/data/historical/hitting_2023.json",
    "projections/data/historical/hitting_2024.json",
    "projections/data/historical/hitting_2025.json",
    "projections/data/historical/hitting_2026.json",
    "projections/data/pitching/pitching_2010.json",
    "projections/data/pitching/pitching_2011.json",
    "projections/data/pitching/pitching_2012.json",
    "projections/data/pitching/pitching_2013.json",
    "projections/data/pitching/pitching_2014.json",
    "projections/data/pitching/pitching_2015.json",
    "projections/data/pitching/pitching_2016.json",
    "projections/data/pitching/pitching_2017.json",
    "projections/data/pitching/pitching_2018.json",
    "projections/data/pitching/pitching_2019.json",
    "projections/data/pitching/pitching_2020.json",
    "projections/data/pitching/pitching_2021.json",
    "projections/data/pitching/pitching_2022.json",
    "projections/data/pitching/pitching_2023.json",
    "projections/data/pitching/pitching_2024.json",
    "projections/data/pitching/pitching_2025.json",
    "projections/data/pitching/pitching_2026.json",
    "projections/data/identity.json",
)
HITTER_KNOTS = ((22, 1.65), (25, 1.42), (27, 1.25), (30, 0.97),
                (32, 0.87), (34, 0.77), (37, 0.48))
PITCHER_KNOTS = ((22, 1.50), (25, 1.30), (27, 1.15), (30, 0.88),
                 (32, 0.78), (34, 0.65), (37, 0.33))
HORIZON_WEIGHTS = (1.0, 0.72, 0.48)
RIDGE_LAMBDA = 10.0
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261001
ROLES = ("hitter", "SP", "RP")
CATEGORIES = {"hitter": ("R", "HR", "RBI", "SB", "AVG"),
              "pitcher": ("W", "SV", "K", "ERA", "WHIP")}
RAW_FIELDS = {"hitter": ("R", "HR", "RBI", "SB", "H", "AB"),
              "pitcher": ("W", "SV", "K", "ER", "IP", "H_ALLOWED", "BB")}


class StudyError(ValueError):
    """An unavailable registered input or invalid scientific operation."""


@dataclass(frozen=True)
class Fold:
    name: str
    origin: int
    training: tuple[int, ...]


FOLDS = (
    Fold("D1", 2018, (2012, 2013, 2014, 2015)),
    Fold("D2", 2019, (2012, 2013, 2014, 2015, 2016)),
    Fold("D3", 2020, (2012, 2013, 2014, 2015, 2016, 2017)),
    Fold("H", 2023, (2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020)),
    Fold("P", 2026, (2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020,
                      2021, 2022, 2023)),
)
assert all(z <= fold.origin - 3 for fold in FOLDS for z in fold.training)
assert len(BUILDER_INPUT_MANIFEST) == 35


@dataclass(frozen=True)
class Reference:
    origin: int
    baselines: dict[str, dict[str, float]]
    scales: dict[str, dict[str, float]]


def _number(value, field: str, *, nonnegative: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise StudyError(f"Missing or invalid {field}")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise StudyError(f"Missing or invalid {field}") from exc
    if not isfinite(result) or (nonnegative and result < 0):
        raise StudyError(f"Nonfinite or invalid {field}")
    return result


def _family(role: str) -> str:
    if role == "hitter":
        return "hitter"
    if role in ("SP", "RP", "pitcher"):
        return "pitcher"
    raise StudyError("Unknown routed family/role")


def _raw_stats(stats: dict, family: str) -> dict[str, float]:
    family = _family(family)
    values = {field: _number(stats.get(field), field, nonnegative=True)
              for field in RAW_FIELDS[family]}
    if family == "hitter" and values["H"] > values["AB"]:
        raise StudyError("H exceeds AB")
    return values


def category_impacts(stats: dict, family: str, reference: Reference) -> dict[str, float]:
    """Engine impacts above zero, validating counts before denominator rules."""
    family = _family(family)
    values = _raw_stats(stats, family)
    baseline = reference.baselines[family]
    if family == "hitter":
        result = {key: values[key] for key in ("R", "HR", "RBI", "SB")}
        avg = _number(baseline.get("AVG"), "AVG baseline", nonnegative=True)
        result["AVG"] = values["H"] - avg * values["AB"] if values["AB"] > 30 else 0.0
    else:
        result = {key: values[key] for key in ("W", "SV", "K")}
        era = _number(baseline.get("ERA"), "ERA baseline", nonnegative=True)
        whip = _number(baseline.get("WHIP"), "WHIP baseline", nonnegative=True)
        result["ERA"] = era * values["IP"] / 9.0 - values["ER"] if values["IP"] > 10 else 0.0
        result["WHIP"] = whip * values["IP"] - values["BB"] - values["H_ALLOWED"] if values["IP"] > 10 else 0.0
    if not all(isfinite(value) for value in result.values()):
        raise StudyError("Nonfinite category impact")
    return result


def utility(stats: dict, family: str, reference: Reference) -> float:
    family = _family(family)
    impacts = category_impacts(stats, family, reference)
    total = 0.0
    for category, impact in impacts.items():
        scale = _number(reference.scales[family].get(category), "reference scale", nonnegative=True)
        if scale == 0:
            raise StudyError("Zero reference scale")
        total += impact / scale
    if not isfinite(total):
        raise StudyError("Nonfinite utility")
    return total


def build_reference(origin: int, seasons: dict) -> Reference:
    populations = {"hitter": [], "pitcher": []}
    for season in (origin - 2, origin - 1, origin):
        if season not in seasons:
            raise StudyError("Missing reference season")
        for family in populations:
            if family not in seasons[season] or not isinstance(seasons[season][family], list):
                raise StudyError("Missing reference family file")
            for row in seasons[season][family]:
                volume = _number(row.get("PA" if family == "hitter" else "IP"), "reference activity", nonnegative=True)
                if volume > 0:
                    populations[family].append(_raw_stats(row, family))
    if not all(populations.values()):
        raise StudyError("Empty reference family population")
    hitters, pitchers = populations["hitter"], populations["pitcher"]
    ab, ip = sum(row["AB"] for row in hitters), sum(row["IP"] for row in pitchers)
    if ab <= 0 or ip <= 0:
        raise StudyError("Zero aggregate reference denominator")
    baselines = {
        "hitter": {"AVG": sum(row["H"] for row in hitters) / ab},
        "pitcher": {"ERA": 9.0 * sum(row["ER"] for row in pitchers) / ip,
                    "WHIP": sum(row["BB"] + row["H_ALLOWED"] for row in pitchers) / ip},
    }
    reference = Reference(origin, baselines, {})
    scales = {}
    for family, population in populations.items():
        impacts = [category_impacts(row, family, reference) for row in population]
        scales[family] = {key: pstdev(row[key] for row in impacts) for key in CATEGORIES[family]}
        if any(not isfinite(value) or value <= 0 for value in scales[family].values()):
            raise StudyError("Zero or nonfinite reference scale blocks fold")
    return Reference(origin, baselines, scales)


def weighted_h3(values) -> float:
    if len(values) != 3:
        raise StudyError("H3 requires three mature seasons")
    return sum(weight * _number(value, "annual utility") for weight, value in zip(HORIZON_WEIGHTS, values)) / 2.20


def unweighted_h3(values) -> float:
    if len(values) != 3:
        raise StudyError("H3 requires three mature seasons")
    return mean(_number(value, "annual utility") for value in values)


def age_feature(age: float) -> float:
    return min(37.0, max(22.0, _number(age, "age"))) - 29.0


def age_multiplier(role: str, age: float) -> float:
    family = _family(role)
    age = _number(age, "age")
    knots = HITTER_KNOTS if family == "hitter" else PITCHER_KNOTS
    if age <= knots[0][0]:
        return knots[0][1]
    if age >= knots[-1][0]:
        return knots[-1][1]
    for (lower, low_value), (upper, high_value) in zip(knots, knots[1:]):
        if lower <= age <= upper:
            return low_value + (age - lower) / (upper - lower) * (high_value - low_value)
    raise StudyError("Age curve interpolation failed")


def reliability(role: str, vol: float) -> float:
    if role not in ROLES:
        raise StudyError("Unknown reliability role")
    vol = _number(vol, "forecast volume")
    regression = {"hitter": 150.0, "SP": 45.0, "RP": 20.0}[role]
    return max(0.55, min(1.0, round(100.0 * vol / (vol + regression), 2) / 100.0)) if vol > 0 else 0.55


def volume_multiplier(role: str, vol: float) -> float:
    if role not in ROLES:
        raise StudyError("Unknown volume role")
    vol = _number(vol, "forecast volume")
    base = {"hitter": 550.0, "SP": 180.0, "RP": 65.0}[role]
    return 0.20 if vol <= 0 else (1.0 if vol >= base else max(0.20, (vol / base) ** 0.75))


def hand_set_multiplier(role: str, age: float, vol: float) -> float:
    age = _number(age, "age")
    rho = reliability(role, vol)
    return volume_multiplier(role, vol) * (
        age_multiplier(role, age) + 0.72 * age_multiplier(role, age + 1) * rho
        + 0.48 * age_multiplier(role, age + 2) * rho
    ) / 2.20


def center_forecasts(rows: list[dict]) -> list[dict]:
    """Center full-universe F1 by family; missing forecasts stay missing."""
    by_family = defaultdict(list)
    for row in rows:
        family = _family(row["role"])
        if row.get("F1") is not None:
            by_family[family].append(_number(row["F1"], "F1"))
    if not by_family:
        raise StudyError("No forecast to center")
    centers = {family: mean(values) for family, values in by_family.items()}
    baseline = min(_number(row["F1"], "F1") - centers[_family(row["role"])]
                   for row in rows if row.get("F1") is not None)
    result = []
    for row in rows:
        centered = dict(row)
        if row.get("F1") is not None:
            centered.update(C_fam=centers[_family(row["role"])],
                            V=row["F1"] - centers[_family(row["role"])], B=baseline)
        result.append(centered)
    return result


def _features(row: dict) -> list[float]:
    spread = _number(row.get("V"), "V") - _number(row.get("B"), "B")
    if spread < 0:
        raise StudyError("V below frozen B")
    a = age_feature(row.get("age"))
    rho = _number(row.get("rho"), "rho")
    if not 0.55 <= rho <= 1.0:
        raise StudyError("Reliability outside registered range")
    return [spread, spread * a, spread * a * a, spread * rho]


def fit_ridge(rows: list[dict], role: str) -> dict:
    if role not in ROLES:
        raise StudyError("Unknown ridge role")
    selected = [row for row in rows if row.get("role") == role]
    if not selected:
        raise StudyError("No training rows for required role")
    x = np.asarray([_features(row) for row in selected], dtype=float)
    y = np.asarray([_number(row.get("H3"), "H3") - _number(row.get("C_fam"), "C_fam")
                    - _number(row.get("B"), "B") for row in selected], dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise StudyError("Nonfinite ridge input")
    scales = np.std(x, axis=0, ddof=0)
    scales[scales == 0] = 1.0
    if not np.isfinite(scales).all():
        raise StudyError("Nonfinite ridge scales")
    standardized = x / scales
    try:
        coefficients = np.linalg.solve(standardized.T @ standardized + RIDGE_LAMBDA * np.eye(4),
                                       standardized.T @ y) / scales
    except np.linalg.LinAlgError as exc:
        raise StudyError("Unsolved ridge fit blocks fold") from exc
    if not np.isfinite(coefficients).all():
        raise StudyError("Nonfinite fitted coefficients")
    return {"role": role, "coefficients": coefficients.tolist(), "scales": scales.tolist(),
            "n": len(selected), "origins": sorted({row["origin"] for row in selected})}


def predict(row: dict, fit: dict) -> dict[str, float]:
    role = row["role"]
    if fit.get("role") != role:
        raise StudyError("Fit role mismatch")
    _features(row)
    coefficients = np.asarray(fit.get("coefficients"), dtype=float)
    if coefficients.shape != (4,) or not np.isfinite(coefficients).all():
        raise StudyError("Invalid fitted coefficients")
    a = age_feature(row["age"])
    candidate = max(0.0, float(coefficients @ np.asarray([1.0, a, a * a, row["rho"]])))
    c = _number(row.get("C_fam"), "C_fam")
    b = _number(row.get("B"), "B")
    v = _number(row.get("V"), "V")
    multipliers = {"flat": 1.0, "hand_set": hand_set_multiplier(role, row["age"], row["volume"]),
                   "candidate": candidate}
    result = {key: c + b + (v - b) * multiplier for key, multiplier in multipliers.items()}
    if not all(isfinite(value) for value in result.values()):
        raise StudyError("Nonfinite frozen prediction")
    return result


def average_ranks(values) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise StudyError("Ranks require a finite vector")
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and sorted_values[end] == sorted_values[start]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    return ranks


def spearman(x, y) -> float | None:
    if len(x) != len(y):
        raise StudyError("Unpaired metric vectors")
    if len(x) < 2:
        return None
    xr, yr = average_ranks(x), average_ranks(y)
    xr, yr = xr - xr.mean(), yr - yr.mean()
    denominator = float(np.linalg.norm(xr) * np.linalg.norm(yr))
    return float(np.dot(xr, yr) / denominator) if denominator > 0 else None


def top_ids(rows: list[dict], n: int = 300) -> tuple[int, ...]:
    scored = []
    seen = set()
    for row in rows:
        pid = _asset_id(row)
        if pid in seen:
            raise StudyError("Duplicate frozen identity")
        seen.add(pid)
        if row.get("F1") is not None:
            scored.append((_number(row["F1"], "F1"), pid))
    return tuple(pid for _, pid in sorted(scored, key=lambda item: (-item[0], item[1]))[:n])


def _asset_id(row: dict) -> int:
    value = _number(row.get("mlbam_id"), "MLBAM identity", nonnegative=True)
    if value <= 0 or value != int(value):
        raise StudyError("Invalid MLBAM identity")
    return int(value)


def percentile_bound(values, alpha: float) -> dict:
    alpha = _number(alpha, "percentile alpha")
    if not 0 < alpha < 1:
        raise StudyError("Invalid percentile alpha")
    values = list(values)
    finite = [float(value) for value in values if value is not None and isfinite(float(value))]
    undefined = len(values) - len(finite)
    available = bool(values) and bool(finite) and undefined / len(values) <= 0.05
    return {"bound": float(np.percentile(finite, 100.0 * alpha, method="linear")) if available else None,
            "undefined": undefined, "replicates": len(values), "finite": len(finite), "alpha": alpha}


def _correlations(rows: list[dict], target: str = "H3") -> dict:
    correlations = {}
    for model in ("candidate", "flat", "hand_set"):
        try:
            actual = [_number(row.get(target), target) for row in rows]
            predicted = [_number(row.get(model), model) for row in rows]
            correlations[model] = spearman(predicted, actual)
        except StudyError:
            # Preserve the frozen vector; invalid rows cannot be dropped to rescue it.
            correlations[model] = None
    correlations["gaps"] = {
        model: correlations["candidate"] - correlations[model]
        if correlations["candidate"] is not None and correlations[model] is not None else None
        for model in ("flat", "hand_set")
    }
    return correlations


def _origin_metrics(rows: list[dict]) -> dict:
    grouped = {fold.name: [row for row in rows if row["origin"] == fold.origin]
               for fold in FOLDS[:4]}
    metrics = {name: _correlations(group) for name, group in grouped.items()}
    dev = {}
    for model in ("candidate", "flat", "hand_set"):
        values = [metrics[name][model] for name in ("D1", "D2", "D3")]
        dev[model] = mean(values) if all(value is not None for value in values) else None
    dev["gaps"] = {}
    for model in ("flat", "hand_set"):
        values = [metrics[name]["gaps"][model] for name in ("D1", "D2", "D3")]
        dev["gaps"][model] = mean(values) if all(value is not None for value in values) else None
    metrics["development"] = dev
    return metrics


def bootstrap(gates: dict[str, list[dict]]) -> dict:
    """One fixed set of paired cluster draws, restricted to each frozen gate."""
    assets = sorted({_asset_id(row) for rows in gates.values() for row in rows})
    clusters = {}
    for gate, rows in gates.items():
        by_asset = defaultdict(list)
        for row in rows:
            by_asset[_asset_id(row)].append(row)
        clusters[gate] = by_asset
    values = {gate: {period: {"candidate": [], "gaps": {"flat": [], "hand_set": []}}
                     for period in ("development", "H")} for gate in gates}
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    for _ in range(BOOTSTRAP_REPLICATES):
        draw = rng.choice(assets, size=len(assets), replace=True) if assets else ()
        for gate in gates:
            sample = [row for pid in draw for row in clusters[gate].get(int(pid), ())]
            metrics = _origin_metrics(sample)
            for period in ("development", "H"):
                values[gate][period]["candidate"].append(metrics[period]["candidate"])
                for comparator in ("flat", "hand_set"):
                    values[gate][period]["gaps"][comparator].append(metrics[period]["gaps"][comparator])
    result = {}
    for gate, periods in values.items():
        result[gate] = {}
        for period, statistics in periods.items():
            candidate = statistics["candidate"]
            result[gate][period] = {
                "candidate": {**percentile_bound(candidate, 0.05), "values": candidate},
                "gaps": {comparator: {**percentile_bound(draws, 0.025),
                                      "unadjusted": percentile_bound(draws, 0.05), "values": draws}
                         for comparator, draws in statistics["gaps"].items()},
            }
    return result


def mechanical_disposition(*, failures=(), ineligible=(), unavailable=()) -> str:
    if failures:
        return "FAIL"
    if ineligible:
        return "INELIGIBLE"
    if unavailable:
        return "UNDERPOWERED"
    return "PASS"


def _slice_flags(row: dict, *, include_unresolved: bool = False) -> dict[str, bool]:
    flags = {"hitter": row.get("role") == "hitter", "SP": row.get("role") == "SP",
             "RP": row.get("role") == "RP", "cold_start": row.get("cold_start") is True,
             "graduate": row.get("graduate") is True}
    if include_unresolved:
        if row.get("role") not in ROLES:
            flags.update({role: True for role in ROLES})
        for name in ("cold_start", "graduate"):
            if not isinstance(row.get(name), bool):
                flags[name] = True
    return flags


def gate_admission(rows: list[dict], frozen: list[dict]) -> dict:
    blockers = []
    coverage = {}
    for fold in FOLDS[:4]:
        source = [row for row in frozen if row.get("origin") == fold.origin]
        matched = [row for row in rows if row.get("origin") == fold.origin]
        def identities(population):
            result = []
            for row in population:
                try:
                    result.append(_asset_id(row))
                except StudyError:
                    result.append(None)
            return result

        source_ids, matched_ids = identities(source), identities(matched)
        if None in source_ids or None in matched_ids:
            blockers.append(f"{fold.name}: invalid reconciled identity")
        if len(set(source_ids)) != len(source_ids) or len(set(matched_ids)) != len(matched_ids):
            blockers.append(f"{fold.name}: duplicate identity")
        if not set(matched_ids) <= set(source_ids):
            blockers.append(f"{fold.name}: matched row outside frozen gate")
        source_by_id = {pid: row for pid, row in zip(source_ids, source) if pid is not None}
        admitted_ids = set()
        for pid, row in zip(matched_ids, matched):
            original = source_by_id.get(pid)
            valid = pid is not None and original is not None and row.get("complete") is True
            if original is not None:
                if original.get("complete") is not True:
                    valid = False
                for field in ("role", "cold_start", "graduate", "both_component", "age", "rho",
                              "F1", "C_fam", "V", "B", "volume"):
                    if field in original and row.get(field) != original[field]:
                        valid = False
                        blockers.append(f"{fold.name}: matched metadata differs from frozen {field}")
            try:
                for field in ("candidate", "flat", "hand_set", "H3", "age", "rho", "F1",
                              "C_fam", "V", "B", "volume"):
                    _number(row.get(field), field)
                if row.get("role") not in ROLES or not all(isinstance(row.get(flag), bool)
                        for flag in ("cold_start", "graduate")):
                    valid = False
                _features(row)
                if _number(row["volume"], "volume") < 0:
                    valid = False
            except StudyError:
                valid = False
            if valid:
                admitted_ids.add(pid)
            else:
                blockers.append(f"{fold.name}: missing required-field provenance/completeness")
        if len(admitted_ids) < 200:
            blockers.append(f"{fold.name}: fewer than 200 matched assets")
        fraction = len(admitted_ids) / len(source_ids) if source_ids else 0.0
        if fraction < 0.95:
            blockers.append(f"{fold.name}: overall coverage below 95 percent")
        if any(row.get("complete") is not True for row in matched):
            blockers.append(f"{fold.name}: missing required-field provenance/completeness")
        slices = {}
        for slice_name in ("hitter", "SP", "RP", "cold_start", "graduate"):
            frozen_slice = [row for row in source if _slice_flags(row, include_unresolved=True)[slice_name]]
            frozen_slice_ids = {pid for pid, row in zip(source_ids, source)
                                if pid is not None and _slice_flags(row)[slice_name]}
            matched_slice = admitted_ids & frozen_slice_ids
            covered = len(matched_slice) / len(frozen_slice) if frozen_slice else None
            exempt = len(frozen_slice) < 30
            slices[slice_name] = {"frozen": len(frozen_slice), "matched": len(matched_slice),
                                  "coverage": covered, "exempt": exempt}
            if not exempt and covered < 0.90:
                blockers.append(f"{fold.name}: {slice_name} coverage below 90 percent")
        coverage[fold.name] = {"frozen": len(source), "matched": len(admitted_ids),
                               "coverage": fraction, "slices": slices}
    return {"ineligible": blockers, "coverage": coverage}


def _point_failures(metrics: dict, prefix: str) -> tuple[list, list]:
    failures, ineligible = [], []
    for period in ("D1", "D2", "D3", "H"):
        if any(metrics[period][model] is None for model in ("candidate", "flat", "hand_set")):
            ineligible.append(f"{prefix}/{period}: undefined primary correlation or comparator")
    dev, holdout = metrics["development"], metrics["H"]
    if dev["candidate"] is not None and dev["candidate"] <= 0:
        failures.append(f"{prefix}: development candidate correlation is not positive")
    if holdout["candidate"] is not None and holdout["candidate"] <= 0:
        failures.append(f"{prefix}: H candidate correlation is not positive")
    for comparator in ("flat", "hand_set"):
        gaps = [metrics[name]["gaps"][comparator] for name in ("D1", "D2", "D3")]
        finite = [gap for gap in gaps if gap is not None]
        if dev["gaps"][comparator] is not None and dev["gaps"][comparator] < 0.02:
            failures.append(f"{prefix}/{comparator}: development gap below 0.02")
        if len(finite) == 3 and sum(gap > 0 for gap in finite) < 2:
            failures.append(f"{prefix}/{comparator}: fewer than two positive development gaps")
        if any(gap < -0.05 for gap in finite):
            failures.append(f"{prefix}/{comparator}: development gap below -0.05")
        if holdout["gaps"][comparator] is not None and holdout["gaps"][comparator] < 0.02:
            failures.append(f"{prefix}/{comparator}: H gap below 0.02")
    return failures, ineligible


def _within_family(rows: list[dict]) -> tuple[dict, list, list]:
    result, failures, unavailable = {}, [], []
    for family in ("hitter", "pitcher"):
        selected = [row for row in rows if row.get("role") in ROLES and _family(row["role"]) == family]
        counts = {fold.name: sum(row["origin"] == fold.origin for row in selected) for fold in FOLDS[:4]}
        metrics = _origin_metrics(selected)
        gaps = {period: metrics[period]["gaps"]["hand_set"] for period in ("development", "H")}
        sufficient = all(count >= 30 for count in counts.values())
        result[family] = {"counts": counts, "gaps": gaps,
                          "available": sufficient and all(gap is not None for gap in gaps.values())}
        if not sufficient:
            unavailable.append(f"top300/{family}: fewer than 30 matched rows at an origin")
            continue
        for period, gap in gaps.items():
            if gap is None:
                unavailable.append(f"top300/{family}/{period}: unavailable gap")
            elif gap <= 0:
                failures.append(f"top300/{family}/{period}: hand-set gap is not positive")
    return result, failures, unavailable


def score_gates(gates: dict, frozen_populations: dict) -> dict:
    failures, ineligible, unavailable = [], [], []
    result = {}
    if set(gates) != {"full", "top300"} or set(frozen_populations) != {"full", "top300"}:
        raise StudyError("Both registered gates and frozen populations are required")
    intervals = bootstrap(gates)
    for gate, rows in gates.items():
        admission = gate_admission(rows, frozen_populations[gate])
        metrics = _origin_metrics(rows)
        gate_failures, gate_ineligible = _point_failures(metrics, gate)
        gate_ineligible.extend(f"{gate}/{reason}" for reason in admission["ineligible"])
        gate_unavailable = []
        for name, receipt in [("candidate", intervals[gate]["H"]["candidate"])] + [
                (comparator, intervals[gate]["H"]["gaps"][comparator]) for comparator in ("flat", "hand_set")]:
            if receipt["bound"] is None:
                gate_unavailable.append(f"{gate}/H/{name}: acceptance bound unavailable")
            elif receipt["bound"] <= 0:
                gate_failures.append(f"{gate}/H/{name}: acceptance lower bound is not positive")
        result[gate] = {"metrics": metrics, "coverage": admission["coverage"],
                        "intervals": intervals[gate], "failures": gate_failures,
                        "ineligible": gate_ineligible, "unavailable": gate_unavailable,
                        "disposition": mechanical_disposition(failures=gate_failures,
                            ineligible=gate_ineligible, unavailable=gate_unavailable)}
        failures.extend(gate_failures)
        ineligible.extend(gate_ineligible)
        unavailable.extend(gate_unavailable)
    families, family_failures, family_unavailable = _within_family(gates["top300"])
    failures.extend(family_failures)
    unavailable.extend(family_unavailable)
    return {"disposition": mechanical_disposition(failures=failures, ineligible=ineligible, unavailable=unavailable),
            "failures": failures, "ineligible": ineligible, "unavailable": unavailable,
            "gates": result, "within_family": families, "confirmation": "INELIGIBLE",
            "release": "SEPARATE_OWNER_DECISION"}


def top_capture(rows: list[dict], model: str, n: int = 50, target: str = "H3") -> dict:
    """Positive-utility capture with fractional inclusion across cutoff ties."""
    if not rows or n <= 0:
        return {"capture": None, "coverage_blocked": False}
    ordered = sorted(rows, key=lambda row: _number(row.get(model), model), reverse=True)
    cutoff = ordered[min(n, len(ordered)) - 1][model]
    above = [row for row in ordered if row[model] > cutoff]
    tied = [row for row in ordered if row[model] == cutoff]
    fraction = (min(n, len(ordered)) - len(above)) / len(tied)
    selected = above + tied
    blocked = any(row.get("complete") is not True or row.get(target) is None for row in selected)
    matched = [row for row in rows if row.get("complete") is True and row.get(target) is not None]
    denominator = sum(max(_number(row[target], target), 0.0) for row in matched)
    numerator = (sum(max(_number(row[target], target), 0.0) for row in above)
                 + fraction * sum(max(_number(row[target], target), 0.0) for row in tied)) if not blocked else None
    return {"capture": numerator / denominator if numerator is not None and denominator > 0 else None,
            "coverage_blocked": blocked, "cutoff_fraction": fraction}


def per162_stats(stats: dict, family: str, scheduled_games: float) -> dict:
    games = _number(scheduled_games, "documented league scheduled games", nonnegative=True)
    if games <= 0:
        raise StudyError("Missing schedule metadata")
    raw = _raw_stats(stats, family)
    return {key: value * 162.0 / games for key, value in raw.items()}


def _aggregate_diagnostic(n: int, compute):
    return compute() if n >= 30 else None


def descriptive_metrics(rows: list[dict], *, include_top50: bool = True) -> dict:
    """Aggregate diagnostics have no connection to the disposition function."""
    slices = {"hitter": lambda row: row["role"] == "hitter", "SP": lambda row: row["role"] == "SP",
              "RP": lambda row: row["role"] == "RP", "both_component": lambda row: row.get("both_component") is True,
              "cold_start": lambda row: row.get("cold_start") is True,
              "graduate": lambda row: row.get("graduate") is True,
              "age33plus": lambda row: row.get("age") is not None and row["age"] >= 33}
    result = {}
    for fold in FOLDS[:4]:
        origin_rows = [row for row in rows if row["origin"] == fold.origin]
        result[fold.name] = {"slices": {}}
        if include_top50:
            result[fold.name]["top50"] = {model: top_capture(origin_rows, model)
                for model in ("candidate", "flat", "hand_set")}
        for name, select in slices.items():
            selected = [row for row in origin_rows if select(row)]
            metrics = _correlations(selected)
            result[fold.name]["slices"][name] = {"n": len(selected), "qualified_size": len(selected) >= 30,
                "metrics": metrics, "role_claim_failures": [model for model, gap in metrics["gaps"].items()
                    if name in ROLES and len(selected) >= 30 and gap is not None and gap < -0.05]}
        result[fold.name]["zero_production_fraction"] = {"n": len(origin_rows),
            "fraction": _aggregate_diagnostic(len(origin_rows), lambda:
                sum(row["H3"] == 0 for row in origin_rows) / len(origin_rows))}
        for target in ("H3_unweighted", "H3_per162"):
            available = [row for row in origin_rows if row.get(target) is not None]
            result[fold.name][target] = {"n": len(available), "metrics": _correlations(available, target)}
    return result


def asset_id(value) -> str:
    if isinstance(value, bool) or value is None:
        raise StudyError("Unreconciled MLBAM identity")
    text = str(value)
    if not text.isascii() or not text.isdigit() or int(text) <= 0:
        raise StudyError("Unreconciled MLBAM identity")
    return str(int(text))


def reconcile_stints(rows: list[dict], family: str) -> dict[str, dict]:
    """Sum distinct legitimate stints; use a total only when no stints exist."""
    groups = defaultdict(list)
    for row in rows:
        groups[asset_id(row.get("mlbam_id"))].append(row)
    reconciled = {}
    for pid, group in groups.items():
        if len(group) == 1:
            reconciled[pid] = {**group[0], "mlbam_id": pid}
            continue
        totals, stints = [], []
        for row in group:
            team = str(row.get("team", row.get("team_id", ""))).upper()
            if not team:
                raise StudyError("Duplicate identity without distinct team-stint provenance")
            (totals if team == "TOT" or (team.endswith("TM") and team[:-2].isdigit()) else stints).append(row)
        teams = [str(row.get("team", row.get("team_id"))) for row in stints]
        if len(totals) > 1 or len(set(teams)) != len(teams) or not stints:
            raise StudyError("Unreconciled aggregate/team stints")
        fields = set(RAW_FIELDS[_family(family)]) | ({"PA"} if family == "hitter" else {"BF", "G", "GS"})
        fields |= {key for row in stints for key, value in row.items()
                   if isinstance(value, (int, float)) and key not in ("season", "mlbam_id", "team_id")}
        combined = {key: sum(_number(row.get(key), key, nonnegative=True) for row in stints)
                    for key in fields}
        if totals:
            for key in fields:
                if not np.isclose(_number(totals[0].get(key), key), combined[key], rtol=0, atol=0.0002):
                    raise StudyError("Aggregate line disagrees with team stints")
        reconciled[pid] = {**combined, "mlbam_id": pid}
    return reconciled


def route_asset(hit: dict | None, pitch: dict | None) -> tuple[str, bool]:
    pa = _number(hit.get("PA"), "routing PA", nonnegative=True) if hit is not None else 0.0
    ip = _number(pitch.get("IP"), "routing IP", nonnegative=True) if pitch is not None else 0.0
    hitting, pitching = pa > 0, ip > 0
    if not hitting and not pitching:
        raise StudyError("No verified activity in routing season")
    both = hitting and pitching
    bf = _number(pitch.get("BF"), "routing BF", nonnegative=True) if both else None
    if both and bf <= 0:
        raise StudyError("Positive pitching activity with zero BF")
    if hitting and (not pitching or pa >= bf):
        return "hitter", both
    games = _number(pitch.get("G"), "routing G", nonnegative=True)
    starts = _number(pitch.get("GS"), "routing GS", nonnegative=True)
    if games <= 0 or starts > games:
        raise StudyError("Inconsistent pitching routing counts")
    return ("SP" if starts / games >= 0.5 else "RP"), both


class OriginData:
    """A capability containing admitted seasons at or before one cutoff only."""

    def __init__(self, origin: int, seasons: dict, identities: dict, complete: bool = True):
        if not complete or not seasons or any(year > origin or year < 2010 for year in seasons):
            raise StudyError("Incomplete or future origin inputs")
        self.origin = origin
        self.identities = {}
        for pid, identity in identities.items():
            key = asset_id(pid)
            if key in self.identities or not isinstance(identity, dict):
                raise StudyError("Unreconciled identity crosswalk")
            if "mlbam_id" in identity and asset_id(identity["mlbam_id"]) != key:
                raise StudyError("Identity crosswalk mismatch")
            self.identities[key] = dict(identity)
        self._seasons = {}
        for year, families in seasons.items():
            if any(family not in families or not isinstance(families[family], list)
                   for family in ("hitter", "pitcher")):
                raise StudyError("Incomplete admitted season files")
            self._seasons[year] = {family: reconcile_stints(families[family], family)
                                   for family in ("hitter", "pitcher")}

    def season(self, year: int) -> dict:
        if year > self.origin or year not in self._seasons:
            raise StudyError("Season outside admitted origin view")
        return {family: list(rows.values()) for family, rows in self._seasons[year].items()}

    def component(self, pid: str, year: int, family: str) -> dict | None:
        if year > self.origin or year not in self._seasons:
            raise StudyError("Season outside admitted origin view")
        if asset_id(pid) not in self.identities:
            raise StudyError("Unresolved identity; absence cannot be zero")
        return self._seasons[year][_family(family)].get(asset_id(pid))

    def actual(self, pid: str, year: int, family: str) -> dict:
        row = self.component(pid, year, family)
        if row is None:
            return {field: 0.0 for field in RAW_FIELDS[_family(family)]}
        return _raw_stats(row, family)


def _activity(data: OriginData, pid: str, year: int) -> tuple[float, float]:
    hit = data.component(pid, year, "hitter")
    pitch = data.component(pid, year, "pitcher")
    return (_number(hit.get("PA"), "activity PA", nonnegative=True) if hit is not None else 0.0,
            _number(pitch.get("IP"), "activity IP", nonnegative=True) if pitch is not None else 0.0)


def _april_age(identity: dict, season: int) -> int:
    from datetime import date
    from projections.data.identity import age_for

    try:
        dob = date.fromisoformat(identity.get("birth_date", ""))
    except (TypeError, ValueError) as exc:
        raise StudyError("Missing or invalid DOB") from exc
    reference = date(season, 4, 1)
    if dob > reference:
        raise StudyError("DOB after projection origin")
    age = age_for(identity.get("birth_date"), season)
    if age is None:
        raise StudyError("Missing or invalid DOB")
    return age


def build_origin(data: OriginData, forecast) -> dict:
    """Freeze universe, missing inputs, units, F1 and selection before labels."""
    origin = data.origin
    seasons = {year: data.season(year) for year in range(2010, origin + 1)}
    reference = build_reference(origin, seasons)
    forecasts = forecast(data)
    candidates = set()
    for year in (origin - 1, origin):
        for family, field in (("hitter", "PA"), ("pitcher", "IP")):
            for row in seasons[year][family]:
                # Unknown activity cannot be silently excluded from the universe.
                if _number(row.get(field), "universe activity", nonnegative=True) > 0:
                    candidates.add(asset_id(row["mlbam_id"]))
    rows, ledger = [], []
    for pid in sorted(candidates, key=int):
        row = {"mlbam_id": pid, "origin": origin, "role": None, "both_component": None,
               "cold_start": None, "graduate": None, "graduate_left_censored_2010": True,
               "age": None, "age_33_plus": None, "F1": None, "volume": None,
               "rho": None, "complete": False, "exclusions": []}
        try:
            activity = _activity(data, pid, origin)
            routing_year = origin if any(value > 0 for value in activity) else origin - 1
            hit = data.component(pid, routing_year, "hitter")
            pitch = data.component(pid, routing_year, "pitcher")
            row["role"], row["both_component"] = route_asset(hit, pitch)
        except StudyError as exc:
            row["exclusions"].append(str(exc))
        try:
            history = {year: any(value > 0 for value in _activity(data, pid, year))
                       for year in range(2010, origin + 1)}
            row["cold_start"] = sum(history[year] for year in range(origin - 2, origin + 1)) < 3
            row["graduate"] = not any(active for year, active in history.items() if year < origin - 1)
        except StudyError as exc:
            row["exclusions"].append(str(exc))
        try:
            row["age"] = _april_age(data.identities.get(pid, {}), origin + 1)
            row["age_33_plus"] = row["age"] >= 33
        except StudyError as exc:
            row["exclusions"].append(str(exc))
        if row["role"] is not None:
            try:
                family = _family(row["role"])
                stats = forecasts.get(family, {}).get(pid)
                if stats is None:
                    raise StudyError("Absent forecast for active routed component")
                row["F1"] = utility(stats, family, reference)
                row["volume"] = _number(stats.get("PA" if family == "hitter" else "IP"),
                                        "forecast volume", nonnegative=True)
                row["rho"] = reliability(row["role"], row["volume"])
                row["forecast_categories"] = category_impacts(stats, family, reference)
            except StudyError as exc:
                row["F1"] = None
                row["exclusions"].append(str(exc))
        rows.append(row)
    centered = {row["mlbam_id"]: row for row in center_forecasts([r for r in rows if r["role"] is not None])}
    for row in rows:
        row.update(centered.get(row["mlbam_id"], {}))
        row["complete"] = not row["exclusions"]
        ledger.append({"mlbam_id": row["mlbam_id"], "reasons": row["exclusions"]})
    return {"origin": origin, "reference": {"origin": origin, "baselines": reference.baselines,
            "scales": reference.scales}, "rows": rows, "ledger": ledger,
            "top300": top_ids([row for row in rows if row["F1"] is not None])}


def _reference(snapshot: dict) -> Reference:
    return Reference(**snapshot["reference"])


def _realized(row: dict, reference: Reference, data: OriginData, schedule_lengths=None) -> dict:
    annual, categories, per162, no_production = [], [], [], []
    family = _family(row["role"])
    for year in range(row["origin"] + 1, row["origin"] + 4):
        stats = data.actual(row["mlbam_id"], year, family)
        no_production.append(all(value == 0 for value in stats.values()))
        annual.append(utility(stats, family, reference))
        categories.append(category_impacts(stats, family, reference))
        if schedule_lengths is not None:
            length = schedule_lengths.get(str(year), schedule_lengths.get(year))
            per162.append(utility(per162_stats(stats, family, length), family, reference))
    return {"H3": weighted_h3(annual), "H3_unweighted": unweighted_h3(annual),
            "H3_per162": weighted_h3(per162) if schedule_lengths is not None else None,
            "annual_U": annual, "annual_categories": categories,
            "verified_zero_production": all(no_production)}


def fit_origin(fold: Fold, snapshot: dict, training_snapshots: dict, data: OriginData) -> dict:
    if data.origin != fold.origin or snapshot["origin"] != fold.origin:
        raise StudyError("Fold origin mismatch")
    if any(year > fold.origin - 3 for year in fold.training):
        raise StudyError("Training-label chronology violated")
    train, training_ledger = [], []
    for year in fold.training:
        if year not in training_snapshots or training_snapshots[year]["origin"] != year:
            raise StudyError("A registered training origin is not admitted")
        older = training_snapshots[year]
        admitted = 0
        for row in older["rows"]:
            if not row["complete"]:
                training_ledger.append({"origin": year, "mlbam_id": row["mlbam_id"], "reasons": row["exclusions"]})
                continue
            try:
                label = _realized(row, _reference(older), data)
                train.append({**row, **label})
                admitted += 1
            except StudyError as exc:
                training_ledger.append({"origin": year, "mlbam_id": row["mlbam_id"], "reasons": [str(exc)]})
        if not admitted:
            raise StudyError("A registered training origin has no admitted rows")
    fits = {role: fit_ridge(train, role) for role in ROLES}
    rows = []
    for source in snapshot["rows"]:
        row = dict(source)
        if row["complete"]:
            row.update(predict(row, fits[row["role"]]))
            row["candidate_multiplier"] = max(0.0, float(np.dot(fits[row["role"]]["coefficients"],
                [1.0, age_feature(row["age"]), age_feature(row["age"]) ** 2, row["rho"]])))
        rows.append(row)
    return {**snapshot, "fold": fold.name, "rows": rows, "fits": fits,
            "training_origins": list(fold.training), "training_ledger": training_ledger,
            "training_frozen_inputs": {str(year): training_snapshots[year] for year in fold.training},
            "training_rows": train, "evaluation_labels_accessed": False}


def score_frozen(record: dict, labels: OriginData, schedule_lengths: dict) -> dict:
    if labels.origin < record["origin"] + 3:
        raise StudyError("Immature evaluation window")
    rows = []
    for source in record["rows"]:
        row = dict(source)
        if row["complete"]:
            try:
                row.update(_realized(row, _reference(record), labels, schedule_lengths))
            except StudyError as exc:
                row.update(complete=False, label_exclusions=[str(exc)])
        rows.append(row)
    return {"origin": record["origin"], "fold": record["fold"], "rows": rows}


def build_transfer(registered: dict, feed: list[dict], identities: dict) -> dict:
    """Consume admitted, reconciled feed rows with explicitly supplied roles."""
    reference = _reference(registered)
    rows, seen = [], set()
    for item in feed:
        pid = asset_id(item.get("mlbam_id", item.get("metadata", {}).get("mlbam_id")))
        role = item.get("role")
        if role not in ROLES or pid in seen:
            raise StudyError("Transfer feed needs one reconciled routed asset per row")
        seen.add(pid)
        row = {"mlbam_id": pid, "origin": 2026, "role": role, "age": None,
               "volume": None, "rho": None, "F1": None, "complete": False,
               "exclusions": []}
        try:
            row["age"] = _april_age(identities.get(pid, {}), 2027)
        except StudyError as exc:
            row["exclusions"].append(str(exc))
        try:
            stats = item.get("stats")
            if not isinstance(stats, dict):
                raise StudyError("Missing or invalid transfer stats")
            row["F1"] = utility(stats, _family(role), reference)
            row["volume"] = _number(stats.get("PA" if role == "hitter" else "IP"),
                                    "transfer volume", nonnegative=True)
            row["rho"] = reliability(role, row["volume"])
        except StudyError as exc:
            row["F1"] = None
            row["exclusions"].append(str(exc))
        row["complete"] = not row["exclusions"]
        rows.append(row)
    rows = center_forecasts(rows)
    for row in rows:
        if row["complete"]:
            row.update(predict(row, registered["fits"][row["role"]]))
    return {"origin": 2026, "reference": registered["reference"], "fits": registered["fits"],
            "rows": rows, "feed_centering_recomputed": True,
            "ledger": [{"mlbam_id": row["mlbam_id"], "reasons": row["exclusions"]} for row in rows],
            "coverage": {"frozen": len(rows), "matched": sum(row["complete"] for row in rows)}}


def describe_study(evaluations: list[dict], frozen: list[dict], *, include_top50: bool = True) -> dict:
    matched = [row for evaluation in evaluations for row in evaluation["rows"] if row["complete"]]
    diagnostics = descriptive_metrics(matched, include_top50=include_top50)
    for evaluation in evaluations:
        name = evaluation["fold"]
        population = evaluation["rows"]
        predicted = [row for row in population if row.get("candidate") is not None]
        available = [row for row in population if row["complete"]]
        n = len(available)
        if include_top50:
            diagnostics[name]["top50"] = {model: top_capture(predicted, model)
                                           for model in ("candidate", "flat", "hand_set")}
        diagnostics[name]["coverage"] = {"frozen": len(population),
            "matched": sum(row["complete"] for row in population)}
        diagnostics[name]["outcome_distribution"] = {"n": n,
            "quantiles": _aggregate_diagnostic(n, lambda:
                np.percentile([row["H3"] for row in available],
                              [5, 25, 50, 75, 95], method="linear").tolist())}
        for slice_name, slice_data in diagnostics[name]["slices"].items():
            def belongs(row):
                if slice_name in ROLES:
                    return row["role"] == slice_name
                if slice_name == "age33plus":
                    return row.get("age_33_plus") is True
                return row.get(slice_name) is True
            slice_data["frozen_n"] = sum(belongs(row) for row in population)
            slice_data["coverage"] = (slice_data["n"] / slice_data["frozen_n"]
                                      if slice_data["frozen_n"] else None)
        for source in frozen:
            if source["fold"] == name:
                diagnostics[name]["fits"] = source["fits"]
        family_diagnostics = {}
        for family in ("hitter", "pitcher"):
            family_rows = [row for row in available if _family(row["role"]) == family]
            family_n = len(family_rows)
            family_diagnostics[family] = {
                "n": family_n,
                "annual_U_mean": _aggregate_diagnostic(family_n, lambda: [
                    mean(row["annual_U"][offset] for row in family_rows) for offset in range(3)]),
                "annual_category_impact_means": _aggregate_diagnostic(family_n, lambda: [
                    {category: mean(row["annual_categories"][offset][category] for row in family_rows)
                     for category in CATEGORIES[family]} for offset in range(3)]),
                "weighted_category_bias_from_F1": _aggregate_diagnostic(family_n, lambda: {
                    category: mean(row["forecast_categories"][category] -
                        weighted_h3([annual[category] for annual in row["annual_categories"]])
                        for row in family_rows) for category in CATEGORIES[family]}),
                "target_mean": _aggregate_diagnostic(family_n, lambda: mean(row["H3"] for row in family_rows)),
            }
        diagnostics[name]["family_contributions"] = family_diagnostics
        diagnostics[name]["zero_production_fraction"] = {"n": n,
            "fraction": _aggregate_diagnostic(n, lambda:
                sum(row["verified_zero_production"] for row in available) / len(available))}
        diagnostics[name]["multiplier_and_baseline"] = {
            "n": n, "predicted_n": len(predicted),
            "mean_candidate_multiplier": _aggregate_diagnostic(n, lambda:
                mean(row["candidate_multiplier"] for row in available)),
            "mean_centering": _aggregate_diagnostic(n, lambda: mean(row["C_fam"] for row in available)),
            "full_universe_B": _aggregate_diagnostic(len(predicted), lambda: predicted[0]["B"]),
            "mean_target_bias": _aggregate_diagnostic(n, lambda:
                mean(row["candidate"] - row["H3"] for row in available)),
        }
        diagnostics[name]["component_movement"] = {
            model: {"n": n,
                    "mean_score_shift_from_F1": _aggregate_diagnostic(n, lambda:
                        mean(row[model] - row["F1"] for row in available)),
                    "mean_absolute_rank_shift": _aggregate_diagnostic(n, lambda: float(np.mean(np.abs(
                        average_ranks([row[model] for row in available]) -
                        average_ranks([row["F1"] for row in available])))))}
            for model in ("hand_set", "candidate")}
    return diagnostics
