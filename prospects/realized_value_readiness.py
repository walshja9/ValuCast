"""Pure readiness audit for prospect realized-value validation."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict


IDENTITY_POLICY = {
    "identity_key": "integer_mlbam_id",
    "cohort_key": "cohort_year:mlbam_id",
    "one_row_per_cohort_identity": True,
    "historical_role": "frozen_from_cohort_cutoff_row",
    "later_role_changes": "disclosed_never_relabels_prior_cohort",
    "same_cohort_role_conflict": "block_affected_cohort",
    "common_pool": "unique_mlbam_identities",
    "role_results": "frozen_cohort_role",
}

_ROLES = ("hitter", "pitcher")


def _identity(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_opportunity(
    seasons: dict, cohort_year: int, mlbam_id: int, role: str
) -> bool:
    opportunity_field = "pa" if role == "hitter" else "ip"
    for season in seasons.get(f"{mlbam_id}_{role}") or []:
        year = _identity(season.get("year"))
        try:
            opportunity = float(season.get(opportunity_field) or 0)
        except (TypeError, ValueError):
            opportunity = 0
        if year is not None and cohort_year < year <= cohort_year + 4 and opportunity > 0:
            return True
    return False


def _category_coverage(seasons: dict, impact: dict, role: str) -> dict:
    canonical = list(impact.get(f"canonical_{role}_categories") or [])
    declared_missing = list(impact.get(f"missing_{role}_categories") or [])
    missing_set = set(declared_missing)
    missing = [category for category in canonical if category in missing_set]
    missing.extend(sorted(missing_set - set(canonical)))
    source_fields = {
        category: (["sv", "hld"] if category == "sv_hld" else [category])
        for category in canonical
    }
    role_seasons = [
        season
        for key, values in seasons.items()
        if str(key).endswith(f"_{role}")
        for season in (values or [])
        if isinstance(season, dict)
    ]
    return {
        "canonical": canonical,
        "available": [category for category in canonical if category not in missing_set],
        "missing": missing,
        "complete": bool(canonical) and not missing,
        "source_fields": source_fields,
        "season_rows": len(role_seasons),
        "season_rows_with_category": {
            category: sum(
                all(season.get(field) is not None for field in fields)
                for season in role_seasons
            )
            for category, fields in source_fields.items()
        },
    }


def _content_sha256(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_sha256(content: bytes) -> str:
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def audit_realized_value_readiness(contract: dict, model_artifact: dict) -> dict:
    rows = list((contract.get("historical") or {}).get("rows") or [])
    seasons = contract.get("historical_mlb_seasons") or {}
    impact = model_artifact.get("impact_target_contract") or {}

    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    invalid_rows = []
    for index, row in enumerate(rows):
        cohort_year = _identity(row.get("cohort_year"))
        mlbam_id = _identity(row.get("mlbam_id"))
        if cohort_year is None or mlbam_id is None or row.get("role") not in _ROLES:
            invalid_rows.append(index)
            continue
        grouped[(cohort_year, mlbam_id)].append(row)

    duplicates = sorted(
        f"{year}:{mlbam_id}"
        for (year, mlbam_id), identity_rows in grouped.items()
        if len(identity_rows) > 1
    )
    conflicts = sorted(
        f"{year}:{mlbam_id}"
        for (year, mlbam_id), identity_rows in grouped.items()
        if len({row["role"] for row in identity_rows}) > 1
    )

    frozen_roles = {
        key: next(iter(roles))
        for key, identity_rows in grouped.items()
        if len(roles := {row["role"] for row in identity_rows}) == 1
    }
    roles_by_player: dict[int, dict[int, str]] = defaultdict(dict)
    for (cohort_year, mlbam_id), role in frozen_roles.items():
        roles_by_player[mlbam_id][cohort_year] = role
    later_role_changes = [
        {
            "mlbam_id": str(mlbam_id),
            "roles_by_cohort": {
                str(year): role for year, role in sorted(roles_by_cohort.items())
            },
        }
        for mlbam_id, roles_by_cohort in sorted(roles_by_player.items())
        if len(set(roles_by_cohort.values())) > 1
    ]

    cohorts = {}
    for cohort_year in sorted({year for year, _ in grouped}):
        cohort_keys = [key for key in grouped if key[0] == cohort_year]
        cohort_duplicates = [
            key for key in duplicates if key.startswith(f"{cohort_year}:")
        ]
        cohort_conflicts = [
            key for key in conflicts if key.startswith(f"{cohort_year}:")
        ]
        eligible = {role: 0 for role in _ROLES}
        resolved = {role: 0 for role in _ROLES}
        with_opportunity = {role: 0 for role in _ROLES}
        zero_opportunity = {role: 0 for role in _ROLES}
        for key in cohort_keys:
            role = frozen_roles.get(key)
            if role is None:
                continue
            eligible[role] += 1
            if any(row.get("outcome") is not None for row in grouped[key]):
                resolved[role] += 1
            if _has_opportunity(seasons, key[0], key[1], role):
                with_opportunity[role] += 1
            else:
                zero_opportunity[role] += 1
        for counts in (eligible, resolved, with_opportunity, zero_opportunity):
            counts["common_pool"] = sum(counts.values())
        cohorts[str(cohort_year)] = {
            "identity_status": (
                "blocked" if cohort_duplicates or cohort_conflicts else "ready"
            ),
            "eligible": eligible,
            "resolved": resolved,
            "with_opportunity": with_opportunity,
            "zero_opportunity": zero_opportunity,
            "duplicate_cohort_identities": cohort_duplicates,
            "conflicting_cohort_roles": cohort_conflicts,
        }

    category_coverage = {
        "direct_7x7": impact.get("direct_7x7") is True,
        **{
            role: _category_coverage(seasons, impact, role)
            for role in _ROLES
        },
    }
    replay = {
        "historical_cutoff": "cohort_season_completion",
        "intra_season_cutoff_reconstructable": False,
        "retrospective_input_kind": "reconstructed_full_season",
        "exact_prospective_replay_ready": False,
        "partial_category_secondary_ready": (
            not impact.get("missing_hitter_categories")
            and bool(
                set(impact.get("canonical_pitcher_categories") or [])
                - set(impact.get("missing_pitcher_categories") or [])
            )
        ),
        "realized_value_regret_ready": False,
    }

    blockers = [
        f"missing_{role}_category:{category}"
        for role in _ROLES
        for category in category_coverage[role]["missing"]
    ]
    blockers.extend(f"duplicate_cohort_identity:{key}" for key in duplicates)
    blockers.extend(f"conflicting_cohort_roles:{key}" for key in conflicts)
    blockers.extend(f"invalid_historical_row:{index}" for index in invalid_rows)
    if not grouped:
        blockers.append("missing_historical_cohorts")
    if not impact.get("direct_7x7"):
        blockers.append("impact_target_not_direct_7x7")
    if not replay["exact_prospective_replay_ready"]:
        blockers.append("exact_prospective_replay_not_reconstructable")

    report = {
        "schema": "valucast_prospect_realized_value_readiness",
        "status": "blocked" if blockers else "ready",
        "identity_policy": dict(IDENTITY_POLICY),
        "identity_audit": {
            "historical_row_count": len(rows),
            "cohort_identity_count": len(grouped),
            "unique_mlbam_identities": len({mlbam_id for _, mlbam_id in grouped}),
            "invalid_historical_rows": invalid_rows,
            "duplicate_cohort_identities": duplicates,
            "conflicting_cohort_roles": conflicts,
            "later_role_changes": later_role_changes,
        },
        "category_coverage": category_coverage,
        "cohorts": cohorts,
        "replay": replay,
        "blockers": blockers,
    }
    report["content_sha256"] = _content_sha256(report)
    return report


def _stage2_category_coverage(seasons: dict, role: str) -> dict:
    from prospects.model import (  # Keep the old pure audit's import path unchanged.
        IMPACT_CATEGORIES,
        IMPACT_CATEGORY_COVERAGE,
        IMPACT_REFERENCE_MIN,
    )

    sample_field = "pa" if role == "hitter" else "ip"
    source_fields = {
        category: (["sv", "hld"] if category == "sv_hld" else [category])
        for category in IMPACT_CATEGORIES[role]
    }
    role_rows = [
        row
        for key, values in seasons.items()
        if str(key).endswith(f"_{role}")
        for row in (values or [])
        if isinstance(row, dict)
    ]
    eligible = []
    for row in role_rows:
        try:
            sample = float(row.get(sample_field) or 0)
        except (TypeError, ValueError):
            sample = 0
        if sample >= IMPACT_REFERENCE_MIN[role]:
            eligible.append(row)
    counts = {
        category: sum(
            all(row.get(field) is not None for field in fields)
            for row in eligible
        )
        for category, fields in source_fields.items()
    }
    best = max(counts.values(), default=0)
    threshold = best * IMPACT_CATEGORY_COVERAGE
    active = [
        category
        for category in IMPACT_CATEGORIES[role]
        if best and counts[category] >= threshold
    ]
    missing = [
        category
        for category in IMPACT_CATEGORIES[role]
        if category not in active
    ]
    return {
        "canonical": list(IMPACT_CATEGORIES[role]),
        "active": active,
        "missing": missing,
        "complete": bool(active) and not missing,
        "season_rows": len(role_rows),
        "eligible_reference_seasons": len(eligible),
        "coverage_ratio": IMPACT_CATEGORY_COVERAGE,
        "populated_reference_seasons": counts,
        "source_fields": source_fields,
    }


def _strict_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def audit_stage2_realized_value_readiness(
    contract: dict,
    model_artifact: dict,
    qs_sidecar: dict,
    *,
    contract_sha256: str,
) -> dict:
    base = audit_realized_value_readiness(contract, model_artifact)
    seasons = contract.get("historical_mlb_seasons") or {}
    blockers = [
        blocker
        for blocker in base["blockers"]
        if blocker.startswith(
            (
                "duplicate_cohort_identity:",
                "conflicting_cohort_roles:",
                "invalid_historical_row:",
            )
        )
        or blocker == "missing_historical_cohorts"
    ]

    expected_path = "data/prospects/prospect_model_inputs.json"
    current = contract.get("current")
    cutoff = str(
        current.get("fetched_date") or "" if isinstance(current, dict) else ""
    )
    if not isinstance(qs_sidecar, dict):
        qs_sidecar = {}
    sidecar_input = qs_sidecar.get("input")
    if not isinstance(sidecar_input, dict):
        sidecar_input = {}
    sidecar_validation = qs_sidecar.get("validation")
    if not isinstance(sidecar_validation, dict):
        sidecar_validation = {}
    if qs_sidecar.get("schema") != "valucast_stage2_quality_starts":
        blockers.append("qs_sidecar_schema_invalid")
    if qs_sidecar.get("version") != "1.0.0":
        blockers.append("qs_sidecar_version_unsupported")
    if qs_sidecar.get("status") != "ready":
        blockers.append("qs_sidecar_status_not_ready")
    for blocker in qs_sidecar.get("blockers") or []:
        blockers.append(f"qs_sidecar_declared_blocker:{blocker}")
    if sidecar_input.get("path") != expected_path:
        blockers.append("qs_sidecar_input_path_mismatch")
    if sidecar_input.get("sha256") != contract_sha256:
        blockers.append("qs_sidecar_input_sha256_mismatch")
    if sidecar_input.get("cutoff_date") != cutoff:
        blockers.append("qs_sidecar_cutoff_mismatch")
    if qs_sidecar.get("content_sha256") != _content_sha256(qs_sidecar):
        blockers.append("qs_sidecar_content_sha256_mismatch")

    source_identities = set()
    for key, values in seasons.items():
        if not str(key).endswith("_pitcher"):
            continue
        try:
            mlbam_id = int(str(key).rsplit("_", 1)[0])
        except ValueError:
            blockers.append(f"invalid_pitcher_season_key:{key}")
            continue
        for index, row in enumerate(values or []):
            year = _identity(row.get("year")) if isinstance(row, dict) else None
            if year is None:
                blockers.append(f"invalid_pitcher_season:{key}:{index}")
                continue
            source_identities.add((mlbam_id, year))

    sidecar_rows = {}
    for index, row in enumerate(qs_sidecar.get("rows") or []):
        if not isinstance(row, dict):
            blockers.append(f"qs_sidecar_invalid_row:{index}")
            continue
        values = (
            row.get("mlbam_id"),
            row.get("season"),
            row.get("games_started"),
            row.get("quality_starts"),
        )
        if (
            not all(_strict_nonnegative_int(value) for value in values)
            or values[0] == 0
            or values[1] == 0
            or values[3] > values[2]
        ):
            blockers.append(f"qs_sidecar_invalid_row:{index}")
            continue
        identity = (values[0], values[1])
        if identity in sidecar_rows:
            blockers.append(
                f"qs_sidecar_duplicate_identity:{identity[0]}:{identity[1]}"
            )
            continue
        sidecar_rows[identity] = row

    for mlbam_id, season in sorted(source_identities - set(sidecar_rows)):
        blockers.append(f"qs_sidecar_missing_identity:{mlbam_id}:{season}")
    for mlbam_id, season in sorted(set(sidecar_rows) - source_identities):
        blockers.append(f"qs_sidecar_extra_identity:{mlbam_id}:{season}")

    disclosures = {
        (int(row["mlbam_id"]), int(row["season"])): (
            row.get("existing"),
            row.get("derived"),
        )
        for row in (
            sidecar_validation.get("current_season_values_superseded") or []
        )
        if isinstance(row, dict)
        and _identity(row.get("mlbam_id")) is not None
        and _identity(row.get("season")) is not None
    }
    cutoff_year = _identity(cutoff[:4])
    enriched = {
        key: [
            dict(row) if isinstance(row, dict) else row
            for row in (values or [])
        ]
        for key, values in seasons.items()
    }
    for key, values in enriched.items():
        if not str(key).endswith("_pitcher"):
            continue
        try:
            mlbam_id = int(str(key).rsplit("_", 1)[0])
        except ValueError:
            continue
        for row in values:
            if not isinstance(row, dict):
                continue
            year = _identity(row.get("year"))
            sidecar_row = sidecar_rows.get((mlbam_id, year))
            if sidecar_row is None:
                continue
            derived = sidecar_row["quality_starts"]
            existing = row.get("qs")
            if existing is not None and existing != derived:
                disclosed = disclosures.get((mlbam_id, year))
                allowed = year == cutoff_year and disclosed == (existing, derived)
                if not allowed:
                    blockers.append(f"qs_source_conflict:{mlbam_id}:{year}")
            row["qs"] = derived

    evidence = {
        role: _stage2_category_coverage(enriched, role) for role in _ROLES
    }
    for role in _ROLES:
        blockers.extend(
            f"missing_{role}_category:{category}"
            for category in evidence[role]["missing"]
        )
    evidence_blockers = list(blockers)
    evidence_ready = (
        evidence["hitter"]["complete"]
        and evidence["pitcher"]["complete"]
        and not evidence_blockers
    )

    impact = model_artifact.get("impact_target_contract") or {}
    incumbent_ready = (
        impact.get("direct_7x7") is True
        and not impact.get("missing_hitter_categories")
        and not impact.get("missing_pitcher_categories")
    )
    replay = dict(base["replay"])
    if not incumbent_ready:
        blockers.append("impact_target_not_direct_7x7")
    if not replay["exact_prospective_replay_ready"]:
        blockers.append("exact_prospective_replay_not_reconstructable")
    realized_ready = (
        evidence_ready
        and incumbent_ready
        and replay["exact_prospective_replay_ready"]
        and not blockers
    )

    report = {
        "schema": "valucast_stage2_realized_value_readiness",
        "version": "1.0.0",
        "status": "ready" if realized_ready else "blocked",
        "inputs": {
            "prospect_contract": {
                "path": expected_path,
                "sha256": contract_sha256,
                "cutoff_date": cutoff,
            },
            "model_artifact": {
                "path": "data/models/valucast_prospect_model.json",
            },
            "quality_starts_sidecar": {
                "path": (
                    "data/validation/valucast_stage2_quality_starts.json"
                ),
                "content_sha256": qs_sidecar.get("content_sha256"),
            },
        },
        "identity_policy": dict(base["identity_policy"]),
        "identity_audit": dict(base["identity_audit"]),
        "cohorts": dict(base["cohorts"]),
        "outcome_evidence": {
            "status": "ready" if evidence_ready else "blocked",
            "retrospective_direct_7x7_evidence_ready": evidence_ready,
            **evidence,
        },
        "incumbent_impact_target": {
            "direct_7x7": impact.get("direct_7x7") is True,
            "declared_hitter_categories": list(
                impact.get("hitter_categories") or []
            ),
            "declared_pitcher_categories": list(
                impact.get("pitcher_categories") or []
            ),
            "incumbent_direct_7x7_target_ready": incumbent_ready,
        },
        "prospective_replay": replay,
        "realized_value_regret_ready": realized_ready,
        "blockers": list(dict.fromkeys(blockers)),
    }
    report["content_sha256"] = _content_sha256(report)
    return report
