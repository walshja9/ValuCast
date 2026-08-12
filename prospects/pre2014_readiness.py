"""Pure no-outcome readiness audit for the pre-2014 cross-role gate."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COHORTS = tuple([*range(2009, 2020), 2021, 2022])
REGISTERED_OUTER_FOLDS = (2017, 2018, 2019, 2021)
MIN_CANDIDATES_PER_ROLE_FOLD = 250
PARITY_COHORT = 2014
PARITY_IDENTITY_COUNT = 1559
ROLES = ("hitter", "pitcher")
REGISTERED_SOURCE_PATHS = {
    "prepared_artifact": "data/research/extended_prospect_history/prepared.json",
    "prepared_manifest": (
        "data/research/extended_prospect_history/prepared-source-manifest.json"
    ),
    "draft_facts": "data/research/extended_prospect_history/draft-facts.json",
    "current_prospect_contract": "data/prospects/prospect_model_inputs.json",
    "prospect_universe": "data/models/valucast_prospect_universe.json",
    "dynasty_layer": "data/models/valucast_prospect_dynasty_layer.json",
    "prospect_availability": "data/models/valucast_prospect_availability.json",
    "mlb_roster_status": "data/models/valucast_mlb_roster_status.json",
    "investment_evidence": (
        "data/prospects/raw/international_signing_facts.json"
    ),
    "milb_season_stats": "data/prospects/raw/milb_season_stats.json",
    "milb_card_history": "data/prospects/raw/milb_card_history.json",
    "manual_graduation": "data/manual/prospect_graduation_overrides.json",
    "sts_snapshot": "data/sts/sts_consensus_snapshot.json",
    "fangraphs_snapshot": "data/fangraphs/fg_fv_snapshot.json",
    "prospectslive_snapshot": (
        "data/prospectslive/prospectslive_consensus_snapshot.json"
    ),
    "pipeline_snapshot": "data/pipeline/pipeline_consensus_snapshot.json",
    "hkb_snapshot": "data/hkb/hkb_consensus_snapshot.json",
}
REGISTERED_PREPARED_SOURCE_PATHS = (
    *(
        "data/research/extended_prospect_history/checkpoints/"
        f"milb-{year}.json"
        for year in EXPECTED_COHORTS
    ),
    *(
        "data/research/extended_prospect_history/milb-source-responses/"
        f"milb-{year}.json"
        for year in EXPECTED_COHORTS
    ),
    "data/research/extended_prospect_history/parity-2014-identities.json",
    "data/prospects/raw/mlb_draft_facts_cache.json",
    "data/research/extended_prospect_history/draft-facts-supplement.json",
    *(
        "data/research/extended_prospect_history/draft-source-responses/"
        f"draft-{year}.json"
        for year in range(2002, 2013)
    ),
    *(
        "data/research/extended_prospect_history/draft-source-responses/"
        f"people-{batch:02d}.json"
        for batch in range(1, 11)
    ),
)
_MILB_CHECKPOINT_PATHS = tuple(
    "data/research/extended_prospect_history/checkpoints/"
    f"milb-{year}.json"
    for year in EXPECTED_COHORTS
)
_MILB_RESPONSE_PATHS = tuple(
    "data/research/extended_prospect_history/milb-source-responses/"
    f"milb-{year}.json"
    for year in EXPECTED_COHORTS
)
_PARITY_PATH = (
    "data/research/extended_prospect_history/parity-2014-identities.json"
)
_DRAFT_BASE_PATH = "data/prospects/raw/mlb_draft_facts_cache.json"
_DRAFT_SUPPLEMENT_PATH = (
    "data/research/extended_prospect_history/draft-facts-supplement.json"
)
_DRAFT_RAW_PATHS = (
    *(
        "data/research/extended_prospect_history/draft-source-responses/"
        f"draft-{year}.json"
        for year in range(2002, 2013)
    ),
    *(
        "data/research/extended_prospect_history/draft-source-responses/"
        f"people-{batch:02d}.json"
        for batch in range(1, 11)
    ),
)
REGISTERED_RESULT_PATH = (
    "data/validation/valucast_pre2014_cross_role_gate.json"
)
SEALED_OUTCOME_SOURCE_KEY = "current_prospect_contract"
SEALED_OUTCOME_SOURCE_BINDING = "git_blob_only_pre_reservation"
REQUIRED_SOURCE_FILES = tuple(REGISTERED_SOURCE_PATHS)
REGISTERED_IMPLEMENTATION_PATHS = (
    "mlb/__init__.py",
    "mlb/availability.py",
    "mlb/roster_status.py",
    "prospects/__init__.py",
    "prospects/ahead_of_consensus.py",
    "prospects/availability.py",
    "prospects/calibration_report.py",
    "prospects/common_target_calibration.py",
    "prospects/direct_7x7.py",
    "prospects/dynasty.py",
    "prospects/dynasty_backtest.py",
    "prospects/extended_history.py",
    "prospects/gate.py",
    "prospects/input_contract.py",
    "prospects/investment_challenger.py",
    "prospects/level_translation_challenger.py",
    "prospects/milb_translation.py",
    "prospects/model.py",
    "prospects/outcome_oof.py",
    "prospects/peak_projection.py",
    "prospects/pitcher_challenger.py",
    "prospects/pre2014_cross_role_gate.py",
    "prospects/pre2014_current_board.py",
    "prospects/pre2014_fold_scoring.py",
    "prospects/pre2014_readiness.py",
    "prospects/rank_backtest.py",
    "prospects/rank_v1.py",
    "prospects/raw_input_builder.py",
    "prospects/realized_value_readiness.py",
    "prospects/stage1_contract.py",
    "prospects/universe.py",
    "prospects/universal.py",
    "quality/__init__.py",
    "quality/valucast_governor.py",
    "scraper/__init__.py",
    "scraper/mlb_actuals.py",
    "scripts/backfill_extended_prospect_outcomes.py",
    "scripts/build_extended_prospect_history.py",
    "scripts/build_pre2014_cross_role_readiness.py",
    "scripts/build_stage2_quality_starts.py",
    "scripts/run_pre2014_cross_role_gate.py",
    "scripts/validate_pre2014_cross_role_gate.py",
    "web/__init__.py",
    "web/buy_score.py",
    "web/position_matching.py",
    "web/prospect_context.py",
    "web/prospect_percentiles.py",
    "web/public_snapshot_store.py",
    "web/public_snapshot_models.py",
    "web/search_fold.py",
)
DRAFT_FACT_FIELDS = (
    "draft_record_known",
    "rule4_drafted",
    "draft_year",
    "draft_pick_number",
    "draft_round",
    "signing_bonus",
    "pick_value",
    "school_type",
    "bats",
    "throws",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
_OUTCOME_LABEL_KEYS = frozenset({"outcome", "outcome_label"})


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value.lower()) is not None


def _file_record_valid(value: Any) -> bool:
    record = _mapping(value)
    return (
        set(record) == {"path", "sha256", "git_blob"}
        and bool(record.get("path"))
        and _is_sha256(record.get("sha256"))
        and isinstance(record.get("git_blob"), str)
        and _GIT_OBJECT_RE.fullmatch(str(record["git_blob"]).lower()) is not None
    )


def _sealed_outcome_file_record_valid(value: Any) -> bool:
    record = _mapping(value)
    return (
        set(record) == {"path", "git_blob", "binding"}
        and bool(record.get("path"))
        and isinstance(record.get("git_blob"), str)
        and _GIT_OBJECT_RE.fullmatch(str(record["git_blob"]).lower()) is not None
        and record.get("binding") == SEALED_OUTCOME_SOURCE_BINDING
    )


def _source_file_record_valid(key: str, value: Any) -> bool:
    if key == SEALED_OUTCOME_SOURCE_KEY:
        return _sealed_outcome_file_record_valid(value)
    return _file_record_valid(value)


def _declared_repo_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if "\\" in value or ":" in value:
        return None
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        return None
    return value


def _manifest_source_valid(value: Any) -> bool:
    record = _mapping(value)
    return (
        bool(record.get("kind"))
        and bool(record.get("path"))
        and _is_sha256(record.get("sha256"))
    )


def _finite_nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def _draft_fact_valid(value: Any) -> bool:
    if not isinstance(value, Mapping) or set(value) != set(DRAFT_FACT_FIELDS):
        return False
    if value.get("draft_record_known") is not True:
        return False
    drafted = value.get("rule4_drafted")
    if not isinstance(drafted, bool):
        return False
    if value.get("bats") not in {"L", "R", "S"} or value.get("throws") not in {
        "L",
        "R",
        "S",
    }:
        return False
    if value.get("school_type") not in {None, "college", "high_school"}:
        return False
    year = value.get("draft_year")
    pick = value.get("draft_pick_number")
    round_value = value.get("draft_round")
    if year is not None and (
        not isinstance(year, int)
        or isinstance(year, bool)
        or not 1900 <= year <= 2100
    ):
        return False
    if pick is not None and (
        not isinstance(pick, int) or isinstance(pick, bool) or pick <= 0
    ):
        return False
    if round_value is not None and (
        not isinstance(round_value, str) or not round_value.strip()
    ):
        return False
    for field in ("signing_bonus", "pick_value"):
        field_value = value.get(field)
        if field_value is not None and not _finite_nonnegative(field_value):
            return False
    if drafted:
        return year is not None and pick is not None and round_value is not None
    return (
        pick is None
        and round_value is None
        and value.get("pick_value") is None
    )


def _exact_parity(value: Any) -> bool:
    parity = _mapping(value)
    return (
        parity.get("status") == "ready"
        and parity.get("cohort_year") == PARITY_COHORT
        and parity.get("candidate_count") == PARITY_IDENTITY_COUNT
        and parity.get("committed_count") == PARITY_IDENTITY_COUNT
        and parity.get("extra") == []
        and parity.get("missing") == []
    )


def _contains_outcome_label(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in _OUTCOME_LABEL_KEYS
            or _contains_outcome_label(nested)
            for key, nested in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_outcome_label(item) for item in value)
    return False


def _draft_mapping(payload: Any) -> Mapping[str, Any]:
    draft = _mapping(payload)
    nested = draft.get("draft_facts")
    return nested if isinstance(nested, Mapping) else draft


def _same_declared_path(left: Any, right: Any) -> bool:
    normalized_left = _declared_repo_path(left)
    normalized_right = _declared_repo_path(right)
    return normalized_left is not None and normalized_left == normalized_right


def _canonical_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_from_bytes(content: bytes, *, path: str) -> Any:
    if not isinstance(content, bytes):
        raise ValueError(f"registered replay loader did not return bytes: {path}")
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"registered replay source is invalid JSON: {path}") from exc


def _registered_replay_inputs(
    manifest: Mapping[str, Any],
    *,
    load_bytes: Callable[[str], bytes],
) -> tuple[dict[str, Any], dict[str, bytes], list[dict[str, str]]]:
    raw_sources = manifest.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) != len(
        REGISTERED_PREPARED_SOURCE_PATHS
    ):
        raise ValueError("prepared manifest source set is not registered")
    sources = [dict(_mapping(source)) for source in raw_sources]
    if [source.get("path") for source in sources] != list(
        REGISTERED_PREPARED_SOURCE_PATHS
    ):
        raise ValueError("prepared manifest source order is not registered")
    expected_kinds = [
        *["milb_checkpoint"] * len(EXPECTED_COHORTS),
        *["milb_statsapi_response"] * len(EXPECTED_COHORTS),
        "identity_parity_contract",
        "draft_facts_base",
        "draft_facts_supplement",
        *["draft_facts_statsapi_response"] * len(_DRAFT_RAW_PATHS),
    ]
    if [source.get("kind") for source in sources] != expected_kinds:
        raise ValueError("prepared manifest source kinds are not registered")

    payloads: dict[str, Any] = {}
    contents: dict[str, bytes] = {}
    records: list[dict[str, str]] = []
    for path, source in zip(
        REGISTERED_PREPARED_SOURCE_PATHS, sources, strict=True
    ):
        content = load_bytes(path)
        sha256 = _content_sha256(content)
        if source.get("sha256") != sha256:
            raise ValueError(f"registered replay source hash mismatch: {path}")
        contents[path] = content
        payloads[path] = _json_from_bytes(content, path=path)
        records.append({"path": path, "sha256": sha256})
    return payloads, contents, records


def _replay_milb_candidates(
    payloads: Mapping[str, Any],
    contents: Mapping[str, bytes],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from scripts import build_extended_prospect_history as history_builder

    all_rows: list[dict[str, Any]] = []
    for year, checkpoint_path, response_path in zip(
        EXPECTED_COHORTS,
        _MILB_CHECKPOINT_PATHS,
        _MILB_RESPONSE_PATHS,
        strict=True,
    ):
        checkpoint = payloads[checkpoint_path]
        if (
            not isinstance(checkpoint, Mapping)
            or set(checkpoint)
            != {
                "artifact",
                "schema_version",
                "cohort_year",
                "source_receipt",
                "row_count",
                "rows_sha256",
                "rows",
            }
            or checkpoint.get("artifact")
            != "valucast_extended_history_milb_checkpoint"
            or checkpoint.get("schema_version") != 2
            or checkpoint.get("cohort_year") != year
        ):
            raise ValueError(f"registered MiLB checkpoint schema mismatch: {year}")
        receipt = _mapping(checkpoint.get("source_receipt"))
        if (
            set(receipt)
            != {
                "endpoint",
                "query",
                "status",
                "response_path",
                "response_sha256",
            }
            or receipt.get("endpoint") != history_builder.MILB_STATS_ENDPOINT
            or receipt.get("query") != history_builder._milb_query(year)
            or receipt.get("status") != 200
            or receipt.get("response_path") != response_path
        ):
            raise ValueError(f"registered MiLB checkpoint receipt mismatch: {year}")
        response_sha256 = _content_sha256(contents[response_path])
        if receipt.get("response_sha256") != response_sha256:
            raise ValueError(f"MiLB raw response hash mismatch: {year}")
        replayed = history_builder.parse_milb_stats_response(
            payloads[response_path], year=year
        )
        if (
            checkpoint.get("row_count") != len(replayed)
            or checkpoint.get("rows_sha256")
            != _content_sha256(_canonical_json_bytes(replayed))
            or checkpoint.get("rows") != replayed
        ):
            raise ValueError(f"MiLB checkpoint parser output mismatch: {year}")
        all_rows.extend(replayed)

    parity_rows = history_builder._identity_parity_rows(
        payloads[_PARITY_PATH], source=Path(_PARITY_PATH)
    )
    parity_candidates = history_builder.select_earliest_candidates(
        row for row in all_rows if row.get("cohort_year") == PARITY_COHORT
    )
    parity = history_builder.validate_identity_parity(
        parity_candidates,
        parity_rows,
        cohort_year=PARITY_COHORT,
    )
    if parity.get("status") != "ready":
        raise ValueError("registered MiLB replay fails identity parity")
    candidates = history_builder.select_earliest_candidates(all_rows)
    if any(_contains_outcome_label(candidate) for candidate in candidates):
        raise ValueError("registered MiLB replay contains outcome labels")
    return candidates, parity


def _replay_draft_facts(
    candidates: list[dict[str, Any]],
    payloads: Mapping[str, Any],
    contents: Mapping[str, bytes],
) -> dict[str, dict[str, Any]]:
    from scripts import build_extended_prospect_history as history_builder

    base = payloads[_DRAFT_BASE_PATH]
    supplement = payloads[_DRAFT_SUPPLEMENT_PATH]
    if not isinstance(base, Mapping):
        raise ValueError("registered draft base is invalid")
    candidate_ids = {str(int(row["mlbam_id"])) for row in candidates}
    missing_ids = candidate_ids - set(base)
    if (
        not isinstance(supplement, Mapping)
        or supplement.get("artifact")
        != "valucast_extended_history_draft_fact_supplement"
        or supplement.get("schema_version") != 1
        or supplement.get("candidate_ids_sha256")
        != history_builder._identity_set_sha256(missing_ids)
    ):
        raise ValueError("registered draft supplement contract mismatch")
    supplemental_facts = supplement.get("facts")
    receipts = supplement.get("receipts")
    if not isinstance(supplemental_facts, Mapping) or not isinstance(receipts, list):
        raise ValueError("registered draft supplement is invalid")
    drafted_count = sum(
        fact.get("rule4_drafted") is True
        for fact in supplemental_facts.values()
        if isinstance(fact, Mapping)
    )
    if (
        supplement.get("candidate_count") != len(missing_ids)
        or supplement.get("drafted_count") != drafted_count
        or supplement.get("people_only_count") != len(missing_ids) - drafted_count
        or supplement.get("draft_years") != list(range(2002, 2013))
        or len(receipts) != len(_DRAFT_RAW_PATHS)
        or [receipt.get("response_path") for receipt in receipts if isinstance(receipt, Mapping)]
        != list(_DRAFT_RAW_PATHS)
    ):
        raise ValueError("registered draft supplement audit mismatch")

    draft_picks: dict[str, dict[str, Any]] = {}
    people: dict[str, dict[str, Any]] = {}
    draft_years: set[int] = set()
    queried_people: set[str] = set()
    for receipt, response_path in zip(receipts, _DRAFT_RAW_PATHS, strict=True):
        if not isinstance(receipt, Mapping) or set(receipt) != {
            "endpoint",
            "fetched_at",
            "query",
            "response_path",
            "response_sha256",
        }:
            raise ValueError("registered draft receipt schema mismatch")
        endpoint = receipt.get("endpoint")
        query = receipt.get("query")
        if (
            not isinstance(endpoint, str)
            or not isinstance(query, Mapping)
            or not isinstance(receipt.get("fetched_at"), str)
            or not receipt.get("fetched_at")
            or receipt.get("response_path") != response_path
            or receipt.get("response_sha256")
            != _content_sha256(contents[response_path])
        ):
            raise ValueError("registered draft receipt binding mismatch")
        response = payloads[response_path]
        if endpoint.startswith("https://statsapi.mlb.com/api/v1/draft/"):
            if query:
                raise ValueError("registered draft receipt query mismatch")
            try:
                year = int(endpoint.rsplit("/", 1)[1])
            except ValueError as exc:
                raise ValueError("registered draft receipt year mismatch") from exc
            if not 2002 <= year <= 2012 or year in draft_years:
                raise ValueError("registered draft receipt year set mismatch")
            draft_years.add(year)
            drafts = response.get("drafts") if isinstance(response, Mapping) else None
            rounds = drafts.get("rounds") if isinstance(drafts, Mapping) else None
            if not isinstance(rounds, list):
                raise ValueError("registered draft response schema mismatch")
            for round_record in rounds:
                if not isinstance(round_record, Mapping):
                    raise ValueError("registered draft round schema mismatch")
                picks = round_record.get("picks") or []
                if not isinstance(picks, list):
                    raise ValueError("registered draft picks schema mismatch")
                for pick in picks:
                    if not isinstance(pick, Mapping):
                        raise ValueError("registered draft pick schema mismatch")
                    person = _mapping(pick.get("person"))
                    player_id = str(person.get("id") or "")
                    if player_id not in missing_ids:
                        continue
                    choice = (int(pick["year"]), int(pick["pickNumber"]))
                    prior = draft_picks.get(player_id)
                    if prior is None or choice >= (
                        int(prior["year"]),
                        int(prior["pickNumber"]),
                    ):
                        draft_picks[player_id] = dict(pick)
        elif endpoint == "https://statsapi.mlb.com/api/v1/people":
            if set(query) != {"personIds"} or not isinstance(
                query.get("personIds"), str
            ):
                raise ValueError("registered people receipt query mismatch")
            requested = set(query["personIds"].split(","))
            response_people = (
                response.get("people") if isinstance(response, Mapping) else None
            )
            if not isinstance(response_people, list) or any(
                not isinstance(person, Mapping) for person in response_people
            ):
                raise ValueError("registered people response schema mismatch")
            returned = {str(person.get("id") or "") for person in response_people}
            if returned != requested or not returned <= missing_ids:
                raise ValueError("registered people response identity mismatch")
            if queried_people & returned:
                raise ValueError("registered people receipts overlap")
            queried_people.update(returned)
            people.update(
                {str(person["id"]): dict(person) for person in response_people}
            )
        else:
            raise ValueError("registered draft receipt endpoint mismatch")
    if draft_years != set(range(2002, 2013)):
        raise ValueError("registered draft receipt year set mismatch")
    if queried_people != missing_ids - set(draft_picks):
        raise ValueError("registered people receipts do not cover undrafted IDs")

    rebuilt_supplement = {}
    for player_id in sorted(missing_ids, key=int):
        pick = draft_picks.get(player_id)
        person = _mapping((pick or {}).get("person")) or _mapping(
            people.get(player_id)
        )
        if not person:
            raise ValueError(f"registered draft person fact missing: {player_id}")
        rebuilt_supplement[player_id] = history_builder._draft_fact_from_statsapi(
            player_id,
            person=person,
            pick=pick,
        )
    normalized_declared = {
        player_id: history_builder._normalize_draft_fact(player_id, fact)
        for player_id, fact in supplemental_facts.items()
    }
    if normalized_declared != rebuilt_supplement:
        raise ValueError("registered draft supplement facts differ from raw replay")
    return history_builder.build_candidate_draft_facts(
        candidates,
        base,
        supplemental_facts,
    )


def replay_pre2014_source_contract(
    prepared: Mapping[str, Any],
    manifest: Mapping[str, Any],
    draft_facts: Mapping[str, Any],
    *,
    load_bytes: Callable[[str], bytes],
) -> dict[str, Any]:
    """Rebuild the no-outcome contract from every registered source byte."""
    if not all(isinstance(value, Mapping) for value in (prepared, manifest, draft_facts)):
        raise ValueError("registered replay outputs must be JSON objects")
    payloads, contents, input_records = _registered_replay_inputs(
        manifest,
        load_bytes=load_bytes,
    )
    candidates, parity = _replay_milb_candidates(payloads, contents)
    rebuilt_prepared = {
        "artifact": "valucast_extended_prospect_history_prepared",
        "schema_version": 2,
        "mode": "prepare_only",
        "source_policy": {
            "separate_research_contract": True,
            "production_contract_overwritten": False,
            "outcomes_read": False,
            "labels_scored": False,
        },
        "cohort_years": sorted(
            {int(candidate["cohort_year"]) for candidate in candidates}
        ),
        "candidate_count": len(candidates),
        "identity_parity": parity,
        "rows": candidates,
    }
    if dict(prepared) != rebuilt_prepared:
        raise ValueError("prepared rows do not match source replay")
    rebuilt_draft_facts = _replay_draft_facts(candidates, payloads, contents)
    if dict(draft_facts) != rebuilt_draft_facts:
        raise ValueError("draft facts do not match source replay")

    prepared_sha256 = _content_sha256(_canonical_json_bytes(rebuilt_prepared))
    draft_sha256 = _content_sha256(_canonical_json_bytes(rebuilt_draft_facts))
    output = _mapping(manifest.get("output"))
    draft_output = _mapping(manifest.get("draft_facts_output"))
    if output != {
        "path": REGISTERED_SOURCE_PATHS["prepared_artifact"],
        "sha256": prepared_sha256,
    }:
        raise ValueError("prepared manifest output does not match source replay")
    if draft_output != {
        "path": REGISTERED_SOURCE_PATHS["draft_facts"],
        "sha256": draft_sha256,
    }:
        raise ValueError("draft manifest output does not match source replay")
    if manifest.get("identity_parity") != parity:
        raise ValueError("prepared manifest parity does not match source replay")

    return {
        "artifact": "valucast_pre2014_source_replay",
        "schema_version": 1,
        "inputs": input_records,
        "replay_counts": {
            "milb_cohorts": len(EXPECTED_COHORTS),
            "draft_sources": 2 + len(_DRAFT_RAW_PATHS),
            "prepared_sources": len(input_records),
        },
        "prepared_output": {
            "path": REGISTERED_SOURCE_PATHS["prepared_artifact"],
            "sha256": prepared_sha256,
            "candidate_count": len(candidates),
        },
        "draft_facts_output": {
            "path": REGISTERED_SOURCE_PATHS["draft_facts"],
            "sha256": draft_sha256,
            "candidate_id_count": len(rebuilt_draft_facts),
        },
    }


def _source_replay_valid(
    value: Any,
    *,
    prepared: Mapping[str, Any],
    draft_facts: Mapping[str, Any],
    prepared_source_files: Sequence[Mapping[str, Any]],
    prepared_output_sha256: Any,
    draft_output_sha256: Any,
    candidate_count: int,
    candidate_id_count: int,
) -> bool:
    receipt = _mapping(value)
    if (
        set(receipt)
        != {
            "artifact",
            "schema_version",
            "inputs",
            "replay_counts",
            "prepared_output",
            "draft_facts_output",
        }
        or receipt.get("artifact") != "valucast_pre2014_source_replay"
        or receipt.get("schema_version") != 1
    ):
        return False
    inputs = receipt.get("inputs")
    expected_inputs = [
        {
            "path": _declared_repo_path(record.get("path")),
            "sha256": record.get("sha256"),
        }
        for record in prepared_source_files
    ]
    if (
        not isinstance(inputs, list)
        or any(not isinstance(record, Mapping) for record in inputs)
        or any(set(record) != {"path", "sha256"} for record in inputs)
        or inputs != expected_inputs
    ):
        return False
    if receipt.get("replay_counts") != {
        "milb_cohorts": len(EXPECTED_COHORTS),
        "draft_sources": 2 + len(_DRAFT_RAW_PATHS),
        "prepared_sources": len(REGISTERED_PREPARED_SOURCE_PATHS),
    }:
        return False
    try:
        canonical_prepared_sha256 = _content_sha256(
            _canonical_json_bytes(dict(prepared))
        )
        canonical_draft_sha256 = _content_sha256(
            _canonical_json_bytes(dict(draft_facts))
        )
    except (TypeError, ValueError):
        return False
    if receipt.get("prepared_output") != {
        "path": REGISTERED_SOURCE_PATHS["prepared_artifact"],
        "sha256": prepared_output_sha256,
        "candidate_count": candidate_count,
    }:
        return False
    if receipt.get("draft_facts_output") != {
        "path": REGISTERED_SOURCE_PATHS["draft_facts"],
        "sha256": draft_output_sha256,
        "candidate_id_count": candidate_id_count,
    }:
        return False
    return (
        canonical_prepared_sha256 == prepared_output_sha256
        and canonical_draft_sha256 == draft_output_sha256
    )


def build_pre2014_readiness(
    prepared: Any,
    prepared_manifest: Any,
    draft_facts: Any,
    *,
    source_files: Mapping[str, Any],
    implementation_files: Sequence[Mapping[str, Any]],
    prepared_source_files: Sequence[Mapping[str, Any]],
    source_replay: Mapping[str, Any],
    implementation_base_commit: str,
    result_path: str,
    result_path_exists: bool,
) -> dict[str, Any]:
    """Return a fail-closed, pre-look authorization artifact.

    All file I/O belongs to the caller.  In particular, this function has no
    outcome or MLB-season input and cannot spend the registered look.
    """
    prepared_map = _mapping(prepared)
    manifest_map = _mapping(prepared_manifest)
    blockers: list[str] = []

    def block(reason: str) -> None:
        if reason not in blockers:
            blockers.append(reason)

    if prepared_map.get("artifact") != "valucast_extended_prospect_history_prepared":
        block("invalid_prepared_artifact")
    if manifest_map.get("artifact") != "valucast_extended_prospect_history_source_manifest":
        block("invalid_prepared_manifest")
    if prepared_map.get("mode") != "prepare_only":
        block("prepared_mode_not_prepare_only")
    if manifest_map.get("mode") != "prepare_only":
        block("manifest_mode_not_prepare_only")
    source_policy = _mapping(prepared_map.get("source_policy"))
    if source_policy.get("outcomes_read") is not False:
        block("prepared_outcomes_read_not_false")
    if source_policy.get("labels_scored") is not False:
        block("prepared_labels_scored_not_false")

    prepared_parity = prepared_map.get("identity_parity")
    manifest_parity = manifest_map.get("identity_parity")
    if (
        not _exact_parity(prepared_parity)
        or not _exact_parity(manifest_parity)
        or prepared_parity != manifest_parity
    ):
        block("identity_parity_not_exact")

    raw_rows = prepared_map.get("rows")
    if not isinstance(raw_rows, list) or any(
        not isinstance(row, Mapping) for row in raw_rows
    ):
        block("invalid_candidate_rows")
        rows: list[Mapping[str, Any]] = []
    else:
        rows = list(raw_rows)

    declared_cohorts = prepared_map.get("cohort_years")
    observed_cohorts = sorted(
        {
            row.get("cohort_year")
            for row in rows
            if isinstance(row.get("cohort_year"), int)
            and not isinstance(row.get("cohort_year"), bool)
        }
    )
    if declared_cohorts != list(EXPECTED_COHORTS) or observed_cohorts != list(
        EXPECTED_COHORTS
    ):
        block("cohort_set_mismatch")
    if prepared_map.get("candidate_count") != len(rows):
        block("candidate_count_mismatch")

    identity_counts: Counter[str] = Counter()
    candidate_ids: set[str] = set()
    invalid_identities = 0
    cohort_2014_count = 0
    fold_role_counts = {
        str(fold): {role: 0 for role in ROLES} for fold in REGISTERED_OUTER_FOLDS
    }
    outcome_label_count = 0
    for row in rows:
        mlbam_id = row.get("mlbam_id")
        role = row.get("role")
        year = row.get("cohort_year")
        valid_id = (
            isinstance(mlbam_id, (int, str))
            and not isinstance(mlbam_id, bool)
            and str(mlbam_id).strip() != ""
        )
        valid_year = isinstance(year, int) and not isinstance(year, bool)
        if not valid_id or role not in ROLES or not valid_year:
            invalid_identities += 1
            continue
        identity_counts[f"{mlbam_id}:{role}"] += 1
        candidate_ids.add(str(mlbam_id))
        if year == PARITY_COHORT:
            cohort_2014_count += 1
        if year in REGISTERED_OUTER_FOLDS:
            fold_role_counts[str(year)][str(role)] += 1
        if _contains_outcome_label(row):
            outcome_label_count += 1
    if invalid_identities:
        block("invalid_candidate_identity")
    duplicates = sorted(key for key, count in identity_counts.items() if count > 1)
    if duplicates:
        block("duplicate_mlbam_role_identity")
    if outcome_label_count:
        block("outcome_labels_present")

    insufficient_folds = []
    for fold in REGISTERED_OUTER_FOLDS:
        for role in ROLES:
            count = fold_role_counts[str(fold)][role]
            if count < MIN_CANDIDATES_PER_ROLE_FOLD:
                insufficient_folds.append(
                    {"cohort_year": fold, "role": role, "count": count}
                )
    if insufficient_folds:
        block("outer_fold_role_minimum_not_met")

    draft_map = _draft_mapping(draft_facts)
    draft_ids = {str(key) for key in draft_map}
    missing_draft_ids = sorted(candidate_ids - draft_ids)
    extra_draft_ids = sorted(draft_ids - candidate_ids)
    invalid_draft_ids = sorted(
        str(key) for key, value in draft_map.items() if not _draft_fact_valid(value)
    )
    if missing_draft_ids:
        block("draft_fact_coverage_incomplete")
    if missing_draft_ids or extra_draft_ids:
        block("draft_fact_identity_set_mismatch")
    if invalid_draft_ids:
        block("draft_fact_schema_invalid")

    unscorable_identities: list[str] = []
    try:
        from prospects.extended_history import draft_for_cohort
        from prospects.model import _outcome_feature_vector
        from prospects.pre2014_fold_scoring import CANDIDATE_MODEL_FLAGS
        from prospects.rank_backtest import _model_flags

        with _model_flags(dict(CANDIDATE_MODEL_FLAGS)):
            for row in rows:
                mlbam_id = row.get("mlbam_id")
                role = str(row.get("role") or "")
                cohort_year = row.get("cohort_year")
                identity = f"{mlbam_id}:{role}"
                try:
                    draft = draft_for_cohort(
                        _mapping(draft_map.get(str(mlbam_id))), int(cohort_year)
                    )
                    scoring_row = {**dict(row), **draft}
                    if _outcome_feature_vector(scoring_row, role) is None:
                        unscorable_identities.append(identity)
                except (KeyError, TypeError, ValueError):
                    unscorable_identities.append(identity)
    except (ImportError, RuntimeError):
        unscorable_identities = ["candidate_feature_validator_unavailable"]
    if unscorable_identities:
        block("candidate_feature_eligibility_failed")

    normalized_sources = {
        key: deepcopy(dict(_mapping(source_files.get(key))))
        for key in REQUIRED_SOURCE_FILES
    }
    if set(source_files) != set(REQUIRED_SOURCE_FILES) or any(
        _declared_repo_path(normalized_sources[key].get("path"))
        != REGISTERED_SOURCE_PATHS[key]
        for key in REQUIRED_SOURCE_FILES
    ):
        block("source_file_path_set_mismatch")
    if not all(
        _source_file_record_valid(key, normalized_sources[key])
        for key in REQUIRED_SOURCE_FILES
    ):
        block("source_file_hashes_invalid")

    output_record = _mapping(manifest_map.get("output"))
    prepared_record = normalized_sources["prepared_artifact"]
    if output_record.get("sha256") != prepared_record.get("sha256"):
        block("prepared_manifest_output_sha256_mismatch")
    if not _same_declared_path(output_record.get("path"), prepared_record.get("path")):
        block("prepared_manifest_output_path_mismatch")

    draft_output_record = _mapping(manifest_map.get("draft_facts_output"))
    registered_draft_record = normalized_sources["draft_facts"]
    if draft_output_record.get("sha256") != registered_draft_record.get("sha256"):
        block("prepared_manifest_draft_facts_sha256_mismatch")
    if not _same_declared_path(
        draft_output_record.get("path"), registered_draft_record.get("path")
    ):
        block("prepared_manifest_draft_facts_path_mismatch")

    manifest_sources_value = manifest_map.get("sources")
    if not isinstance(manifest_sources_value, list) or not manifest_sources_value:
        manifest_sources: list[dict[str, Any]] = []
        block("prepared_source_hashes_invalid")
    else:
        manifest_sources = [
            deepcopy(dict(_mapping(source))) for source in manifest_sources_value
        ]
        if not all(_manifest_source_valid(source) for source in manifest_sources):
            block("prepared_source_hashes_invalid")
        if any(
            "outcome" in str(source.get("kind") or "").lower()
            or "mlb_season" in str(source.get("kind") or "").lower()
            for source in manifest_sources
        ):
            block("outcome_source_in_prepared_manifest")

    normalized_prepared_sources = [
        deepcopy(dict(_mapping(record))) for record in prepared_source_files
    ]
    prepared_source_paths = [
        _declared_repo_path(record.get("path"))
        for record in normalized_prepared_sources
    ]
    if prepared_source_paths != list(REGISTERED_PREPARED_SOURCE_PATHS):
        block("prepared_source_path_set_mismatch")
    if not all(
        _file_record_valid(record) for record in normalized_prepared_sources
    ):
        block("prepared_source_hashes_invalid")
    registered_sources_by_path = {
        _declared_repo_path(record.get("path")): record
        for record in normalized_sources.values()
    }
    if any(
        path in registered_sources_by_path
        and record != registered_sources_by_path[path]
        for path, record in zip(prepared_source_paths, normalized_prepared_sources)
    ):
        block("source_overlap_binding_mismatch")

    manifest_source_paths = [
        _declared_repo_path(source.get("path")) for source in manifest_sources
    ]
    if manifest_source_paths != list(REGISTERED_PREPARED_SOURCE_PATHS):
        block("prepared_manifest_source_path_set_mismatch")
    elif len(normalized_prepared_sources) == len(manifest_sources) and any(
        source.get("sha256") != record.get("sha256")
        for source, record in zip(
            manifest_sources, normalized_prepared_sources, strict=True
        )
    ):
        block("prepared_manifest_source_binding_mismatch")
    normalized_manifest_source_receipts = [
        {
            "kind": "registered_prepared_source",
            "path": _declared_repo_path(source.get("path")),
            "sha256": source.get("sha256"),
        }
        for source in manifest_sources
    ]

    normalized_source_replay = deepcopy(dict(_mapping(source_replay)))
    if not _source_replay_valid(
        normalized_source_replay,
        prepared=prepared_map,
        draft_facts=draft_map,
        prepared_source_files=normalized_prepared_sources,
        prepared_output_sha256=prepared_record.get("sha256"),
        draft_output_sha256=registered_draft_record.get("sha256"),
        candidate_count=len(rows),
        candidate_id_count=len(draft_map),
    ):
        block("source_replay_invalid")

    normalized_implementations = [
        deepcopy(dict(_mapping(record))) for record in implementation_files
    ]
    if not normalized_implementations:
        block("implementation_hashes_missing")
    elif not all(_file_record_valid(record) for record in normalized_implementations):
        block("implementation_hashes_invalid")
    implementation_paths = [
        _declared_repo_path(record.get("path")) for record in normalized_implementations
    ]
    if implementation_paths != list(REGISTERED_IMPLEMENTATION_PATHS):
        block("implementation_path_set_mismatch")
    if (
        not isinstance(implementation_base_commit, str)
        or _GIT_OBJECT_RE.fullmatch(implementation_base_commit.lower()) is None
    ):
        block("implementation_base_commit_invalid")

    if result_path_exists:
        block("result_path_already_exists")
    normalized_result_path = _declared_repo_path(result_path)
    if normalized_result_path != REGISTERED_RESULT_PATH:
        block("result_path_not_registered")

    ready = not blockers
    return {
        "artifact": "valucast_pre2014_cross_role_readiness",
        "schema_version": 1,
        "status": "ready" if ready else "blocked",
        "blockers": blockers,
        "look_spent": bool(result_path_exists),
        "execution_authorized": ready,
        "claim_authorized": False,
        "production_review_authorized": False,
        "implementation_base_commit": str(implementation_base_commit),
        "source_policy": {
            "phase": "pre_look",
            "reads_outcomes": False,
            "reads_mlb_seasons": False,
            "research_only": True,
        },
        "source_replay": normalized_source_replay,
        "candidate_audit": {
            "row_count": len(rows),
            "candidate_id_count": len(candidate_ids),
            "cohorts": observed_cohorts,
            "expected_cohorts": list(EXPECTED_COHORTS),
            "cohort_2014_identity_count": cohort_2014_count,
            "parity_replay_identity_count": PARITY_IDENTITY_COUNT,
            "duplicate_mlbam_role_keys": duplicates,
            "invalid_identity_count": invalid_identities,
            "outcome_label_count": outcome_label_count,
            "unscorable_identity_count": len(unscorable_identities),
            "unscorable_identities": unscorable_identities[:100],
            "identity_parity": deepcopy(dict(_mapping(prepared_parity))),
        },
        "draft_fact_audit": {
            "candidate_id_count": len(candidate_ids),
            "covered_candidate_id_count": len(candidate_ids) - len(missing_draft_ids),
            "missing_candidate_ids": missing_draft_ids,
            "extra_candidate_ids": extra_draft_ids,
            "invalid_record_count": len(invalid_draft_ids),
            "invalid_record_ids": invalid_draft_ids[:100],
            "exact_candidate_id_set": not missing_draft_ids and not extra_draft_ids,
            "required_fields": list(DRAFT_FACT_FIELDS),
        },
        "outer_fold_audit": {
            "registered_folds": list(REGISTERED_OUTER_FOLDS),
            "minimum_candidates_per_role_fold": MIN_CANDIDATES_PER_ROLE_FOLD,
            "role_counts": fold_role_counts,
            "insufficient": insufficient_folds,
        },
        "result": {
            "path": normalized_result_path or str(result_path),
            "exists": bool(result_path_exists),
            "unspent": not result_path_exists,
        },
        "hashes": {
            "source_files": normalized_sources,
            "prepared_manifest_sources": normalized_manifest_source_receipts,
            "prepared_source_files": normalized_prepared_sources,
            "implementation_files": normalized_implementations,
        },
    }
