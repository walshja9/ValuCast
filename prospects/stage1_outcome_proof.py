from __future__ import annotations

import json
import math
import re
from collections import defaultdict

import numpy as np
from scipy.stats import kendalltau, rankdata, spearmanr

from prospects.probability_reliability import _wilson_interval
from scripts.audit_consensus_decisions import gap_bin

BOOTSTRAP_SEED = 34041
BOOTSTRAP_RESAMPLES = 10_000
ROLES = ("hitter", "pitcher")
SCHEMA_VERSION = "1.0.0"
PREDICTIONS = {
    "model": "model_prediction",
    "level_age_prior": "prior_prediction",
    "historical_neighbors_25": "neighbor_prediction",
}


def _round(value):
    return None if value is None or not math.isfinite(float(value)) else round(float(value), 6)


def auc(scores: list[float], outcomes: list[int]) -> float | None:
    positives = sum(outcomes)
    negatives = len(outcomes) - positives
    if not positives or not negatives:
        return None
    ranks = rankdata(np.asarray(scores, dtype=float), method="average")
    positive_rank_sum = sum(rank for rank, outcome in zip(ranks, outcomes) if outcome)
    return float((positive_rank_sum - positives * (positives + 1) / 2) / (positives * negatives))


def _metric(name: str, predictions: list[float], targets: list[float]) -> float | None:
    if name == "roc_auc":
        return auc(predictions, [int(target > 0.0) for target in targets])
    if len(set(predictions)) < 2 or len(set(targets)) < 2:
        return None
    result = (
        spearmanr(predictions, targets).statistic
        if name == "spearman_rho"
        else kendalltau(predictions, targets, variant="b").statistic
    )
    return None if result is None or not math.isfinite(float(result)) else float(result)


def _draw_indices(rows: list[dict], rng: np.random.Generator) -> list[int]:
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        groups[str(row["mlbam_id"])].append(index)
    ordered = [groups[key] for key in sorted(groups)]
    picks = rng.integers(0, len(ordered), len(ordered))
    return [index for pick in picks for index in ordered[int(pick)]]


def _interval(draws: list[float]) -> dict:
    if not draws:
        return {"low": None, "high": None}
    low, high = np.percentile(np.asarray(draws, dtype=float), [2.5, 97.5])
    return {"low": _round(low), "high": _round(high)}


def build_role_metrics(rows: list[dict], *, seed: int, resamples: int) -> dict:
    rows = sorted(rows, key=lambda row: (int(row["test_cohort"]), str(row["mlbam_id"])))
    targets = [float(row["target"]) for row in rows]
    points = {
        metric: {
            label: _metric(metric, [float(row[key]) for row in rows], targets)
            for label, key in PREDICTIONS.items()
        }
        for metric in ("spearman_rho", "kendall_tau_b", "roc_auc")
    }
    draws = {
        metric: {label: [] for label in PREDICTIONS}
        for metric in points
    }
    deltas = {
        metric: {label: [] for label in PREDICTIONS if label != "model"}
        for metric in points
    }
    rng = np.random.default_rng(seed)
    for _ in range(resamples):
        indices = _draw_indices(rows, rng)
        sample = [rows[index] for index in indices]
        sample_targets = [float(row["target"]) for row in sample]
        for metric in points:
            sampled = {
                label: _metric(metric, [float(row[key]) for row in sample], sample_targets)
                for label, key in PREDICTIONS.items()
            }
            for label, value in sampled.items():
                if value is not None:
                    draws[metric][label].append(value)
            for label in deltas[metric]:
                if sampled["model"] is not None and sampled[label] is not None:
                    deltas[metric][label].append(sampled["model"] - sampled[label])
    metrics = {}
    for metric, values in points.items():
        metrics[metric] = {
            label: {"point": _round(point), **_interval(draws[metric][label])}
            for label, point in values.items()
        }
        metrics[metric]["model_minus_baseline"] = {
            label: {
                "point": _round(values["model"] - values[label])
                if values["model"] is not None and values[label] is not None
                else None,
                **_interval(deltas[metric][label]),
            }
            for label in deltas[metric]
        }
        for comparison in metrics[metric]["model_minus_baseline"].values():
            comparison["historical_support"] = bool(
                len(rows) >= 250
                and len({int(row["test_cohort"]) for row in rows}) >= 3
                and comparison["low"] is not None
                and comparison["low"] > 0.0
            )
            comparison["evidence_status"] = (
                "supported_retrospective" if comparison["historical_support"] else "descriptive"
            )
    cohorts = {}
    for cohort in sorted({int(row["test_cohort"]) for row in rows}):
        cohort_rows = [row for row in rows if int(row["test_cohort"]) == cohort]
        cohort_targets = [float(row["target"]) for row in cohort_rows]
        cohorts[str(cohort)] = {
            "sample_size": len(cohort_rows),
            "contributor_base_rate": _round(
                sum(target > 0.0 for target in cohort_targets) / len(cohort_rows)
            ),
            "metrics": {
                metric: {
                    label: _round(
                        _metric(
                            metric,
                            [float(row[key]) for row in cohort_rows],
                            cohort_targets,
                        )
                    )
                    for label, key in PREDICTIONS.items()
                }
                for metric in points
            },
        }
    return {
        "sample_size": len(rows),
        "cohort_count": len({int(row["test_cohort"]) for row in rows}),
        "contributor_base_rate": _round(sum(target > 0.0 for target in targets) / len(rows)),
        "metrics": metrics,
        "cohorts": cohorts,
        "bootstrap": {"seed": seed, "resamples": resamples, "cluster": "mlbam_id"},
    }


FUNNEL_STATUSES = {
    "open": {"open_toward", "open_flat", "open_away"},
    "resolved": {"closed_caught_up", "resolved_called_up_or_graduated"},
    "censored": {"left_universe"},
    "retracted": {"retired_we_backed_off"},
}


def _evidence_label(sample_size: int) -> str:
    if sample_size < 10:
        return "insufficient"
    if sample_size < 20:
        return "descriptive"
    return "observed"


def build_evidence_bands(rows: list[dict], reliability_role: dict) -> list[dict]:
    ordered = sorted(rows, key=lambda row: (float(row["model_prediction"]), str(row["mlbam_id"])))
    expected = reliability_role.get("bins") or []
    bands = []
    for decile in range(10):
        start = decile * len(ordered) // 10
        stop = (decile + 1) * len(ordered) // 10
        chunk = ordered[start:stop]
        counts = {
            "bust": sum(float(row["target"]) == 0.0 for row in chunk),
            "role": sum(float(row["target"]) == 0.5 for row in chunk),
            "star": sum(float(row["target"]) == 1.0 for row in chunk),
        }
        contributors = counts["role"] + counts["star"]
        actual = {
            "count": len(chunk),
            "predicted_score_min": _round(chunk[0]["model_prediction"]),
            "predicted_score_max": _round(chunk[-1]["model_prediction"]),
            "reached_role_or_better_freq": _round(contributors / len(chunk)),
        }
        expected_values = {
            key: _round(expected[decile][key]) if key != "count" else int(expected[decile][key])
            for key in actual
        } if decile < len(expected) else None
        if actual != expected_values:
            raise ValueError(f"reliability decile {decile + 1} does not reconcile")
        bands.append({
            "decile": decile + 1,
            "sample_size": len(chunk),
            "score_min": _round(chunk[0]["model_prediction"]),
            "score_max": _round(chunk[-1]["model_prediction"]),
            "outcome_counts": counts,
            "outcome_shares": {key: _round(value / len(chunk)) for key, value in counts.items()},
            "contributor_rate": _round(contributors / len(chunk)),
            "contributor_wilson95": _wilson_interval(contributors, len(chunk)),
            "evidence_label": _evidence_label(len(chunk)),
        })
    return bands


def _role(identity_key: str) -> str:
    role = identity_key.rsplit("_", 1)[-1]
    if role not in ROLES:
        raise ValueError(f"invalid disagreement identity role: {identity_key}")
    return role


def _empty_funnel() -> dict:
    return {
        "total": 0,
        "open": 0,
        "resolved": 0,
        "censored": 0,
        "retracted": 0,
        "moved_toward": 0,
        "moved_away": 0,
    }


def build_disagreement_funnel(scorecard: dict) -> dict:
    output = {"overall": {**_empty_funnel(), "bins": {}}, "roles": {}}
    for role in ROLES:
        output["roles"][role] = {**_empty_funnel(), "bins": {}}
    for call in scorecard.get("calls") or []:
        role = _role(str(call["identity_key"]))
        if float(call["initial_gap"]) < 25:
            raise ValueError("disagreement call is below the frozen 25-rank gap floor")
        band = gap_bin(call["initial_gap"])
        if band == "missing":
            raise ValueError("disagreement call is missing its frozen initial gap")
        for target in (output["overall"], output["roles"][role]):
            target["total"] += 1
            cell = target["bins"].setdefault(band, _empty_funnel())
            cell["total"] += 1
            lifecycle = [label for label, statuses in FUNNEL_STATUSES.items() if call["status"] in statuses]
            if len(lifecycle) != 1:
                raise ValueError(f"unclassified disagreement status: {call['status']}")
            target[lifecycle[0]] += 1
            cell[lifecycle[0]] += 1
            if call.get("bucket") == "toward":
                target["moved_toward"] += 1
                cell["moved_toward"] += 1
            if call.get("bucket") == "away":
                target["moved_away"] += 1
                cell["moved_away"] += 1
    for summary in (output["overall"], *output["roles"].values()):
        for cell in (summary, *summary["bins"].values()):
            if sum(cell[key] for key in FUNNEL_STATUSES) != cell["total"]:
                raise ValueError("disagreement lifecycle does not partition its population")
            cell["evidence_label"] = _evidence_label(cell["total"])
    return output


def build_stage1_outcome_proof(
    *,
    oof_payload: dict,
    reliability_payload: dict,
    backtest_payload: dict,
    scorecard_payload: dict,
    sources: dict[str, dict[str, str]],
    generated_at: str,
    seed: int = BOOTSTRAP_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict:
    from prospects.outcome_oof import validate_outcome_oof_artifact
    from prospects.probability_reliability import validate_probability_reliability

    oof_problems = validate_outcome_oof_artifact(oof_payload)
    reliability_problems = validate_probability_reliability(reliability_payload)
    if oof_problems or reliability_problems:
        raise ValueError("invalid Stage 1 evidence: " + "; ".join(oof_problems + reliability_problems))
    calls = scorecard_payload.get("calls") or []
    identities = [str(call.get("identity_key") or "") for call in calls]
    source_policy = scorecard_payload.get("source_policy") or {}
    source_policy_flags = (
        "feeds_model_score", "feeds_public_rank", "feeds_buy_score",
        "external_rankings_used", "dd_ranks_used", "dd_values_used", "market_values_used",
    )
    if (
        scorecard_payload.get("artifact") != "valucast_ahead_of_consensus_scorecard"
        or source_policy.get("inputs") != "valucast_prospect_rank_v1_dated_archive"
        or any(source_policy.get(key) is not False for key in source_policy_flags)
        or not identities
        or len(identities) != len(set(identities))
    ):
        raise ValueError("disagreement evidence is not an exact research-only claim-time archive join")
    rows = oof_payload["rows"]
    roles = {}
    for role in ROLES:
        role_rows = [row for row in rows if row["role"] == role]
        roles[role] = {
            **build_role_metrics(role_rows, seed=seed, resamples=resamples),
            "evidence_bands": build_evidence_bands(role_rows, reliability_payload["roles"][role]),
        }
    payload = {
        "artifact": "valucast_stage1_outcome_proof",
        "schema_version": SCHEMA_VERSION,
        "status": "research_only",
        "generated_at": generated_at,
        "versions": {
            "stage1_model": backtest_payload["universal_model_version"],
            "backtest": backtest_payload["backtest_version"],
            "reliability_schema": reliability_payload["schema_version"],
            "rank_calibration": "not_applicable_to_oof_stage1_scores",
            "outcome_contract": "four_year_bust_role_star_v1",
        },
        "sources": sources,
        "evaluation": {
            "mature_through_cohort": max(int(row["test_cohort"]) for row in rows),
            "closed_cohorts": sorted({int(row["test_cohort"]) for row in rows}),
            "historical_rows": len(rows),
            "historical_censored_rows": 0,
        },
        "outcome_contract": {
            "horizon_years": 4,
            "contributor": "role_or_star",
            "targets": {"bust": 0.0, "role": 0.5, "star": 1.0},
        },
        "historical": {"roles": roles},
        "disagreements": build_disagreement_funnel(scorecard_payload),
        "claim_policy": {
            "minimum_closed_cohorts": 3,
            "minimum_matched_role_n": 250,
            "delta_interval_must_exclude_zero": True,
            "retrospective_only": True,
        },
        "policy": {
            "public_superiority_authorized": False,
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_value": False,
            "feeds_buy_score": False,
            "feeds_role_watch": False,
            "feeds_pitcher_publication": False,
        },
        "validation": {"problems": []},
    }
    problems = validate_stage1_outcome_proof(payload)
    if problems:
        raise ValueError("Stage 1 proof failed validation: " + "; ".join(problems))
    return payload


def validate_stage1_outcome_proof(payload: dict) -> list[str]:
    problems = []
    if payload.get("artifact") != "valucast_stage1_outcome_proof":
        problems.append("artifact name is invalid")
    if payload.get("status") != "research_only":
        problems.append("status must be research_only")
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is invalid")
    roles = ((payload.get("historical") or {}).get("roles") or {})
    if set(roles) != set(ROLES):
        problems.append("historical roles must be hitter and pitcher")
    for role, summary in roles.items():
        bands = summary.get("evidence_bands") or []
        if len(bands) != 10 or any(band.get("decile") != index + 1 for index, band in enumerate(bands)):
            problems.append(f"{role} evidence bands must be ten ordered deciles")
        if sum(band.get("sample_size", 0) for band in bands) != summary.get("sample_size"):
            problems.append(f"{role} evidence bands do not reconcile")
        if any(
            sum((band.get("outcome_counts") or {}).values()) != band.get("sample_size")
            for band in bands
        ):
            problems.append(f"{role} evidence band outcomes do not reconcile")
        if len(summary.get("cohorts") or {}) != summary.get("cohort_count"):
            problems.append(f"{role} cohort detail does not reconcile")
    evaluation = payload.get("evaluation") or {}
    if roles and sum(int(summary.get("sample_size", 0)) for summary in roles.values()) != evaluation.get("historical_rows"):
        problems.append("hitter and pitcher samples do not reconcile to the matched population")
    disagreements = payload.get("disagreements") or {}
    disagreement_roles = disagreements.get("roles") or {}
    if set(disagreement_roles) != set(ROLES):
        problems.append("disagreement roles must be hitter and pitcher")
    if not isinstance(disagreements.get("overall"), dict):
        problems.append("disagreement overall scope is required")
    if set(disagreement_roles) == set(ROLES) and isinstance(disagreements.get("overall"), dict):
        overall = disagreements["overall"]
        measures = ("total", *FUNNEL_STATUSES, "moved_toward", "moved_away")
        if any(
            int(overall.get(key, 0)) != sum(int(disagreement_roles[role].get(key, 0)) for role in ROLES)
            for key in measures
        ):
            problems.append("overall disagreement funnel does not reconcile to role scopes")
        for band in ("25_49", "50_99", "100_199", "200_plus"):
            overall_cell = (overall.get("bins") or {}).get(band, {})
            if any(
                int(overall_cell.get(key, 0)) != sum(
                    int(((disagreement_roles[role].get("bins") or {}).get(band, {})).get(key, 0))
                    for role in ROLES
                )
                for key in measures
            ):
                problems.append("overall disagreement bins do not reconcile to role scopes")
                break
    scopes = [disagreements.get("overall") or {}, *disagreement_roles.values()]
    for scope in scopes:
        bins = scope.get("bins") or {}
        if not set(bins).issubset({"25_49", "50_99", "100_199", "200_plus"}):
            problems.append("disagreement bins are invalid")
        for cell in [scope, *bins.values()]:
            if cell and sum(int(cell.get(key, 0)) for key in FUNNEL_STATUSES) != int(cell.get("total", 0)):
                problems.append("disagreement lifecycle does not partition its population")
    sources = payload.get("sources") or {}
    if set(sources) != {"oof", "reliability", "backtest", "scorecard"}:
        problems.append("source hashes are incomplete")
    if any(
        not isinstance(value, dict)
        or not value.get("path")
        or not isinstance(value.get("sha256"), str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", value["sha256"]) is None
        for value in sources.values()
    ):
        problems.append("sources must include paths and SHA-256 digests")
    policy = payload.get("policy") or {}
    if policy.get("public_superiority_authorized") is not False:
        problems.append("retrospective evidence cannot authorize public superiority")
    for key in (
        "feeds_model_score", "feeds_public_rank", "feeds_value", "feeds_buy_score",
        "feeds_role_watch", "feeds_pitcher_publication",
    ):
        if policy.get(key) is not False:
            problems.append(f"policy.{key} must be false")
    serialized = json.dumps(payload, sort_keys=True).lower()
    for forbidden in ("source_ranks", "public_source_consensus", "fangraphs", "mlb pipeline", "eephus", "efv", "wag"):
        if forbidden in serialized:
            problems.append(f"forbidden public-comparison token present: {forbidden}")
    return problems


def _estimate(cell: dict) -> str:
    if cell.get("point") is None:
        return "n/a"
    if cell.get("low") is None or cell.get("high") is None:
        return f"{cell['point']:.3f}"
    return f"{cell['point']:.3f} [{cell['low']:.3f}, {cell['high']:.3f}]"


def _point(value) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_markdown(payload: dict) -> str:
    lines = [
        "# ValuCast Stage 1 Outcome Proof",
        "",
        f"**Generated:** {payload['generated_at']}",
        f"**Stage 1 model:** {payload['versions']['stage1_model']}",
        f"**Backtest:** {payload['versions']['backtest']}",
        f"**Mature through cohort:** {payload['evaluation']['mature_through_cohort']}",
        f"**Bootstrap:** {payload['historical']['roles']['hitter']['bootstrap']['resamples']:,} player-clustered resamples; seed {payload['historical']['roles']['hitter']['bootstrap']['seed']}",
        "**Status:** Research-only retrospective evidence",
        "Public superiority authorized: **No**",
        "",
        "Contributor means a factual Role or Star outcome within the fixed four-year horizon. All historical rows are mature; open, censored, and retracted claim-time disagreements remain visible in their full funnel. These ordinal outcomes are not realized WAR.",
        "",
        "## Contributor discrimination and ordering",
        "",
        "### Closed-cohort detail",
        "",
        "| Role | Cohort | N | Contributor rate | Spearman | Kendall tau-b | ROC AUC |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for role in ROLES:
        for cohort, row in payload["historical"]["roles"][role]["cohorts"].items():
            lines.append(
                f"| {role.title()} | {cohort} | {row['sample_size']} | {row['contributor_base_rate']:.1%} | "
                f"{_point(row['metrics']['spearman_rho']['model'])} | "
                f"{_point(row['metrics']['kendall_tau_b']['model'])} | "
                f"{_point(row['metrics']['roc_auc']['model'])} |"
            )
    lines.extend([
        "",
        "### Pooled role results",
        "",
        "Each estimate is followed by its 95% player-cluster bootstrap interval. Baseline deltas remain descriptive unless their evidence status is `supported_retrospective`.",
        "",
        "| Role | Metric | ValuCast | Level/age prior | Historical neighbors (25) | vs prior | Evidence | vs neighbors | Evidence |",
        "|---|---|---:|---:|---:|---:|:---:|---:|:---:|",
    ])
    for role in ROLES:
        summary = payload["historical"]["roles"][role]
        metrics = summary["metrics"]
        for metric, label in (("spearman_rho", "Spearman rho"), ("kendall_tau_b", "Kendall tau-b"), ("roc_auc", "ROC AUC")):
            row = metrics[metric]
            prior_delta = row["model_minus_baseline"]["level_age_prior"]
            neighbor_delta = row["model_minus_baseline"]["historical_neighbors_25"]
            lines.append(
                f"| {role.title()} (n={summary['sample_size']}, {summary['cohort_count']} cohorts) | {label} | "
                f"{_estimate(row['model'])} | {_estimate(row['level_age_prior'])} | "
                f"{_estimate(row['historical_neighbors_25'])} | {_estimate(prior_delta)} | "
                f"{prior_delta['evidence_status']} | {_estimate(neighbor_delta)} | "
                f"{neighbor_delta['evidence_status']} |"
            )
    lines.extend([
        "",
        "## Stage 1 evidence bands",
        "",
        "Bands are within-role score deciles, not probabilities or public player grades.",
    ])
    for role in ROLES:
        lines.extend(["", f"### {role.title()}s", "", "| Decile | N | Score range | Bust | Role | Star | Contributor | 95% CI | Evidence |", "|---:|---:|---:|---:|---:|---:|---:|---:|---|"])
        for band in payload["historical"]["roles"][role]["evidence_bands"]:
            shares = band["outcome_shares"]
            interval = band["contributor_wilson95"]
            lines.append(
                f"| {band['decile']} | {band['sample_size']} | {band['score_min']:.3f}-{band['score_max']:.3f} | {shares['bust']:.1%} | "
                f"{shares['role']:.1%} | {shares['star']:.1%} | {band['contributor_rate']:.1%} | "
                f"{interval['low']:.1%}-{interval['high']:.1%} | {band['evidence_label']} |"
            )
    lines.extend([
        "",
        "## Frozen disagreements",
        "",
        "Initial-gap bins use frozen claim-time ranks. Open, resolved, censored, and retracted calls remain in the denominator.",
    ])
    gap_labels = {"25_49": "25-49", "50_99": "50-99", "100_199": "100-199", "200_plus": "200+"}
    lines.extend(["", "| Scope | Initial gap | Total | Open | Resolved | Censored | Retracted | Toward | Away | Evidence |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"])
    scopes = [("Overall", payload["disagreements"]["overall"])] + [
        (role.title(), payload["disagreements"]["roles"][role]) for role in ROLES
    ]
    for scope_label, scope in scopes:
        for key, gap_label in gap_labels.items():
            cell = scope["bins"].get(key, {**_empty_funnel(), "evidence_label": "insufficient"})
            lines.append(
                f"| {scope_label} | {gap_label} | {cell['total']} | {cell['open']} | {cell['resolved']} | "
                f"{cell['censored']} | {cell['retracted']} | {cell['moved_toward']} | {cell['moved_away']} | "
                f"{cell['evidence_label']} |"
            )
    lines.extend([
        "",
        "## Provenance",
        "",
        "| Input | Path | SHA-256 |",
        "|---|---|---|",
    ])
    for name, source in sorted(payload["sources"].items()):
        lines.append(f"| {name} | `{source['path']}` | `{source['sha256']}` |")
    lines.extend([
        "",
        "## Boundaries",
        "",
        "This report feeds no model score, rank, value, buy signal, Role Watch output, or pitcher publication decision.",
        "It does not claim WAR accuracy, probability calibration, or public superiority.",
        "",
    ])
    return "\n".join(lines)
