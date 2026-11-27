"""Inert Prospect Rank v2 wrapper and historical-fold reconstruction."""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

from prospects.cross_role_calibration import score_profiles
from prospects.model import OUTCOME_TARGET, _select_current_records
from prospects.prospect_v2_candidate import score_v08_profiles
from prospects.prospect_v09 import SCORE_SOURCE as V09_SCORE_SOURCE
from prospects.rank_v1 import _score_source_sort_order, build_prospect_rank_from_stage1
from prospects.stage1_contract import build_stage1_contract

ROOT = Path(__file__).resolve().parents[1]
RANK_ID = "prospect_rank_v2"
RANK_NAME = "ValuCast Prospect Rank v2"
RANK_VERSION = "2.0.0"
SCORE_SOURCE = "prospect_model_v0_8"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v2.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v2"
EMPTY_CONSENSUS = {
    key: {} for key in ("sts", "fangraphs", "prospectslive", "pipeline", "hkb")
}


def _v2_dynasty_layer(layer: dict, *, state: str) -> dict:
    if state not in {"candidate", "promoted"}:
        raise ValueError("invalid Prospect Rank v2 state")
    wrapped = deepcopy(layer)
    wrapped["release_contract"] = {
        **(wrapped.get("release_contract") or {}),
        "consumer": RANK_ID,
        "feeds_live_valucast_rank": state == "promoted",
    }
    return wrapped


def _v2_investment_evidence(evidence: dict | None) -> dict | None:
    if evidence is None:
        return None
    wrapped = deepcopy(evidence)
    wrapped["source_policy"] = {
        **(wrapped.get("source_policy") or {}),
        "permitted_use": "prospect_rank_v2_factual_investment_context_only",
    }
    return wrapped


def _keys(rows: list[dict]) -> set[tuple[str, str]]:
    keys = {(str(row.get("mlbam_id")), str(row.get("role"))) for row in rows}
    if len(keys) != len(rows) or any(key[0] in {"", "None"} for key in keys):
        raise ValueError("duplicate or invalid v2 profile identity")
    return keys


def build_prospect_rank_v2(
    prospect_universe: dict,
    dynasty_layer: dict,
    frozen_model: dict,
    input_contract: dict,
    calibrator: dict,
    *,
    state: str,
    prospect_availability: dict | None = None,
    milb_history_by_key: dict | None = None,
    mlb_roster_status: dict | None = None,
    require_mlb_roster_status: bool = False,
    investment_evidence: dict | None = None,
    manual_graduated_ids: set[str] | None = None,
    consensus_snapshots: dict[str, dict] | None = None,
) -> dict:
    if state not in {"candidate", "promoted"}:
        raise ValueError("invalid Prospect Rank v2 state")
    current = input_contract.get("current") or {}
    current_rows = [*(current.get("hitters") or []), *(current.get("pitchers") or [])]
    selected = [
        *_select_current_records(current, "hitter"),
        *_select_current_records(current, "pitcher"),
    ]
    raw_profiles = score_v08_profiles(current_rows, frozen_model)
    calibrated_profiles = score_profiles(raw_profiles, calibrator)
    expected_keys = _keys(selected)
    if _keys(raw_profiles) != expected_keys or _keys(calibrated_profiles) != expected_keys:
        raise ValueError("v2 scoring identity mismatch")

    model = deepcopy(frozen_model)
    model["model_version"] = "0.8.0"
    model["score_source"] = SCORE_SOURCE
    model["input_contract"] = {"generated_at": input_contract.get("generated_at")}
    model["release_contract"] = {
        "consumer": RANK_ID,
        "score_source": SCORE_SOURCE,
        "feeds_live_valucast_rank": False,
    }
    model["ranked"] = calibrated_profiles
    layer = _v2_dynasty_layer(dynasty_layer, state=state)
    stage1 = build_stage1_contract(
        model,
        layer,
        input_contract.get("generated_at"),
        state=state,
        expected_model_version="0.8.0",
        expected_model_consumer=RANK_ID,
        expected_layer_consumer=RANK_ID,
        expected_score_source=SCORE_SOURCE,
        expected_model_feed=False,
        expected_layer_feed=state == "promoted",
    )
    return build_prospect_rank_from_stage1(
        prospect_universe,
        stage1,
        input_contract,
        prospect_availability=prospect_availability,
        milb_history_by_key=milb_history_by_key,
        mlb_roster_status=mlb_roster_status,
        require_mlb_roster_status=require_mlb_roster_status,
        investment_evidence=_v2_investment_evidence(investment_evidence),
        investment_permitted_use="prospect_rank_v2_factual_investment_context_only",
        rank_name=RANK_NAME,
        rank_version=RANK_VERSION,
        score_source=SCORE_SOURCE,
        model_score_field="calibrated_expected_tier",
        normalize_role_quantiles=False,
        manual_graduated_ids=manual_graduated_ids,
        consensus_snapshots=consensus_snapshots,
    )


def build_fold_contract(source_contract: dict, test_cohort: int) -> dict:
    from prospects.rank_backtest import _eligible_fold_rows, build_fold_rank_context

    mature_through = source_contract.get("mature_through")
    if (
        source_contract.get("schema_version") != "prospect_v2_development_contract_v1"
        or mature_through not in {2021, 2022}
        or test_cohort > mature_through
    ):
        raise ValueError("source contract does not authorize this mature cohort")
    fold_rows = _eligible_fold_rows(
        source_contract, test_cohort, mature_through=mature_through
    )
    if not fold_rows:
        raise ValueError(f"empty eligible cohort {test_cohort}")
    context = build_fold_rank_context(
        source_contract, test_cohort, mature_through=mature_through
    )
    required = {
        "prospect_universe",
        "dynasty_layer",
        "prospect_availability",
        "mlb_roster_status",
        "milb_history_by_key",
        "investment_evidence",
        "manual_graduated_ids",
        "consensus_snapshots",
        "incumbent_profiles",
        "input_contract",
    }
    if set(context) != required:
        raise ValueError("rank context fields do not match the frozen contract")
    return {
        "test_cohort": test_cohort,
        "eligible_rows": [deepcopy(row) for row in fold_rows.values()],
        "targets": {
            key: OUTCOME_TARGET[row["outcome"]] for key, row in fold_rows.items()
        },
        "input_contract": deepcopy(context["input_contract"]),
        "context": {
            key: deepcopy(value)
            for key, value in context.items()
            if key != "input_contract"
        },
    }


def reconstruct_fold_scores(
    fold_contract: dict,
    candidate_profiles: list[dict],
    calibrator: dict,
    test_cohort: int,
) -> list[dict]:
    if fold_contract.get("test_cohort") != test_cohort:
        raise ValueError("cohort mismatch")
    targets = fold_contract.get("targets") or {}
    if _keys(candidate_profiles) != set(targets):
        raise ValueError("candidate identity mismatch")
    calibrator_hash = calibrator.get("artifact_sha256")
    if not calibrator_hash or any(
        row.get("calibrator_sha256") != calibrator_hash
        for row in candidate_profiles
    ):
        raise ValueError("candidate calibrator mismatch")

    context = fold_contract["context"]
    input_contract = fold_contract["input_contract"]
    generated_at = input_contract.get("generated_at")
    layer = context["dynasty_layer"]
    incumbent_model = {
        "model_version": "0.6.1",
        "input_contract": {"generated_at": generated_at},
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "ranked": deepcopy(context["incumbent_profiles"]),
    }
    incumbent_stage1 = build_stage1_contract(
        incumbent_model,
        layer,
        generated_at,
        state="incumbent",
        expected_model_version="0.6.1",
        expected_model_consumer="prospect_rank_v1",
        expected_layer_consumer="prospect_rank_v1",
        expected_score_source="prospect_model_v0_6",
        expected_model_feed=True,
        expected_layer_feed=True,
    )
    candidate_layer = _v2_dynasty_layer(layer, state="candidate")
    candidate_model = {
        "model_version": "0.8.0",
        "input_contract": {"generated_at": generated_at},
        "release_contract": {
            "consumer": RANK_ID,
            "score_source": SCORE_SOURCE,
            "feeds_live_valucast_rank": False,
        },
        "ranked": deepcopy(candidate_profiles),
    }
    candidate_stage1 = build_stage1_contract(
        candidate_model,
        candidate_layer,
        generated_at,
        state="candidate",
        expected_model_version="0.8.0",
        expected_model_consumer=RANK_ID,
        expected_layer_consumer=RANK_ID,
        expected_score_source=SCORE_SOURCE,
        expected_model_feed=False,
        expected_layer_feed=False,
    )
    common = {
        "prospect_availability": context["prospect_availability"],
        "milb_history_by_key": context["milb_history_by_key"],
        "mlb_roster_status": context["mlb_roster_status"],
        "investment_evidence": context["investment_evidence"],
        "manual_graduated_ids": context["manual_graduated_ids"],
        "consensus_snapshots": context["consensus_snapshots"],
    }
    incumbent = build_prospect_rank_from_stage1(
        context["prospect_universe"],
        incumbent_stage1,
        input_contract,
        investment_permitted_use="prospect_rank_v1_factual_investment_context_only",
        rank_name="ValuCast Prospect Rank v1",
        rank_version="0.2.9",
        score_source="prospect_model_v0_6",
        model_score_field=None,
        normalize_role_quantiles=True,
        **common,
    )
    candidate_common = {
        **common,
        "investment_evidence": _v2_investment_evidence(common["investment_evidence"]),
    }
    candidate = build_prospect_rank_from_stage1(
        context["prospect_universe"],
        candidate_stage1,
        input_contract,
        investment_permitted_use="prospect_rank_v2_factual_investment_context_only",
        rank_name=RANK_NAME,
        rank_version=RANK_VERSION,
        score_source=SCORE_SOURCE,
        model_score_field="calibrated_expected_tier",
        normalize_role_quantiles=False,
        **candidate_common,
    )
    incumbent_scores = {
        (str(row["mlbam_id"]), row["role"]): row["score"]
        for row in incumbent["board"]
    }
    candidate_scores = {
        (str(row["mlbam_id"]), row["role"]): row["score"]
        for row in candidate["board"]
    }
    if set(incumbent_scores) != set(targets) or set(candidate_scores) != set(targets):
        raise ValueError("fold rank identity mismatch")
    return [
        {
            "mlbam_id": int(key[0]),
            "role": key[1],
            "target": targets[key],
            "candidate_final_score": candidate_scores[key],
            "incumbent_final_score": incumbent_scores[key],
        }
        for key in sorted(targets)
    ]


def _ranked_role_rows(rows: list[dict], role: str) -> list[dict]:
    selected = [dict(row) for row in rows if row.get("role") == role]
    keys = _keys(selected)
    if len(keys) != len(selected) or any(
        not isinstance(row.get("score"), (int, float))
        or isinstance(row.get("score"), bool)
        or not math.isfinite(float(row["score"]))
        for row in selected
    ):
        raise ValueError("rank ladder has a missing or invalid score")
    supplied_positions = [row.get("source_ladder_position") for row in selected]
    if any(position is not None for position in supplied_positions) and supplied_positions != list(
        range(1, len(selected) + 1)
    ):
        raise ValueError("rank ladder positions are not contiguous")
    if selected != sorted(
        selected,
        key=lambda row: (
            -float(row["score"]),
            _score_source_sort_order(row.get("score_source")),
            str(row.get("role") or ""),
            str(row.get("name") or ""),
            int(row["mlbam_id"]),
        ),
    ):
        raise ValueError("rank ladder order is not deterministic")
    return selected


def select_role_ladders(
    incumbent_board: list[dict], candidate_board: list[dict], targets: dict
) -> dict:
    target_keys = {(str(key[0]), str(key[1])) for key in targets}
    incumbent_keys = _keys(incumbent_board)
    candidate_keys = _keys(candidate_board)
    if incumbent_keys != target_keys or candidate_keys != target_keys:
        raise ValueError("rank ladder identity mismatch")
    incumbent_hitters = _ranked_role_rows(incumbent_board, "hitter")
    incumbent_pitchers = _ranked_role_rows(incumbent_board, "pitcher")
    _ranked_role_rows(candidate_board, "hitter")
    candidate_pitchers = _ranked_role_rows(candidate_board, "pitcher")
    if any(row.get("score_source") != V09_SCORE_SOURCE for row in candidate_pitchers):
        raise ValueError("candidate pitcher ladder must use v0.9 source")
    if not incumbent_hitters or not incumbent_pitchers or not candidate_pitchers:
        raise ValueError("rank ladder is missing a role")
    return {
        "candidate_hitters": incumbent_hitters,
        "candidate_pitchers": candidate_pitchers,
        "incumbent_hitters": incumbent_hitters,
        "incumbent_pitchers": incumbent_pitchers,
        "hitter_pair_inversions": 0,
    }


def _ladder_rows(rows: list[dict], targets: dict, outcomes: dict) -> list[dict]:
    ladder = []
    for position, row in enumerate(rows, 1):
        key = (str(row["mlbam_id"]), row["role"])
        target = targets.get(key)
        outcome = outcomes.get(key)
        if target is None or outcome not in OUTCOME_TARGET:
            raise ValueError("rank ladder has a missing target or outcome")
        ladder.append(
            {
                **row,
                "source_ladder_position": position,
                "ladder_score": float(row["score"]),
                "target": float(target),
                "outcome": outcome,
            }
        )
    if [row["source_ladder_position"] for row in ladder] != list(
        range(1, len(ladder) + 1)
    ):
        raise ValueError("rank ladder positions are not contiguous")
    return ladder


def reconstruct_fold_ladders(
    fold_contract: dict, pitcher_profiles: list[dict], test_cohort: int
) -> dict:
    if fold_contract.get("test_cohort") != test_cohort:
        raise ValueError("cohort mismatch")
    targets = fold_contract.get("targets") or {}
    if any(
        not isinstance(target, (int, float))
        or isinstance(target, bool)
        or not math.isfinite(float(target))
        for target in targets.values()
    ):
        raise ValueError("rank ladder has an invalid target")
    target_keys = {(str(key[0]), str(key[1])) for key in targets}
    pitcher_keys = _keys(pitcher_profiles)
    expected_pitcher_keys = {key for key in target_keys if key[1] == "pitcher"}
    if pitcher_keys != expected_pitcher_keys or any(
        row.get("score_source") != V09_SCORE_SOURCE for row in pitcher_profiles
    ):
        raise ValueError("v0.9 pitcher identity or source mismatch")
    outcomes = {}
    for row in fold_contract.get("eligible_rows") or []:
        key = (str(row.get("mlbam_id")), row.get("role"))
        if key in outcomes:
            raise ValueError("duplicate outcome identity")
        outcomes[key] = row.get("outcome")
    if set(outcomes) != target_keys:
        raise ValueError("fold outcome identity mismatch")

    context = fold_contract["context"]
    input_contract = fold_contract["input_contract"]
    generated_at = input_contract.get("generated_at")
    layer = context["dynasty_layer"]
    incumbent_model = {
        "model_version": "0.6.1",
        "input_contract": {"generated_at": generated_at},
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "ranked": deepcopy(context["incumbent_profiles"]),
    }
    incumbent_stage1 = build_stage1_contract(
        incumbent_model,
        layer,
        generated_at,
        state="incumbent",
        expected_model_version="0.6.1",
        expected_model_consumer="prospect_rank_v1",
        expected_layer_consumer="prospect_rank_v1",
        expected_score_source="prospect_model_v0_6",
        expected_model_feed=True,
        expected_layer_feed=True,
    )
    candidate_layer = _v2_dynasty_layer(layer, state="candidate")
    candidate_model = {
        "model_version": "0.9.0",
        "input_contract": {"generated_at": generated_at},
        "release_contract": {
            "consumer": RANK_ID,
            "score_source": V09_SCORE_SOURCE,
            "feeds_live_valucast_rank": False,
        },
        "ranked": deepcopy(pitcher_profiles),
    }
    candidate_stage1 = build_stage1_contract(
        candidate_model,
        candidate_layer,
        generated_at,
        state="candidate",
        expected_model_version="0.9.0",
        expected_model_consumer=RANK_ID,
        expected_layer_consumer=RANK_ID,
        expected_score_source=V09_SCORE_SOURCE,
        expected_model_feed=False,
        expected_layer_feed=False,
    )
    common = {
        "prospect_availability": context["prospect_availability"],
        "milb_history_by_key": context["milb_history_by_key"],
        "mlb_roster_status": context["mlb_roster_status"],
        "investment_evidence": context["investment_evidence"],
        "manual_graduated_ids": context["manual_graduated_ids"],
        "consensus_snapshots": context["consensus_snapshots"],
    }
    incumbent = build_prospect_rank_from_stage1(
        context["prospect_universe"],
        incumbent_stage1,
        input_contract,
        investment_permitted_use="prospect_rank_v1_factual_investment_context_only",
        rank_name="ValuCast Prospect Rank v1",
        rank_version="0.2.9",
        score_source="prospect_model_v0_6",
        model_score_field=None,
        normalize_role_quantiles=True,
        **common,
    )
    candidate = build_prospect_rank_from_stage1(
        context["prospect_universe"],
        candidate_stage1,
        input_contract,
        investment_permitted_use="prospect_rank_v2_factual_investment_context_only",
        rank_name=RANK_NAME,
        rank_version=RANK_VERSION,
        score_source=V09_SCORE_SOURCE,
        model_score_field="raw_composite",
        normalize_role_quantiles=False,
        **{**common, "investment_evidence": _v2_investment_evidence(common["investment_evidence"])},
    )
    ladders = select_role_ladders(incumbent["board"], candidate["board"], targets)
    return {
        "test_cohort": test_cohort,
        "candidate_hitters": _ladder_rows(ladders["candidate_hitters"], targets, outcomes),
        "candidate_pitchers": _ladder_rows(ladders["candidate_pitchers"], targets, outcomes),
        "incumbent_hitters": _ladder_rows(ladders["incumbent_hitters"], targets, outcomes),
        "incumbent_pitchers": _ladder_rows(ladders["incumbent_pitchers"], targets, outcomes),
        "hitter_pair_inversions": ladders["hitter_pair_inversions"],
    }
