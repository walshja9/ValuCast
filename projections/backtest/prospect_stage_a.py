"""Research-only Stage A checks; this module has no serving entry point."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import lru_cache, wraps
import hashlib
import json
from pathlib import Path
import re
from statistics import mean, pstdev
from types import FunctionType

import numpy as np
from scipy.stats import kendalltau

from prospects import model
from prospects.gate import decide_gate
from prospects.input_contract import SUPPORTED_SCHEMA_SOURCES, validate_factual_contract
from prospects.raw_input_builder import ROOKIE_AB_LIMIT, ROOKIE_IP_LIMIT, _service_totals


SEED = 20261103
SEALED_COHORT = 2022
FAMILIES = ("outcome-hitter", "outcome-pitcher", "impact-hitter", "impact-pitcher")
FIXED_NOW = "2026-11-03T00:00:00+00:00"


class SealedDataError(Exception):
    pass


class EquivalenceError(Exception):
    pass


class FreezeError(Exception):
    pass


def canonical_bytes(value) -> bytes:
    def scalar(item):
        if isinstance(item, np.ndarray):
            return item.tolist()
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(type(item).__name__)

    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False, default=scalar) + "\n").encode("utf-8")


@dataclass
class SafeContract:
    rows: list[dict]
    seasons_by_player: dict
    current: dict
    input_sha256: str
    sealed_ids_sha256: str
    counts: dict
    mlb_service: list[dict]
    service_consistent: bool
    _sealed_ids: frozenset[int] = field(default_factory=frozenset, repr=False)
    _reference_windows: dict = field(default_factory=dict, repr=False)

    @property
    def sealed_ids(self):
        return self._sealed_ids


def assert_no_sealed(rows, seasons_by_player, sealed_ids):
    if any(int(row.get("cohort_year", 9999)) >= 2020
           or int(row.get("mlbam_id") or 0) in sealed_ids for row in rows):
        raise SealedDataError()
    if any(int(str(key).split("_", 1)[0]) in sealed_ids for key in seasons_by_player):
        raise SealedDataError()


def sealed_guarded(function):
    @wraps(function)
    def guarded(safe, *args, **kwargs):
        assert_no_sealed(safe.rows, safe.seasons_by_player, safe.sealed_ids)
        assert_no_sealed([], safe._reference_windows, safe.sealed_ids)
        for group in ("hitters", "pitchers"):
            if any(int(row.get("mlbam_id") or 0) in safe.sealed_ids
                   for row in safe.current.get(group, [])):
                raise SealedDataError()
        return function(safe, *args, **kwargs)
    return guarded


def assert_serialization_safe(safe, payload):
    assert_no_sealed(safe.rows, safe.seasons_by_player, safe.sealed_ids)
    assert_no_sealed([], safe._reference_windows, safe.sealed_ids)
    content = json.loads(payload if isinstance(payload, bytes) else canonical_bytes(payload))
    tokens = re.compile(r"(?<![\w.])(?:" + "|".join(map(str, safe.sealed_ids)) + r")(?![\w.])") if safe.sealed_ids else None
    pending = [content]
    while pending:
        value = pending.pop()
        if type(value) is int and value in safe.sealed_ids:
            raise SealedDataError()
        if isinstance(value, str) and tokens is not None and tokens.search(value):
            raise SealedDataError()
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


def load_sealed_safe_contract(path) -> SafeContract:
    raw = Path(path).read_bytes()
    payload = json.loads(raw)
    input_sha256 = hashlib.sha256(raw).hexdigest()
    if not isinstance(payload, dict) or validate_factual_contract(payload):
        raise ValueError("invalid factual contract")
    records = payload["historical"]["rows"]
    sealed_rows = [row for row in records if int(row["cohort_year"]) == SEALED_COHORT]
    sealed_ids = frozenset(int(row["mlbam_id"]) for row in sealed_rows if row.get("mlbam_id"))
    reference_windows = {}
    for row in records:
        if row.get("mlbam_id") and int(row["mlbam_id"]) not in sealed_ids:
            key = f"{int(row['mlbam_id'])}_{row['role']}"
            year = int(row["cohort_year"])
            reference_windows[key] = min(reference_windows.get(key, year), year)
    dual_ids = {int(row["mlbam_id"]) for row in records
                if int(row["cohort_year"]) <= model.MATURE_THROUGH
                and int(row.get("mlbam_id") or 0) in sealed_ids}
    rows = [copy.deepcopy(row) for row in records
            if int(row["cohort_year"]) <= model.MATURE_THROUGH
            and int(row.get("mlbam_id") or 0) not in sealed_ids]
    seasons = {key: copy.deepcopy(value) for key, value in payload["historical_mlb_seasons"].items()
               if int(str(key).split("_", 1)[0]) not in sealed_ids}
    current = {key: copy.deepcopy(value) for key, value in payload["current"].items()
               if key not in ("hitters", "pitchers")}
    excluded_current = set()
    for group in ("hitters", "pitchers"):
        excluded_current.update(int(row["mlbam_id"]) for row in payload["current"][group]
                                if int(row.get("mlbam_id") or 0) in sealed_ids)
        current[group] = [copy.deepcopy(row) for row in payload["current"][group]
                          if int(row.get("mlbam_id") or 0) not in sealed_ids]
    stored_service = {(int(row["mlbam_id"]), row["role"]): row
                      for row in payload["mlb_service"]
                      if int(row.get("mlbam_id") or 0) not in sealed_ids}
    service = []
    seen = set()
    for role, group in (("hitter", "hitters"), ("pitcher", "pitchers")):
        for row in current[group]:
            player_id = int(row.get("mlbam_id") or 0)
            if not player_id or (player_id, role) in seen:
                continue
            seen.add((player_id, role))
            totals = _service_totals(seasons, player_id, role)
            fact = {"mlbam_id": player_id, "role": role, **totals,
                    "graduated": totals["ab"] >= ROOKIE_AB_LIMIT or totals["ip"] >= ROOKIE_IP_LIMIT}
            original = stored_service.get((player_id, role))
            if original is not None and any(original.get(key) != fact[key]
                                            for key in ("pa", "ab", "ip", "graduated")):
                raise ValueError("inconsistent service contract")
            service.append(fact)
    result = SafeContract(rows, seasons, current, input_sha256,
                          hashlib.sha256(canonical_bytes(sorted(sealed_ids))).hexdigest(),
                          {"sealed_rows_seen": len(sealed_rows), "sealed_ids": len(sealed_ids),
                           "dual_cohort_players_removed": len(dual_ids),
                           "current_board_ids_excluded": len(excluded_current)},
                          service, True, sealed_ids, reference_windows)
    assert_no_sealed(result.rows, result.seasons_by_player, sealed_ids)
    del payload, records, raw, stored_service, sealed_rows
    return result


def neighbor_indices(train, test, feature_key="features"):
    neighbors = model._fit_neighbors(train, feature_key)
    if neighbors is None:
        return []
    selected = []
    for row in test:
        x = [(value - center) / spread for value, center, spread in
             zip(row.get(feature_key, row["features"]), neighbors["means"], neighbors["stds"])]
        distances = [(sum((left - right) ** 2 for left, right in zip(features, x)), index)
                     for index, features in enumerate(neighbors["features"])]
        selected.append([index for _, index in sorted(distances)[:model.NEIGHBOR_K]])
    return selected


def _ridge_prediction(train_x, targets, test_x, ridge_lambda):
    if len(targets) == 0:
        return None
    centers = train_x.mean(axis=0)
    spreads = train_x.std(axis=0)
    constant = np.all(train_x == train_x[0], axis=0)
    centers = np.where(constant, train_x[0], centers)
    spreads = np.where(constant | (spreads == 0.0), 1.0, spreads)
    design = np.column_stack((np.ones(len(targets)), (train_x - centers) / spreads))
    penalty = np.eye(design.shape[1]) * ridge_lambda
    penalty[0, 0] = 0.0
    weights = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
    test_design = np.column_stack((np.ones(len(test_x)), (test_x - centers) / spreads))
    return np.clip(test_design @ weights, 0.0, 1.0)


def _concordance(predictions, targets):
    if not len(targets):
        return None
    pairs = len(targets) * (len(targets) - 1) // 2
    _, target_counts = np.unique(targets, return_counts=True)
    _, prediction_counts = np.unique(predictions, return_counts=True)
    target_pairs = pairs - int(np.sum(target_counts * (target_counts - 1) // 2))
    prediction_pairs = pairs - int(np.sum(prediction_counts * (prediction_counts - 1) // 2))
    if not target_pairs:
        return None
    if not prediction_pairs:
        return 0.5
    tau = float(kendalltau(predictions, targets).statistic)
    return 0.5 + tau * (target_pairs * prediction_pairs) ** 0.5 / (2 * target_pairs)


class WalkForwardEngine:
    def __init__(self, rows, model_kind="hurdle_ridge", ridge_lambda=10.0,
                 neighbor_feature_key="features"):
        if model_kind not in ("ridge", "hurdle_ridge"):
            raise ValueError("unknown architecture")
        self.rows = rows
        self.targets = np.asarray([row["target"] for row in rows], dtype=float)
        self.model_kind = model_kind
        self.ridge_lambda = ridge_lambda
        self.neighbor_feature_key = neighbor_feature_key
        self.features = np.asarray([row["features"] for row in rows], dtype=float)
        self.cohorts = sorted({row["cohort_year"] for row in rows})
        self.folds = [self._fold(year) for year in self.cohorts[2:]]

    def _fold(self, year, train_filter=None):
        train_indices = np.asarray([i for i, row in enumerate(self.rows)
                                    if row["cohort_year"] < year
                                    and (train_filter is None or train_filter(row, year))], dtype=int)
        test_indices = np.asarray([i for i, row in enumerate(self.rows)
                                   if row["cohort_year"] == year], dtype=int)
        train = [self.rows[i] for i in train_indices]
        test = [self.rows[i] for i in test_indices]
        canonical_train = [{**row, "features": row.get("baseline_features", row["features"])}
                           for row in train]
        canonical_test = [{**row, "features": row.get("baseline_features", row["features"])}
                          for row in test]
        keys = [f"{row['level']}|{model._age_bucket(row['age'])}" for row in train]
        cells = {key: i for i, key in enumerate(dict.fromkeys(keys))}
        return {"test_year": year, "train_indices": train_indices, "test_indices": test_indices,
                "neighbors": neighbor_indices(train, test, self.neighbor_feature_key),
                "canonical_neighbors": neighbor_indices(canonical_train, canonical_test),
                "cell_indices": np.asarray([cells[key] for key in keys], dtype=int),
                "test_cells": np.asarray([cells.get(f"{row['level']}|{model._age_bucket(row['age'])}", -1)
                                          for row in test], dtype=int), "n_cells": len(cells)}

    def run(self, targets=None, train_filter=None):
        labels = self.targets if targets is None else np.asarray(targets, dtype=float)
        if labels.shape != self.targets.shape:
            raise ValueError("target shape mismatch")
        output = {key: [] for key in ("model_predictions", "prior_predictions", "neighbor_predictions",
                                      "canonical_neighbor_predictions", "targets", "folds")}
        folds = self.folds if train_filter is None else [self._fold(year, train_filter) for year in self.cohorts[2:]]
        for fold in folds:
            train_indices, test_indices = fold["train_indices"], fold["test_indices"]
            if not len(train_indices) or not len(test_indices):
                continue
            train_targets = labels[train_indices]
            train_x, test_x = self.features[train_indices], self.features[test_indices]
            if self.model_kind == "ridge":
                predictions = _ridge_prediction(train_x, train_targets, test_x, self.ridge_lambda)
            else:
                positive = train_targets > 0
                if not np.any(positive):
                    continue
                arrival = _ridge_prediction(train_x, positive.astype(float), test_x, self.ridge_lambda)
                conditional = _ridge_prediction(train_x[positive], train_targets[positive], test_x, self.ridge_lambda)
                predictions = arrival * conditional
            overall = float(train_targets.mean())
            sums = np.bincount(fold["cell_indices"], weights=train_targets, minlength=fold["n_cells"])
            counts = np.bincount(fold["cell_indices"], minlength=fold["n_cells"])
            cell_means = (sums + overall * model.PRIOR_K) / (counts + model.PRIOR_K)
            prior = [float(cell_means[index]) if index >= 0 else overall for index in fold["test_cells"]]
            neighbor = [mean(float(train_targets[i]) for i in indices) for indices in fold["neighbors"]]
            canonical = [mean(float(train_targets[i]) for i in indices) for indices in fold["canonical_neighbors"]]
            output["model_predictions"].extend(predictions.tolist())
            output["prior_predictions"].extend(prior)
            output["neighbor_predictions"].extend(neighbor)
            output["canonical_neighbor_predictions"].extend(canonical)
            output["targets"].extend(labels[test_indices].tolist())
            output["folds"].append({"test_year": fold["test_year"],
                                     "train_year_max": max(self.rows[i]["cohort_year"] for i in train_indices),
                                     "train_ids": [self.rows[i]["mlbam_id"] for i in train_indices],
                                     "test_ids": [self.rows[i]["mlbam_id"] for i in test_indices]})
        for label, prediction_key in (("model", "model_predictions"), ("prior", "prior_predictions"),
                                      ("neighbor", "neighbor_predictions"), ("canonical_neighbor", "canonical_neighbor_predictions")):
            output[f"{label}_mae"] = (mean(abs(prediction - target) for prediction, target in
                                          zip(output[prediction_key], output["targets"]))
                                       if output["targets"] else None)
        output["rank_concordance"] = _concordance(output["model_predictions"], output["targets"])
        return output


def prepare_families(safe):
    assert_no_sealed(safe.rows, safe.seasons_by_player, safe.sealed_ids)
    references = model._impact_references(safe.seasons_by_player)
    families = {}
    for axis in ("outcome", "impact"):
        for role in ("hitter", "pitcher"):
            rows = (model._historical_rows(safe.rows, role, model.MATURE_THROUGH) if axis == "outcome"
                    else model._historical_impact_rows(safe.rows, role, safe.seasons_by_player, references,
                                                       model.MATURE_THROUGH))
            families[f"{axis}-{role}"] = {"rows": rows, "model_kind": "hurdle_ridge",
                                        "ridge_lambda": (model.HITTER_IMPACT_RIDGE_LAMBDA
                                                         if axis == "impact" and role == "hitter" else model.RIDGE_LAMBDA),
                                        "neighbor_feature_key": "baseline_features" if axis == "outcome" else "features"}
    return families


def gate_for(validation, axis="outcome", min_sample=None):
    baselines = {"level_age_prior": validation["prior_mae"],
                 "historical_neighbors_25": validation["neighbor_mae"]}
    if axis == "impact":
        baselines["canonical_historical_neighbors_25"] = validation["canonical_neighbor_mae"]
    return decide_gate(metric="outcome_score_mae" if axis == "outcome" else "category_impact_mae",
                       model_score=validation["model_mae"], baselines=baselines,
                       sample_size=len(validation["targets"]), cv_method="walk_forward",
                       validated_through=str(model.MATURE_THROUGH),
                       min_sample=model.MIN_GATE_SAMPLE if min_sample is None else min_sample,
                       min_improvement_pct=model.MIN_GATE_IMPROVEMENT_PCT,
                       lower_is_better=True, now=FIXED_NOW)


@sealed_guarded
def engine_equivalence(safe):
    evidence = {}
    for family, settings in prepare_families(safe).items():
        evidence[family] = {}
        for kind in ("ridge", "hurdle_ridge"):
            arguments = {**settings, "model_kind": kind}
            served = model._walk_forward(arguments["rows"], kind, arguments["ridge_lambda"],
                                         arguments["neighbor_feature_key"])
            fast = WalkForwardEngine(**arguments).run()
            maximum = 0.0
            for key in ("model_predictions", "prior_predictions", "neighbor_predictions",
                        "canonical_neighbor_predictions", "targets"):
                left, right = np.asarray(served[key]), np.asarray(fast[key])
                if left.shape != right.shape or not np.allclose(left, right, atol=1e-8, rtol=0.0):
                    raise EquivalenceError()
                if left.size:
                    maximum = max(maximum, float(np.max(np.abs(left - right))))
            axis = family.split("-", 1)[0]
            if gate_for(served, axis)["improvement_pct"] != gate_for(fast, axis)["improvement_pct"]:
                raise EquivalenceError()
            evidence[family][kind] = {"equivalent": True, "maximum_absolute_difference": maximum,
                                      "sample_size": len(fast["targets"])}
    return evidence


def permute_targets(rows, stage_id, family_id, config_id, draw_index, cell_stratified=False):
    child = np.random.SeedSequence([SEED, stage_id, family_id, config_id], spawn_key=(draw_index,))
    rng = np.random.default_rng(child)
    targets = np.asarray([row["target"] for row in rows], dtype=float)
    groups = {}
    for index, row in enumerate(rows):
        key = (row["cohort_year"], row["level"], model._age_bucket(row["age"])) if cell_stratified else row["cohort_year"]
        groups.setdefault(key, []).append(index)
    for indices in groups.values():
        targets[indices] = rng.permutation(targets[indices])
    return targets


def synthetic_contract(signal=True, seed=SEED, rows_per_cohort=12):
    rng = np.random.default_rng(np.random.SeedSequence([SEED, int(seed)]))
    rows, seasons = [], {}

    def record(player_id, role, year, index, latent):
        feature_signal = latent if signal else float(rng.choice([0.0, 0.5, 1.0]))
        q = float(rng.uniform(0.0, 1.0))
        row = {"mlbam_id": player_id, "cohort_year": year, "role": role,
               "name": f"Synthetic {player_id}", "normalized_name": f"synthetic {player_id}",
               "age": 21, "level": "AA", "outcome": ("bust" if latent == 0 else "role" if latent == 0.5 else "star"),
               "draft_record_known": True, "rule4_drafted": True,
               "draft_pick_number": 1 if feature_signal == 1 else 10 if feature_signal == 0.5 else 1000,
               "draft_round": 1 if feature_signal else 20, "pick_value": feature_signal,
               "signing_bonus": 1000000 * feature_signal, "school_type": "college", "bats": "R", "throws": "R",
               "source_kind": "current_season", "sample_season": 2026, "position": "OF" if role == "hitter" else "P"}
        if role == "hitter":
            row.update(plate_appearances=300 + index, iso=0.15 + q * 0.08, k_pct=18 + q * 8,
                       bb_pct=8 + q * 3, ops=0.70 + q * 0.1, avg=0.25 + q * 0.02,
                       obp=0.32 + q * 0.02, slg=0.40 + q * 0.03, babip=0.30 + q * 0.01,
                       home_runs=8 + index % 4, stolen_bases=index % 7)
        else:
            row.update(innings_pitched=70 + index, k_per_9=8 + q * 2, bb_per_9=2 + q,
                       k_bb_pct=15 + q * 5, era=3 + q, whip=1.1 + q * 0.2, is_starter=True,
                       home_runs=8 + index % 3, hits=60 + index, walks=20 + index,
                       batters_faced=300 + index, games_started=15, games=18, games_played=18)
        return row

    for role_id, role in enumerate(("hitter", "pitcher")):
        for cohort_id, year in enumerate(range(2014, 2020)):
            latents = np.resize(np.asarray([0.0, 0.5, 1.0]), rows_per_cohort)
            rng.shuffle(latents)
            for index, latent in enumerate(latents):
                player_id = 100000 + role_id * 10000 + cohort_id * 1000 + index
                rows.append(record(player_id, role, year, index, float(latent)))
                key = f"{player_id}_{role}"
                seasons[key] = []
                if latent:
                    q = float(latent) + float(rng.uniform(-0.02, 0.02))
                    season = ({"year": year + 1, "pa": 400, "ab": 350, "r": 20 + q * 70,
                               "hr": 4 + q * 35, "rbi": 20 + q * 80, "sb": 2 + q * 20,
                               "avg": 0.20 + q * 0.10, "ops": 0.55 + q * 0.45, "so": 180 - q * 100}
                              if role == "hitter" else
                              {"year": year + 1, "ip": 100, "so": 50 + q * 120, "qs": q * 20,
                               "sv": q * 5, "hld": q * 5, "era": 6 - q * 4, "whip": 1.8 - q * 0.8,
                               "k_bb": 1 + q * 4, "l": 15 - q * 10})
                    seasons[key].append(season)
    seasons["100001_hitter"].append({"year": 2022, "pa": 200, "ab": 180, "r": 20, "hr": 5,
                                      "rbi": 20, "sb": 3, "avg": 0.25, "ops": 0.7, "so": 60})
    current = {"season": 2026, "fetched_date": "2026-11-03", "hitters": [], "pitchers": []}
    for role_id, role in enumerate(("hitter", "pitcher")):
        for index in range(6):
            player_id = 800000 + role_id * 1000 + index
            row = record(player_id, role, 2019, index, (index % 3) / 2)
            row.pop("cohort_year")
            row.pop("outcome")
            if index == 0:
                row["level"] = "A"
            if index == 1:
                row["draft_record_known"] = False
                row["draft_pick_number"] = None
            if index == 2:
                row["iso" if role == "hitter" else "k_per_9"] = 2.0 if role == "hitter" else 30.0
            current["hitters" if role == "hitter" else "pitchers"].append(row)
            seasons[f"{player_id}_{role}"] = []
    for index, player_id in enumerate((9000001, 9000002)):
        row = record(player_id, "hitter", 2022, index, 1.0)
        row["sealed_sentinel"] = "SYNTHETIC_SEALED_SENTINEL"
        rows.append(row)
        seasons[f"{player_id}_hitter"] = [{"year": 2023, "pa": 999999, "sealed_sentinel": "SYNTHETIC_SEALED_SENTINEL"}]
        if index == 1:
            rows.append({**row, "cohort_year": 2016})
        current["hitters"].append({**row, "cohort_year": 2022})
    for year in (2020, 2021):
        rows.append(record(700000 + year, "hitter", year, 0, 0.5))
    service = []
    for role, group in (("hitter", "hitters"), ("pitcher", "pitchers")):
        for row in current[group]:
            totals = _service_totals(seasons, row["mlbam_id"], role)
            service.append({"mlbam_id": row["mlbam_id"], "role": role, **totals,
                            "graduated": totals["ab"] >= ROOKIE_AB_LIMIT or totals["ip"] >= ROOKIE_IP_LIMIT})
    return {"schema_version": "1.2", "generated_at": FIXED_NOW,
            "source_policy": {"kind": "factual_only", "sources": sorted(SUPPORTED_SCHEMA_SOURCES["1.2"]),
                              "external_rankings_used": False, "external_projections_used": False,
                              "market_values_used": False, "dynasty_values_used": False},
            "historical": {"rows": rows, "cohorts": [2022], "omitted_cohorts": [2022]},
            "historical_mlb_seasons": seasons, "current": current, "mlb_service": service}


# Stage outputs contain aggregates; player-aligned objects remain local to computations.
from dataclasses import replace
import platform
import time
import scipy
from scipy.stats import binom, spearmanr
from prospects import impact_oof
from prospects.stage1_outcome_proof import _metric


REPETITIONS = {1: 5000, 2: 5000, 3: 2000}
BOOTSTRAPS = 5000
_EQUIVALENT = {}
LAST_CALIBRATION_SECONDS = None
MECHANICAL_NOTES = [
    "Stored service is checked inside the loader before discarding it.",
    "Sealed current candidates are removed at load so no later board path can expose them.",
    "Raw margins are retained when decide_gate returns insufficient_sample without a margin.",
    "Calibration timing is measured separately from byte-stable result artifacts.",
    "R1 uses private id-to-cohort metadata for nonsealed players including 2020/2021, without retaining their outcome rows; missing nonempty-store windows abort instead of being guessed.",
    "The line-selection counterfactual keeps the first eligible input line per player.",
    "The calibration band is predeclared at 99%; best-of-8 calibration uses max-versus-max and separately records the conservative realized-versus-max comparison.",
    "Permutation children use the exactly spawn-equivalent spawn_key for constant-time resume access.",
    "Outcome dataset builder and historical cache writer were not located in the permitted source search; horizon uses the served four-year constant.",
]


def _fingerprint(safe):
    return hashlib.sha256(canonical_bytes([safe.rows, safe.seasons_by_player])).hexdigest()


def _ensure_equivalence(safe):
    key = _fingerprint(safe)
    if key not in _EQUIVALENT:
        _EQUIVALENT[key] = engine_equivalence(safe)
    return _EQUIVALENT[key]


def _margin(validation, axis):
    baselines = [validation["prior_mae"], validation["neighbor_mae"]]
    if axis == "impact":
        baselines.append(validation["canonical_neighbor_mae"])
    available = [value for value in baselines if value is not None]
    if not available or validation["model_mae"] is None:
        return None
    best = min(available)
    return (best - validation["model_mae"]) / abs(best) * 100 if best else 0.0


def _ordering(validation, observed=False):
    result = {}
    metrics = ["spearman_rho", "roc_auc"] + (["kendall_tau_b"] if observed else [])
    for metric in metrics:
        own = _metric(metric, validation["model_predictions"], validation["targets"])
        result[metric] = {"model": own}
        for baseline in ("prior", "neighbor", "canonical_neighbor"):
            value = _metric(metric, validation[baseline + "_predictions"], validation["targets"])
            result[metric][baseline] = value
            result[metric]["delta_" + baseline] = own - value if own is not None and value is not None else None
    return result


def _slice_validation(validation, indices):
    result = {key: [values[i] for i in indices] for key, values in validation.items()
              if key in ("targets", "model_predictions", "prior_predictions", "neighbor_predictions", "canonical_neighbor_predictions")}
    for name in ("model", "prior", "neighbor", "canonical_neighbor"):
        result[name + "_mae"] = (mean(abs(a - b) for a, b in zip(result[name + "_predictions"], result["targets"]))
                                 if result["targets"] else None)
    result["folds"] = []
    return result


def _summary(validation, axis, observed=True):
    result = {name + "_mae": validation[name + "_mae"]
              for name in ("model", "prior", "neighbor", "canonical_neighbor")}
    result.update(sample_size=len(validation["targets"]), margin=_margin(validation, axis),
                  gate=gate_for(validation, axis), ordering=_ordering(validation, observed))
    offset = 0
    result["folds"] = []
    for fold in validation.get("folds", []):
        count = len(fold["test_ids"])
        local = _slice_validation(validation, range(offset, offset + count))
        result["folds"].append({"test_year": fold["test_year"], "train_year_max": fold["train_year_max"],
                                 "training_sample": len(fold["train_ids"]), "test_sample": count,
                                 "margin": _margin(local, axis), "ordering": _ordering(local, observed),
                                 "model_mae": local["model_mae"], "gate": gate_for(local, axis)})
        offset += count
    return result


def _distribution(values):
    undefined = sum(value is None for value in values)
    values = np.asarray([value for value in values if value is not None], dtype=float)
    if not len(values):
        return {"n": 0, "undefined": undefined, "mean": None, "sd": None, "quantiles": None, "max": None}
    return {"n": len(values), "undefined": undefined, "mean": float(values.mean()), "sd": float(values.std()),
            "quantiles": dict(zip(("0", "25", "50", "75", "95", "99", "100"),
                                  np.percentile(values, [0, 25, 50, 75, 95, 99, 100]).tolist())),
            "max": float(values.max())}


def _p_value(observed, draws):
    return (1 + sum(value is None or value >= observed for value in draws)) / (len(draws) + 1) if observed is not None and draws else None


def _bootstrap(validation, family_id, resamples=BOOTSTRAPS):
    rows, offset = [], 0
    for fold in validation["folds"]:
        for i in range(offset, offset + len(fold["test_ids"])):
            target = validation["targets"][i]
            rows.append({"test_cohort": fold["test_year"], "model_error": abs(validation["model_predictions"][i] - target),
                         **{name + "_error": abs(validation[name + "_predictions"][i] - target)
                            for name in ("prior", "neighbor", "canonical_neighbor")}})
        offset += len(fold["test_ids"])
    seed = int(np.random.SeedSequence([SEED, 99, family_id]).generate_state(1)[0])
    return {name: impact_oof.cohort_player_bootstrap(rows, baseline_error_key=name + "_error", seed=seed, resamples=resamples)
            for name in ("prior", "neighbor", "canonical_neighbor")}


@sealed_guarded
def stage_0(safe, bootstrap_resamples=BOOTSTRAPS):
    # This certificate is obtained before any null draw, including resumed runs.
    equivalence = engine_equivalence(safe)
    _EQUIVALENT[_fingerprint(safe)] = equivalence
    result = {"equivalence": equivalence, "counts": safe.counts,
              "input_sha256": safe.input_sha256, "sealed_ids_sha256": safe.sealed_ids_sha256,
              "versions": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
              "families": {}}
    for family_id, (family, settings) in enumerate(prepare_families(safe).items()):
        validation = WalkForwardEngine(**settings).run()
        result["families"][family] = {**_summary(validation, family.split("-")[0]),
                                      "bootstrap": _bootstrap(validation, family_id, bootstrap_resamples)}
    return result


def _checkpoint(safe, out, stage_id, family, draw, identity):
    if out is not None:
        payload = {"identity": identity, "draws": draw}
        assert_serialization_safe(safe, payload)
        _output_path(out, f"checkpoint-{stage_id}-{family}.json").write_bytes(canonical_bytes(payload))


def _resume_draws(safe, out, stage_id, family, identity, resume):
    path = _output_path(out, f"checkpoint-{stage_id}-{family}.json") if resume and out is not None else None
    if not resume or path is None or not path.exists():
        return []
    payload = json.loads(path.read_bytes())
    assert_serialization_safe(safe, payload)
    if payload["identity"] != identity:
        raise FreezeError()
    return payload["draws"]


def _checkpoint_identity(safe, stage_id, family, **options):
    from scripts.run_prospect_stage_a import build_freeze_manifest

    return {"input": safe.input_sha256, "safe": _fingerprint(safe), "seed": SEED,
            "stage": stage_id, "family": family,
            "freeze": build_freeze_manifest(safe.input_sha256), **options}


@sealed_guarded
def null_experiment(safe, family, stage_id, reps, out=None, resume=False, deadline=None):
    _ensure_equivalence(safe)
    settings = prepare_families(safe)[family]
    engine = WalkForwardEngine(**settings)
    axis = family.split("-")[0]
    observed = _summary(engine.run(), axis)
    identity = _checkpoint_identity(safe, stage_id, family)
    draws = _resume_draws(safe, out, stage_id, family, identity, resume)[:reps]
    for index in range(len(draws), reps):
        if deadline is not None and time.monotonic() >= deadline:
            break
        labels = permute_targets(settings["rows"], stage_id, FAMILIES.index(family), 0, index, stage_id == 2)
        validation = engine.run(labels)
        draws.append({"margin": _margin(validation, axis), "active": gate_for(validation, axis)["status"] == "active",
                      "ordering": _ordering(validation), **{name + "_mae": validation[name + "_mae"]
                      for name in ("model", "prior", "neighbor", "canonical_neighbor")}})
        if len(draws) % 250 == 0:
            _checkpoint(safe, out, stage_id, family, draws, identity)
    _checkpoint(safe, out, stage_id, family, draws, identity)
    p = _p_value(observed["margin"], [row["margin"] for row in draws])
    partial = len(draws) < REPETITIONS[stage_id]
    distribution = _distribution([row["margin"] for row in draws])
    concern = None
    if not partial:
        concern = bool((p is not None and p > .05 and observed["gate"]["status"] == "active")
                       or (stage_id == 2 and (sum(row["active"] for row in draws) / len(draws) > .05
                           or (distribution["quantiles"] is not None and distribution["quantiles"]["50"] > 1.0))))
    return {"observed": observed, "p_value": p, "null": distribution,
            "mae_nulls": {name: _distribution([row[name + "_mae"] for row in draws]) for name in ("model", "prior", "neighbor", "canonical_neighbor")},
            "ordering_nulls": {metric: {baseline: {"null": _distribution([row["ordering"][metric]["delta_" + baseline] for row in draws]),
                                                  "p_value": _p_value(observed["ordering"][metric]["delta_" + baseline], [row["ordering"][metric]["delta_" + baseline] for row in draws])}
                                           for baseline in ("prior", "neighbor", "canonical_neighbor")}
                               for metric in ("spearman_rho", "roc_auc")},
            "false_active_rate": sum(row["active"] for row in draws) / len(draws) if draws else None,
            "draws_completed": len(draws), "partial": partial, "concern": concern,
            "interpretation": None if partial else ("noise_artifact_not_sufficient" if p is not None and p <= .01 else "ambiguous" if p is not None and p <= .05 else "within_noise_null")}


def configuration_grid():
    return [{"name": f"{features}-{kind}-{lam:g}", "features": features, "model_kind": kind, "ridge_lambda": lam}
            for features in ("promoted", "without_pedigree") for lam in (3.0, 10.0) for kind in ("hurdle_ridge", "ridge")]


def _reference_summary(references, role, baseline=None):
    result = {"sha256": impact_oof._canonical_sha256(references),
              "counts": {category: len(values) for category, values in references[role].items()},
              "active_categories": list(model._active_impact_categories(references, role)), "deciles": {},
              "largest_decile_rank_displacement": {}}
    for category, values in references[role].items():
        cutpoints = np.percentile(values, np.arange(10, 100, 10)).tolist() if values else []
        result["deciles"][category] = cutpoints
        original = baseline[role][category] if baseline is not None else values
        result["largest_decile_rank_displacement"][category] = max(
            (abs(model._percentile(values, point) - model._percentile(original, point)) for point in cutpoints), default=0.0)
    return result


def _window_seasons(safe):
    windows = safe._reference_windows
    return {key: [season for season in seasons if windows[key] < int(season.get("year") or 0) <= windows[key] + model.OUTCOME_HORIZON_YEARS]
            for key, seasons in safe.seasons_by_player.items() if key in windows}


def _evidence_validation(evidence):
    result = {"targets": [row["target"] for row in evidence["rows"]], "folds": []}
    for name in ("model", "prior", "neighbor", "canonical_neighbor"):
        result[name + "_predictions"] = [row[name + "_prediction"] for row in evidence["rows"]]
        result[name + "_mae"] = (mean(abs(pred - target) for pred, target in zip(result[name + "_predictions"], result["targets"])) if result["targets"] else None)
    for fold in evidence["folds"]:
        if fold["status"] == "scored":
            result["folds"].append({"test_year": fold["test_cohort"], "train_year_max": fold["train_cohort_max"],
                                     "train_ids": fold["train_ids"], "test_ids": fold["test_ids"]})
    return result


@sealed_guarded
def reference_variants(safe, role):
    original_refs = model._impact_references(safe.seasons_by_player)
    window_refs = model._impact_references(_window_seasons(safe))
    result = {}
    for name, references in (("R0", original_refs), ("R1", window_refs)):
        fitted = model.train_impact_role(role, safe.rows, safe.seasons_by_player, references, now=FIXED_NOW)
        rows = model._historical_impact_rows(safe.rows, role, safe.seasons_by_player, references, model.MATURE_THROUGH)
        result[name] = {"validation": fitted["_validation"], "rows": rows,
                        "reference_summary": _reference_summary(references, role, original_refs)}
    excluded = [seasons for key, seasons in safe.seasons_by_player.items()
                if key.endswith("_" + role) and key not in safe._reference_windows]
    result["R1"]["reference_summary"].update(excluded_players_without_window=len(excluded),
                                              excluded_seasons_without_window=sum(map(len, excluded)))
    evidence = impact_oof.fold_local_impact_oof(safe.rows, safe.seasons_by_player, role, model.MATURE_THROUGH)
    templates = impact_oof._eligible_templates(safe.rows, role, model.MATURE_THROUGH)
    training_labels, summaries = {}, []
    for fold in evidence["folds"]:
        year = fold["test_cohort"]
        contract = impact_oof._fold_reference_contract(templates, role, safe.seasons_by_player, year)
        training_labels[year] = [row for row in model._historical_impact_rows(safe.rows, role, safe.seasons_by_player, contract["references"], model.MATURE_THROUGH) if row["cohort_year"] < year]
        summaries.append({"test_year": year, "reference_player_count": contract["reference_player_count"],
                          "reference_season_count": contract["reference_season_count"],
                          "reference_source_sha256": contract["reference_source_sha256"],
                          **_reference_summary(contract["references"], role, original_refs)})
    result["R2"] = {"validation": _evidence_validation(evidence), "rows": templates, "evidence": evidence,
                    "training_labels": training_labels, "reference_summary": summaries, "folds": evidence["folds"]}
    return result


def _label_changes(before, after):
    old = {(row["cohort_year"], row["mlbam_id"]): row["target"] for row in before}
    grouped = {}
    for row in after:
        key = (row["cohort_year"], row["mlbam_id"])
        if key in old:
            grouped.setdefault(str(row["cohort_year"]), []).append(float(row["target"] - old[key]))
    return {year: {"n": len(values), "changed": sum(abs(value) > 1e-12 for value in values),
                   "share_changed": sum(abs(value) > 1e-12 for value in values) / len(values),
                   "mean_absolute_change": mean(abs(value) for value in values), "max_absolute_change": max(map(abs, values)),
                   "up": sum(value > 1e-12 for value in values), "down": sum(value < -1e-12 for value in values)}
            for year, values in grouped.items()}


def _margin_drop(before, after):
    return bool(before is not None and after is not None and before > after
                and before - after >= abs(before) * .5)


def _concern_change(before, after):
    return bool(before is not None and after is not None
                and (np.sign(before) != np.sign(after) or _margin_drop(before, after)))


@sealed_guarded
def stage_5(safe, bootstrap_resamples=BOOTSTRAPS):
    output = {"families": {family: {"applicable": False, "reason": "outcome_axis_unchanged"} for family in FAMILIES if family.startswith("outcome")}}
    for role in ("hitter", "pitcher"):
        variants = reference_variants(safe, role)
        family = "impact-" + role
        rows0 = variants["R0"]["rows"]
        validation0, validation2 = variants["R0"]["validation"], variants["R2"]["validation"]
        indexed0, offset = {}, 0
        for fold in validation0["folds"]:
            for player_id in fold["test_ids"]:
                indexed0[(fold["test_year"], player_id)] = abs(validation0["model_predictions"][offset] - validation0["targets"][offset])
                offset += 1
        paired = [{"test_cohort": row["test_cohort"], "model_error": row["model_error"],
                   "r0_error": indexed0[(row["test_cohort"], row["mlbam_id"])]} for row in variants["R2"]["evidence"]["rows"]
                  if (row["test_cohort"], row["mlbam_id"]) in indexed0]
        seed = int(np.random.SeedSequence([SEED, 99, FAMILIES.index(family)]).generate_state(1)[0])
        paired_bootstrap = impact_oof.cohort_player_bootstrap(paired, baseline_error_key="r0_error", seed=seed, resamples=bootstrap_resamples)
        summary0, summary2 = _summary(validation0, "impact"), _summary(validation2, "impact")
        concern = (summary0["gate"]["status"] == "active" and summary2["gate"]["status"] != "active"
                   or _margin_drop(summary0["margin"], summary2["margin"])
                   or paired_bootstrap["high"] is not None and paired_bootstrap["high"] < 0)
        output["families"][family] = {"variants": {name: {"validation": _summary(item["validation"], "impact"),
                                                                        "references": item["reference_summary"]}
                                                               for name, item in variants.items()},
                                               "R1_label_changes": _label_changes(rows0, variants["R1"]["rows"]),
                                               "R2_label_changes": {str(year): _label_changes(rows0, rows) for year, rows in variants["R2"]["training_labels"].items()},
                                               "paired_bootstrap_R0_error_minus_R2_error": paired_bootstrap,
                                               "concern": bool(concern),
                                               "structural_category_differences": {"R1": variants["R0"]["reference_summary"]["active_categories"] != variants["R1"]["reference_summary"]["active_categories"],
                                                                                   "R2": any(item["active_categories"] != variants["R0"]["reference_summary"]["active_categories"] for item in variants["R2"]["reference_summary"])}}
    return output


@sealed_guarded
def purge_validation(safe, family, clip=False, reference_regime="R0"):
    settings = prepare_families(safe)[family]
    axis, role = family.split("-")
    if not clip:
        result = WalkForwardEngine(**settings).run(train_filter=lambda row, year: row["cohort_year"] + model.OUTCOME_HORIZON_YEARS <= year)
        for fold in result["folds"]:
            fold["training_rows"] = [row for row in settings["rows"] if row["mlbam_id"] in fold["train_ids"]]
        return result
    if axis != "impact":
        raise ValueError("outcome labels cannot be clipped")
    output = {key: [] for key in ("model_predictions", "prior_predictions", "neighbor_predictions", "canonical_neighbor_predictions", "targets", "folds")}
    templates = impact_oof._eligible_templates(safe.rows, role, model.MATURE_THROUGH)
    for year in sorted({row["cohort_year"] for row in templates})[2:]:
        references = (model._impact_references(safe.seasons_by_player) if reference_regime == "R0" else
                      impact_oof._fold_reference_contract(templates, role, safe.seasons_by_player, year)["references"])
        clipped = {key: [season for season in seasons if int(season.get("year") or 0) <= year] for key, seasons in safe.seasons_by_player.items()}
        train_rows = model._historical_impact_rows(safe.rows, role, clipped, references, model.MATURE_THROUGH)
        test_rows = model._historical_impact_rows(safe.rows, role, safe.seasons_by_player, references, model.MATURE_THROUGH)
        rows = [row for row in train_rows if row["cohort_year"] < year] + [row for row in test_rows if row["cohort_year"] == year]
        engine = WalkForwardEngine(rows, settings["model_kind"], settings["ridge_lambda"], settings["neighbor_feature_key"])
        engine.folds = [engine._fold(year)]
        local = engine.run()
        used_ids = {row["mlbam_id"] for row in train_rows if row["cohort_year"] < year}
        max_season = max((int(season.get("year") or 0) for key, seasons in clipped.items() if int(key.split("_")[0]) in used_ids for season in seasons), default=None)
        for fold in local["folds"]:
            fold["max_training_season"] = max_season
            fold["training_rows"] = [row for row in train_rows if row["cohort_year"] < year]
            fold["training_seasons"] = clipped
        for key in output:
            output[key].extend(local[key])
    for name in ("model", "prior", "neighbor", "canonical_neighbor"):
        output[name + "_mae"] = mean(abs(a - b) for a, b in zip(output[name + "_predictions"], output["targets"])) if output["targets"] else None
    return output


@sealed_guarded
def stage_4(safe):
    result = {"families": {}, "outcome_horizon_years": model.OUTCOME_HORIZON_YEARS,
              "outcome_builder_source_verification": "not_located_in_permitted_source_directories"}
    for family, settings in prepare_families(safe).items():
        axis = family.split("-")[0]
        original = WalkForwardEngine(**settings).run()
        purged = purge_validation(safe, family)
        kept_years = {fold["test_year"] for fold in purged["folds"]}
        indices, offset = [], 0
        for fold in original["folds"]:
            if fold["test_year"] in kept_years:
                indices.extend(range(offset, offset + len(fold["test_ids"])))
            offset += len(fold["test_ids"])
        same_folds = _slice_validation(original, indices)
        local = {"P_drop": _summary(purged, axis), "unpurged_same_folds": _summary(same_folds, axis),
                 "absent_test_cohorts": sorted({fold["test_year"] for fold in original["folds"]} - kept_years),
                 "concern": _concern_change(_margin(same_folds, axis), _margin(purged, axis)),
                 "interpretation": "descriptive_only_no_contradiction_is_not_confirmation"}
        if axis == "impact":
            local["P_clip"] = {regime: _summary(purge_validation(safe, family, True, regime), axis) for regime in ("R0", "R2")}
            local["P_clip_unpurged"] = {"R0": _summary(original, axis),
                                         "R2": _summary(_evidence_validation(impact_oof.fold_local_impact_oof(safe.rows, safe.seasons_by_player, family.split("-")[1], model.MATURE_THROUGH)), axis)}
            local["P_clip_concern"] = {regime: _concern_change(local["P_clip_unpurged"][regime]["margin"], value["margin"]) for regime, value in local["P_clip"].items()}
        else:
            local["P_clip"] = {"applicable": False, "reason": "precomputed_outcome_labels"}
        result["families"][family] = local
    return result


@sealed_guarded
def _board(safe):
    if not safe.service_consistent:
        raise ValueError("inconsistent service contract")
    references = model._impact_references(safe.seasons_by_player)
    role_models = {role: model.train_role(role, safe.rows, now=FIXED_NOW) for role in ("hitter", "pitcher")}
    impact_models = {role: model.train_impact_role(role, safe.rows, safe.seasons_by_player, references, now=FIXED_NOW) for role in ("hitter", "pitcher")}
    board = model.score_current({"current": safe.current, "mlb_service": safe.mlb_service}, role_models, impact_models)
    return board, role_models, impact_models


def deduplicate_seasons(seasons, rule="D1"):
    if rule not in ("D1", "D2"):
        raise ValueError("unknown dedup rule")
    result = {}
    counts = dict.fromkeys(("verified_combined", "no_combined_row", "identical_duplicate", "other",
                            "repeated_groups", "rows_removed"), 0)
    for key, records in seasons.items():
        sample = "pa" if key.endswith("_hitter") else "ip"
        groups = {}
        for index, row in enumerate(records):
            groups.setdefault(row.get("year"), []).append((index, row))
        keep = set(range(len(records)))
        for group in groups.values():
            if len(group) < 2:
                continue
            counts["repeated_groups"] += 1
            largest = max(group, key=lambda item: float(item[1].get(sample) or 0.0))
            others = [row for index, row in group if index != largest[0]]
            sample_matches = abs(float(largest[1].get(sample) or 0.0)
                                 - sum(float(row.get(sample) or 0.0) for row in others)) <= (.01 if sample == "pa" else .34)
            count_matches = any(largest[1].get(category) is not None and all(row.get(category) is not None for row in others)
                                and float(largest[1][category]) == sum(float(row[category]) for row in others)
                                for category in ("hr", "r", "rbi", "sb", "so"))
            verified = sample_matches and count_matches
            category = ("identical_duplicate" if all(row == group[0][1] for _, row in group)
                        else "verified_combined" if verified else "other" if sample_matches else "no_combined_row")
            counts[category] += 1
            if rule == "D1" or verified:
                for index, _ in group:
                    if index != largest[0]:
                        keep.remove(index)
                        counts["rows_removed"] += 1
        result[key] = [copy.deepcopy(row) for index, row in enumerate(records) if index in keep]
    return result, counts


def support_counts(training, board, role):
    names = model._outcome_feature_names(role)
    vectors = [row.get("features") if row.get("features") is not None else model._outcome_feature_vector(row, role)
               for row in training]
    vectors = [vector for vector in vectors if vector is not None]
    limits = np.asarray(vectors, dtype=float)
    lows, highs = (limits.min(axis=0), limits.max(axis=0)) if len(vectors) else (None, None)
    levels = {str(row.get("level") or "").upper() for row in training}
    drafted = lambda row: bool(row.get("draft_record_known")) and bool(row.get("draft_pick_number"))
    training_undrafted = sum(not drafted(row) for row in training)
    samples = [float(row.get("sample", model._sample(row, role)) or 0.0) for row in training]
    minimum_sample = min(samples) if samples else 0.0
    result = {"n": len(board), "absent_level": 0, "undrafted": 0, "below_sample": 0,
              "outside_range": 0, "features_outside_support": 0, "levels_A": 0, "levels_A_plus": 0,
              "training_undrafted_share": training_undrafted / len(training) if training else None,
              "minimum_training_sample": minimum_sample, "out_of_support_top100": 0}
    feature_counts = {}
    for index, row in enumerate(board):
        level = str(row.get("level") or "").upper()
        absent = level not in levels
        undrafted = not drafted(row)
        vector = row.get("features") if row.get("features") is not None else model._outcome_feature_vector(row, role)
        outside = [] if vector is None or lows is None else [i for i, value in enumerate(vector)
                                                            if i >= len(lows) or value < lows[i] or value > highs[i]]
        result["absent_level"] += int(absent)
        result["undrafted"] += int(undrafted)
        result["below_sample"] += int(float(row.get("sample", model._sample(row, role)) or 0.0) < minimum_sample)
        result["outside_range"] += int(bool(outside))
        result["features_outside_support"] += len(outside)
        result["levels_A"] += int(level == "A")
        result["levels_A_plus"] += int(level == "A+")
        for column in outside:
            name = names[column] if column < len(names) else f"feature_{column}"
            feature_counts[name] = feature_counts.get(name, 0) + 1
        if index < 100 and (absent or (undrafted and training_undrafted == 0) or len(outside) >= 3):
            result["out_of_support_top100"] += 1
    result["top_five_features"] = dict(sorted(feature_counts.items(), key=lambda item: (-item[1], item[0]))[:5])
    result["top100_sample"] = min(100, len(board))
    result["out_of_support_top100_share"] = result["out_of_support_top100"] / result["top100_sample"] if board else 0.0
    result["concern"] = result["out_of_support_top100_share"] > .10
    return result


def _score_key(axis):
    return "expected_outcome_score" if axis == "outcome" else "expected_category_impact_score"


def _ranked_scores(board, axis, role=None):
    key = _score_key(axis)
    rows = [row for row in board if role is None or row["role"] == role]
    rows.sort(key=lambda row: (-row[key], row["mlbam_id"], row["role"]))
    return {(row["mlbam_id"], row["role"]): (index + 1, row[key]) for index, row in enumerate(rows)}


def _compare_boards(before, after, axis, role=None):
    left, right = _ranked_scores(before, axis, role), _ranked_scores(after, axis, role)
    common = sorted(left.keys() & right.keys())
    moves = [right[key][0] - left[key][0] for key in common]
    score_changes = [round(right[key][1] - left[key][1], 4) for key in common]
    if len(common) > 1:
        from scipy.stats import spearmanr
        correlation = float(spearmanr([left[key][0] for key in common], [right[key][0] for key in common]).statistic)
    else:
        correlation = None
    return {"before_n": len(left), "after_n": len(right), "common_n": len(common),
            "entered": len(right.keys() - left.keys()), "left": len(left.keys() - right.keys()),
            "top_overlap": {str(k): {"overlap": len({key for key in left if left[key][0] <= k}
                                                       & {key for key in right if right[key][0] <= k}),
                                      "before_n": min(k, len(left)), "after_n": min(k, len(right))}
                            for k in (25, 50, 100)},
            "rank_spearman": correlation, "top50_threshold_applicable": len(left) >= 50 and len(right) >= 50,
            "maximum_rank_move": max(map(abs, moves), default=0),
            "rank_moves_over_10": sum(abs(move) > 10 for move in moves),
            "rank_change": _distribution(moves), "score_change": _distribution(score_changes),
            "score_changes_over_002": sum(abs(change) > .02 for change in score_changes)}


def _counterfactual_step(board, alternatives, axis, role):
    score_key = _score_key(axis)
    changed = []
    deltas = []
    for row in board:
        key = (row["mlbam_id"], row["role"])
        alternative = alternatives.get(key, row[score_key])
        changed.append({**row, score_key: alternative})
        if row["role"] == role and key in alternatives:
            deltas.append(row[score_key] - alternative)
    comparison = _compare_boards(board, changed, axis, role)
    denominator = sum(row["role"] == role for row in board)
    return {"rows_touched": len(deltas), "signed_score_change": _distribution(deltas), **comparison,
            "concern": bool(denominator and (comparison["score_changes_over_002"] / denominator > .10
                                              or comparison["rank_moves_over_10"] / denominator > .10))}


def _regression_off_score(record, role_model, role, current):
    runtime = role_model["prediction_model"]
    raw = model._outcome_feature_vector(record, role)
    score = round(model._predict_model(runtime, raw), 4)
    if str(record.get("source_kind")) != "current_season":
        group = "hitters" if role == "hitter" else "pitchers"
        comparators = [row for row in current[group] if row.get("mlbam_id")
                       and int(row["mlbam_id"]) == int(record["mlbam_id"])
                       and str(row.get("source_kind")) == "current_season"]
        comparator = max(comparators, key=lambda row: model._display_record_key(row, role), default=None)
        comparator_raw = model._outcome_feature_vector(comparator, role) if comparator is not None else None
        if comparator_raw is not None and model._current_line_is_bad(comparator, role):
            comparator_score = model._predict_model(runtime, comparator_raw)
            sample = model._sample(comparator, role)
            pull = min(model.STALE_PULL_CAP, max(model.STALE_PULL_FLOOR,
                                                sample / (sample + model.SAMPLE_REGRESSION[role])))
            score = round(score - pull * max(0.0, score - comparator_score), 4)
    if role == "pitcher" and str(record.get("source_kind")) == "current_season" and model._current_line_is_bad(record, role):
        shrunk, _ = model._regress_current_features(raw, role_model, role, model._sample(record, role),
                                                   also_shrink=model.PITCHER_PEDIGREE_FEATURES)
        pedigree_only = [shrunk[index] if name in model.PITCHER_PEDIGREE_FEATURES else raw[index]
                         for index, name in enumerate(model._outcome_feature_names(role))]
        score = round(min(score, round(model._predict_model(runtime, pedigree_only), 4)), 4)
    return score


@sealed_guarded
def stage_6(safe):
    board, role_models, impact_models = _board(safe)
    selected = {(int(row["mlbam_id"]), role): row for role in ("hitter", "pitcher")
                for row in model._select_current_records(safe.current, role)}
    # Stable sample ties select the first eligible line while retaining every comparator.
    first_selector = FunctionType(model._select_current_records.__code__,
                                  {**model._select_current_records.__globals__, "_sample": lambda record, role: 0.0})
    selection_scorer = FunctionType(model.score_current.__code__,
                                    {**model.score_current.__globals__, "_select_current_records": first_selector})
    same_selection = all(first_selector(safe.current, role) == model._select_current_records(safe.current, role)
                         for role, group in (("hitter", "hitters"), ("pitcher", "pitchers")))
    selection_board = board if same_selection else selection_scorer(
        {"current": safe.current, "mlb_service": safe.mlb_service}, role_models, impact_models)
    result = {"families": {}, "current_board_ids_excluded": safe.counts["current_board_ids_excluded"],
              "board_scope": "live candidates excluding sealed ids; role ranks computed within role"}
    for role, group in (("hitter", "hitters"), ("pitcher", "pitchers")):
        role_board = [row for row in board if row["role"] == role]
        for axis, models in (("outcome", role_models), ("impact", impact_models)):
            key = _score_key(axis)
            prepared = (model._historical_rows(safe.rows, role) if axis == "outcome" else
                        model._historical_impact_rows(safe.rows, role, safe.seasons_by_player,
                                                      model._impact_references(safe.seasons_by_player)))
            training = [{**next(raw for raw in safe.rows if int(raw.get("mlbam_id") or 0) == record["mlbam_id"]
                                and raw.get("role") == role and int(raw["cohort_year"]) == record["cohort_year"]
                                and str(raw.get("level") or "").upper() == record["level"]
                                and (axis != "outcome" or raw.get("outcome") in model.OUTCOME_TARGET)
                                and model._outcome_feature_vector(raw, role) == record["features"]),
                         "features": record["features"]} for record in prepared]
            ordered = sorted(role_board, key=lambda row: (-row[key], row["mlbam_id"]))
            support = support_counts(training, [selected[(row["mlbam_id"], role)] for row in ordered], role)
            regression, stale, pedigree, pooled = {}, {}, {}, {}
            for row in role_board:
                identity = (row["mlbam_id"], role)
                record = selected[identity]
                regression[identity] = _regression_off_score(record, models[role], role, safe.current)
                if "stale_current_correction" in row:
                    stale[identity] = row["stale_current_correction"]["raw_" + axis]
                if "pedigree_shrink_correction" in row:
                    pedigree[identity] = row["pedigree_shrink_correction"]["raw_" + axis]
                if axis == "outcome" and "pooled_shadow" in row:
                    pooled[identity] = row["pooled_shadow"]["pooled_score"]
            multiple_lines = {int(record["mlbam_id"]) for record in safe.current[group]
                              if record.get("mlbam_id") and sum(int(other.get("mlbam_id") or 0) == int(record["mlbam_id"])
                              and model._eligible_current(other, role) for other in safe.current[group]) > 1}
            selection = {(row["mlbam_id"], row["role"]): row[key] for row in selection_board
                         if row["role"] == role and row["mlbam_id"] in multiple_lines}
            steps = {name: _counterfactual_step(board, alternatives, axis, role)
                     for name, alternatives in (("regression", regression), ("selection", selection),
                                                ("stale_current", stale), ("pedigree_shrink", pedigree), ("pooled_shadow", pooled))}
            selection_comparison = _compare_boards(board, selection_board, axis, role)
            denominator = len(role_board)
            steps["selection"].update(selection_comparison)
            steps["selection"]["rows_touched"] = sum(row["mlbam_id"] in multiple_lines for row in role_board)
            steps["selection"]["concern"] = bool(denominator and
                (selection_comparison["score_changes_over_002"] / denominator > .10
                 or selection_comparison["rank_moves_over_10"] / denominator > .10))
            steps["pooled_shadow"]["observe_only"] = True
            if axis == "outcome":
                steps["pooled_shadow"]["signed_score_change"] = _distribution(
                    [row["pooled_shadow"]["delta"] for row in role_board if "pooled_shadow" in row])
            if axis == "impact":
                steps["pooled_shadow"]["measurement"] = "served pooled shadow exposes outcome score only"
            result["families"][f"{axis}-{role}"] = {"support": support, "steps": steps,
                                                         "concern": support["concern"] or any(step["concern"] for step in steps.values())}
    result["concern"] = any(family["concern"] for family in result["families"].values())
    return result


def _service_for_seasons(safe, seasons):
    service, seen = [], set()
    for role, group in (("hitter", "hitters"), ("pitcher", "pitchers")):
        for row in safe.current[group]:
            identity = (int(row.get("mlbam_id") or 0), role)
            if not identity[0] or identity in seen:
                continue
            seen.add(identity)
            totals = _service_totals(seasons, *identity)
            service.append({"mlbam_id": identity[0], "role": role, **totals,
                            "graduated": totals["ab"] >= ROOKIE_AB_LIMIT or totals["ip"] >= ROOKIE_IP_LIMIT})
    return service


def _label_change_counts(before, after):
    prior = {(row["mlbam_id"], row["cohort_year"]): row["target"] for row in before}
    current = {(row["mlbam_id"], row["cohort_year"]): row["target"] for row in after}
    result = {}
    for cohort in sorted({key[1] for key in prior} | {key[1] for key in current}):
        keys = [key for key in prior.keys() & current.keys() if key[1] == cohort]
        deltas = [current[key] - prior[key] for key in keys]
        changed = [value for value in deltas if abs(value) > 1e-12]
        result[str(cohort)] = {"n": len(keys), "changed": len(changed), "share_changed": len(changed) / len(keys) if keys else 0.0,
                               "mean_absolute_change": mean(map(abs, deltas)) if deltas else None,
                               "max_absolute_change": max(map(abs, deltas), default=0.0),
                               "up": sum(value > 0 for value in changed), "down": sum(value < 0 for value in changed),
                               "missing_before_or_after": len([key for key in prior.keys() ^ current.keys() if key[1] == cohort])}
    return result


def _combined_validation(validations):
    joined = {key: [] for key in ("targets", "model_predictions", "prior_predictions", "neighbor_predictions", "canonical_neighbor_predictions")}
    for validation in validations:
        for key in joined:
            joined[key].extend(validation[key])
    for name in ("model", "prior", "neighbor", "canonical_neighbor"):
        joined[name + "_mae"] = mean(abs(a - b) for a, b in zip(joined[name + "_predictions"], joined["targets"])) if joined["targets"] else None
    joined["folds"] = []
    return joined


@sealed_guarded
def stage_7(safe, bootstrap_resamples=5000):
    if not safe.service_consistent:
        raise ValueError("inconsistent service contract")
    stores = {"A0": safe.seasons_by_player}
    classification = {}
    for name, rule in (("A1", "D1"), ("A2", "D2")):
        stores[name], classification[name] = deduplicate_seasons(safe.seasons_by_player, rule)
    result = {"classification": classification, "prevalence": {}, "labels": {}, "references": {}, "gates": {},
              "current_board_ids_excluded": safe.counts["current_board_ids_excluded"],
              "raw_cache_probe": "skipped; D3 not applicable", "historical_cache_writer": "not found in permitted source search",
              "measurement_only": True, "outcome_axis": "unchanged by season deduplication"}
    for role in ("hitter", "pitcher"):
        cohorts = sorted({row["cohort_year"] for row in safe.rows if row.get("role") == role})
        result["prevalence"][role] = {}
        for cohort in cohorts:
            ids = {int(row["mlbam_id"]) for row in safe.rows if row.get("role") == role and row["cohort_year"] == cohort}
            repeated = 0
            for player_id in ids:
                years = [row.get("year") for row in safe.seasons_by_player.get(f"{player_id}_{role}", [])]
                repeated += int(len(years) > len(set(years)))
            result["prevalence"][role][str(cohort)] = {"n": len(ids), "repeated": repeated,
                                                        "share": repeated / len(ids) if ids else 0.0}
        role_seasons = [records for key, records in safe.seasons_by_player.items() if key.endswith("_" + role)]
        repeated = sum(len(records) > len({row.get("year") for row in records}) for records in role_seasons)
        result["prevalence"][role]["all_safe_store_players"] = {"n": len(role_seasons), "repeated": repeated,
                                                                "share": repeated / len(role_seasons) if role_seasons else 0.0,
                                                                "with_any_season": sum(bool(records) for records in role_seasons)}
    references = {name: model._impact_references(store) for name, store in stores.items()}
    role_models = {role: model.train_role(role, safe.rows, now=FIXED_NOW) for role in ("hitter", "pitcher")}
    impact_models = {}
    all_full_labels, all_train_labels = {}, {}
    for name, store in stores.items():
        result["references"][name], result["gates"][name] = {}, {}
        impact_models[name] = {}
        all_full_labels[name], all_train_labels[name] = {}, {}
        for regime in ("R0", "R2"):
            models = {}
            for role in ("hitter", "pitcher"):
                duplicate_baseline = name != "A0" and store == stores["A0"]
                models[role] = (impact_models["A0"][regime][role] if duplicate_baseline else
                                model.train_impact_role(role, safe.rows, store, references[name], now=FIXED_NOW,
                                                        fold_local_evidence=regime == "R2"))
            impact_models[name][regime] = models
            result["gates"][name][regime] = {role: models[role]["gate"] for role in ("hitter", "pitcher")}
            result["gates"][name][regime]["pooled"] = gate_for(
                _combined_validation([models[role]["_validation"] for role in ("hitter", "pitcher")]), "impact", model.MIN_GATE_SAMPLE * 2)
        for role in ("hitter", "pitcher"):
            result["references"][name][role] = {"R0": _reference_summary(references[name], role, references["A0"]), "R2": {}}
            full = model._historical_impact_rows(safe.rows, role, store, references[name])
            all_full_labels[name][role] = full
            all_train_labels[name][role] = {}
            templates = impact_oof._eligible_templates(safe.rows, role, model.MATURE_THROUGH)
            for year in sorted({row["cohort_year"] for row in templates})[2:]:
                local = impact_oof._fold_reference_contract(templates, role, store, year)
                original = impact_oof._fold_reference_contract(templates, role, stores["A0"], year)
                all_train_labels[name][role][year] = [row for row in model._historical_impact_rows(safe.rows, role, store, local["references"])
                                                      if row["cohort_year"] < year]
                result["references"][name][role]["R2"][str(year)] = _reference_summary(local["references"], role, original["references"])
    for name in ("A1", "A2"):
        result["labels"][name] = {role: {"R0": _label_change_counts(all_full_labels["A0"][role], all_full_labels[name][role]),
                                           "R2": {str(year): _label_change_counts(all_train_labels["A0"][role][year], labels)
                                                  for year, labels in all_train_labels[name][role].items()}}
                                   for role in ("hitter", "pitcher")}
    service = {name: _service_for_seasons(safe, store) for name, store in stores.items()}
    service_index = {name: {(row["mlbam_id"], row["role"]): row for row in facts} for name, facts in service.items()}
    if {(row["mlbam_id"], row["role"]): row for row in safe.mlb_service} != service_index["A0"]:
        raise ValueError("inconsistent service contract")
    result["service"] = {role: {"n": sum(key[1] == role for key in service_index["A0"]),
                                 "graduated_flips": sum(service_index["A0"][key]["graduated"] != service_index["A1"][key]["graduated"]
                                                        for key in service_index["A0"] if key[1] == role)}
                         for role in ("hitter", "pitcher")}
    boards = {name: model.score_current({"current": safe.current, "mlb_service": service[name]}, role_models, impact_models[name]["R0"])
              for name in ("A0", "A1")}
    result["board"] = {axis: {role or "pooled": _compare_boards(boards["A0"], boards["A1"], axis, role)
                              for role in ("hitter", "pitcher", None)} for axis in ("outcome", "impact")}
    result["outcome_gates"] = {role: role_models[role]["gate"] for role in ("hitter", "pitcher")}
    result["outcome_gates"]["pooled"] = gate_for(_combined_validation([role_models[role]["_validation"] for role in ("hitter", "pitcher")]),
                                                   "outcome", model.MIN_GATE_SAMPLE * 2)
    gate_change = any(result["gates"]["A0"][regime][role]["status"] != result["gates"]["A1"][regime][role]["status"]
                      for regime in ("R0", "R2") for role in ("hitter", "pitcher"))
    def aggregate_share(cohorts):
        n = sum(row["n"] for row in cohorts.values())
        changed = sum(row["changed"] for row in cohorts.values())
        return {"n": n, "changed": changed, "share_changed": changed / n if n else 0.0}

    result["label_aggregates"] = {role: {"R0": aggregate_share(result["labels"]["A1"][role]["R0"]),
                                                "R2": {year: aggregate_share(cohorts) for year, cohorts
                                                       in result["labels"]["A1"][role]["R2"].items()}}
                                  for role in ("hitter", "pitcher")}
    label_change = any(result["label_aggregates"][role]["R0"]["share_changed"] > .05
                       or any(fold["share_changed"] > .05 for fold in result["label_aggregates"][role]["R2"].values())
                       for role in ("hitter", "pitcher"))
    board_change = any((comparison["before_n"] >= 50 and comparison["after_n"] >= 50
                        and comparison["top_overlap"]["50"]["overlap"] < 45)
                       or (comparison["rank_spearman"] is not None and comparison["rank_spearman"] < .99)
                       for axis in result["board"].values() for comparison in axis.values())
    result["concern"] = bool(gate_change or label_change or board_change or any(row["graduated_flips"] for row in result["service"].values()))
    result["reason_flags"] = {role: {regime: {"gate_status_changed": result["gates"]["A0"][regime][role]["status"] != result["gates"]["A1"][regime][role]["status"],
                                             "training_label_share_over_005": (result["label_aggregates"][role]["R0"]["share_changed"] > .05 if regime == "R0" else
                                                                               any(fold["share_changed"] > .05 for fold in result["label_aggregates"][role]["R2"].values()))}
                                           for regime in ("R0", "R2")} for role in ("hitter", "pitcher")}
    result["families"] = {}
    for role in ("hitter", "pitcher"):
        result["families"]["outcome-" + role] = {"gate": result["outcome_gates"][role], "label_unchanged": True,
                                                  "board": result["board"]["outcome"][role]}
        result["families"]["impact-" + role] = {"gates": {name: {regime: result["gates"][name][regime][role]
                                                                            for regime in ("R0", "R2")} for name in stores},
                                                 "label_aggregates": result["label_aggregates"][role],
                                                 "reason_flags": result["reason_flags"][role],
                                                 "board": result["board"]["impact"][role]}
    return result


def _configuration_engines(settings, role, configurations=None):
    engines = []
    original = WalkForwardEngine(**settings)
    names = model._outcome_feature_names(role)
    drop = ({"inverse_draft_pick", "draft_record_known"} if role == "hitter" else model.PITCHER_PEDIGREE_FEATURES)
    for config in configurations or configuration_grid():
        indices = [i for i, name in enumerate(names) if config["features"] == "promoted" or name not in drop]
        rows = [{**row, "features": [row["features"][i] for i in indices]} for row in settings["rows"]]
        # Only prediction features change; all configurations share the cached baseline sets.
        engine = copy.copy(original)
        engine.rows = rows
        engine.features = np.asarray([row["features"] for row in rows], dtype=float)
        engine.model_kind, engine.ridge_lambda = config["model_kind"], config["ridge_lambda"]
        engines.append(engine)
    return engines


@sealed_guarded
def best_of_k(safe, family, reps, out=None, resume=False, deadline=None, k_extra=0, configurations=None):
    _ensure_equivalence(safe)
    settings = prepare_families(safe)[family]
    axis, role = family.split("-")
    engines = _configuration_engines(settings, role, configurations)
    realized_engine = WalkForwardEngine(**settings)
    observed = _margin(realized_engine.run(), axis)
    observed_margins = [_margin(engine.run(), axis) for engine in engines]
    identity = _checkpoint_identity(safe, 3, family, configs=configurations or configuration_grid(), k_extra=k_extra)
    draws = _resume_draws(safe, out, 3, family, identity, resume)[:reps]
    realized_lambda = settings["ridge_lambda"]
    realized_offset = 0 if realized_lambda == 3.0 else 2
    for index in range(len(draws), reps):
        if deadline is not None and time.monotonic() >= deadline:
            break
        labels = permute_targets(settings["rows"], 3, FAMILIES.index(family), 0, index)
        margins = [_margin(engine.run(labels), axis) for engine in engines]
        if any(value is None for value in margins):
            raise ValueError("selection statistic unavailable")
        subsets = {"2": max(margins[realized_offset:realized_offset + 2]), "4": max(margins[:4]), "8": max(margins)} if configurations is None else {str(len(margins)): max(margins)}
        if k_extra:
            extras = [_margin(realized_engine.run(permute_targets(settings["rows"], 3, FAMILIES.index(family), extra + 1, index)), axis)
                      for extra in range(k_extra)]
            subsets[str(8 + k_extra)] = max([subsets["8"], *extras])
        draws.append(subsets)
        if len(draws) % 250 == 0:
            _checkpoint(safe, out, 3, family, draws, identity)
    _checkpoint(safe, out, 3, family, draws, identity)
    keys = list(draws[0]) if draws else (["2", "4", "8"] if configurations is None else [str(len(engines))])
    p_values = {key: _p_value(observed, [draw[key] for draw in draws]) for key in keys}
    partial = len(draws) < REPETITIONS[3]
    return {"observed_realized_margin": observed, "observed_best_margin": max(observed_margins), "observed_configuration_margins": observed_margins,
            "p_values": p_values, "null_maxima": {key: _distribution([draw[key] for draw in draws]) for key in keys},
            "draws_completed": len(draws), "partial": partial,
            "interpretation": None if partial else {key: "selection_artifact_not_sufficient" if value <= .01 else "ambiguous" if value <= .05 else "within_selection_null" for key, value in p_values.items()},
            "selection_pool": "lower_bound_only"}


@lru_cache(maxsize=4)
def calibration_loop(datasets=200, reps=39):
    """Check permutation calibration on independently generated noise datasets."""
    global LAST_CALIBRATION_SECONDS
    if datasets < 1 or reps < 1:
        raise ValueError("calibration counts must be positive")
    started = time.monotonic()
    low, high = (int(value) for value in binom.interval(0.99, datasets, 0.05))
    counts = {name: 0 for name in ("N1", "N2", "best_of_8")}
    realised_count = 0
    configurations = configuration_grid()
    realised_index = next(i for i, config in enumerate(configurations)
                          if config["features"] == "promoted"
                          and config["model_kind"] == "hurdle_ridge"
                          and config["ridge_lambda"] == 10.0)
    for dataset_id in range(datasets):
        rng = np.random.default_rng(np.random.SeedSequence([SEED, 77, dataset_id]))
        features = rng.normal(size=(54, 4))
        targets = rng.choice([0.0, 0.5, 1.0], size=54)
        rows = [{"mlbam_id": 700000 + dataset_id * 100 + index,
                 "cohort_year": 2014 + index // 9, "level": "AA", "age": 22,
                 "features": vector.tolist(), "baseline_features": vector.tolist(),
                 "target": float(target)}
                for index, (vector, target) in enumerate(zip(features, targets))]
        engines = []
        for config in configurations:
            prepared = [{**row, "features": row["features"] if config["features"] == "promoted"
                         else row["features"][:-1]} for row in rows]
            engines.append(WalkForwardEngine(prepared, config["model_kind"],
                                             config["ridge_lambda"], "baseline_features"))
        # Every configuration keeps the original baseline vectors and fold ordering.
        for engine in engines[1:]:
            engine.folds = engines[0].folds
        observed = [_margin(engine.run(), "outcome") for engine in engines]
        if any(value is None for value in observed):
            raise ValueError("calibration statistic unavailable")
        observed_realised = observed[realised_index]
        for stage_id, name in ((1, "N1"), (2, "N2")):
            null = [_margin(engines[realised_index].run(permute_targets(
                rows, stage_id, dataset_id + 100, 0, draw, cell_stratified=stage_id == 2)),
                "outcome") for draw in range(reps)]
            counts[name] += int(_p_value(observed_realised, null) <= 0.05)
        maxima = []
        for draw in range(reps):
            labels = permute_targets(rows, 3, dataset_id + 100, 0, draw)
            margins = [_margin(engine.run(labels), "outcome") for engine in engines]
            if any(value is None for value in margins):
                raise ValueError("calibration selection statistic unavailable")
            maxima.append(max(margins))
        # Max-versus-max is exchangeable; realised-versus-max is conservative.
        counts["best_of_8"] += int(_p_value(max(observed), maxima) <= 0.05)
        realised_count += int(_p_value(observed_realised, maxima) <= 0.05)
    families = {name: {"extreme_count": count, "extreme_share": count / datasets,
                       "binomial_band": [low, high], "within_band": low <= count <= high}
                for name, count in counts.items()}
    families["best_of_8"].update({
        "calibration_comparison": "observed best-of-8 versus null best-of-8",
        "realised_comparison": "observed realised versus null best-of-8; conservative",
        "realised_extreme_count": realised_count,
        "realised_extreme_share": realised_count / datasets,
    })
    LAST_CALIBRATION_SECONDS = time.monotonic() - started
    return {"datasets": datasets, "reps": reps, "extreme_count": counts["N1"],
            "binomial_band": [low, high], "binomial_confidence": 0.99,
            "within_band": all(value["within_band"] for value in families.values()),
            "families": families}


@sealed_guarded
def stage_1(safe, reps=5000, **options):
    return {"families": {family: null_experiment(safe, family, 1, reps, **options) for family in FAMILIES}}


@sealed_guarded
def stage_2(safe, reps=5000, **options):
    return {"families": {family: null_experiment(safe, family, 2, reps, **options) for family in FAMILIES}}


@sealed_guarded
def stage_3(safe, reps=2000, **options):
    return {"families": {family: best_of_k(safe, family, reps, **options) for family in FAMILIES}}


def _output_directory(out):
    root = Path(__file__).resolve().parents[2]
    resolved = Path(out).resolve()
    if resolved == root or root in resolved.parents:
        raise ValueError("output must be outside checkout")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _output_path(out, name):
    directory = Path(out).resolve()
    path = directory / name
    root = Path(__file__).resolve().parents[2]
    if path.is_symlink():
        raise ValueError("output destination is a symlink")
    resolved = path.resolve()
    if resolved == root or root in resolved.parents or resolved.parent != directory:
        raise ValueError("output destination must stay outside checkout and inside output directory")
    return path


def _write_results(safe, out, stages, result):
    encoded = {f"stage-{number}.json": canonical_bytes(payload) for number, payload in stages.items()}
    result["stage_sha256"] = {name: hashlib.sha256(content).hexdigest() for name, content in encoded.items()}
    encoded["results.json"] = canonical_bytes(result)
    # Validate all prospective files before opening any final artifact for writing.
    for content in encoded.values():
        assert_serialization_safe(safe, content)
    destinations = {name: _output_path(out, name) for name in encoded}
    for name, content in encoded.items():
        destinations[name].write_bytes(content)
    return result


@sealed_guarded
def run_stages(safe, out, stage="all", reps=None, budget_minutes=None, k_extra=0, resume=False, synthetic=False):
    out = _output_directory(out)
    if stage != "all" and str(stage) not in {str(number) for number in range(8)}:
        raise ValueError("unknown stage")
    if reps is not None and reps < 1 or k_extra not in (0, 8, 24):
        raise ValueError("invalid draw controls")
    deadline = time.monotonic() + budget_minutes * 60 if budget_minutes is not None else None
    bootstrap_resamples = 39 if synthetic else BOOTSTRAPS
    # Never trust a persisted equivalence certificate: run the oracle again on resume.
    stages = {0: stage_0(safe, bootstrap_resamples)}
    order = [0, 4, 6, 1, 2, 5, 3, 7]
    requested = order if stage == "all" else [0] + ([int(stage)] if int(stage) != 0 else [])
    partial = False
    for number in requested[1:]:
        if deadline is not None and time.monotonic() >= deadline:
            partial = True
            break
        if number in REPETITIONS:
            cap = min(reps, REPETITIONS[number]) if reps is not None else (9 if synthetic else REPETITIONS[number])
            options = dict(out=out, resume=resume, deadline=deadline)
            if number == 3:
                options["k_extra"] = k_extra
            stages[number] = globals()[f"stage_{number}"](safe, reps=cap, **options)
            partial |= any(item["partial"] for item in stages[number]["families"].values())
        elif number == 5:
            stages[number] = stage_5(safe, bootstrap_resamples)
        elif number == 7:
            stages[number] = stage_7(safe, bootstrap_resamples)
        else:
            stages[number] = globals()[f"stage_{number}"](safe)
    result = {"status": "partial" if partial else "ok", "synthetic": bool(synthetic), "seed": SEED,
              "input_sha256": safe.input_sha256, "sealed_ids_sha256": safe.sealed_ids_sha256,
              "counts": safe.counts, "versions": stages[0]["versions"], "requested_stage": str(stage),
              "completed_stages": sorted(stages), "mechanical_notes": MECHANICAL_NOTES,
              "interpretation": "partial_not_interpreted" if partial else "named_artifact_measurements_only",
              "claim_limits": "No predictive skill, composite-rank validation, or sealed-cohort claim is established."}
    if 1 in stages and 2 in stages:
        result["cross_null_interpretation"] = {}
        for family in FAMILIES:
            n1, n2 = (stages[number]["families"][family] for number in (1, 2))
            result["cross_null_interpretation"][family] = (
                "partial_not_interpreted" if n1["partial"] or n2["partial"] else
                "level_age_prior_explains_margin_baselines_are_weak" if n1["p_value"] is not None and n1["p_value"] <= .01 and n2["p_value"] is not None and n2["p_value"] > .01 else
                "see_individual_null_measurements")
    return _write_results(safe, out, stages, result)


_CALIBRATION_CACHE = {}


def run_synthetic(out, stage="all", reps=None, budget_minutes=None, k_extra=0, resume=False):
    out = _output_directory(out)
    contracts = {}
    # These temporary inputs are generated here; no default data loader is invoked.
    for label, signal in (("planted", True), ("no_signal", False)):
        input_path = _output_path(out, f"synthetic-{label}-input.json")
        input_path.write_bytes(canonical_bytes(synthetic_contract(signal=signal)))
        try:
            contracts[label] = load_sealed_safe_contract(input_path)
        finally:
            input_path.unlink()
    result = run_stages(contracts["planted"], out, stage, reps, budget_minutes, k_extra, resume, synthetic=True)
    noise_out = out / "no-signal"
    noise_result = run_stages(contracts["no_signal"], noise_out, stage, reps, budget_minutes, k_extra, resume, synthetic=True)
    if budget_minutes is not None:
        return result
    planted = {}
    for family in FAMILIES:
        p1 = null_experiment(contracts["planted"], family, 1, 99)["p_value"]
        p2 = null_experiment(contracts["planted"], family, 2, 99)["p_value"]
        p8 = best_of_k(contracts["planted"], family, 99)["p_values"]["8"]
        planted[family] = {"N1": p1, "N2": p2, "best_of_8": p8}
        if any(value is None or value > .01 for value in (p1, p2, p8)):
            raise AssertionError("synthetic planted-signal proof failed")
    if (200, 39) not in _CALIBRATION_CACHE:
        _CALIBRATION_CACHE[(200, 39)] = calibration_loop(200, 39)
    calibration = _CALIBRATION_CACHE[(200, 39)]
    if not calibration["within_band"]:
        raise AssertionError("synthetic calibration proof failed")
    result["status"] = "ok"
    result["synthetic_proof"] = {"planted": planted, "calibration": calibration,
                                  "no_signal_results_sha256": hashlib.sha256((noise_out / "results.json").read_bytes()).hexdigest(),
                                  "no_signal_stages": noise_result["completed_stages"],
                                  "null_stages_use_small_B_and_are_not_interpreted": True}
    assert_serialization_safe(contracts["planted"], result)
    assert_serialization_safe(contracts["no_signal"], result)
    _output_path(out, "results.json").write_bytes(canonical_bytes(result))
    return result
