"""Historical rank-core replay for Rank-gate v1 (registered in plan 028).

Replays the RANK scoring core (build_prospect_rank_v1) over the committed
historical cohort folds with fold-local inputs, per the frozen "Rank-gate v1
registration" section of plans/028-pitcher-lean-model-fix.md and the verified
design in docs/design-response-sol-gate-extension-2026-07-13.md. The
registration governs; do not change metric definitions or neutralizations
without a registered amendment.

What this is NOT: an exact historical board replay (impossible from committed
data — class-(b) inputs have no dated archives). It is an out-of-sample replay
of the score-producing core over a fixed pseudo-universe (the test cohort's
eligible historical rows), with class-(b) inputs neutralized as HARD errors:

- prospect_availability=None (apply_availability_adjustment is a no-op),
- milb_history_by_key=None (career softener off),
- mlb_roster_status=None (normalization pool excludes nobody),
- manual graduation + the 5 consensus snapshot paths patched to empty,
- generated_at explicit per fold (never wall clock).

Evidence budget (registered): C0 absolute replay is harness validation and
does not unblind anything; the C0-vs-C1 delta may be looked at EXACTLY ONCE,
via run_gate() with the C1 lever kwargs, after the lever exists. C_cross is
REPORT-ONLY (2026-07-14 power-check amendment): it is emitted for the record
and can never be pass/fail evidence.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from prospects import model as prospect_model_module
from prospects import rank_v1
from prospects.dynasty import build_layer
from prospects.dynasty_backtest import (
    OUTCOME_COMPLETE_THROUGH,
    OUTCOME_HORIZON_YEARS,
    _weighted_fold_metric,
)
from prospects.model import (
    OUTCOME_TARGET,
    _impact_references,
    score_current as model_score_current,
    train_impact_role,
    train_role,
)
from prospects.rank_v1 import build_prospect_rank_v1
from prospects.universal import (
    INPUT_PATH,
    MODEL_NAME,
    MODEL_VERSION,
    TARGET_SPECS,
    _base_historical_rows,
    _horizon_clipped_seasons,
    load_input_contract,
    score_current as universal_score_current,
    train_target,
)
from prospects.universe import build_universe

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_rank_backtest.json"
BACKTEST_VERSION = "0.1.0"

# Registered evidence procedure (plan 028 registration; matches
# scripts/power_check_rank_gate.py, which calibrated the thresholds).
BOOTSTRAP_SEED = 28013
N_BOOTSTRAPS = 10_000
Z_ONE_SIDED = 2.128045234184983  # norm.ppf(1 - 0.05/3), Bonferroni 98.33%
C1_POINT_THRESHOLD = 0.005

_NEUTRALIZED_PATH_ATTRS = (
    "MANUAL_GRADUATION_PATH",
    "STS_CONSENSUS_PATH",
    "FG_FV_SNAPSHOT_PATH",
    "PROSPECTSLIVE_PATH",
    "PIPELINE_PATH",
    "HKB_PATH",
)


class NeutralizationError(RuntimeError):
    """A registered anachronism neutralization was violated. Never a warning."""


@contextmanager
def _neutralized_module_state():
    """Patch rank_v1's disk-read constants to a nonexistent path, hard-verified.

    build_prospect_rank_v1 internally reads today's manual-graduation list and
    five consensus snapshots (rank_v1.py:1908-1913). Both are score-inert but
    anachronistic; the registration requires them empty, verified, restored.
    """
    void = ROOT / "data" / "models" / "__rank_backtest_void__.json"
    if void.exists():
        raise NeutralizationError(f"neutralization sentinel exists: {void}")
    saved = {attr: getattr(rank_v1, attr) for attr in _NEUTRALIZED_PATH_ATTRS}
    try:
        for attr in _NEUTRALIZED_PATH_ATTRS:
            setattr(rank_v1, attr, void)
        if rank_v1._manual_graduated_ids() != set():
            raise NeutralizationError("manual graduation list not empty")
        if rank_v1._snapshot_by_mlbam(void) != {}:
            raise NeutralizationError("consensus snapshot not empty")
        yield
    finally:
        for attr, value in saved.items():
            setattr(rank_v1, attr, value)


_VARIANT_SPEC_KEYS = {"rank_kwargs", "model_flags"}


def _validate_variant_spec(name: str, spec: dict) -> None:
    unknown = set(spec or {}) - _VARIANT_SPEC_KEYS
    if unknown:
        raise NeutralizationError(
            f"variant {name!r} has unknown spec keys {sorted(unknown)}; "
            f"allowed: {sorted(_VARIANT_SPEC_KEYS)}"
        )


@contextmanager
def _model_flags(flags: dict | None):
    """Set registered lever flags on prospects.model for one fold, restored after.

    Wraps TRAINING and scoring together: a feature-construction lever (like the
    C1 pedigree decay) must apply identically in both or the fold is incoherent.
    """
    flags = flags or {}
    for name in flags:
        if not hasattr(prospect_model_module, name):
            raise NeutralizationError(f"unknown model flag {name!r}")
    saved = {name: getattr(prospect_model_module, name) for name in flags}
    try:
        for name, value in flags.items():
            setattr(prospect_model_module, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(prospect_model_module, name, value)


def _fold_now(test_year: int) -> str:
    return f"{test_year}-09-30T00:00:00+00:00"


def _eligible_fold_rows(contract: dict, test_year: int) -> dict:
    """Raw test-cohort rows restricted to the eligible mature pseudo-universe.

    Eligibility mirrors the adapter/dynasty harnesses (_base_historical_rows,
    mature through OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS) so every
    board row has a factual four-year outcome label. Returns
    {(str(mlbam_id), role): raw_row}, deduped to the higher-sample row.
    """
    eligible_keys = set()
    for role in ("hitter", "pitcher"):
        for row in _base_historical_rows(
            contract["historical"]["rows"],
            role,
            mature_through=OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS,
        ):
            if row["cohort_year"] == test_year:
                eligible_keys.add((str(row["mlbam_id"]), role))

    def sample(row: dict) -> float:
        key = "plate_appearances" if row.get("role") == "hitter" else "innings_pitched"
        try:
            return float(row.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    by_key: dict[tuple[str, str], dict] = {}
    for row in contract["historical"]["rows"]:
        if int(row.get("cohort_year") or -1) != test_year:
            continue
        role = row.get("role")
        mlbam_id = row.get("mlbam_id")
        if role not in ("hitter", "pitcher") or mlbam_id in (None, ""):
            continue
        key = (str(mlbam_id), role)
        if key not in eligible_keys:
            continue
        if row.get("outcome") not in OUTCOME_TARGET:
            continue
        if key not in by_key or sample(row) > sample(by_key[key]):
            by_key[key] = row
    # build_universe raises on a duplicate mlbam_id across roles (two-way
    # players): keep the higher-sample role so the fold can score.
    by_mlbam: dict[str, tuple[str, str]] = {}
    for (mlbam_id, role), row in sorted(by_key.items()):
        prior = by_mlbam.get(mlbam_id)
        if prior is None or sample(row) > sample(by_key[prior]):
            by_mlbam[mlbam_id] = (mlbam_id, role)
    return {key: by_key[key] for key in by_mlbam.values()}


def _fold_contract(contract: dict, fold_rows: dict, test_year: int) -> dict:
    """Fold-local input contract for the production scorers.

    Two registered landmines this construction exists to avoid:
    - historical rows lack source_kind/sample_season; un-stamped rows take the
      no-current-season penalty on EVERY row (rank_v1.py:1311) and lose the
      newest-season sort key in both scorers — stamp them.
    - today's mlb_service would silently drop the whole cohort (historical
      players are graduated NOW; both score_current()s skip graduated rows) —
      build fold-local service rows with graduated=False.
    """
    now = _fold_now(test_year)
    current: dict[str, list[dict]] = {"hitters": [], "pitchers": []}
    service = []
    for (mlbam_id, role), row in sorted(fold_rows.items()):
        stamped = {
            **row,
            "source_kind": "current_season",
            "sample_season": test_year,
        }
        current["hitters" if role == "hitter" else "pitchers"].append(stamped)
        service.append(
            {"mlbam_id": row["mlbam_id"], "role": role, "graduated": False,
             "ab": 0.0, "pa": 0.0, "ip": 0.0}
        )
    return {
        "schema_version": contract.get("schema_version"),
        "generated_at": now,
        "historical": contract["historical"],
        "historical_mlb_seasons": contract["historical_mlb_seasons"],
        "current": current,
        "mlb_service": service,
        "rookie_limits": contract.get("rookie_limits")
        or {"at_bats": 131, "innings_pitched": 51},
    }


def _fold_board_scores(
    contract: dict,
    test_year: int,
    variant: dict | None = None,
) -> tuple[dict, dict]:
    """Score one fold through the production pipeline; return scores + diagnostics.

    variant spec: {"model_flags": {...}} flips registered levers on
    prospects.model around BOTH training and scoring (the C1 pedigree decay
    lives in feature construction); {"rank_kwargs": {...}} threads kwargs into
    build_prospect_rank_v1 for scoring-side levers. C0 = empty spec.
    """
    variant = variant or {}
    with _model_flags(variant.get("model_flags")):
        return _fold_board_scores_inner(
            contract, test_year, variant.get("rank_kwargs")
        )


def _fold_board_scores_inner(
    contract: dict,
    test_year: int,
    rank_kwargs: dict | None = None,
) -> tuple[dict, dict]:
    now = _fold_now(test_year)
    train_through = test_year - OUTCOME_HORIZON_YEARS
    training_rows = [
        row
        for row in contract["historical"]["rows"]
        if int(row.get("cohort_year") or 9999) <= train_through
    ]
    if not training_rows:
        raise ValueError(f"fold {test_year}: no eligible training cohorts")
    fold_rows = _eligible_fold_rows(contract, test_year)
    if not fold_rows:
        raise ValueError(f"fold {test_year}: empty eligible pseudo-universe")
    fold_contract = _fold_contract(contract, fold_rows, test_year)
    seasons = contract["historical_mlb_seasons"]

    # Prospect model: production trainers + production scorer, fold-trained.
    # model.py clips impact labels internally (Phase 0 F4 fix); universal needs
    # the external clip (same call production's build_shadow_model makes).
    role_models = {
        role: train_role(role, training_rows, now=now)
        for role in ("hitter", "pitcher")
    }
    references = _impact_references(seasons)
    impact_models = {
        role: train_impact_role(role, training_rows, seasons, references, now=now)
        for role in ("hitter", "pitcher")
    }
    prospect_model = {
        "ranked": model_score_current(fold_contract, role_models, impact_models),
        "model_version": f"rank_backtest_fold_{test_year}",
    }

    clipped_seasons = _horizon_clipped_seasons(training_rows, seasons)
    role_targets = {
        role: {
            target: train_target(role, target, training_rows, clipped_seasons, now=now)
            for target in TARGET_SPECS[role]
        }
        for role in ("hitter", "pitcher")
    }
    dynasty_layer = build_layer(
        {
            "profiles": universal_score_current(fold_contract, role_targets),
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "input_contract": {"generated_at": now},
        },
        backtest=None,
    )
    prospect_universe = build_universe(dynasty_layer, None, generated_at=now)

    with _neutralized_module_state():
        payload = build_prospect_rank_v1(
            prospect_universe,
            dynasty_layer,
            prospect_model,
            fold_contract,
            prospect_availability=None,
            milb_history_by_key=None,
            mlb_roster_status=None,
            **(rank_kwargs or {}),
        )

    scores = {}
    source_counts: dict[str, int] = {}
    for row in payload.get("board") or []:
        key = (str(row.get("mlbam_id")), row.get("role"))
        if key in fold_rows:
            scores[key] = float(row["score"])
        source = str(row.get("score_source"))
        source_counts[source] = source_counts.get(source, 0) + 1
    tiers = {key: OUTCOME_TARGET[row["outcome"]] for key, row in fold_rows.items()}
    diagnostics = {
        "test_cohort": test_year,
        "train_cohort_max": train_through,
        "pseudo_universe": len(fold_rows),
        "board_rows": len(payload.get("board") or []),
        "scored_and_labeled": len(scores),
        "hitters": sum(1 for _, role in scores if role == "hitter"),
        "pitchers": sum(1 for _, role in scores if role == "pitcher"),
        "score_source_counts": source_counts,
        "rank_status": payload.get("status"),
    }
    return {"scores": scores, "tiers": tiers}, diagnostics


def _tier_concordance_fast(scores: np.ndarray, tiers: np.ndarray) -> float | None:
    """Vectorized _pair_concordance (identical values, property-locked in tests).

    The bootstrap runs 30k+ evaluations; the O(n^2) reference loop is fine for
    one fold but not for that. Between each ordered tier pair, count
    higher-tier scores strictly above (concordant) and equal (0.5) via
    searchsorted on the sorted lower-tier scores: O(n log n) per eval.
    """
    values = np.unique(tiers)
    if len(values) < 2:
        return None
    by_tier = {value: np.sort(scores[tiers == value]) for value in values}
    concordant = 0.0
    total = 0
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            low = by_tier[values[i]]
            high = by_tier[values[j]]
            below = np.searchsorted(low, high, side="left")
            at_or_below = np.searchsorted(low, high, side="right")
            concordant += below.sum() + 0.5 * (at_or_below - below).sum()
            total += len(low) * len(high)
    return concordant / total if total else None


def _pair_concordance(items: list[tuple[float, float]]) -> float | None:
    """Tier-pair concordance: pairs with differing outcome tier; score ties 0.5.

    Matches the estimator scripts/power_check_rank_gate.py calibrated the
    registered thresholds under. items = [(score, tier), ...].
    ponytail: O(n^2) reference implementation — kept as the readable spec that
    _tier_concordance_fast is property-tested against.
    """
    concordant = 0.0
    total = 0
    for i in range(len(items)):
        score_i, tier_i = items[i]
        for j in range(i + 1, len(items)):
            score_j, tier_j = items[j]
            if tier_i == tier_j:
                continue
            total += 1
            if score_i == score_j:
                concordant += 0.5
            elif (score_i - score_j) * (tier_i - tier_j) > 0:
                concordant += 1.0
    return concordant / total if total else None


def _fold_metrics(scores: dict, tiers: dict) -> dict:
    def partition(pred) -> list[tuple[float, float]]:
        return [
            (score, tiers[key])
            for key, score in scores.items()
            if pred(key[1])
        ]

    hitters = partition(lambda role: role == "hitter")
    pitchers = partition(lambda role: role == "pitcher")
    everyone = partition(lambda role: True)
    # C_cross: hitter-pitcher pairs only (differing tier), per the registered
    # cross-role tier definition. REPORT-ONLY per the power-check amendment.
    cross_concordant = 0.0
    cross_total = 0
    keys = sorted(scores)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            role_i, role_j = keys[i][1], keys[j][1]
            if role_i == role_j:
                continue
            tier_i, tier_j = tiers[keys[i]], tiers[keys[j]]
            if tier_i == tier_j:
                continue
            cross_total += 1
            score_i, score_j = scores[keys[i]], scores[keys[j]]
            if score_i == score_j:
                cross_concordant += 0.5
            elif (score_i - score_j) * (tier_i - tier_j) > 0:
                cross_concordant += 1.0
    return {
        "sample_size": len(everyone),
        "hitter_sample": len(hitters),
        "pitcher_sample": len(pitchers),
        "c_pitcher": _pair_concordance(pitchers),
        "c_hitter": _pair_concordance(hitters),
        "c_all": _pair_concordance(everyone),
        "c_cross_report_only": (
            cross_concordant / cross_total if cross_total else None
        ),
    }


def _weighted(folds: list[dict], metric: str, weight: str) -> float | None:
    available = [
        (fold[metric], fold[weight])
        for fold in folds
        if fold.get(metric) is not None and fold.get(weight)
    ]
    if not available:
        return None
    return sum(value * n for value, n in available) / sum(n for _, n in available)


def paired_bootstrap_lower_bound(
    fold_pairs: list[dict],
    metric_role: str,
    n_bootstraps: int = N_BOOTSTRAPS,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """One-sided 98.33% lower bound on the weighted candidate-baseline delta.

    fold_pairs: per fold, {"baseline": {key: score}, "candidate": {key: score},
    "tiers": {key: tier}}. Paired: each bootstrap resamples players WITHIN a
    fold (with replacement) and scores both variants on the identical resample.
    Registered procedure: seed 28013, normal-approx LB at z=2.128 (matches
    scripts/power_check_rank_gate.py).
    """
    rng = np.random.default_rng(seed)

    prepared = []
    point_deltas = []
    weights = []
    for fold in fold_pairs:
        keys = sorted(
            key
            for key in fold["baseline"]
            if metric_role == "all" or key[1] == metric_role
        )
        if not keys:
            continue
        base = np.array([fold["baseline"][key] for key in keys], dtype=float)
        cand = np.array([fold["candidate"][key] for key in keys], dtype=float)
        tiers = np.array([fold["tiers"][key] for key in keys], dtype=float)
        base_c = _tier_concordance_fast(base, tiers)
        cand_c = _tier_concordance_fast(cand, tiers)
        if base_c is None or cand_c is None:
            continue
        point_deltas.append(cand_c - base_c)
        weights.append(len(keys))
        prepared.append((base, cand, tiers, len(keys)))
    if not point_deltas:
        return {"point": None, "lower_bound": None}
    point = float(np.average(point_deltas, weights=weights))

    boot_deltas = np.empty(n_bootstraps)
    for b in range(n_bootstraps):
        deltas = []
        w = []
        for base, cand, tiers, count in prepared:
            index = rng.integers(0, count, count)
            base_c = _tier_concordance_fast(base[index], tiers[index])
            cand_c = _tier_concordance_fast(cand[index], tiers[index])
            if base_c is None or cand_c is None:
                continue
            deltas.append(cand_c - base_c)
            w.append(count)
        boot_deltas[b] = np.average(deltas, weights=w) if deltas else np.nan
    sd = float(np.nanstd(boot_deltas, ddof=1))
    return {
        "point": point,
        "lower_bound": point - Z_ONE_SIDED * sd,
        "bootstrap_sd": sd,
        "n_bootstraps": n_bootstraps,
        "seed": seed,
    }


def build_rank_backtest(
    contract: dict,
    variant_specs: dict[str, dict] | None = None,
) -> dict:
    """Replay every fold for each variant. Default: C0 only (harness validation).

    Passing {"C0": {}, "C1": {"model_flags": {"PITCHER_STALE_PEDIGREE_DECAY_ENABLED":
    True}}} is THE one registered historical look — run it exactly once.
    """
    variants = variant_specs or {"C0": {}}
    for name, spec in variants.items():
        _validate_variant_spec(name, spec)
    cohorts = sorted(
        {
            int(row.get("cohort_year") or 0)
            for row in contract["historical"]["rows"]
        }
    )
    fold_years = [
        year
        for year in cohorts
        if year <= OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS
        and year - OUTCOME_HORIZON_YEARS >= min(cohorts)
    ]
    results: dict[str, dict] = {name: {"folds": []} for name in variants}
    fold_pair_data: list[dict] = []
    diagnostics = []
    for test_year in fold_years:
        per_variant = {}
        for name, spec in variants.items():
            data, diag = _fold_board_scores(contract, test_year, spec or None)
            per_variant[name] = data
            if name == next(iter(variants)):
                diagnostics.append(diag)
            metrics = _fold_metrics(data["scores"], data["tiers"])
            results[name]["folds"].append({"test_cohort": test_year, **metrics})
        if len(variants) == 2:
            names = list(variants)
            shared = sorted(
                set(per_variant[names[0]]["scores"])
                & set(per_variant[names[1]]["scores"])
            )
            if set(per_variant[names[0]]["scores"]) != set(
                per_variant[names[1]]["scores"]
            ):
                raise NeutralizationError(
                    f"fold {test_year}: variant identity sets differ "
                    "(registered invariant: exactly equal)"
                )
            fold_pair_data.append(
                {
                    "baseline": per_variant[names[0]]["scores"],
                    "candidate": per_variant[names[1]]["scores"],
                    "tiers": {
                        key: per_variant[names[0]]["tiers"][key] for key in shared
                    },
                }
            )
    for name, result in results.items():
        folds = result["folds"]
        result["weighted"] = {
            "c_pitcher": _weighted(folds, "c_pitcher", "pitcher_sample"),
            "c_hitter": _weighted(folds, "c_hitter", "hitter_sample"),
            "c_all": _weighted(folds, "c_all", "sample_size"),
            "c_cross_report_only": _weighted(
                folds, "c_cross_report_only", "sample_size"
            ),
        }
    payload = {
        "status": "research_only",
        "backtest_version": BACKTEST_VERSION,
        "registration": "plans/028-pitcher-lean-model-fix.md#rank-gate-v1-registration",
        "fold_years": fold_years,
        "variants": {
            name: {
                "weighted": result["weighted"],
                "folds": [
                    {
                        key: round(value, 6) if isinstance(value, float) else value
                        for key, value in fold.items()
                    }
                    for fold in result["folds"]
                ],
            }
            for name, result in results.items()
        },
        "fold_diagnostics": diagnostics,
    }
    if len(variants) == 2:
        names = list(variants)
        evidence = paired_bootstrap_lower_bound(fold_pair_data, "pitcher")
        point = evidence.get("point")
        lower = evidence.get("lower_bound")
        payload["gate"] = {
            "comparison": f"{names[1]} vs {names[0]}",
            "primary_metric": "delta_c_pitcher",
            **{key: round(v, 6) if isinstance(v, float) else v
               for key, v in evidence.items()},
            "point_threshold": C1_POINT_THRESHOLD,
            "passed": bool(
                point is not None
                and lower is not None
                and point >= C1_POINT_THRESHOLD
                and lower > 0
            ),
            "note": (
                "One registered historical look. C_cross is report-only "
                "(2026-07-14 power-check amendment); it can never be evidence."
            ),
        }
    return payload


def run_rank_backtest(
    input_path: Path = INPUT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    variant_specs: dict[str, dict] | None = None,
) -> dict:
    payload = build_rank_backtest(load_input_contract(input_path), variant_specs)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "fold_years": payload["fold_years"],
        "variants": {
            name: variant["weighted"] for name, variant in payload["variants"].items()
        },
        "gate": payload.get("gate"),
    }


if __name__ == "__main__":
    summary = run_rank_backtest()
    print(json.dumps(summary, indent=2, sort_keys=True))
